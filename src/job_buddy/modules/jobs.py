import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field, model_validator

from job_buddy.core.boss import map_boss_operation_error, raise_for_boss_healthcheck
from job_buddy.core.engines.models import JobDetailRequest, SearchRequest
from job_buddy.core.engines.runtime import EngineRuntimeManager
from job_buddy.modules.common import (
    TASK_TIMEOUT,
    BaseRepository,
    DocumentModel,
    TaskStatus,
    TimestampedSchema,
    utc_now,
)
from job_buddy.modules.targets import TargetProfile


logger = logging.getLogger(__name__)


def _coerce_numeric_job_id(raw_payload: dict[str, Any]) -> int | None:
    value = raw_payload.get("jobId")
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class JobLead(DocumentModel):
    source: str = "boss"
    source_job_id: str
    job_id: int | None = None
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    match_status: str = "new"
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    detail_payload: dict[str, Any] = Field(default_factory=dict)
    detail_text: str | None = None
    detail_source_url: str | None = None
    detail_fetched_at: datetime | None = None
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    search_count: int = 1
    last_searched_at: datetime = Field(default_factory=utc_now)
    greeted: bool = False


class JobLeadRead(TimestampedSchema):
    source: str
    source_job_id: str
    job_id: int | None = None
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    match_status: str
    search_count: int
    last_searched_at: datetime | None = None
    detail_fetched_at: datetime | None = None
    detail_source_url: str | None = None
    last_seen_at: datetime
    greeted: bool
    raw_payload: dict[str, Any]
    detail_payload: dict[str, Any] = Field(default_factory=dict)
    detail_text: str | None = None

    @model_validator(mode="before")
    @classmethod
    def fill_job_id_from_raw_payload(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("job_id") is None:
            raw_payload = data.get("raw_payload")
            if isinstance(raw_payload, dict):
                data["job_id"] = _coerce_numeric_job_id(raw_payload)
        return data


class JobLeadDetailRead(JobLeadRead):
    pass


class JobDetailResponse(BaseModel):
    cached: bool
    job: JobLeadDetailRead


class SearchJobsRequest(BaseModel):
    query: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    education: str | None = None
    scale: str | None = None
    industry: str | None = None
    stage: str | None = None
    job_type: str | None = None
    page: int = 1


class SearchJobsResponse(BaseModel):
    success: bool
    count: int
    items: list[dict[str, Any]]
    error: str | None = None
    code: str | None = None


class JobCollectionRecord(DocumentModel):
    task_id: str
    trace_id: str | None = None
    target_profile_id: str | None = None
    source: str = "boss"
    source_job_id: str
    job_id: int | None = None
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=utc_now)


