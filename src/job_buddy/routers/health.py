from fastapi import APIRouter, Depends

from job_buddy.deps import get_runtime
from job_buddy.core.engines.runtime import EngineRuntimeManager
from job_buddy.modules.system import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, operation_id="get_health")
async def get_health(runtime: EngineRuntimeManager = Depends(get_runtime)) -> HealthResponse:
    client_status = await runtime.healthcheck()
    return HealthResponse(
        status="ok",
        mongodb="connected",
        boss_client=client_status.get("status", "unknown"),
    )
