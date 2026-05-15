import asyncio
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from job_buddy.core.config import Settings


class BossClientProtocol(Protocol):
    async def search_jobs(self, query: dict[str, Any]) -> list[dict[str, Any]]: ...
    async def greet_job(self, job: dict[str, Any], message: str | None = None) -> dict[str, Any]: ...
    async def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]: ...
    async def healthcheck(self) -> dict[str, Any]: ...


@dataclass
class LocalBossStubClient:
    async def search_jobs(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        keyword = ",".join(query.get("keywords", [])) or "Python"
        return [
            {
                "job_id": "demo-backend-001",
                "title": f"{keyword} Backend Engineer",
                "company": "Demo Tech",
                "city": query.get("city") or "Shanghai",
                "salary": query.get("salary") or "20-30K",
                "experience": query.get("experience") or "3-5 years",
            },
            {
                "job_id": "demo-platform-002",
                "title": f"{keyword} Platform Engineer",
                "company": "Example AI",
                "city": query.get("city") or "Remote",
                "salary": query.get("salary") or "25-35K",
                "experience": query.get("experience") or "5+ years",
            },
        ]

    async def greet_job(self, job: dict[str, Any], message: str | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "job_id": job["source_job_id"],
            "message": message or "你好，我对这个岗位很感兴趣。",
        }

    async def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        now = datetime.now(tz=UTC).isoformat()
        return [
            {
                "conversation_id": "conversation-demo-001",
                "title": "后端工程师",
                "company": "Demo Tech",
                "last_message": "方便发一份简历吗？",
                "unread_count": 1,
                "last_message_at": now,
            }
        ][:limit]

    async def healthcheck(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "local_stub"}


def build_boss_client(settings: Settings) -> BossClientProtocol:
    _ = settings
    return LocalBossStubClient()


@dataclass
class BossDoctorResult:
    ok: bool
    summary: str
    data_dir: str | None
    checks: list[dict]
    next_actions: list[str]
    stderr: str
    exit_code: int
    error: dict | None = None


class BossDoctorRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_command(self) -> list[str]:
        if shutil.which(self.settings.boss_cli_bin):
            command = [self.settings.boss_cli_bin]
        else:
            command = [sys.executable, "-m", "boss_agent_cli.main"]

        if self.settings.boss_data_dir:
            command.extend(["--data-dir", self.settings.boss_data_dir])
        if self.settings.boss_cdp_url:
            command.extend(["--cdp-url", self.settings.boss_cdp_url])

        command.extend(["--json", "doctor"])
        return command

    async def run(self) -> BossDoctorResult:
        process = await asyncio.create_subprocess_exec(
            *self.build_command(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        payload = self._parse_payload(stdout_text)
        data = payload.get("data") or {}
        hints = payload.get("hints") or {}

        return BossDoctorResult(
            ok=bool(payload.get("ok")),
            summary=data.get("summary", "unknown"),
            data_dir=data.get("data_dir"),
            checks=data.get("checks", []),
            next_actions=hints.get("next_actions", []),
            stderr=stderr_text,
            exit_code=process.returncode or 0,
            error=payload.get("error"),
        )

    def _parse_payload(self, stdout_text: str) -> dict:
        if not stdout_text:
            return {
                "ok": False,
                "data": {"summary": "broken", "data_dir": None, "checks": []},
                "error": {"code": "empty_output", "message": "boss doctor 未返回可解析内容"},
                "hints": {"next_actions": ["检查 boss 命令是否可执行，再重试诊断"]},
            }

        try:
            return json.loads(stdout_text)
        except json.JSONDecodeError:
            for line in reversed([line for line in stdout_text.splitlines() if line.strip()]):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        return {
            "ok": False,
            "data": {"summary": "broken", "data_dir": None, "checks": []},
            "error": {"code": "invalid_output", "message": stdout_text},
            "hints": {"next_actions": ["检查 boss doctor 输出格式是否发生变化"]},
        }
