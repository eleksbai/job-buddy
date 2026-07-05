from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from job_buddy.boss import BossOperationError
from job_buddy.deps import (
    get_agent_worker,
    get_ai_matching_service,
    get_ai_matching_worker,
    get_friend_service,
    get_greeting_service,
    get_job_service,
    get_scroll_and_collect_worker,
    get_system_service,
)
from job_buddy.schemas import (
    AIMessageRequest,
    AIMessageResponse,
    AuthStatusResponse,
    DoctorResponse,
    FriendMessagesResponse,
    FriendRecordRead,
    FriendSyncResponse,
    GreetTaskRequest,
    JobCollectionRecordRead,
    JobDetailResponse,
    JobLeadDetailRead,
    JobLeadRead,
    JobListResponse,
    SearchTaskRequest,
    SearchJobsRequest,
    SearchJobsResponse,
    GreetingRecordRead,
    GreetingTaskRead,
    SendMessagePayload,
    SendMessageResponse,
    TaskTriggerResponse,
    TaskDetailResponse,
    WorkerConfigRead,
    WorkerConfigUpdate,
)
from job_buddy.worker import AIMatchingWorker
from job_buddy.services import (
    AIMatchingService,
    FriendService,
    GreetingService,
    JobCollectionService,
    ScrollAndCollectWorker,
    SystemService,
)

router = APIRouter(prefix="/boss")


