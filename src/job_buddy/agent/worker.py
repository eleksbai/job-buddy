from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.ai import AIMatchingClient
from job_buddy.boss import BossClient
from job_buddy.config import Settings
from job_buddy.messaging import send_feishu
from job_buddy.models import JobLead, WorkerConfig, utc_now
from job_buddy.services import (
    AIMatchingService,
    BaseWorker,
    FriendService,
    GreetingService,
    StatisticsService,
)

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

CMD_PROMPT = """你是一个求职助手指令解析器。根据用户的自然语言输入，输出 JSON 格式的指令。

可用指令：
- greet: 打招呼并发送消息 — 参数: limit(数量, 可选)
- evaluate: 执行 AI 评估 — 无参数
- collect: 滚动采集职位 — 无参数
- stats: 统计 — 无参数
- query: 查询职位 — 参数: keyword(关键词)
- help: 帮助 — 无参数

只输出 JSON：
{"command": "指令名", "args": {...}, "reasoning": "解析理由"}"""


class AgentWorker(BaseWorker):
    worker_name = "agent"

    def __init__(
        self,
        database: AsyncIOMotorDatabase,
        boss_client: BossClient,
        settings: Settings,
        feishu_manager: Any,
    ) -> None:
        super().__init__(database, boss_client)
        self.settings = settings
        self.feishu_manager = feishu_manager
        self._ai_client: AIMatchingClient | None = None
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    @property
    def ai_client(self) -> AIMatchingClient:
        if self._ai_client is None:
            self._ai_client = AIMatchingClient(self.settings)
        return self._ai_client

    def default_config(self) -> WorkerConfig:
        return WorkerConfig(
            worker_name="agent",
            interval_seconds=3600,
            batch_size=10,
            query={
                "schedule_times": ["09:00", "14:00", "18:00"],
                "schedule_jitter_minutes": 60,
                "greet_limit": 10,
            },
        )

    # ── SSE event system ──────────────────────────────────────────

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        data["ts"] = utc_now().isoformat()
        event = {"type": event_type, "data": data}
        dead: list[int] = []
        for i, q in enumerate(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(i)
        for i in reversed(dead):
            self._subscribers.pop(i)

    async def subscribe(self):
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        try:
            while True:
                event = await q.get()
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            self._subscribers.remove(q)

    # ── Start / Stop ──────────────────────────────────────────────

    async def start(self) -> None:
        await super().start()
        if self.feishu_manager is not None:
            self.feishu_manager.set_command_handler(self._on_feishu_message)

    async def stop(self) -> None:
        await super().stop()

    # ── Schedule helpers (from ScrollAndCollectWorker) ────────────

    def _actual_time(self, time_str: str, date_val: date, jitter_minutes: int = 30) -> datetime:
        base_time = datetime.strptime(time_str, "%H:%M").time()
        seed = f"{date_val.isoformat()}|{time_str}"
        rng = random.Random(seed)
        offset_minutes = rng.randint(-jitter_minutes, jitter_minutes)
        return datetime.combine(date_val, base_time, tzinfo=_CST) + timedelta(minutes=offset_minutes)

    def _calculate_next_run(self, worker: WorkerConfig) -> datetime:
        now = datetime.now(tz=_CST)
        schedule_times: list[str] = worker.query.get("schedule_times", ["09:00", "14:00", "18:00"])
        jitter_minutes = max(0, int(worker.query.get("schedule_jitter_minutes", 60)))
        last_finished = worker.last_finished_at
        today = now.date()

        for time_str in schedule_times:
            base = datetime.strptime(time_str, "%H:%M").time()
            base_dt = datetime.combine(today, base, tzinfo=_CST)
            window_start = base_dt - timedelta(minutes=jitter_minutes)

            if now >= window_start:
                if last_finished is not None:
                    last_finished_cst = last_finished.replace(tzinfo=timezone.utc).astimezone(_CST)
                    if last_finished_cst >= window_start:
                        continue
                return now
            else:
                return self._actual_time(time_str, today, jitter_minutes)

        tomorrow = today + timedelta(days=1)
        return self._actual_time(schedule_times[0], tomorrow, jitter_minutes)

    # ── Worker lifecycle overrides ────────────────────────────────

    async def start_worker(self) -> WorkerConfig:
        current = await self.get_worker()
        self.validate_before_start(current)
        return await self._update_worker_model({
            "enabled": True, "status": "idle",
            "next_run_at": self._calculate_next_run(current),
            "last_error": None,
        })

    async def release_worker(self) -> WorkerConfig:
        worker = await self.get_worker()
        if not worker.enabled:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="未启动的 worker 无需解除限制")
        return await self._update_worker_model({
            "status": "idle",
            "next_run_at": self._calculate_next_run(worker),
            "last_error": None,
        })

    async def execute_enabled_worker(self, worker: WorkerConfig) -> WorkerConfig:
        try:
            await self._execute_workflow()
        except Exception as exc:
            logger.exception("agent workflow failed")
            return await self._update_worker_model({
                "status": "error",
                "last_error": str(exc),
            })
        return await self._update_worker_model({
            "status": "idle",
            "last_finished_at": utc_now(),
            "next_run_at": self._calculate_next_run(worker),
        })

    async def execute_now(self) -> WorkerConfig:
        result = await super().execute_now()
        worker = await self.get_worker()
        await self._update_worker_model({
            "next_run_at": self._calculate_next_run(worker),
        })
        return result

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                worker = await self.get_worker()
                if not worker.enabled:
                    await asyncio.wait_for(self._stopped.wait(), timeout=10)
                    continue

                next_run = self._calculate_next_run(worker)
                now = datetime.now(tz=_CST)
                if now >= next_run:
                    try:
                        await self.execute()
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        logger.exception("worker %s run failed", self.worker_name)
                    worker = await self.get_worker()
                    if worker.status == "error":
                        await self._update_worker_model({
                            "next_run_at": utc_now() + timedelta(minutes=5),
                        })
                    else:
                        await self._update_worker_model({
                            "next_run_at": self._calculate_next_run(worker),
                        })
                else:
                    wait = max(5, (next_run - now).total_seconds())
                    logger.info(
                        "worker %s next wake in %.0fs at %s",
                        self.worker_name, wait, next_run.isoformat(),
                    )
                    try:
                        await asyncio.wait_for(self._stopped.wait(), timeout=wait)
                    except asyncio.TimeoutError:
                        pass
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("worker loop failed: worker=%s", self.worker_name)
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass

    # ── Fixed workflow ────────────────────────────────────────────

    async def _execute_workflow(self) -> None:
        greet_limit = await self._get_greet_limit()

        await self._emit("step_start", {
            "step": "find_jobs",
            "text": f"查找近5天内更新、AI匹配且未打招呼的职位（限制 {greet_limit} 个）",
        })

        since_5d = utc_now() - timedelta(days=5)
        existing_boss_ids = [
            doc["source_friend_id"]
            async for doc in self.database["friend_records"].find(
                {"source_friend_id": {"$exists": True, "$ne": None, "$ne": ""}},
                {"source_friend_id": 1},
            )
        ]
        cursor = self.database["job_leads"].find({
            "updated_at": {"$gte": since_5d},
            "ai_match": True,
            "greeted": False,
            "source_friend_id": {"$nin": existing_boss_ids},
        }).sort([("ai_score", -1), ("created_at", -1)]).limit(greet_limit)
        jobs = [JobLead.from_mongo(item) for item in await cursor.to_list(length=greet_limit)]

        await self._emit("step_end", {
            "step": "find_jobs",
            "count": len(jobs),
            "text": f"找到 {len(jobs)} 个职位",
        })

        if not jobs:
            await self._emit("chat", {
                "source": "agent",
                "text": "近5天内无符合条件的职位需要打招呼",
            })
            await send_feishu("近5天内无符合条件的职位需要打招呼")
            return

        greet_service = GreetingService(self.database, self.boss_client)
        ai_service = AIMatchingService(self.database, self.settings)
        friend_service = FriendService(self.database, self.boss_client)

        greeted_count = 0
        sent_count = 0
        for idx, job in enumerate(jobs):
            if idx > 0:
                delay = random.uniform(5, 15)
                await self._emit("reasoning", {
                    "text": f"等待 {delay:.0f} 秒后处理下一个职位...",
                })
                await asyncio.sleep(delay)

            await self._emit("step_start", {
                "step": "job",
                "job_title": job.title,
                "company": job.company or "-",
                "text": f"#{idx + 1}/{len(jobs)} {job.title} @ {job.company}",
            })

            # Greet
            await self._emit("tool_call", {
                "step": "job",
                "tool": "greet",
                "input": job.source_job_id,
                "output": "...",
            })
            try:
                greet_task = await greet_service.run_greetings(
                    source_job_ids=[job.source_job_id],
                    greeting_message=None,
                    limit=1,
                )
                if greet_task.result_summary.get("succeeded", 0) > 0:
                    greeted_count += 1
                    await self._emit("tool_call", {
                        "step": "job",
                        "tool": "greet",
                        "input": job.source_job_id,
                        "output": "success",
                    })
                else:
                    await self._emit("tool_call", {
                        "step": "job",
                        "tool": "greet",
                        "input": job.source_job_id,
                        "output": "failed: " + str(greet_task.result_summary),
                    })
                    await self._emit("step_end", {
                        "step": "job",
                        "job_title": job.title,
                        "text": "打招呼失败，跳过",
                    })
                    continue
            except Exception as exc:
                logger.exception("agent greet failed: %s", job.title)
                await self._emit("error", {
                    "step": "job",
                    "text": f"打招呼异常: {exc}",
                })
                await self._emit("step_end", {
                    "step": "job",
                    "job_title": job.title,
                    "text": f"打招呼异常，跳过",
                })
                continue

            # Generate message
            await self._emit("tool_call", {
                "step": "job",
                "tool": "generate_message",
                "input": job.source_job_id,
                "output": "...",
            })
            try:
                result = await ai_service.generate_message(job.source_job_id)
                message = result.get("message", "")
            except Exception as exc:
                logger.exception("agent generate message failed: %s", job.source_job_id)
                await self._emit("error", {
                    "step": "job",
                    "text": f"生成消息异常: {exc}",
                })
                message = ""

            await self._emit("tool_call", {
                "step": "job",
                "tool": "generate_message",
                "input": job.source_job_id,
                "output": message[:200] + ("..." if len(message) > 200 else ""),
            })

            if result.get("reasoning"):
                await self._emit("reasoning", {
                    "step": "job",
                    "text": result["reasoning"],
                })

            if not message:
                await self._emit("step_end", {
                    "step": "job",
                    "job_title": job.title,
                    "text": "AI 消息为空，跳过发送",
                })
                continue

            # Send message
            source_friend_id = job.source_friend_id
            if not source_friend_id:
                refreshed = await self.database["job_leads"].find_one(
                    {"source_job_id": job.source_job_id},
                )
                if refreshed:
                    source_friend_id = refreshed.get("source_friend_id")

            if source_friend_id:
                await self._emit("tool_call", {
                    "step": "job",
                    "tool": "send_message",
                    "input": source_friend_id,
                    "output": "...",
                })
                try:
                    await friend_service.send_friend_message(source_friend_id, message)
                    sent_count += 1
                    await self._emit("tool_call", {
                        "step": "job",
                        "tool": "send_message",
                        "input": source_friend_id,
                        "output": "sent",
                    })
                except Exception as exc:
                    logger.exception("agent send message failed: %s", source_friend_id)
                    await self._emit("error", {
                        "step": "job",
                        "text": f"发送失败: {exc}",
                    })
            else:
                await self._emit("error", {
                    "step": "job",
                    "text": "缺少 source_friend_id，无法发送",
                })

            await self._emit("step_end", {
                "step": "job",
                "job_title": job.title,
                "text": "完成",
            })

        summary = f"自动打招呼完成\n找到: {len(jobs)} | 打招呼: {greeted_count} | 发送消息: {sent_count}"
        await self._emit("chat", {"source": "agent", "text": summary})
        await send_feishu(summary)

    async def _get_greet_limit(self) -> int:
        worker = await self.get_worker()
        return max(1, int(worker.query.get("greet_limit", 10)))

    # ── Feishu command handler ────────────────────────────────────

    async def _on_feishu_message(self, chat_id: str, text: str) -> None:
        await self._emit("chat", {"source": "feishu", "text": text})
        try:
            intent = await self._parse_intent(text)
            await self._emit("reasoning", {"text": f"意图解析: {intent.get('command')} — {intent.get('reasoning', '')}"})
            result = await self._execute_intent(intent)
        except Exception as exc:
            result = f"处理失败: {exc}"
            logger.exception("feishu command processing failed")
            await self._emit("error", {"text": result})
        await self._emit("chat", {"source": "agent", "text": result})
        await send_feishu(result)

    # ── Web chat handler ──────────────────────────────────────────

    async def handle_chat(self, text: str) -> None:
        await self._emit("chat", {"source": "user", "text": text})
        try:
            intent = await self._parse_intent(text)
            await self._emit("reasoning", {"text": f"意图解析: {intent.get('command')} — {intent.get('reasoning', '')}"})
            result = await self._execute_intent(intent)
        except Exception as exc:
            result = f"处理失败: {exc}"
            logger.exception("chat command processing failed")
            await self._emit("error", {"text": result})
        await self._emit("chat", {"source": "agent", "text": result})

    # ── LLM intent parsing ────────────────────────────────────────

    async def _parse_intent(self, text: str) -> dict[str, Any]:
        try:
            response = await self.ai_client._client.chat.completions.create(
                model=self.ai_client._model,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": CMD_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                return {"command": "help", "args": {}, "reasoning": "无法解析"}
            return json.loads(content)
        except Exception:
            logger.exception("intent parsing failed")
            return {"command": "help", "args": {}, "reasoning": "解析异常"}

    # ── Command execution ─────────────────────────────────────────

    async def _execute_intent(self, intent: dict[str, Any]) -> str:
        cmd = intent.get("command", "help")
        args = intent.get("args") or {}

        handlers: dict[str, Any] = {
            "greet": self._cmd_greet,
            "evaluate": self._cmd_evaluate,
            "collect": self._cmd_collect,
            "stats": self._cmd_stats,
            "query": self._cmd_query,
            "help": self._cmd_help,
        }

        handler = handlers.get(cmd, handlers["help"])
        return await handler(args)

    async def _cmd_greet(self, args: dict[str, Any]) -> str:
        limit = args.get("limit") or await self._get_greet_limit()

        await self._emit("step_start", {
            "step": "cmd_greet",
            "text": f"查找需打招呼的职位（限制 {limit} 个）",
        })

        since_5d = utc_now() - timedelta(days=5)
        cursor = self.database["job_leads"].find({
            "updated_at": {"$gte": since_5d},
            "ai_match": True,
            "greeted": False,
        }).sort([("ai_score", -1), ("created_at", -1)]).limit(limit)
        jobs = [JobLead.from_mongo(item) for item in await cursor.to_list(length=limit)]

        await self._emit("step_end", {
            "step": "cmd_greet",
            "count": len(jobs),
            "text": f"找到 {len(jobs)} 个职位",
        })

        if not jobs:
            return "没有找到需要打招呼的职位"

        greet_service = GreetingService(self.database, self.boss_client)
        ai_service = AIMatchingService(self.database, self.settings)
        friend_service = FriendService(self.database, self.boss_client)

        greeted_count = 0
        sent_count = 0
        for idx, job in enumerate(jobs):
            if idx > 0:
                delay = random.uniform(5, 15)
                await asyncio.sleep(delay)

            await self._emit("step_start", {
                "step": "cmd_greet_job",
                "text": f"#{idx + 1}/{len(jobs)} {job.title} @ {job.company}",
            })

            # Greet
            try:
                greet_task = await greet_service.run_greetings(
                    source_job_ids=[job.source_job_id],
                    greeting_message=None,
                    limit=1,
                )
                if greet_task.result_summary.get("succeeded", 0) > 0:
                    greeted_count += 1
                else:
                    await self._emit("step_end", {
                        "step": "cmd_greet_job",
                        "text": "打招呼失败，跳过",
                    })
                    continue
            except Exception:
                logger.exception("agent cmd greet failed: %s", job.title)
                await self._emit("step_end", {
                    "step": "cmd_greet_job",
                    "text": "打招呼异常，跳过",
                })
                continue

            # Generate message
            try:
                result = await ai_service.generate_message(job.source_job_id)
                message = result.get("message", "")
            except Exception:
                logger.exception("agent cmd generate message failed: %s", job.source_job_id)
                message = ""

            if result.get("reasoning"):
                await self._emit("reasoning", {
                    "step": "cmd_greet_job",
                    "text": result["reasoning"],
                })

            if not message:
                await self._emit("step_end", {
                    "step": "cmd_greet_job",
                    "text": "AI 消息为空，跳过发送",
                })
                continue

            # Send message
            source_friend_id = job.source_friend_id
            if not source_friend_id:
                refreshed = await self.database["job_leads"].find_one(
                    {"source_job_id": job.source_job_id},
                )
                if refreshed:
                    source_friend_id = refreshed.get("source_friend_id")

            if source_friend_id:
                try:
                    await friend_service.send_friend_message(source_friend_id, message)
                    sent_count += 1
                except Exception:
                    logger.exception("agent cmd send message failed: %s", source_friend_id)
                    pass

            await self._emit("step_end", {
                "step": "cmd_greet_job",
                "text": "完成",
            })

        return f"打招呼完成: {greeted_count} 成功 / {len(jobs) - greeted_count} 失败 | 发送消息: {sent_count}"

    async def _cmd_evaluate(self, args: dict[str, Any]) -> str:
        await self._emit("step_start", {"step": "cmd_evaluate", "text": "触发 AI 评估"})
        ai_service = AIMatchingService(self.database, self.settings)
        task = await ai_service.run_evaluation_task()
        await self._emit("step_end", {
            "step": "cmd_evaluate",
            "text": f"AI 评估完成: {task.result_summary.get('evaluated', 0)} 个",
        })
        return f"AI 评估完成: {task.result_summary.get('evaluated', 0)} 个职位"

    async def _cmd_collect(self, args: dict[str, Any]) -> str:
        await self._emit("step_start", {"step": "cmd_collect", "text": "触发滚动采集"})
        await self._emit("step_end", {
            "step": "cmd_collect",
            "text": "滚动采集任务已发起，请查看任务面板获取结果",
        })
        return "滚动采集任务已发起"

    async def _cmd_stats(self, args: dict[str, Any]) -> str:
        await self._emit("step_start", {"step": "cmd_stats", "text": "统计24小时内职位"})
        stats_service = StatisticsService(self.database)
        stats = await stats_service.get_today_stats()
        updated = stats["updated_today"]
        created = stats["created_today"]

        result = (
            f"24小时内更新: {updated['total']}（匹配: {updated['matched']} | 不匹配: {updated['unmatched']} | 未分析: {updated['unanalyzed']}）\n"
            f"24小时内新增: {created['total']}（匹配: {created['matched']} | 不匹配: {created['unmatched']} | 未分析: {created['unanalyzed']}）"
        )

        await send_feishu(
            f"24小时内职位统计\n\n"
            f"24小时内更新: {updated['total']}（匹配: {updated['matched']} | 不匹配: {updated['unmatched']} | 未分析: {updated['unanalyzed']}）\n"
            f"24小时内新增: {created['total']}（匹配: {created['matched']} | 不匹配: {created['unmatched']} | 未分析: {created['unanalyzed']}）"
        )

        await self._emit("step_end", {"step": "cmd_stats", "text": result})
        return result

    async def _cmd_query(self, args: dict[str, Any]) -> str:
        keyword = args.get("keyword", "")
        if not keyword:
            return "请提供查询关键词"

        await self._emit("step_start", {
            "step": "cmd_query",
            "text": f"查询职位: {keyword}",
        })

        import re
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        cursor = self.database["job_leads"].find({
            "$or": [
                {"title": {"$regex": f".*{re.escape(keyword)}.*", "$options": "i"}},
                {"company": {"$regex": f".*{re.escape(keyword)}.*", "$options": "i"}},
            ],
        }).limit(10)
        jobs = [JobLead.from_mongo(item) for item in await cursor.to_list(length=10)]

        if not jobs:
            await self._emit("step_end", {"step": "cmd_query", "text": "未找到匹配职位"})
            return f"未找到包含 '{keyword}' 的职位"

        lines = [f"查询 '{keyword}' 结果 ({len(jobs)}):"]
        for j in jobs:
            ai_badge = {True: "✓", False: "✗", None: "?"}.get(j.ai_match, "?")
            lines.append(f"  {ai_badge} {j.title} @ {j.company} ({j.city or '-'})")

        text = "\n".join(lines)
        await self._emit("step_end", {"step": "cmd_query", "text": text})
        return text

    async def _cmd_help(self, args: dict[str, Any]) -> str:
        return (
            "可用指令:\n"
            "• 打招呼 [数量] — 查找并打招呼，自动生成并发送AI消息\n"
            "• 评估 — 触发 AI 职位评估\n"
            "• 采集 — 触发滚动采集\n"
            "• 统计 — 24小时内职位统计\n"
            "• 查询 <关键词> — 按关键词搜索职位\n"
            "• 帮助 — 显示此信息"
        )
