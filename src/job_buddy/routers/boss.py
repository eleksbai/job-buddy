from fastapi import APIRouter, Depends, HTTPException, Query, status

from job_buddy.boss import BossOperationError
from job_buddy.deps import (
    get_detail_worker,
    get_friend_service,
    get_greeting_service,
    get_job_service,
    get_search_worker,
    get_system_service,
    get_target_service,
)
from job_buddy.schemas import (
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
from job_buddy.services import (
    DetailWorker,
    FriendService,
    GreetingService,
    JobCollectionService,
    SearchWorker,
    SystemService,
    TargetProfileService,
)

router = APIRouter(prefix="/boss")


@router.get("/jobs", response_model=list[JobLeadRead], tags=["jobs"], operation_id="list_jobs")
async def list_jobs(
    match_status: str | None = None,
    greeted: bool | None = None,
    limit: int = Query(default=100, le=200),
    service: JobCollectionService = Depends(get_job_service),
) -> list[JobLeadRead]:
    jobs = await service.list_jobs(match_status=match_status, greeted=greeted, limit=limit)
    return [JobLeadRead(**item.model_dump()) for item in jobs]


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
    target_profile_id: str | None = None,
    source_job_id: str | None = None,
    limit: int = Query(default=100, le=200),
    service: JobCollectionService = Depends(get_job_service),
) -> list[JobCollectionRecordRead]:
    items = await service.list_collection_records(
        task_id=task_id,
        target_profile_id=target_profile_id,
        source_job_id=source_job_id,
        limit=limit,
    )
    return [JobCollectionRecordRead(**item.model_dump()) for item in items]


@router.post("/tasks/search", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_search_task")
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


@router.post("/tasks/search/scroll", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_scroll_search_task")
async def trigger_scroll_search_task(
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
    task = await job_service.search_jobs_by_scroll(query=query, target=target)
    return TaskTriggerResponse(task_id=task.id, status=task.status)


@router.post("/tasks/greet", response_model=TaskTriggerResponse, tags=["tasks"], operation_id="trigger_greet_task")
async def trigger_greet_task(
    payload: GreetTaskRequest,
    target_service: TargetProfileService = Depends(get_target_service),
    greeting_service: GreetingService = Depends(get_greeting_service),
) -> TaskTriggerResponse:
    target = await target_service.get_target(payload.target_profile_id) if payload.target_profile_id else None
    task = await greeting_service.run_greetings(
        target=target,
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
    search_worker: SearchWorker = Depends(get_search_worker),
    detail_worker: DetailWorker = Depends(get_detail_worker),
) -> list[WorkerConfigRead]:
    items = [await search_worker.get_worker(), await detail_worker.get_worker()]
    return [WorkerConfigRead(**item.model_dump()) for item in items]


@router.get("/workers/{worker_name}", response_model=WorkerConfigRead, tags=["workers"], operation_id="get_worker")
async def get_worker(
    worker_name: str,
    search_worker: SearchWorker = Depends(get_search_worker),
    detail_worker: DetailWorker = Depends(get_detail_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, search_worker, detail_worker).get_worker()
    return WorkerConfigRead(**item.model_dump())


@router.put("/workers/{worker_name}", response_model=WorkerConfigRead, tags=["workers"], operation_id="update_worker")
async def update_worker(
    worker_name: str,
    payload: WorkerConfigUpdate,
    search_worker: SearchWorker = Depends(get_search_worker),
    detail_worker: DetailWorker = Depends(get_detail_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, search_worker, detail_worker).update_worker(payload)
    return WorkerConfigRead(**item.model_dump())


@router.post("/workers/{worker_name}/start", response_model=WorkerConfigRead, tags=["workers"], operation_id="start_worker")
async def start_worker(
    worker_name: str,
    search_worker: SearchWorker = Depends(get_search_worker),
    detail_worker: DetailWorker = Depends(get_detail_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, search_worker, detail_worker).start_worker()
    return WorkerConfigRead(**item.model_dump())


@router.post("/workers/{worker_name}/stop", response_model=WorkerConfigRead, tags=["workers"], operation_id="stop_worker")
async def stop_worker(
    worker_name: str,
    search_worker: SearchWorker = Depends(get_search_worker),
    detail_worker: DetailWorker = Depends(get_detail_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, search_worker, detail_worker).stop_worker()
    return WorkerConfigRead(**item.model_dump())


@router.post("/workers/{worker_name}/release", response_model=WorkerConfigRead, tags=["workers"], operation_id="release_worker")
async def release_worker(
    worker_name: str,
    search_worker: SearchWorker = Depends(get_search_worker),
    detail_worker: DetailWorker = Depends(get_detail_worker),
) -> WorkerConfigRead:
    item = await _select_worker(worker_name, search_worker, detail_worker).release_worker()
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
def _select_worker(worker_name: str, search_worker: SearchWorker, detail_worker: DetailWorker) -> SearchWorker | DetailWorker:
    if worker_name == "search":
        return search_worker
    if worker_name == "detail":
        return detail_worker
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found.")