@router.get("/jobs", response_model=JobListResponse, tags=["jobs"], operation_id="list_jobs")
async def list_jobs(
    greeted: bool | None = None,
    created_today: bool = False,
    updated_today: bool = False,
    ai_match: str | None = None,
    pre_check: str | None = None,
    city: str | None = None,
    keyword: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    service: JobCollectionService = Depends(get_job_service),
) -> JobListResponse:
    skip = (page - 1) * limit
    jobs, total = await service.list_jobs(
        greeted=greeted,
        created_today=created_today,
        updated_today=updated_today,
        ai_match=ai_match,
        pre_check=pre_check,
        city=city,
        keyword=keyword,
        sort_by=sort_by,
        sort_dir=sort_dir,
        skip=skip,
        limit=limit,
    )
    return JobListResponse(
        items=[JobLeadRead(**item.model_dump()) for item in jobs],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/jobs/{source_job_id}/detail", response_model=JobDetailResponse, tags=["jobs"], operation_id="get_job_detail")
async def get_job_detail(
    source_job_id: str,
    security_id: str | None = Query(default=None, description="BOSS security_id, used when job is not yet in the database"),
    force_refresh: bool = Query(default=False, description="Force re-fetch latest job detail from BOSS"),
    service: JobCollectionService = Depends(get_job_service),
) -> JobDetailResponse:
    job, cached = await service.get_job_detail(
        source_job_id,
        security_id=security_id,
        force_refresh=force_refresh,
    )
    return JobDetailResponse(cached=cached, job=JobLeadDetailRead(**job.model_dump()))


@router.post("/jobs/search", response_model=SearchJobsResponse, tags=["jobs"], operation_id="search_jobs")
async def search_jobs(
    payload: SearchJobsRequest,
    service: JobCollectionService = Depends(get_job_service),
) -> SearchJobsResponse:
    query_dict: dict[str, object] = {"query": payload.query, "page": payload.page}
    for field in ("city", "salary", "experience", "education", "scale", "industry", "stage", "job_type"):
        value = getattr(payload, field, None)
        if value is not None:
            query_dict[field] = value
    try:
        items = await service.search_jobs_readonly(query_dict)
    except BossOperationError as exc:
        return SearchJobsResponse(success=False, count=0, items=[], error=exc.message, code=exc.code)
    return SearchJobsResponse(success=True, count=len(items), items=items)


@router.get("/jobs/collections", response_model=list[JobCollectionRecordRead], tags=["jobs"], operation_id="list_job_collection_records")
async def list_job_collection_records(
    task_id: str | None = None,
    source_job_id: str | None = None,
    limit: int = Query(default=100, le=200),
    service: JobCollectionService = Depends(get_job_service),
) -> list[JobCollectionRecordRead]:
    items = await service.list_collection_records(
        task_id=task_id,
        source_job_id=source_job_id,
        limit=limit,
    )
    return [JobCollectionRecordRead(**item.model_dump()) for item in items]


# ── AI Matching Endpoints ──

@router.post("/jobs/{source_job_id}/ai/evaluate", tags=["jobs"], operation_id="evaluate_single_job")
async def evaluate_single_job(
    source_job_id: str,
    service: AIMatchingService = Depends(get_ai_matching_service),
) -> dict:
    """Evaluate a single job with AI and persist the result."""
    return await service.evaluate_single_job(source_job_id)


@router.post("/jobs/ai/evaluate", response_model=TaskTriggerResponse, tags=["jobs"], operation_id="trigger_ai_evaluation")
async def trigger_ai_evaluation(
    service: AIMatchingService = Depends(get_ai_matching_service),
) -> TaskTriggerResponse:
    """Trigger an AI evaluation task for all unevaluated jobs."""
    task = await service.run_evaluation_task()
    return TaskTriggerResponse(task_id=task.id, status=task.status)


class ClearAIMarksRequest(BaseModel):
    source_job_ids: list[str]


@router.post("/jobs/ai/clear", tags=["jobs"], operation_id="clear_ai_marks")
async def clear_ai_marks(
    payload: ClearAIMarksRequest,
    service: AIMatchingService = Depends(get_ai_matching_service),
) -> dict[str, int]:
    """Clear AI evaluation marks and scores for the specified jobs."""
    count = await service.clear_all_marks(source_job_ids=payload.source_job_ids)
    return {"cleared_count": count}


@router.post("/jobs/{source_job_id}/ai/message", response_model=AIMessageResponse, tags=["jobs"], operation_id="generate_ai_message")
async def generate_ai_message(
    source_job_id: str,
    payload: AIMessageRequest,
    service: AIMatchingService = Depends(get_ai_matching_service),
) -> AIMessageResponse:
    """Generate an AI-crafted chat message for the job's BOSS."""
    result = await service.generate_message(source_job_id, context=payload.context)
    return AIMessageResponse(**result)


class PreCheckRequest(BaseModel):
    source_job_ids: list[str]


@router.post("/jobs/pre-check", tags=["jobs"], operation_id="pre_check_jobs_batch")
async def pre_check_jobs_batch(
    payload: PreCheckRequest,
    service: JobCollectionService = Depends(get_job_service),
) -> dict[str, int]:
    count = await service.pre_check_jobs(payload.source_job_ids)
    return {"count": count}


@router.post("/tasks/search", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_search_task")
async def trigger_search_task(
    payload: SearchTaskRequest,
    job_service: JobCollectionService = Depends(get_job_service),
) -> TaskTriggerResponse:
    query = payload.query_override or {}
    task = await job_service.search_jobs(query=query)
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.post("/tasks/search/scroll", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_scroll_search_task")
async def trigger_scroll_search_task(
    payload: SearchTaskRequest,
    job_service: JobCollectionService = Depends(get_job_service),
) -> TaskTriggerResponse:
    query = payload.query_override or {}
    task = await job_service.search_jobs_by_scroll(query=query)
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.post("/tasks/search/detail-click", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_detail_click_task")
async def trigger_detail_click_task(
    payload: SearchTaskRequest,
    job_service: JobCollectionService = Depends(get_job_service),
) -> TaskTriggerResponse:
    task = await job_service.collect_job_details_by_click()
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.post("/tasks/search/scroll-and-detail", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_scroll_and_detail_task")
async def trigger_scroll_and_detail_task(
    payload: SearchTaskRequest,
    job_service: JobCollectionService = Depends(get_job_service),
) -> TaskTriggerResponse:
    query = payload.query_override or {}
    task = await job_service.scroll_and_collect_jobs(query=query)
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.post("/tasks/greet", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_greet_task")
async def trigger_greet_task(
    payload: GreetTaskRequest,
    greeting_service: GreetingService = Depends(get_greeting_service),
) -> TaskTriggerResponse:
    task = await greeting_service.run_greetings(
        source_job_ids=payload.source_job_ids,
        greeting_message=payload.greeting_message,
        limit=payload.limit,
    )
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.get("/tasks", response_model=list[GreetingTaskRead], tags=["tasks"], operation_id="list_tasks")
async def list_tasks(
    limit: int = Query(default=100, le=200),
    greeting_service: GreetingService = Depends(get_greeting_service),
) -> list[GreetingTaskRead]:
    tasks = await greeting_service.list_tasks(limit=limit)
    return [GreetingTaskRead(**item.model_dump()) for item in tasks]


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse, tags=["tasks"], operation_id="get_task")
async def get_task(task_id: str, greeting_service: GreetingService = Depends(get_greeting_service)) -> TaskDetailResponse:
    task, records = await greeting_service.get_task_detail(task_id)
    return TaskDetailResponse(
        task=GreetingTaskRead(**task.model_dump()),
        records=[GreetingRecordRead(**record.model_dump()) for record in records],
    )


@router.get("/workers", response_model=list[WorkerConfigRead], tags=["workers"], operation_id="list_workers")
async def list_workers(
    scroll_and_collect_worker: ScrollAndCollectWorker = Depends(get_scroll_and_collect_worker),
    ai_matching_worker = Depends(get_ai_matching_worker),
    agent_worker = Depends(get_agent_worker),
) -> list[WorkerConfigRead]:
    items = [
        await scroll_and_collect_worker.get_worker(),
        await ai_matching_worker.get_worker(),
        await agent_worker.get_worker(),
    ]
    return [WorkerConfigRead(**item.model_dump()) for item in items]


@router.get("/workers/{worker_name}", response_model=WorkerConfigRead, tags=["workers"], operation_id="get_worker")
async def get_worker(
    worker_name: str,
    scroll_and_collect_worker: ScrollAndCollectWorker = Depends(get_scroll_and_collect_worker),
    ai_matching_worker = Depends(get_ai_matching_worker),
    agent_worker = Depends(get_agent_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, scroll_and_collect_worker, ai_matching_worker, agent_worker).get_worker()
    return WorkerConfigRead(**item.model_dump())


@router.put("/workers/{worker_name}", response_model=WorkerConfigRead, tags=["workers"], operation_id="update_worker")
async def update_worker(
    worker_name: str,
    payload: WorkerConfigUpdate,
    scroll_and_collect_worker: ScrollAndCollectWorker = Depends(get_scroll_and_collect_worker),
    ai_matching_worker = Depends(get_ai_matching_worker),
    agent_worker = Depends(get_agent_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, scroll_and_collect_worker, ai_matching_worker, agent_worker).update_worker(payload)
    return WorkerConfigRead(**item.model_dump())


@router.post("/workers/{worker_name}/start", response_model=WorkerConfigRead, tags=["workers"], operation_id="start_worker")
async def start_worker(
    worker_name: str,
    scroll_and_collect_worker: ScrollAndCollectWorker = Depends(get_scroll_and_collect_worker),
    ai_matching_worker = Depends(get_ai_matching_worker),
    agent_worker = Depends(get_agent_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, scroll_and_collect_worker, ai_matching_worker, agent_worker).start_worker()
    return WorkerConfigRead(**item.model_dump())


@router.post("/workers/{worker_name}/stop", response_model=WorkerConfigRead, tags=["workers"], operation_id="stop_worker")
async def stop_worker(
    worker_name: str,
    scroll_and_collect_worker: ScrollAndCollectWorker = Depends(get_scroll_and_collect_worker),
    ai_matching_worker = Depends(get_ai_matching_worker),
    agent_worker = Depends(get_agent_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, scroll_and_collect_worker, ai_matching_worker, agent_worker).stop_worker()
    return WorkerConfigRead(**item.model_dump())


@router.post("/workers/{worker_name}/release", response_model=WorkerConfigRead, tags=["workers"], operation_id="release_worker")
async def release_worker(
    worker_name: str,
    scroll_and_collect_worker: ScrollAndCollectWorker = Depends(get_scroll_and_collect_worker),
    ai_matching_worker = Depends(get_ai_matching_worker),
    agent_worker = Depends(get_agent_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, scroll_and_collect_worker, ai_matching_worker, agent_worker).release_worker()
    return WorkerConfigRead(**item.model_dump())


@router.post("/workers/{worker_name}/execute", response_model=WorkerConfigRead, tags=["workers"], operation_id="execute_worker")
async def execute_worker(
    worker_name: str,
    scroll_and_collect_worker: ScrollAndCollectWorker = Depends(get_scroll_and_collect_worker),
    ai_matching_worker = Depends(get_ai_matching_worker),
    agent_worker = Depends(get_agent_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, scroll_and_collect_worker, ai_matching_worker, agent_worker).execute_now()
    return WorkerConfigRead(**item.model_dump())


@router.get("/friends", response_model=list[FriendRecordRead], tags=["friends"], operation_id="list_friends")
async def list_friends(
    service: FriendService = Depends(get_friend_service),
) -> list[FriendRecordRead]:
    friends = await service.list_friends()
    return [FriendRecordRead(**item.model_dump()) for item in friends]


@router.post("/friends/sync", response_model=FriendSyncResponse, status_code=status.HTTP_202_ACCEPTED, tags=["friends"], operation_id="sync_friends")
async def sync_friends(
    service: FriendService = Depends(get_friend_service),
) -> FriendSyncResponse:
    count = await service.sync_friends()
    return FriendSyncResponse(count=count)


@router.get("/friends/{source_friend_id}/messages", response_model=FriendMessagesResponse, tags=["friends"], operation_id="get_friend_messages")
async def get_friend_messages(
    source_friend_id: str,
    page: int = Query(default=1, ge=1),
    count: int = Query(default=20, le=100),
    cached_only: bool = Query(default=False, description="Only return cached messages, skip BOSS fetch"),
    service: FriendService = Depends(get_friend_service),
) -> FriendMessagesResponse:
    return await service.get_friend_messages(source_friend_id=source_friend_id, page=page, count=count, cached_only=cached_only)


@router.post("/friends/{source_friend_id}/messages/send", response_model=SendMessageResponse, tags=["friends"], operation_id="send_friend_message")
async def send_friend_message(
    source_friend_id: str,
    payload: SendMessagePayload,
    service: FriendService = Depends(get_friend_service),
) -> SendMessageResponse:
    return await service.send_friend_message(source_friend_id=source_friend_id, content=payload.content)


@router.get("/system/doctor", response_model=DoctorResponse, tags=["system"], operation_id="run_boss_doctor")
async def run_boss_doctor(service: SystemService = Depends(get_system_service)) -> DoctorResponse:
    return await service.run_doctor()


@router.get("/system/auth", response_model=AuthStatusResponse, tags=["system"], operation_id="get_auth_status")
async def get_auth_status(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.get_auth_status()


@router.post("/system/auth/login", response_model=AuthStatusResponse, tags=["system"], operation_id="login_auth")
async def login_auth(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.login()


@router.post("/system/auth/logout", response_model=AuthStatusResponse, tags=["system"], operation_id="logout_auth")
async def logout_auth(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.logout()
def _select_worker(
    worker_name: str,
    scroll_and_collect_worker: ScrollAndCollectWorker,
    ai_matching_worker: "AIMatchingWorker",
    agent_worker,
):
    if worker_name == "scroll_and_collect":
        return scroll_and_collect_worker
    if worker_name == "ai_matching":
        return ai_matching_worker
    if worker_name == "agent":
        return agent_worker
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found.")
