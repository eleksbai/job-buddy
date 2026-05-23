from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
import logging
import random
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from job_buddy.boss import (
    BossClient,
    BossDoctorRunner,
    BossOperationError,
    map_boss_operation_error,
    normalize_search_query,
)
from job_buddy.boss.config import (
    CITY_CODES,
    EDUCATION_CODES,
    EXPERIENCE_CODES,
    INDUSTRY_CODES,
    JOB_TYPE_CODES,
    SALARY_CODES,
    SCALE_CODES,
    STAGE_CODES,
)
from job_buddy.boss.schemas import ChatHistoryIn, FriendListIn, GreetJobIn, JobDetailIn, LoginIn, LoginOut, SearchIn, \
    SendMessageIn, SearchOut
from job_buddy.config import Settings
from job_buddy.models import (
    AuthState,
    DocumentModel,
    FriendMessage,
    FriendRecord,
    GreetingRecord,
    GreetingTask,
    JobCollectionRecord,
    JobCollectionTrace,
    JobLead,
    TASK_TIMEOUT,
    TargetProfile,
    TaskStatus,
    WorkerConfig,
    utc_now,
)
from job_buddy.schemas import (
    AuthStatusResponse,
    DataClearResponse,
    DoctorCheckResponse,
    DoctorErrorResponse,
    DoctorResponse,
    FriendMessagesResponse,
    HealthResponse,
    FriendSyncResponse,
    FriendRecordRead,
    LogLineResponse,
    LogsResponse,
    SearchOptionsResponse,
    SendMessageResponse,
    WorkerConfigUpdate,
)

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))
ModelT = TypeVar("ModelT", bound=DocumentModel)


async def _list_models(
        collection: AsyncIOMotorCollection,
        model_cls: type[ModelT],
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 0,
        sort_by: str = "updated_at",
) -> list[ModelT]:
    cursor = collection.find(filters or {}).sort(sort_by, -1)
    if limit > 0:
        cursor = cursor.limit(limit)
    return [model_cls.from_mongo(item) for item in await cursor.to_list(length=limit or None)]


async def _get_model(
        collection: AsyncIOMotorCollection,
        model_cls: type[ModelT],
        entity_id: str,
) -> ModelT | None:
    payload = await collection.find_one({"_id": ObjectId(entity_id)})
    if not payload:
        return None
    return model_cls.from_mongo(payload)


async def _create_model(
        collection: AsyncIOMotorCollection,
        entity: ModelT,
        model_cls: type[ModelT],
) -> ModelT:
    payload = entity.to_mongo()
    payload.pop("_id", None)
    result = await collection.insert_one(payload)
    stored = await collection.find_one({"_id": result.inserted_id})
    return model_cls.from_mongo(stored)


async def _update_model(
        collection: AsyncIOMotorCollection,
        model_cls: type[ModelT],
        entity_id: str,
        updates: dict[str, Any],
) -> ModelT | None:
    updates["updated_at"] = utc_now()
    await collection.update_one({"_id": ObjectId(entity_id)}, {"$set": updates})
    return await _get_model(collection, model_cls, entity_id)


async def _delete_model(collection: AsyncIOMotorCollection, entity_id: str) -> bool:
    result = await collection.delete_one({"_id": ObjectId(entity_id)})
    return result.deleted_count > 0


def _format_last_time(ts_ms: float) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=_CST)
    now = datetime.now(tz=_CST)
    today = now.date()
    date = dt.date()
    hm = dt.strftime("%H:%M")
    if date == today:
        return f"今天 {hm}"
    if date == today - timedelta(days=1):
        return f"昨天 {hm}"
    if date == today - timedelta(days=2):
        return f"前天 {hm}"
    if date.year == today.year:
        return f"{date.month}月{date.day}日 {hm}"
    return f"{date.year}年{date.month}月{date.day}日 {hm}"


def _extract_self_id(item: dict[str, Any]) -> str | None:
    raw = item.get("raw_payload", item)
    boss_uid = item.get("boss_uid") or raw.get("uid")
    last_message_info = raw.get("lastMessageInfo") or {}
    if not boss_uid or not isinstance(last_message_info, dict):
        return None
    from_id = last_message_info.get("fromId")
    to_id = last_message_info.get("toId")
    if from_id is not None and str(from_id) == str(boss_uid) and to_id is not None:
        return str(to_id)
    if to_id is not None and str(to_id) == str(boss_uid) and from_id is not None:
        return str(from_id)
    return None


def _extract_self_id_from_messages(boss_uid: str | None, messages: list[dict[str, Any]]) -> str | None:
    if not boss_uid:
        return None
    for message in messages:
        raw = message.get("raw_payload") or message
        from_id = ((raw.get("from") or {}).get("uid")) or message.get("from_id")
        to_id = (raw.get("to") or {}).get("uid")
        if from_id is not None and str(from_id) == str(boss_uid) and to_id is not None:
            return str(to_id)
        if to_id is not None and str(to_id) == str(boss_uid) and from_id is not None:
            return str(from_id)
    return None


def _normalize_friend_messages(messages: list[dict[str, Any]]) -> list[FriendMessage]:
    deduped: dict[str, FriendMessage] = {}
    for message in messages:
        message_id = str(message.get("message_id") or "")
        if not message_id:
            continue
        deduped[message_id] = FriendMessage(
            message_id=message_id,
            from_id=str(message.get("from_id") or ""),
            from_name=message.get("from_name"),
            content=str(message.get("content") or ""),
            msg_type=message.get("type"),
            sent_at=message.get("created_at"),
            raw_payload=dict(message.get("raw_payload") or message),
        )
    return sorted(
        deduped.values(),
        key=lambda item: (item.sent_at if item.sent_at is not None else -1, item.message_id),
    )


def _merge_friend_messages(
        existing: list[dict[str, Any]] | list[FriendMessage] | None,
        incoming: list[dict[str, Any]],
        limit: int = 100,
) -> list[FriendMessage]:
    merged_inputs: list[dict[str, Any]] = []
    for message in existing or []:
        if isinstance(message, FriendMessage):
            merged_inputs.append(
                {
                    "message_id": message.message_id,
                    "from_id": message.from_id,
                    "from_name": message.from_name,
                    "content": message.content,
                    "type": message.msg_type,
                    "created_at": message.sent_at,
                    "raw_payload": message.raw_payload,
                }
            )
        elif isinstance(message, dict):
            merged_inputs.append(
                {
                    "message_id": message.get("message_id"),
                    "from_id": message.get("from_id"),
                    "from_name": message.get("from_name"),
                    "content": message.get("content"),
                    "type": message.get("msg_type", message.get("type")),
                    "created_at": message.get("sent_at", message.get("created_at")),
                    "raw_payload": message.get("raw_payload", message),
                }
            )
    merged_inputs.extend(incoming)
    normalized = _normalize_friend_messages(merged_inputs)
    if len(normalized) > limit:
        normalized = normalized[-limit:]
    return normalized


