import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import Field

from job_buddy.core.boss import map_boss_operation_error, raise_for_boss_healthcheck
from job_buddy.core.engines.models import SearchRequest
from job_buddy.core.engines.runtime import EngineRuntimeManager
from job_buddy.modules.common import BaseRepository, DocumentModel, TaskStatus, TimestampedSchema, utc_now
from job_buddy.modules.targets import TargetProfile


logger = logging.getLogger(__name__)


class JobLead(DocumentModel):
    source: str = "boss"
    source_job_id: str
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    match_status: str = "new"
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    greeted: bool = False


class JobLeadRead(TimestampedSchema):
    source: str
    source_job_id: str
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    match_status: str
    greeted: bool
    raw_payload: dict[str, Any]


class JobCollectionRecord(DocumentModel):
    task_id: str
    trace_id: str | None = None
    target_profile_id: str | None = None
    source: str = "boss"
    source_job_id: str
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
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    raw_payload: dict[str, Any]
    collected_at: datetime


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
        return await self.list(filters=filters, limit=limit)

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
            try:
                health = await self.runtime.healthcheck()
                raise_for_boss_healthcheck(health)
                search_result = await self.runtime.search(SearchRequest(query=query))
            except Exception as exc:
                raise map_boss_operation_error(exc) from exc
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
                await self.records.create(
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
                    )
                )
                collected += 1

                existing = await self.jobs.get_by_source_job_id(item.job_id)
                if existing is None:
                    await self.jobs.create(
                        JobLead(
                            source_job_id=item.job_id,
                            security_id=item.security_id,
                            title=item.title,
                            company=item.company,
                            city=item.city,
                            salary=item.salary,
                            experience=item.experience,
                            job_url=item.job_url,
                            match_status="matched" if target else "new",
                            raw_payload=item.raw_payload,
                        )
                    )
                    dedup_created += 1
                else:
                    await self.jobs.update(
                        existing.id,
                        {
                            "security_id": item.security_id,
                            "title": item.title,
                            "company": item.company,
                            "city": item.city,
                            "salary": item.salary,
                            "experience": item.experience,
                            "job_url": item.job_url,
                            "raw_payload": item.raw_payload,
                            "last_seen_at": utc_now(),
                        },
                    )
                    dedup_updated += 1

            updated = await self.tasks.update(
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
            if updated is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
            return updated
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
