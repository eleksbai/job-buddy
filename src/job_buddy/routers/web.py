from fastapi import APIRouter, Depends, Query, Response, status

from job_buddy.boss import BossClient
from job_buddy.deps import get_boss_client, get_dashboard_service, get_system_service
from job_buddy.schemas import (
    DataClearResponse,
    HealthResponse,
    LogsResponse,
    SearchOptionsResponse,
)
from job_buddy.services import DashboardService, SystemService

router = APIRouter(prefix="/web")


@router.get("/health", response_model=HealthResponse, tags=["health"], operation_id="get_health")
async def get_health(boss_client: BossClient = Depends(get_boss_client)) -> HealthResponse:
    client_status = await boss_client.healthcheck()
    return HealthResponse(
        status="ok",
        mongodb="connected",
        boss_client=client_status.status or "unknown",
    )


@router.get("/dashboard", tags=["dashboard"], operation_id="get_dashboard_summary")
async def get_dashboard_summary(service: DashboardService = Depends(get_dashboard_service)) -> dict[str, int]:
    return await service.get_summary()


@router.get("/system/search-options", response_model=SearchOptionsResponse, tags=["system"], operation_id="get_search_options")
async def get_search_options(service: SystemService = Depends(get_system_service)) -> SearchOptionsResponse:
    return await service.get_search_options()


@router.get("/system/logs", response_model=LogsResponse, tags=["system"], operation_id="get_logs")
async def get_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    service: SystemService = Depends(get_system_service),
) -> LogsResponse:
    return await service.get_logs(limit=limit)


@router.post("/system/data/clear", response_model=DataClearResponse, tags=["system"], operation_id="clear_data")
async def clear_data(service: SystemService = Depends(get_system_service)) -> DataClearResponse:
    return await service.clear_data()
