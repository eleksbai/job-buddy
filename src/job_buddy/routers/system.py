from fastapi import APIRouter, Depends, Query

from job_buddy.deps import get_system_service
from job_buddy.modules.system import (
    AuthStatusResponse,
    DoctorResponse,
    LogsResponse,
    SearchOptionsResponse,
    SystemService,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/doctor", response_model=DoctorResponse, operation_id="run_boss_doctor")
async def run_boss_doctor(service: SystemService = Depends(get_system_service)) -> DoctorResponse:
    return await service.run_doctor()


@router.get("/auth", response_model=AuthStatusResponse, operation_id="get_auth_status")
async def get_auth_status(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.get_auth_status()


@router.get("/search-options", response_model=SearchOptionsResponse, operation_id="get_search_options")
async def get_search_options(service: SystemService = Depends(get_system_service)) -> SearchOptionsResponse:
    return await service.get_search_options()


@router.get("/logs", response_model=LogsResponse, operation_id="get_logs")
async def get_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    service: SystemService = Depends(get_system_service),
) -> LogsResponse:
    return await service.get_logs(limit=limit)


@router.post("/auth/login", response_model=AuthStatusResponse, operation_id="login_auth")
async def login_auth(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.login()


@router.post("/auth/logout", response_model=AuthStatusResponse, operation_id="logout_auth")
async def logout_auth(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.logout()
