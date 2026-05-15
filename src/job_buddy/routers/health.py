from fastapi import APIRouter, Depends

from job_buddy.deps import get_boss_client
from job_buddy.core.boss import BossClientProtocol
from job_buddy.modules.system import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, operation_id="get_health")
async def get_health(boss_client: BossClientProtocol = Depends(get_boss_client)) -> HealthResponse:
    client_status = await boss_client.healthcheck()
    return HealthResponse(
        status="ok",
        mongodb="connected",
        boss_client=client_status.get("status", "unknown"),
    )
