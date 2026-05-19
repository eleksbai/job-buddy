from fastapi import APIRouter, Depends, Query

from job_buddy.core.boss import BossOperationError
from job_buddy.deps import get_job_service
from job_buddy.modules.jobs import (
    JobCollectionRecordRead,
    JobCollectionService,
    JobDetailResponse,
    JobLeadDetailRead,
    JobLeadRead,
    SearchJobsRequest,
    SearchJobsResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobLeadRead], operation_id="list_jobs")
async def list_jobs(
    match_status: str | None = None,
    greeted: bool | None = None,
    limit: int = Query(default=100, le=200),
    service: JobCollectionService = Depends(get_job_service),
) -> list[JobLeadRead]:
    jobs = await service.list_jobs(match_status=match_status, greeted=greeted, limit=limit)
    return [JobLeadRead(**item.model_dump()) for item in jobs]


@router.get("/{source_job_id}/detail", response_model=JobDetailResponse, operation_id="get_job_detail")
async def get_job_detail(
    source_job_id: str,
    security_id: str | None = Query(default=None, description="BOSS security_id, used when job is not yet in the database"),
    service: JobCollectionService = Depends(get_job_service),
) -> JobDetailResponse:
    job, cached = await service.get_job_detail(source_job_id, security_id=security_id)
    return JobDetailResponse(cached=cached, job=JobLeadDetailRead(**job.model_dump()))


@router.post("/search", response_model=SearchJobsResponse, operation_id="search_jobs")
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


@router.get("/collections", response_model=list[JobCollectionRecordRead], operation_id="list_job_collection_records")
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
