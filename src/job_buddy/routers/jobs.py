from fastapi import APIRouter, Depends, Query

from job_buddy.deps import get_job_service
from job_buddy.modules.jobs import JobCollectionService, JobLeadRead

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
