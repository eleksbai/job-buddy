from fastapi import APIRouter, Depends, Query

from job_buddy.deps import get_job_service
from job_buddy.modules.jobs import JobCollectionRecordRead, JobCollectionService, JobLeadRead

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