def _detect_log_level(line: str) -> str:
    upper_line = line.upper()
    if " ERROR " in upper_line:
        return "error"
    if " WARNING " in upper_line or " WARN " in upper_line:
        return "warn"
    if " DEBUG " in upper_line:
        return "debug"
    return "info"


class BossAuthService:
    def __init__(self, boss_client: BossClient, auth_states: AsyncIOMotorCollection) -> None:
        self.boss_client = boss_client
        self.auth_states = auth_states

    async def get_current_auth_state(self, provider: str = "zhipin") -> AuthState | None:
        payload = await self.auth_states.find_one({"provider": provider})
        if not payload:
            return None
        return AuthState.from_mongo(payload)

    async def upsert_auth_state(self, state: AuthState) -> AuthState:
        existing = await self.get_current_auth_state(provider=state.provider)
        payload = state.to_mongo()
        payload.pop("_id", None)
        payload["updated_at"] = utc_now()
        if existing is None:
            result = await self.auth_states.insert_one(payload)
            stored = await self.auth_states.find_one({"_id": result.inserted_id})
            return AuthState.from_mongo(stored)
        await self.auth_states.update_one({"_id": ObjectId(existing.id)}, {"$set": payload})
        refreshed = await _get_model(self.auth_states, AuthState, existing.id)
        if refreshed is None:
            raise RuntimeError("failed to refresh auth state")
        return refreshed

    async def sync_auth_state(
            self,
            local: LoginOut,
            stored: AuthState | None,
    ) -> AuthState:
        current = stored or AuthState()
        payload = AuthState(
            id=current.id,
            provider=current.provider,
            logged_in=local.logged_in,
            user_name=local.user_name,
            city=local.city or None,
            ip=local.ip or None,
            uid=local.uid or None,
            last_error=current.last_error,
            created_at=current.created_at,
        )
        if local.logged_in:
            payload.last_error = None
        return await self.upsert_auth_state(payload)

    async def refresh_auth_state(self) -> tuple[LoginOut, AuthState]:
        try:
            local = await self.boss_client.get_auth_status()
        except Exception as exc:
            raise map_boss_operation_error(exc) from exc
        stored = await self.get_current_auth_state()
        state = await self.sync_auth_state(local, stored)
        return local, state

    async def require_authenticated(self) -> LoginOut:
        local, _ = await self.refresh_auth_state()
        if local.logged_in:
            return local
        message = local.message or "未登录，请先点击页面右上角登录"
        code = "TOKEN_INVALID" if "无效" in message else "AUTH_REQUIRED"
        raise BossOperationError(
            code=code,
            message=message,
            recoverable=True,
            recovery_action="login",
            status_code=401,
            boss_side=True,
        )


