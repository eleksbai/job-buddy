import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from job_buddy.core.boss import map_boss_operation_error, BossClientProtocol
from job_buddy.modules.common import (
    TASK_TIMEOUT,
    BaseRepository,
    DocumentModel,
    TaskStatus,
    TaskTriggerResponse,
    TimestampedSchema,
    utc_now,
)
from job_buddy.modules.jobs import GreetingTask, GreetingTaskRepository, JobLeadRepository
from job_buddy.modules.targets import TargetProfile

logger = logging.getLogger(__name__)


class SearchTaskRequest(BaseModel):
    target_profile_id: str | None = None
    query_override: dict[str, Any] = Field(default_factory=dict)


class GreetTaskRequest(BaseModel):
    target_profile_id: str | None = None
    job_ids: list[str] = Field(default_factory=list)
    greeting_message: str | None = None
    limit: int = 20


class GreetingTaskRead(TimestampedSchema):
    task_type: str
    status: str
    target_profile_id: str | None = None
    input_payload: dict[str, Any]
    result_summary: dict[str, Any]
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class GreetingRecord(DocumentModel):
    task_id: str
    job_lead_id: str
    source_job_id: str
    status: str
    message: str | None = None
    response_payload: dict[str, Any] = Field(default_factory=dict)


class GreetingRecordRead(TimestampedSchema):
    task_id: str
    job_lead_id: str
    source_job_id: str
    status: str
    message: str | None = None
    response_payload: dict[str, Any]


class TaskDetailResponse(BaseModel):
    task: GreetingTaskRead
    records: list[GreetingRecordRead]


class GreetingRecordRepository(BaseRepository[GreetingRecord]):
    collection_name = "greeting_records"
    model_cls = GreetingRecord

    async def list_by_task_id(self, task_id: str) -> list[GreetingRecord]:
        return await self.list(filters={"task_id": task_id}, limit=500)


class GreetingService:
    def __init__(self, database: AsyncIOMotorDatabase, boss_client: BossClientProtocol) -> None:
        self.tasks = GreetingTaskRepository(database)
        self.records = GreetingRecordRepository(database)
        self.jobs = JobLeadRepository(database)
        self.boss_client = boss_client

    async def run_greetings(
        self,
        target: TargetProfile | None,
        job_ids: list[str],
        greeting_message: str | None,
        limit: int,
    ) -> GreetingTask:
        task = await self.tasks.create(
            GreetingTask(
                task_type="greet",
                status=TaskStatus.RUNNING,
                target_profile_id=target.id if target else None,
                input_payload={"job_ids": job_ids, "greeting_message": greeting_message, "limit": limit},
                started_at=utc_now(),
            )
        )

        try:
            await asyncio.wait_for(
                self._do_greet(task, target, job_ids, greeting_message, limit),
                timeout=TASK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            current = await self.tasks.get(task.id)
            step = "unknown"
            if current and current.result_summary:
                step = current.result_summary.get("step", "unknown")
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

        updated = await self.tasks.get(task.id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task update failed.")
        return updated

    async def _do_greet(
        self,
        task: GreetingTask,
        target: TargetProfile | None,
        job_ids: list[str],
        greeting_message: str | None,
        limit: int,
    ) -> None:
        await self._update_step(task.id, "fetch_jobs")
        if job_ids:
            jobs = [job for job_id in job_ids if (job := await self.jobs.get(job_id)) is not None]
        else:
            jobs = await self.jobs.list_filtered(greeted=False, limit=limit)

        success_count = 0
        failed_count = 0
        default_message = greeting_message or (target.greeting_template if target else None)

        for idx, job in enumerate(jobs):
            await self._update_step(task.id, f"greet_job_{idx + 1}_of_{len(jobs)}")
            try:
                try:
                    response = await self.boss_client.greet_job(
                        {
                            "source_job_id": job.source_job_id,
                            "security_id": job.security_id,
                            "title": job.title,
                            "company": job.company,
                        },
                        message=default_message,
                    )
                except Exception as exc:
                    logger.warning(
                        "BOSS greet failed: task_id=%s source_job_id=%s error=%s",
                        task.id, job.source_job_id, exc,
                    )
                    raise map_boss_operation_error(exc) from exc
                await self.records.create(
                    GreetingRecord(
                        task_id=task.id,
                        job_lead_id=job.id,
                        source_job_id=job.source_job_id,
                        status="succeeded",
                        message=default_message,
                        response_payload=response,
                    )
                )
                await self.jobs.update(job.id, {"greeted": True, "match_status": "contacted"})
                success_count += 1
            except Exception as exc:
                await self.records.create(
                    GreetingRecord(
                        task_id=task.id,
                        job_lead_id=job.id,
                        source_job_id=job.source_job_id,
                        status="failed",
                        message=default_message,
                        response_payload={"error": str(exc)},
                    )
                )
                failed_count += 1

        final_status = TaskStatus.SUCCEEDED
        if failed_count and success_count:
            final_status = TaskStatus.PARTIAL_SUCCESS
        elif failed_count and not success_count:
            final_status = TaskStatus.FAILED

        await self.tasks.update(
            task.id,
            {
                "status": final_status,
                "result_summary": {"total": len(jobs), "succeeded": success_count, "failed": failed_count},
                "finished_at": utc_now(),
            },
        )

    async def _update_step(self, task_id: str, step: str) -> None:
        await self.tasks.update(task_id, {"result_summary": {"step": step}})

    async def get_task_detail(self, task_id: str) -> tuple[GreetingTask, list[GreetingRecord]]:
        task = await self.tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        records = await self.records.list_by_task_id(task_id)
        return task, records

    async def list_tasks(self, limit: int) -> list[GreetingTask]:
        return await self.tasks.list(limit=limit)
