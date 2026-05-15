from fastapi import APIRouter, Depends, Query

from job_buddy.deps import get_greeting_service, get_job_service, get_target_service
from job_buddy.modules.jobs import JobCollectionService
from job_buddy.modules.targets import TargetProfileService
from job_buddy.modules.tasks import (
    GreetTaskRequest,
    GreetingRecordRead,
    GreetingService,
    GreetingTaskRead,
    SearchTaskRequest,
    TaskDetailResponse,
)
from job_buddy.modules.common import TaskTriggerResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/search", response_model=TaskTriggerResponse, operation_id="trigger_search_task")
async def trigger_search_task(
    payload: SearchTaskRequest,
    target_service: TargetProfileService = Depends(get_target_service),
    job_service: JobCollectionService = Depends(get_job_service),
) -> TaskTriggerResponse:
    target = await target_service.get_target(payload.target_profile_id) if payload.target_profile_id else None
    query = payload.query_override or {}
    if target:
        query = {
            "keywords": target.keywords,
            "city": target.city,
            "salary": target.salary,
            "experience": target.experience,
            **target.filters,
            **query,
        }
    task = await job_service.search_jobs(query=query, target=target)
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.post("/greet", response_model=TaskTriggerResponse, operation_id="trigger_greet_task")
async def trigger_greet_task(
    payload: GreetTaskRequest,
    target_service: TargetProfileService = Depends(get_target_service),
    greeting_service: GreetingService = Depends(get_greeting_service),
) -> TaskTriggerResponse:
    target = await target_service.get_target(payload.target_profile_id) if payload.target_profile_id else None
    task = await greeting_service.run_greetings(
        target=target,
        job_ids=payload.job_ids,
        greeting_message=payload.greeting_message,
        limit=payload.limit,
    )
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.get("", response_model=list[GreetingTaskRead], operation_id="list_tasks")
async def list_tasks(
    limit: int = Query(default=100, le=200),
    greeting_service: GreetingService = Depends(get_greeting_service),
) -> list[GreetingTaskRead]:
    tasks = await greeting_service.list_tasks(limit=limit)
    return [GreetingTaskRead(**item.model_dump()) for item in tasks]


@router.get("/{task_id}", response_model=TaskDetailResponse, operation_id="get_task")
async def get_task(task_id: str, greeting_service: GreetingService = Depends(get_greeting_service)) -> TaskDetailResponse:
    task, records = await greeting_service.get_task_detail(task_id)
    return TaskDetailResponse(
        task=GreetingTaskRead(**task.model_dump()),
        records=[GreetingRecordRead(**record.model_dump()) for record in records],
    )
