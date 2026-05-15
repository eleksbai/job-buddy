from fastapi import APIRouter, Depends

from job_buddy.deps import get_dashboard_service
from job_buddy.modules.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", operation_id="get_dashboard_summary")
async def get_dashboard_summary(service: DashboardService = Depends(get_dashboard_service)) -> dict[str, int]:
    return await service.get_summary()
