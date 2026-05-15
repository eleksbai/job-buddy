from fastapi import APIRouter, Depends

from job_buddy.deps import get_system_service
from job_buddy.modules.system import (
    AuthStatusResponse,
    BrowserControlResponse,
    CdpStatusResponse,
    DoctorResponse,
    SystemService,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/doctor", response_model=DoctorResponse, operation_id="run_boss_doctor")
async def run_boss_doctor(service: SystemService = Depends(get_system_service)) -> DoctorResponse:
    return await service.run_doctor()


@router.get("/cdp", response_model=CdpStatusResponse, operation_id="get_cdp_status")
async def get_cdp_status(service: SystemService = Depends(get_system_service)) -> CdpStatusResponse:
    return await service.get_cdp_status()


@router.get("/auth", response_model=AuthStatusResponse, operation_id="get_auth_status")
async def get_auth_status(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.get_auth_status()


@router.post("/auth/login", response_model=AuthStatusResponse, operation_id="login_auth")
async def login_auth(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.login()


@router.post("/auth/logout", response_model=AuthStatusResponse, operation_id="logout_auth")
async def logout_auth(service: SystemService = Depends(get_system_service)) -> AuthStatusResponse:
    return await service.logout()


@router.post("/cdp/start", response_model=BrowserControlResponse, operation_id="start_cdp_browser")
async def start_cdp_browser(service: SystemService = Depends(get_system_service)) -> BrowserControlResponse:
    return await service.start_cdp_browser()


@router.post("/cdp/stop", response_model=BrowserControlResponse, operation_id="stop_cdp_browser")
async def stop_cdp_browser(service: SystemService = Depends(get_system_service)) -> BrowserControlResponse:
    return await service.stop_cdp_browser()
