from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import Field

from job_buddy.core.boss import BossClientProtocol
from job_buddy.modules.common import BaseRepository, DocumentModel, TaskStatus, TimestampedSchema, utc_now
from job_buddy.modules.targets import TargetProfile


class JobLead(DocumentModel):
    source: str = "boss"
    source_job_id: str
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    match_status: str = "new"
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    greeted: bool = False


class JobLeadRead(TimestampedSchema):
    source: str
    source_job_id: str
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    match_status: str
    greeted: bool
    raw_payload: dict[str, Any]


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


class JobCollectionService:
    def __init__(self, database: AsyncIOMotorDatabase, boss_client: BossClientProtocol) -> None:
        self.jobs = JobLeadRepository(database)
        self.tasks = GreetingTaskRepository(database)
        self.boss_client = boss_client

    async def list_jobs(self, match_status: str | None, greeted: bool | None, limit: int) -> list[JobLead]:
        return await self.jobs.list_filtered(match_status=match_status, greeted=greeted, limit=limit)

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
            raw_jobs = await self.boss_client.search_jobs(query)
            created = 0
            for raw_job in raw_jobs:
                existing = await self.jobs.get_by_source_job_id(raw_job["job_id"])
                if existing is None:
                    await self.jobs.create(
                        JobLead(
                            source_job_id=raw_job["job_id"],
                            title=raw_job["title"],
                            company=raw_job["company"],
                            city=raw_job.get("city"),
                            salary=raw_job.get("salary"),
                            experience=raw_job.get("experience"),
                            match_status="matched" if target else "new",
                            raw_payload=raw_job,
                        )
                    )
                    created += 1

            updated = await self.tasks.update(
                task.id,
                {
                    "status": TaskStatus.SUCCEEDED,
                    "result_summary": {"fetched": len(raw_jobs), "created": created},
                    "finished_at": utc_now(),
                },
            )
            if updated is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
            return updated
        except Exception as exc:
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
