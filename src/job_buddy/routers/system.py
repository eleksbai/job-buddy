from fastapi import APIRouter, Depends

from job_buddy.deps import get_system_service
from job_buddy.modules.system import DoctorResponse, SystemService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/doctor", response_model=DoctorResponse, operation_id="run_boss_doctor")
async def run_boss_doctor(service: SystemService = Depends(get_system_service)) -> DoctorResponse:
    return await service.run_doctor()