class JobCollectionRecordRead(TimestampedSchema):
    task_id: str
    trace_id: str | None = None
    target_profile_id: str | None = None
    source: str
    source_job_id: str
    job_id: int | None = None
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    raw_payload: dict[str, Any]
    collected_at: datetime

    @model_validator(mode="before")
    @classmethod
    def fill_job_id_from_raw_payload(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("job_id") is None:
            raw_payload = data.get("raw_payload")
            if isinstance(raw_payload, dict):
                data["job_id"] = _coerce_numeric_job_id(raw_payload)
        return data


class JobCollectionTrace(DocumentModel):
    task_id: str
    target_profile_id: str | None = None
    source: str = "boss"
    engine: str | None = None
    browser: str | None = None
    request_url: str | None = None
    referer: str | None = None
    requested_at: datetime | None = None
    response_received_at: datetime | None = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    request_params: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    result_count: int = 0


class GreetingTask(DocumentModel):
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    target_profile_id: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobLeadRepository(BaseRepository[JobLead]):
    collection_name = "job_leads"
    model_cls = JobLead

    async def list_filtered(
        self,
        match_status: str | None = None,
        greeted: bool | None = None,
        limit: int = 100,
    ) -> list[JobLead]:
        filters: dict[str, object] = {}
        if match_status:
            filters["match_status"] = match_status
        if greeted is not None:
            filters["greeted"] = greeted
        cursor = self.collection.find(filters).sort([("last_searched_at", -1), ("_id", -1)]).limit(limit)
        return [self.model_cls.from_mongo(item) for item in await cursor.to_list(length=limit)]

    async def get_by_source_job_id(self, source_job_id: str) -> JobLead | None:
        payload = await self.collection.find_one({"source_job_id": source_job_id})
        if not payload:
            return None
        return self.model_cls.from_mongo(payload)


class GreetingTaskRepository(BaseRepository[GreetingTask]):
    collection_name = "greeting_tasks"
    model_cls = GreetingTask


class JobCollectionRecordRepository(BaseRepository[JobCollectionRecord]):
    collection_name = "job_collection_records"
    model_cls = JobCollectionRecord

    async def list_filtered(
        self,
        task_id: str | None = None,
        target_profile_id: str | None = None,
        source_job_id: str | None = None,
        limit: int = 100,
    ) -> list[JobCollectionRecord]:
        filters: dict[str, object] = {}
        if task_id:
            filters["task_id"] = task_id
        if target_profile_id:
            filters["target_profile_id"] = target_profile_id
        if source_job_id:
            filters["source_job_id"] = source_job_id
        return await self.list(filters=filters, limit=limit)


class JobCollectionTraceRepository(BaseRepository[JobCollectionTrace]):
    collection_name = "job_collection_traces"
    model_cls = JobCollectionTrace


class JobCollectionService:
    def __init__(self, database: AsyncIOMotorDatabase, runtime: EngineRuntimeManager) -> None:
        self.jobs = JobLeadRepository(database)
        self.records = JobCollectionRecordRepository(database)
        self.traces = JobCollectionTraceRepository(database)
        self.tasks = GreetingTaskRepository(database)
        self.runtime = runtime

    async def list_jobs(self, match_status: str | None, greeted: bool | None, limit: int) -> list[JobLead]:
        return await self.jobs.list_filtered(match_status=match_status, greeted=greeted, limit=limit)

    async def list_collection_records(
        self,
        task_id: str | None,
        target_profile_id: str | None,
        source_job_id: str | None,
        limit: int,
    ) -> list[JobCollectionRecord]:
        return await self.records.list_filtered(
            task_id=task_id,
            target_profile_id=target_profile_id,
            source_job_id=source_job_id,
            limit=limit,
        )

    @staticmethod
    def _extract_numeric_job_id(raw_payload: dict[str, Any]) -> int | None:
        return _coerce_numeric_job_id(raw_payload)

    async def get_job_detail(self, source_job_id: str, security_id: str | None = None) -> tuple[JobLead, bool]:
        job = await self.jobs.get_by_source_job_id(source_job_id)
        if job is None:
            if not security_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
            # Create a minimal job record from conversation data, then fetch detail
            try:
                detail_result = await self.runtime.detail(
                    JobDetailRequest(
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
            job = await self.jobs.create(
                JobLead(
                    source_job_id=source_job_id,
                    security_id=security_id,
                    title=str(detail_result.get("job", {}).get("title") or source_job_id),
                    company=str(detail_result.get("company", {}).get("name") or ""),
                    city=detail_result.get("job", {}).get("city"),
                    salary=detail_result.get("job", {}).get("salary"),
                    experience=detail_result.get("job", {}).get("experience"),
                    job_url=detail_result.get("job_url"),
                    detail_payload=dict(detail_result.get("detail_payload") or {}),
                    detail_text=str(detail_result.get("detail_text") or ""),
                    detail_source_url=detail_result.get("request_url"),
                    detail_fetched_at=utc_now(),
                )
            )
            return job, False

        if job.detail_payload and job.detail_text:
            return job, True

        try:
            detail_result = await self.runtime.detail(
                JobDetailRequest(
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

        updated = await self.jobs.update(
            job.id,
            {
                "title": str(detail_result.get("job", {}).get("title") or job.title),
                "company": str(detail_result.get("company", {}).get("name") or job.company),
                "city": detail_result.get("job", {}).get("city") or job.city,
                "salary": detail_result.get("job", {}).get("salary") or job.salary,
                "experience": detail_result.get("job", {}).get("experience") or job.experience,
                "job_url": detail_result.get("job_url") or job.job_url,
                "detail_payload": dict(detail_result.get("detail_payload") or {}),
                "detail_text": str(detail_result.get("detail_text") or ""),
                "detail_source_url": detail_result.get("request_url") or detail_result.get("job_url") or job.job_url,
                "detail_fetched_at": utc_now(),
            },
        )
        if updated is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job update failed.")
        return updated, False

    async def search_jobs_readonly(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Synchronous read-only search. No persistence."""
        health = None
        try:
            health = await self.runtime.healthcheck()
            raise_for_boss_healthcheck(health)
            search_result = await self.runtime.search(SearchRequest(query=query))
        except Exception as exc:
            logger.warning(
                "BOSS search (readonly) failed: query=%s health=%s error=%s",
                query, health, exc,
            )
            raise map_boss_operation_error(exc) from exc
        return [
            {
                "job_id": item.job_id,
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
        task = await self.tasks.create(
            GreetingTask(
                task_type="search",
                status=TaskStatus.RUNNING,
                target_profile_id=target.id if target else None,
                input_payload=query,
                started_at=utc_now(),
            )
        )
        try:
            await asyncio.wait_for(
                self._do_search(task, query, target),
                timeout=TASK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            current = await self.tasks.get(task.id)
            step = "unknown"
            if current and current.result_summary:
                step = current.result_summary.get("step", "unknown")
            logger.error(
                "search task timed out: task_id=%s step=%s query=%s",
                task.id,
                step,
                query,
            )
            failed = await self.tasks.update(
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
            failed = await self.tasks.update(
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

        updated = await self.tasks.get(task.id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
        return updated

    async def _do_search(
        self, task: GreetingTask, query: dict[str, Any], target: TargetProfile | None
    ) -> None:
        await self._update_step(task.id, "healthcheck")
        health = None
        try:
            health = await self.runtime.healthcheck()
            raise_for_boss_healthcheck(health)
            search_result = await self.runtime.search(SearchRequest(query=query))
        except Exception as exc:
            logger.warning(
                "BOSS search failed: task_id=%s query=%s health=%s error=%s",
                task.id, query, health, exc,
            )
            raise map_boss_operation_error(exc) from exc

        await self._update_step(task.id, "persist_results")
        trace_id: str | None = None
        if search_result.trace:
            requested_at = search_result.trace.get("requested_at")
            response_received_at = search_result.trace.get("response_received_at")
            trace = await self.traces.create(
                JobCollectionTrace(
                    task_id=task.id,
                    target_profile_id=target.id if target else None,
                    engine=search_result.trace.get("engine"),
                    browser=search_result.trace.get("browser"),
                    request_url=search_result.trace.get("request_url"),
                    referer=search_result.trace.get("referer"),
                    requested_at=datetime.fromisoformat(requested_at) if isinstance(requested_at, str) else None,
                    response_received_at=(
                        datetime.fromisoformat(response_received_at) if isinstance(response_received_at, str) else None
                    ),
                    request_payload=dict(search_result.trace.get("request_payload") or {}),
                    request_params=dict(search_result.trace.get("request_params") or {}),
                    response_payload=dict(search_result.trace.get("response_payload") or {}),
                    result_count=int(search_result.trace.get("result_count") or 0),
                )
            )
            trace_id = trace.id
        dedup_created = 0
        dedup_updated = 0
        collected = 0
        for item in search_result.items:
            job_id = self._extract_numeric_job_id(item.raw_payload)
            await self.records.create(
                JobCollectionRecord(
                    task_id=task.id,
                    trace_id=trace_id,
                    target_profile_id=target.id if target else None,
                    source_job_id=item.job_id,
                    job_id=job_id,
                    security_id=item.security_id,
                    title=item.title,
                    company=item.company,
                    city=item.city,
                    salary=item.salary,
                    experience=item.experience,
                    job_url=item.job_url,
                    raw_payload=item.raw_payload,
                )
            )
            collected += 1

            existing = await self.jobs.get_by_source_job_id(item.job_id)
            if existing is None:
                await self.jobs.create(
                    JobLead(
                        source_job_id=item.job_id,
                        job_id=job_id,
                        security_id=item.security_id,
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
                    )
                )
                dedup_created += 1
            else:
                await self.jobs.update(
                    existing.id,
                    {
                        "security_id": item.security_id,
                        "job_id": job_id,
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

        await self.tasks.update(
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

    async def _update_step(self, task_id: str, step: str) -> None:
        await self.tasks.update(task_id, {"result_summary": {"step": step}})