class TargetProfileService:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.targets = database["target_profiles"]

    async def list_targets(self) -> list[TargetProfile]:
        return await _list_models(self.targets, TargetProfile, limit=200)

    async def get_target(self, target_id: str) -> TargetProfile:
        target = await _get_model(self.targets, TargetProfile, target_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target profile not found.")
        return target

    async def create_target(self, payload) -> TargetProfile:
        return await _create_model(self.targets, TargetProfile(**payload.model_dump()), TargetProfile)

    async def update_target(self, target_id: str, payload) -> TargetProfile:
        target = await _update_model(self.targets, TargetProfile, target_id, payload.model_dump(exclude_none=True))
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target profile not found.")
        return target

    async def delete_target(self, target_id: str) -> None:
        deleted = await _delete_model(self.targets, target_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target profile not found.")


class JobCollectionService:
    def __init__(self, database: AsyncIOMotorDatabase, boss_client: BossClient) -> None:
        self.jobs = database["job_leads"]
        self.records = database["job_collection_records"]
        self.traces = database["job_collection_traces"]
        self.tasks = database["greeting_tasks"]
        self.friends = database["friend_records"]
        self.auth_states = database["boss_auth_state"]
        self.boss_client = boss_client
        self._auth_service: BossAuthService | None = None

    @property
    def auth_service(self) -> BossAuthService:
        auth_service = getattr(self, "_auth_service", None)
        if auth_service is None:
            auth_service = BossAuthService(self.boss_client, self.auth_states)
            self._auth_service = auth_service
        return auth_service

    async def list_jobs(self, match_status: str | None, greeted: bool | None, limit: int) -> list[JobLead]:
        filters: dict[str, Any] = {}
        if match_status:
            filters["match_status"] = match_status
        if greeted is not None:
            filters["greeted"] = greeted
        cursor = self.jobs.find(filters).sort([("last_searched_at", -1), ("_id", -1)]).limit(limit)
        return [JobLead.from_mongo(item) for item in await cursor.to_list(length=limit)]

    async def list_collection_records(
            self,
            task_id: str | None,
            target_profile_id: str | None,
            source_job_id: str | None,
            limit: int,
    ) -> list[JobCollectionRecord]:
        filters: dict[str, Any] = {}
        if task_id:
            filters["task_id"] = task_id
        if target_profile_id:
            filters["target_profile_id"] = target_profile_id
        if source_job_id:
            filters["source_job_id"] = source_job_id
        return await _list_models(self.records, JobCollectionRecord, filters=filters, limit=limit)

    async def get_job_detail(
            self,
            source_job_id: str,
            security_id: str | None = None,
            force_refresh: bool = False,
    ) -> tuple[JobLead, bool]:
        job = await self._get_job_by_source_job_id(source_job_id)
        if job is None:
            if not security_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
            await self.auth_service.require_authenticated()
            try:
                detail_result = await self.boss_client.get_job_detail(
                    JobDetailIn(
                        job_id=source_job_id,
                        security_id=security_id,
                        job_url=None,
                        title=source_job_id,
                        company="",
                    )
                )
            except Exception as exc:
                logger.warning(
                    "BOSS detail fetch failed (new job): source_job_id=%s security_id=%s error=%s",
                    source_job_id, security_id, exc,
                )
                raise map_boss_operation_error(exc) from exc
            job = await _create_model(
                self.jobs,
                JobLead(
                    source_job_id=source_job_id,
                    security_id=security_id,
                    source_friend_id=detail_result.encrypt_boss_id or None,
                    contact=detail_result.contact,
                    boss_online=detail_result.boss_online,
                    boss_active_text=detail_result.boss_active_text or None,
                    job_active_time=detail_result.job_active_time or None,
                    title=detail_result.job.title or source_job_id,
                    company=detail_result.company.name or "",
                    city=detail_result.job.city or None,
                    salary=detail_result.job.salary or None,
                    experience=detail_result.job.experience or None,
                    job_url=detail_result.job_url or None,
                    detail_payload=detail_result.model_dump(),
                    detail_text=detail_result.detail_text,
                    detail_source_url=detail_result.request_url,
                    detail_fetched_at=utc_now(),
                ),
                JobLead,
            )
            await self._sync_job_to_friends(job)
            return job, False

        if not force_refresh and job.detail_payload and job.detail_text:
            return job, True

        await self.auth_service.require_authenticated()
        try:
            detail_result = await self.boss_client.get_job_detail(
                JobDetailIn(
                    job_id=job.source_job_id,
                    security_id=job.security_id,
                    job_url=job.job_url,
                    title=job.title,
                    company=job.company,
                )
            )
        except Exception as exc:
            logger.warning(
                "BOSS detail fetch failed (existing job): source_job_id=%s job_url=%s error=%s",
                job.source_job_id, job.job_url, exc,
            )
            raise map_boss_operation_error(exc) from exc

        updated = await _update_model(
            self.jobs,
            JobLead,
            job.id,
            {
                "title": detail_result.job.title or job.title,
                "company": detail_result.company.name or job.company,
                "city": detail_result.job.city or job.city,
                "salary": detail_result.job.salary or job.salary,
                "experience": detail_result.job.experience or job.experience,
                "source_friend_id": detail_result.encrypt_boss_id or job.source_friend_id,
                "contact": detail_result.contact,
                "boss_online": detail_result.boss_online,
                "boss_active_text": detail_result.boss_active_text or job.boss_active_text,
                "job_active_time": detail_result.job_active_time or job.job_active_time,
                "job_url": detail_result.job_url or job.job_url,
                "detail_payload": detail_result.model_dump(),
                "detail_text": detail_result.detail_text,
                "detail_source_url": detail_result.request_url or detail_result.job_url or job.job_url,
                "detail_fetched_at": utc_now(),
            },
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job update failed.")
        await self._sync_job_to_friends(updated)
        return updated, False

    async def search_jobs_readonly(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            await self.auth_service.require_authenticated()
            normalized_query = normalize_search_query(
                query,
                city_codes=CITY_CODES,
                salary_codes=SALARY_CODES,
                experience_codes=EXPERIENCE_CODES,
                education_codes=EDUCATION_CODES,
                industry_codes=INDUSTRY_CODES,
                scale_codes=SCALE_CODES,
                stage_codes=STAGE_CODES,
                job_type_codes=JOB_TYPE_CODES,
            )
            search_result = await self.boss_client.search(SearchIn(query=normalized_query))
        except Exception as exc:
            logger.warning("BOSS search (readonly) failed: query=%s error=%s", query, exc)
            raise map_boss_operation_error(exc) from exc
        return [
            {
                "source_job_id": item.job_id,
                "title": item.title,
                "company": item.company,
                "city": item.city,
                "salary": item.salary,
                "experience": item.experience,
                "job_url": item.job_url,
            }
            for item in search_result.items
        ]

    async def search_jobs(self, query: dict[str, Any], target: TargetProfile | None = None) -> GreetingTask:
        task = await _create_model(
            self.tasks,
            GreetingTask(
                task_type="search",
                status=TaskStatus.RUNNING,
                target_profile_id=target.id if target else None,
                input_payload=query,
                started_at=utc_now(),
            ),
            GreetingTask,
        )
        try:
            search_out =  await asyncio.wait_for(self._do_search(task, query, target), timeout=TASK_TIMEOUT)
        except asyncio.TimeoutError:
            current = await _get_model(self.tasks, GreetingTask, task.id)
            step = "unknown"
            if current and current.result_summary:
                step = current.result_summary.get("step", "unknown")
            logger.error("search task timed out: task_id=%s step=%s query=%s", task.id, step, query)
            failed = await _update_model(
                self.tasks,
                GreetingTask,
                task.id,
                {
                    "status": TaskStatus.FAILED,
                    "error_message": f"任务超时（{TASK_TIMEOUT}s），卡在步骤: {step}",
                    "finished_at": utc_now(),
                },
            )
            if failed is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
            return failed
        except Exception as exc:
            logger.exception(
                "search task failed: task_id=%s target_profile_id=%s query=%s",
                task.id,
                target.id if target else None,
                query,
            )
            failed = await _update_model(
                self.tasks,
                GreetingTask,
                task.id,
                {
                    "status": TaskStatus.FAILED,
                    "error_message": str(exc),
                    "finished_at": utc_now(),
                },
            )
            if failed is None:
                raise
            return failed

        updated = await _get_model(self.tasks, GreetingTask, task.id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
        return updated

    async def run_detail_sync(self, limit: int = 1) -> GreetingTask:
        task = await _create_model(
            self.tasks,
            GreetingTask(
                task_type="detail_sync",
                status=TaskStatus.RUNNING,
                input_payload={"limit": limit},
                started_at=utc_now(),
            ),
            GreetingTask,
        )
        try:
            await asyncio.wait_for(self._do_detail_sync(task, limit), timeout=TASK_TIMEOUT)
        except asyncio.TimeoutError:
            current = await _get_model(self.tasks, GreetingTask, task.id)
            step = "unknown"
            if current and current.result_summary:
                step = current.result_summary.get("step", "unknown")
            failed = await _update_model(
                self.tasks,
                GreetingTask,
                task.id,
                {
                    "status": TaskStatus.FAILED,
                    "error_message": f"任务超时（{TASK_TIMEOUT}s），卡在步骤: {step}",
                    "finished_at": utc_now(),
                },
            )
            if failed is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
            return failed
        except Exception as exc:
            logger.exception("detail sync task failed: task_id=%s limit=%s", task.id, limit)
            failed = await _update_model(
                self.tasks,
                GreetingTask,
                task.id,
                {
                    "status": TaskStatus.FAILED,
                    "error_message": str(exc),
                    "finished_at": utc_now(),
                },
            )
            if failed is None:
                raise
            return failed

        updated = await _get_model(self.tasks, GreetingTask, task.id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
        return updated

    async def _do_search(self, task: GreetingTask, query: dict[str, Any], target: TargetProfile | None) -> SearchOut:
        await self._update_task_step(task.id, "healthcheck")
        try:
            await self.auth_service.require_authenticated()
            normalized_query = normalize_search_query(
                query,
                city_codes=CITY_CODES,
                salary_codes=SALARY_CODES,
                experience_codes=EXPERIENCE_CODES,
                education_codes=EDUCATION_CODES,
                industry_codes=INDUSTRY_CODES,
                scale_codes=SCALE_CODES,
                stage_codes=STAGE_CODES,
                job_type_codes=JOB_TYPE_CODES,
            )
            search_result = await self.boss_client.search(SearchIn(query=normalized_query))
        except Exception as exc:
            logger.warning("BOSS search failed: task_id=%s query=%s error=%s", task.id, query, exc)
            raise map_boss_operation_error(exc) from exc

        await self._update_task_step(task.id, "persist_results")
        trace_id: str | None = None
        if search_result.trace:
            requested_at = search_result.trace.get("requested_at")
            response_received_at = search_result.trace.get("response_received_at")
            trace = await _create_model(
                self.traces,
                JobCollectionTrace(
                    task_id=task.id,
                    target_profile_id=target.id if target else None,
                    engine=search_result.trace.get("engine"),
                    browser=search_result.trace.get("browser"),
                    request_url=search_result.trace.get("request_url"),
                    referer=search_result.trace.get("referer"),
                    requested_at=datetime.fromisoformat(requested_at) if isinstance(requested_at, str) else None,
                    response_received_at=datetime.fromisoformat(response_received_at) if isinstance(
                        response_received_at, str) else None,
                    request_payload=dict(search_result.trace.get("request_payload") or {}),
                    request_params=dict(search_result.trace.get("request_params") or {}),
                    response_payload=dict(search_result.trace.get("response_payload") or {}),
                    result_count=int(search_result.trace.get("result_count") or 0),
                ),
                JobCollectionTrace,
            )
            trace_id = trace.id

        dedup_created = 0
        dedup_updated = 0
        collected = 0
        for item in search_result.items:
            await _create_model(
                self.records,
                JobCollectionRecord(
                    task_id=task.id,
                    trace_id=trace_id,
                    target_profile_id=target.id if target else None,
                    source_job_id=item.job_id,
                    security_id=item.security_id,
                    title=item.title,
                    company=item.company,
                    city=item.city,
                    salary=item.salary,
                    experience=item.experience,
                    job_url=item.job_url,
                    raw_payload=item.raw_payload,
                ),
                JobCollectionRecord,
            )
            collected += 1

            existing = await self._get_job_by_source_job_id(item.job_id)
            if existing is None:
                await _create_model(
                    self.jobs,
                    JobLead(
                        source_job_id=item.job_id,
                        security_id=item.security_id,
                        source_friend_id=item.encrypt_boss_id,
                        contact=item.contact,
                        boss_online=item.boss_online,
                        boss_active_text=item.boss_active_text,
                        job_active_time=item.job_active_time,
                        title=item.title,
                        company=item.company,
                        city=item.city,
                        salary=item.salary,
                        experience=item.experience,
                        job_url=item.job_url,
                        match_status="matched" if target else "new",
                        raw_payload=item.raw_payload,
                        search_count=1,
                        last_searched_at=utc_now(),
                    ),
                    JobLead,
                )
                dedup_created += 1
            else:
                await _update_model(
                    self.jobs,
                    JobLead,
                    existing.id,
                    {
                        "security_id": item.security_id,
                        "source_friend_id": item.encrypt_boss_id or existing.source_friend_id,
                        "contact": item.contact if item.contact is not None else existing.contact,
                        "boss_online": item.boss_online if item.boss_online is not None else existing.boss_online,
                        "boss_active_text": item.boss_active_text or existing.boss_active_text,
                        "job_active_time": item.job_active_time if item.job_active_time is not None else existing.job_active_time,
                        "title": item.title,
                        "company": item.company,
                        "city": item.city,
                        "salary": item.salary,
                        "experience": item.experience,
                        "job_url": item.job_url,
                        "raw_payload": item.raw_payload,
                        "last_seen_at": utc_now(),
                        "last_searched_at": utc_now(),
                        "search_count": max(1, existing.search_count) + 1,
                    },
                )
                dedup_updated += 1

        await _update_model(
            self.tasks,
            GreetingTask,
            task.id,
            {
                "status": TaskStatus.SUCCEEDED,
                "result_summary": {
                    "fetched": len(search_result.items),
                    "collected": collected,
                    "dedup_created": dedup_created,
                    "dedup_updated": dedup_updated,
                },
                "finished_at": utc_now(),
            },
        )
        return search_result


    async def _do_detail_sync(self, task: GreetingTask, limit: int) -> None:
        await self._update_task_step(task.id, "fetch_jobs")
        cursor = self.jobs.find({"detail_fetched_at": None}).sort([("last_searched_at", -1), ("_id", -1)]).limit(limit)
        jobs = [JobLead.from_mongo(item) for item in await cursor.to_list(length=limit)]

        succeeded = 0
        failed = 0
        for idx, job in enumerate(jobs):
            await self._update_task_step(task.id, f"detail_job_{idx + 1}_of_{len(jobs)}")
            try:
                await self.get_job_detail(job.source_job_id, force_refresh=False)
                succeeded += 1
            except Exception as exc:
                logger.warning("detail sync failed: task_id=%s source_job_id=%s error=%s", task.id, job.source_job_id,
                               exc)
                failed += 1

        final_status = TaskStatus.SUCCEEDED
        if failed and succeeded:
            final_status = TaskStatus.PARTIAL_SUCCESS
        elif failed and not succeeded:
            final_status = TaskStatus.FAILED

        await _update_model(
            self.tasks,
            GreetingTask,
            task.id,
            {
                "status": final_status,
                "result_summary": {"total": len(jobs), "succeeded": succeeded, "failed": failed},
                "finished_at": utc_now(),
            },
        )

    async def _update_task_step(self, task_id: str, step: str) -> None:
        await _update_model(self.tasks, GreetingTask, task_id, {"result_summary": {"step": step}})

    async def _get_job_by_source_job_id(self, source_job_id: str) -> JobLead | None:
        payload = await self.jobs.find_one({"source_job_id": source_job_id})
        if not payload:
            return None
        return JobLead.from_mongo(payload)

    async def _sync_job_to_friends(self, job: JobLead) -> None:
        if not job.source_friend_id:
            return
        updates: dict[str, Any] = {
            "title": job.title,
            "company": job.company,
            "security_id": job.security_id,
            "source_job_id": job.source_job_id,
            "updated_at": utc_now(),
        }
        await self.friends.update_one({"source_friend_id": job.source_friend_id}, {"$set": updates})


class GreetingService:
    def __init__(self, database: AsyncIOMotorDatabase, boss_client: BossClient) -> None:
        self.tasks = database["greeting_tasks"]
        self.records = database["greeting_records"]
        self.jobs = database["job_leads"]
        self.auth_states = database["boss_auth_state"]
        self.boss_client = boss_client
        self._auth_service: BossAuthService | None = None

    @property
    def auth_service(self) -> BossAuthService:
        auth_service = getattr(self, "_auth_service", None)
        if auth_service is None:
            auth_service = BossAuthService(self.boss_client, self.auth_states)
            self._auth_service = auth_service
        return auth_service

    async def run_greetings(
            self,
            target: TargetProfile | None,
            source_job_ids: list[str],
            greeting_message: str | None,
            limit: int,
    ) -> GreetingTask:
        task = await _create_model(
            self.tasks,
            GreetingTask(
                task_type="greet",
                status=TaskStatus.RUNNING,
                target_profile_id=target.id if target else None,
                input_payload={"source_job_ids": source_job_ids, "greeting_message": greeting_message, "limit": limit},
                started_at=utc_now(),
            ),
            GreetingTask,
        )
        try:
            await asyncio.wait_for(self._do_greet(task, target, source_job_ids, greeting_message, limit),
                                   timeout=TASK_TIMEOUT)
        except asyncio.TimeoutError:
            current = await _get_model(self.tasks, GreetingTask, task.id)
            step = "unknown"
            if current and current.result_summary:
                step = current.result_summary.get("step", "unknown")
            failed = await _update_model(
                self.tasks,
                GreetingTask,
                task.id,
                {
                    "status": TaskStatus.FAILED,
                    "error_message": f"任务超时（{TASK_TIMEOUT}s），卡在步骤: {step}",
                    "finished_at": utc_now(),
                },
            )
            if failed is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
            return failed

        updated = await _get_model(self.tasks, GreetingTask, task.id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
        return updated

    async def _do_greet(
            self,
            task: GreetingTask,
            target: TargetProfile | None,
            source_job_ids: list[str],
            greeting_message: str | None,
            limit: int,
    ) -> None:
        await self._update_step(task.id, "fetch_jobs")
        await self.auth_service.require_authenticated()
        if source_job_ids:
            jobs = []
            for source_job_id in source_job_ids:
                payload = await self.jobs.find_one({"source_job_id": source_job_id})
                if payload:
                    jobs.append(JobLead.from_mongo(payload))
        else:
            cursor = self.jobs.find({"greeted": False}).sort([("last_searched_at", -1), ("_id", -1)]).limit(limit)
            jobs = [JobLead.from_mongo(item) for item in await cursor.to_list(length=limit)]

        success_count = 0
        failed_count = 0
        default_message = greeting_message or (target.greeting_template if target else None)
        for idx, job in enumerate(jobs):
            await self._update_step(task.id, f"greet_job_{idx + 1}_of_{len(jobs)}")
            try:
                try:
                    response = await self.boss_client.greet_job(
                        GreetJobIn(
                            job_id=job.source_job_id,
                            security_id=str(job.security_id or ""),
                        )
                    )
                except Exception as exc:
                    logger.warning("BOSS greet failed: task_id=%s source_job_id=%s error=%s", task.id,
                                   job.source_job_id, exc)
                    raise map_boss_operation_error(exc) from exc
                await _create_model(
                    self.records,
                    GreetingRecord(
                        task_id=task.id,
                        job_lead_id=job.id,
                        source_job_id=job.source_job_id,
                        status="succeeded",
                        message=default_message,
                        response_payload=response.model_dump(),
                    ),
                    GreetingRecord,
                )
                await _update_model(
                    self.jobs,
                    JobLead,
                    job.id,
                    {
                        "greeted": True,
                        "contact": True,
                        "source_friend_id": response.encrypt_boss_id or job.source_friend_id,
                    },
                )
                success_count += 1
            except Exception as exc:
                await _create_model(
                    self.records,
                    GreetingRecord(
                        task_id=task.id,
                        job_lead_id=job.id,
                        source_job_id=job.source_job_id,
                        status="failed",
                        message=default_message,
                        response_payload={"error": str(exc)},
                    ),
                    GreetingRecord,
                )
                failed_count += 1

        final_status = TaskStatus.SUCCEEDED
        if failed_count and success_count:
            final_status = TaskStatus.PARTIAL_SUCCESS
        elif failed_count and not success_count:
            final_status = TaskStatus.FAILED

        await _update_model(
            self.tasks,
            GreetingTask,
            task.id,
            {
                "status": final_status,
                "result_summary": {"total": len(jobs), "succeeded": success_count, "failed": failed_count},
                "finished_at": utc_now(),
            },
        )

    async def _update_step(self, task_id: str, step: str) -> None:
        await _update_model(self.tasks, GreetingTask, task_id, {"result_summary": {"step": step}})

    async def get_task_detail(self, task_id: str) -> tuple[GreetingTask, list[GreetingRecord]]:
        task = await _get_model(self.tasks, GreetingTask, task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        records = await _list_models(self.records, GreetingRecord, filters={"task_id": task_id}, limit=500)
        return task, records

    async def list_tasks(self, limit: int) -> list[GreetingTask]:
        return await _list_models(self.tasks, GreetingTask, limit=limit)


class WorkerFailException(Exception):
    pass


class BaseWorker(ABC):
    worker_name: str

    def __init__(
        self,
        database: AsyncIOMotorDatabase,
        boss_client: BossClient,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.database = database
        self.boss_client = boss_client
        self.worker_configs = database["worker_configs"]
        self.tasks = database["greeting_tasks"]
        self.poll_interval_seconds = poll_interval_seconds
        self._run_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    @abstractmethod
    def default_config(self) -> WorkerConfig:
        raise NotImplementedError

    async def sync_default_on_startup(self) -> WorkerConfig:
        await self.ensure_default()
        return await self._update_worker_model(
            {
                "enabled": False,
                "status": "idle",
                "next_run_at": None,
                "last_error": None,
            }
        )

    async def ensure_default(self) -> WorkerConfig:
        payload = await self.worker_configs.find_one({"worker_name": self.worker_name})
        if payload is None:
            return await _create_model(
                self.worker_configs,
                self.default_config(),
                WorkerConfig,
            )
        return WorkerConfig.from_mongo(payload)

    async def get_worker(self) -> WorkerConfig:
        payload = await self.worker_configs.find_one({"worker_name": self.worker_name})
        if payload is None:
            return await self.ensure_default()
        return WorkerConfig.from_mongo(payload)

    async def update_worker(self, payload: WorkerConfigUpdate) -> WorkerConfig:
        current = await self.get_worker()
        updates = payload.model_dump(exclude_none=True)
        self._validate_common_updates(updates)
        self.validate_updates(current, updates)
        return await self._update_worker_model(updates)

    def _validate_common_updates(self, updates: dict[str, Any]) -> None:
        if "interval_seconds" in updates and int(updates["interval_seconds"]) < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="interval_seconds 必须大于等于 1")
        if "page" in updates and int(updates["page"]) < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="page 必须大于等于 1")
        if "page_max" in updates and int(updates["page_max"]) < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="page_max 必须大于等于 1")
        if "batch_size" in updates and int(updates["batch_size"]) < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="batch_size 必须大于等于 1")

    def validate_updates(self, current: WorkerConfig, updates: dict[str, Any]) -> None:
        _ = current, updates

    def validate_before_start(self, worker: WorkerConfig) -> None:
        _ = worker

    async def start_worker(self) -> WorkerConfig:
        current = await self.get_worker()
        self.validate_before_start(current)
        return await self._update_worker_model(
            {"enabled": True, "status": "idle", "next_run_at": utc_now(), "last_error": None}
        )

    async def stop_worker(self) -> WorkerConfig:
        return await self._update_worker_model(
            {"enabled": False, "status": "idle", "next_run_at": None, "last_error": None}
        )

    async def has_running_task(self) -> bool:
        return await self.tasks.count_documents({"status": TaskStatus.RUNNING}) > 0

    async def run_once(self) -> WorkerConfig:
        worker = await self.get_worker()
        if not self._is_due(worker) or await self.has_running_task():
            return worker
        async with self._run_lock:
            if await self.has_running_task():
                return await self.get_worker()
            worker = await self.get_worker()
            if not self._is_due(worker):
                return worker
            return await self.execute()

    def _is_due(self, worker: WorkerConfig) -> bool:
        return worker.enabled and worker.next_run_at is not None and worker.next_run_at <= utc_now()

    async def execute(self) -> WorkerConfig:
        worker = await self.get_worker()
        if not worker.enabled:
            return worker

        await self._update_worker_model(
            {"status": "running", "last_started_at": utc_now(), "last_error": None}
        )
        try:
            return await self.execute_enabled_worker(worker)
        except WorkerFailException:
            raise
        except Exception as exc:
            logger.exception("worker execution failed: worker=%s", self.worker_name)
            await self._update_worker_model(
                {
                    "status": "error",
                    "last_finished_at": utc_now(),
                    "next_run_at": self._next_run_at_for_interval(worker.interval_seconds),
                    "last_error": str(exc),
                },
            )
            raise WorkerFailException() from exc

    @abstractmethod
    async def execute_enabled_worker(self, worker: WorkerConfig) -> WorkerConfig:
        raise NotImplementedError

    async def complete_execution(
        self,
        worker: WorkerConfig,
        task: GreetingTask,
        *,
        extra_updates: dict[str, Any] | None = None,
    ) -> WorkerConfig:
        next_status = "idle" if task.status == TaskStatus.SUCCEEDED else "error"
        updates = {
            "last_result_summary": dict(task.result_summary),
            "status": next_status,
            "last_finished_at": utc_now(),
            "next_run_at": self._next_run_at_for_interval(worker.interval_seconds),
            "last_error": task.error_message,
        }
        if extra_updates:
            updates.update(extra_updates)
        updated_worker = await self._update_worker_model(updates)
        if task.status != TaskStatus.SUCCEEDED:
            raise WorkerFailException()
        return updated_worker

    async def start(self) -> None:
        await self.sync_default_on_startup()
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name=f"job-buddy-{self.worker_name}-worker")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        fail_count = 0
        while not self._stopped.is_set():
            await asyncio.sleep(random.random() * 5 + 3)
            try:
                await self.run_once()
                fail_count = 0
            except WorkerFailException:
                fail_count += 1
                logger.warning("Worker %s failed, delay %sH", self.worker_name, 2 ** fail_count)
                await asyncio.sleep(2 ** fail_count * 60 * 60)
            except Exception:
                logger.exception("worker loop failed: worker=%s", self.worker_name)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    def _next_run_at_for_interval(self, interval_seconds: int) -> datetime:
        return utc_now() + timedelta(seconds=max(1, interval_seconds))

    async def _update_worker_model(self, updates: dict[str, Any]) -> WorkerConfig:
        current = await self.get_worker()
        updates["updated_at"] = utc_now()
        await self.worker_configs.update_one({"_id": ObjectId(current.id)}, {"$set": updates})
        refreshed = await self.worker_configs.find_one({"_id": ObjectId(current.id)})
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Worker update failed.")
        return WorkerConfig.from_mongo(refreshed)


class SearchWorker(BaseWorker):
    worker_name = "search"

    def default_config(self) -> WorkerConfig:
        return WorkerConfig(worker_name="search", interval_seconds=60, page=1, page_max=5, batch_size=1)

    def validate_updates(self, current: WorkerConfig, updates: dict[str, Any]) -> None:
        next_query = updates.get("query", current.query)
        if updates.get("enabled") and not next_query.get("keywords"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="启动搜索 worker 前请先配置关键词")

    def validate_before_start(self, worker: WorkerConfig) -> None:
        if not worker.query.get("keywords"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="启动搜索 worker 前请先配置关键词")

    async def execute_enabled_worker(self, worker: WorkerConfig) -> WorkerConfig:
        job_service = JobCollectionService(self.database, self.boss_client)
        query = dict(worker.query)
        query["page"] = max(1, int(worker.page))
        logger.info("executing worker %s start", self.worker_name)
        task = await job_service.search_jobs(query=query)
        logger.info("executing worker %s %s", self.worker_name, task.status)
        next_page = worker.page
        if task.status != TaskStatus.FAILED:
            next_page += 1
            if next_page > max(1, worker.page_max):
                await self.boss_client.goto_job()
                next_page = 1
        return await self.complete_execution(worker, task, extra_updates={"page": next_page})


class DetailWorker(BaseWorker):
    worker_name = "detail"

    def default_config(self) -> WorkerConfig:
        return WorkerConfig(worker_name="detail", interval_seconds=30, page=1, page_max=5, batch_size=1)

    async def execute_enabled_worker(self, worker: WorkerConfig) -> WorkerConfig:
        job_service = JobCollectionService(self.database, self.boss_client)
        logger.info("executing worker %s start", self.worker_name)
        task = await job_service.run_detail_sync(limit=max(1, worker.batch_size))
        logger.info("executing worker %s %s", self.worker_name, task.status)
        return await self.complete_execution(worker, task)


class FriendService:
    def __init__(self, database: AsyncIOMotorDatabase, boss_client: BossClient) -> None:
        self.friends = database["friend_records"]
        self.auth_states = database["boss_auth_state"]
        self.boss_client = boss_client
        self._auth_service: BossAuthService | None = None

    @property
    def auth_service(self) -> BossAuthService:
        auth_service = getattr(self, "_auth_service", None)
        if auth_service is None:
            auth_service = BossAuthService(self.boss_client, self.auth_states)
            self._auth_service = auth_service
        return auth_service

    async def _load_friend(self, source_friend_id: str, *, allow_sync: bool) -> dict[str, Any] | None:
        friend = await self.friends.find_one({"source_friend_id": source_friend_id})
        if friend or not allow_sync:
            return friend

        await self.sync_friends()
        return await self.friends.find_one({"source_friend_id": source_friend_id})

    async def list_friends(self) -> list[FriendRecord]:
        now_cst = datetime.now(tz=_CST)
        today_start = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        filters = {"updated_at": {"$gte": today_start, "$lt": tomorrow_start}}
        cursor = self.friends.find(filters).sort("last_message_ts", -1)
        return [FriendRecord.from_mongo(item) for item in await cursor.to_list(length=None)]

    async def get_friend_messages(
            self,
            source_friend_id: str,
            page: int = 1,
            count: int = 20,
            cached_only: bool = False,
    ) -> FriendMessagesResponse:
        friend = await self._load_friend(source_friend_id, allow_sync=not cached_only)
        if not friend:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"未找到 source_friend_id={source_friend_id} 的好友记录",
                recoverable=False,
                status_code=404,
            )

        gid = str(friend.get("gid") or "")
        security_id = friend.get("security_id")
        if cached_only:
            cached_messages = friend.get("messages") or []
            messages = [
                {
                    "message_id": message.get("message_id"),
                    "from_id": message.get("from_id"),
                    "from_name": message.get("from_name"),
                    "content": message.get("content", ""),
                    "type": message.get("msg_type"),
                    "created_at": message.get("sent_at"),
                    "raw_payload": message.get("raw_payload", message),
                }
                for message in cached_messages[-count:]
            ]
            return FriendMessagesResponse(
                gid=gid,
                source_friend_id=source_friend_id,
                security_id=security_id,
                page=1,
                count=len(messages),
                has_more=False,
                total=len(cached_messages),
                messages=messages,
            )

        await self.auth_service.require_authenticated()
        try:
            result = await self.boss_client.get_chat_history(
                ChatHistoryIn(
                    boss_id=source_friend_id,
                    security_id=security_id,
                    page=page,
                    count=count,
                )
            )
        except Exception as exc:
            logger.warning(
                "BOSS friend message fetch failed: source_friend_id=%s gid=%s page=%s count=%s error=%s",
                source_friend_id, gid, page, count, exc,
            )
            raise map_boss_operation_error(exc) from exc

        messages = [message.model_dump() for message in result.messages]
        boss_uid = str(friend.get("boss_uid") or "")
        backfilled_self_id = _extract_self_id_from_messages(boss_uid, messages)
        refreshed_messages = _normalize_friend_messages(messages)

        updates: dict[str, Any] = {
            "messages": [message.model_dump() for message in refreshed_messages],
            "updated_at": utc_now(),
        }
        if messages:
            last_message = messages[-1]
            updates["last_message"] = last_message.get("content") or friend.get("last_message")
            if last_message.get("created_at") is not None:
                try:
                    last_ts = float(last_message["created_at"])
                    updates["last_message_ts"] = last_ts
                    updates["last_message_at"] = _format_last_time(last_ts)
                except (TypeError, ValueError):
                    pass
        if backfilled_self_id and backfilled_self_id != friend.get("self_id"):
            updates["self_id"] = backfilled_self_id
        if updates:
            await self.friends.update_one(
                {"_id": friend["_id"]},
                {"$set": updates},
            )
            friend.update(updates)

        return FriendMessagesResponse(
            gid=gid,
            source_friend_id=source_friend_id,
            security_id=security_id,
            page=result.page,
            count=result.count,
            has_more=result.has_more,
            total=result.total,
            messages=messages,
        )

    async def send_friend_message(self, source_friend_id: str, content: str) -> SendMessageResponse:
        content = content.strip()
        if not content:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message="消息内容不能为空",
                recoverable=False,
                status_code=400,
            )
        friend = await self._load_friend(source_friend_id, allow_sync=True)
        if not friend:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"未找到 source_friend_id={source_friend_id} 的好友记录",
                recoverable=False,
                status_code=404,
            )
        await self.auth_service.require_authenticated()
        friend = await self._ensure_send_identity(friend, source_friend_id)
        try:
            raw_payload = friend.get("raw_payload") or {}
            result = await self.boss_client.send_message(
                SendMessageIn(
                    job_id=str(friend.get("source_job_id") or ""),
                    gid=str(friend.get("gid") or ""),
                    self_id=str(friend.get("self_id") or ""),
                    boss_uid=str(friend.get("boss_uid") or ""),
                    boss_id=str(friend.get("source_friend_id") or ""),
                    friend_source=int(friend.get("friend_source") or 0),
                    security_id=friend.get("security_id"),
                    content=content,
                    raw_payload=raw_payload,
                )
            )
        except Exception as exc:
            logger.warning("BOSS send friend message failed: source_friend_id=%s error=%s", source_friend_id, exc)
            raise map_boss_operation_error(exc) from exc

        outgoing_messages = _merge_friend_messages(
            friend.get("messages"),
            [
                {
                    "message_id": f"local-{utc_now().timestamp()}",
                    "from_id": result.self_id or str(friend.get("self_id") or ""),
                    "from_name": "",
                    "content": content,
                    "type": 1,
                    "created_at": int(utc_now().timestamp() * 1000),
                    "raw_payload": result.model_dump(),
                }
            ],
        )
        try:
            last_ts = float(outgoing_messages[-1].sent_at) if outgoing_messages and outgoing_messages[
                -1].sent_at is not None else None
        except (TypeError, ValueError):
            last_ts = None
        friend_updates: dict[str, Any] = {
            "messages": [message.model_dump() for message in outgoing_messages],
            "last_message": content,
            "updated_at": utc_now(),
        }
        if last_ts is not None:
            friend_updates["last_message_ts"] = last_ts
            friend_updates["last_message_at"] = _format_last_time(last_ts)
        await self.friends.update_one({"_id": friend["_id"]}, {"$set": friend_updates})
        return SendMessageResponse(
            gid=str(friend.get("gid") or ""),
            source_friend_id=source_friend_id,
            content=content,
            status=result.status or "sent",
            raw_payload=result.model_dump(),
        )

    async def _ensure_send_identity(self, friend: dict[str, Any], source_friend_id: str) -> dict[str, Any]:
        boss_uid = str(friend.get("boss_uid") or "")
        if friend.get("self_id") and boss_uid and friend.get("source_friend_id"):
            return friend
        boss_id_for_history = friend.get("source_friend_id")
        security_id = friend.get("security_id")
        if not boss_id_for_history or not security_id:
            return friend
        await self.auth_service.require_authenticated()
        try:
            result = await self.boss_client.get_chat_history(
                ChatHistoryIn(
                    boss_id=boss_id_for_history,
                    security_id=security_id,
                    page=1,
                    count=20,
                )
            )
        except Exception as exc:
            logger.warning("BOSS send identity backfill failed: source_friend_id=%s error=%s", source_friend_id, exc)
            return friend

        self_id = _extract_self_id_from_messages(
            boss_uid,
            [message.model_dump() for message in result.messages],
        )
        updates: dict[str, Any] = {}
        if self_id:
            updates["self_id"] = self_id
        if boss_uid:
            updates["boss_uid"] = boss_uid
        if updates:
            updates["updated_at"] = utc_now()
            await self.friends.update_one({"_id": friend["_id"]}, {"$set": updates})
            friend.update(updates)
        return friend

    async def sync_friends(self) -> int:
        await self.auth_service.require_authenticated()
        try:
            friends = await self.boss_client.list_friends(FriendListIn(page=1))
        except Exception as exc:
            logger.warning("BOSS friend sync failed: error=%s", exc)
            raise map_boss_operation_error(exc) from exc

        synced = 0
        for item in friends:
            source_friend_id = item.encrypt_boss_id
            if not source_friend_id:
                continue

            last_message_ts = None
            if item.last_message_ts:
                try:
                    last_message_ts = float(item.last_message_ts)
                except (ValueError, TypeError):
                    pass

            last_message_at = _format_last_time(last_message_ts) if last_message_ts else None
            self_id = _extract_self_id(item.model_dump())
            existing = await self.friends.find_one({"source_friend_id": source_friend_id})
            messages = existing.get("messages", []) if existing else []
            await self.friends.update_one(
                {"source_friend_id": source_friend_id},
                {
                    "$set": {
                        "gid": item.gid,
                        "boss_uid": item.gid,
                        "friend_source": item.friend_source,
                        "relation_type": item.relation_type,
                        "read_status": item.read_status,
                        "self_id": self_id,
                        "source_job_id": item.encrypt_job_id or None,
                        "source_friend_id": source_friend_id,
                        "security_id": item.security_id or None,
                        "name": item.name,
                        "title": item.title,
                        "company": item.company or None,
                        "avatar": item.avatar or None,
                        "last_message": item.last_message or None,
                        "unread_count": item.unread_count,
                        "last_message_at": last_message_at,
                        "last_message_ts": last_message_ts,
                        "raw_payload": item.raw_payload,
                        "messages": messages,
                        "updated_at": utc_now(),
                    }
                },
                upsert=True,
            )
            synced += 1
        return synced


class DashboardService:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.targets = database["target_profiles"]
        self.jobs = database["job_leads"]
        self.tasks = database["greeting_tasks"]
        self.friends = database["friend_records"]

    async def get_summary(self) -> dict[str, int]:
        return {
            "targets": await self.targets.count_documents({}),
            "jobs": await self.jobs.count_documents({}),
            "tasks": await self.tasks.count_documents({}),
            "friends": await self.friends.count_documents({}),
        }


class SystemService:
    data_collection_names = (
        "target_profiles",
        "job_leads",
        "job_collection_records",
        "job_collection_traces",
        "greeting_tasks",
        "greeting_records",
        "friend_records",
    )

    def __init__(
            self,
            doctor_runner: BossDoctorRunner,
            settings: Settings,
            boss_client: BossClient,
            database: AsyncIOMotorDatabase,
    ) -> None:
        self.doctor_runner = doctor_runner
        self.settings = settings
        self.boss_client = boss_client
        self.auth_states = database["boss_auth_state"]
        self.database = database
        self._auth_service = BossAuthService(boss_client, self.auth_states)

    async def run_doctor(self) -> DoctorResponse:
        result = await self.doctor_runner.run()
        return DoctorResponse(
            ok=result.ok,
            summary=result.summary,
            data_dir=result.data_dir,
            checks=[DoctorCheckResponse(**check) for check in result.checks],
            next_actions=result.next_actions,
            stderr=result.stderr or None,
            exit_code=result.exit_code,
            error=DoctorErrorResponse(**result.error) if result.error else None,
        )

    async def get_auth_status(self) -> AuthStatusResponse:
        local, state = await self._auth_service.refresh_auth_state()
        return self._build_auth_response(local, state)

    async def login(self, timeout: int = 120) -> AuthStatusResponse:
        try:
            local = await self.boss_client.login(LoginIn(timeout=timeout))
        except Exception as exc:
            mapped = map_boss_operation_error(exc)
            await self._persist_login_error(mapped.message)
            raise mapped from exc
        stored = await self._auth_service.get_current_auth_state()
        state = await self._auth_service.sync_auth_state(local, stored)
        return self._build_auth_response(local, state)

    async def logout(self) -> AuthStatusResponse:
        try:
            local = await self.boss_client.logout()
        except Exception as exc:
            raise map_boss_operation_error(exc) from exc
        stored = await self._auth_service.get_current_auth_state()
        state = await self._auth_service.sync_auth_state(local, stored)
        return self._build_auth_response(local, state)

    async def get_search_options(self) -> SearchOptionsResponse:
        return SearchOptionsResponse(
            cities=sorted(CITY_CODES.keys()),
            salary_ranges=sorted(SALARY_CODES.keys()),
            experience_levels=sorted(EXPERIENCE_CODES.keys()),
            education_levels=sorted(EDUCATION_CODES.keys()),
            industries=sorted(INDUSTRY_CODES.keys()),
            scales=sorted(SCALE_CODES.keys()),
            stages=sorted(STAGE_CODES.keys()),
            job_types=sorted(JOB_TYPE_CODES.keys()),
        )

    async def get_logs(self, limit: int = 200) -> LogsResponse:
        log_file = Path(self.settings.app_log_dir).expanduser() / self.settings.app_log_file
        lines: deque[str] = deque(maxlen=limit)
        truncated = False
        if log_file.exists():
            total_lines = 0
            with log_file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    total_lines += 1
                    lines.append(line.rstrip("\n"))
            truncated = total_lines > limit
        return LogsResponse(
            lines=[LogLineResponse(text=line, level_hint=_detect_log_level(line)) for line in lines],
            truncated=truncated,
            source=log_file.name,
            updated_at=utc_now(),
        )

    async def clear_data(self) -> DataClearResponse:
        deleted_counts: dict[str, int] = {}
        for collection_name in self.data_collection_names:
            result = await self.database[collection_name].delete_many({})
            deleted_counts[collection_name] = result.deleted_count
        return DataClearResponse(
            deleted_counts=deleted_counts,
            total_deleted=sum(deleted_counts.values()),
        )

    async def _get_current_auth_state(self, provider: str = "zhipin") -> AuthState | None:
        return await self._auth_service.get_current_auth_state(provider)

    async def _upsert_auth_state(self, state: AuthState) -> AuthState:
        return await self._auth_service.upsert_auth_state(state)

    async def _sync_auth_state(
            self,
            local: LoginOut,
            stored: AuthState | None,
    ) -> AuthState:
        return await self._auth_service.sync_auth_state(
            local,
            stored,
        )

    async def _persist_login_error(self, message: str) -> None:
        stored = await self._auth_service.get_current_auth_state()
        current = stored or AuthState()
        current.last_error = message
        current.updated_at = utc_now()
        await self._auth_service.upsert_auth_state(current)

    def _build_auth_response(self, local: LoginOut, state: AuthState) -> AuthStatusResponse:
        user_name = local.user_name if local.logged_in else None
        return AuthStatusResponse(
            logged_in=local.logged_in,
            user_name=user_name,
            city=local.city or state.city,
            ip=local.ip or state.ip,
            uid=local.uid or state.uid,
            message=local.message,
        )
