from fastapi import APIRouter, Depends, Query, Response, status

from job_buddy.core.engines.runtime import EngineRuntimeManager
from job_buddy.deps import get_dashboard_service, get_runtime, get_system_service, get_target_service
from job_buddy.schemas import (
    DataClearResponse,
    HealthResponse,
    LogsResponse,
    SearchOptionsResponse,
    TargetProfileCreate,
    TargetProfileRead,
    TargetProfileUpdate,
)
from job_buddy.services import DashboardService, SystemService, TargetProfileService

router = APIRouter(prefix="/web")


@router.get("/health", response_model=HealthResponse, tags=["health"], operation_id="get_health")
async def get_health(runtime: EngineRuntimeManager = Depends(get_runtime)) -> HealthResponse:
    client_status = await runtime.healthcheck()
    return HealthResponse(
        status="ok",
        mongodb="connected",
        boss_client=client_status.get("status", "unknown"),
    )


@router.get("/dashboard", tags=["dashboard"], operation_id="get_dashboard_summary")
async def get_dashboard_summary(service: DashboardService = Depends(get_dashboard_service)) -> dict[str, int]:
    return await service.get_summary()


@router.get("/targets", response_model=list[TargetProfileRead], tags=["targets"], operation_id="list_targets")
async def list_targets(service: TargetProfileService = Depends(get_target_service)) -> list[TargetProfileRead]:
    return [TargetProfileRead(**item.model_dump()) for item in await service.list_targets()]


@router.post("/targets", response_model=TargetProfileRead, status_code=status.HTTP_201_CREATED, tags=["targets"], operation_id="create_target")
async def create_target(
    payload: TargetProfileCreate,
    service: TargetProfileService = Depends(get_target_service),
) -> TargetProfileRead:
    target = await service.create_target(payload)
    return TargetProfileRead(**target.model_dump())


@router.get("/targets/{target_id}", response_model=TargetProfileRead, tags=["targets"], operation_id="get_target")
async def get_target(target_id: str, service: TargetProfileService = Depends(get_target_service)) -> TargetProfileRead:
    target = await service.get_target(target_id)
    return TargetProfileRead(**target.model_dump())


@router.put("/targets/{target_id}", response_model=TargetProfileRead, tags=["targets"], operation_id="update_target")
async def update_target(
    target_id: str,
    payload: TargetProfileUpdate,
    service: TargetProfileService = Depends(get_target_service),
) -> TargetProfileRead:
    target = await service.update_target(target_id, payload)
    return TargetProfileRead(**target.model_dump())


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["targets"], operation_id="delete_target")
async def delete_target(target_id: str, service: TargetProfileService = Depends(get_target_service)) -> Response:
    await service.delete_target(target_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
