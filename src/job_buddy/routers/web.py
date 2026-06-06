import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from job_buddy.boss import BossClient
from job_buddy.deps import get_agent_worker, get_ai_matching_service, get_boss_client, get_dashboard_service, get_statistics_service, get_system_service
from job_buddy.schemas import (
    DataClearResponse,
    HealthResponse,
    LogsResponse,
    SearchOptionsResponse,
)
from job_buddy.services import AIMatchingService, DashboardService, StatisticsService, SystemService
from job_buddy.messaging import send_feishu

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


@router.post("/statistics/today/send", tags=["statistics"], operation_id="send_today_statistics")
async def send_today_statistics(service: StatisticsService = Depends(get_statistics_service)) -> dict:
    stats = await service.get_today_stats()

    updated = stats["updated_today"]
    created = stats["created_today"]

    await send_feishu(
        f"24小时内职位统计\n\n"
        f"24小时内更新: {updated['total']}（匹配: {updated['matched']} | 不匹配: {updated['unmatched']} | 未分析: {updated['unanalyzed']}）\n"
        f"24小时内新增: {created['total']}（匹配: {created['matched']} | 不匹配: {created['unmatched']} | 未分析: {created['unanalyzed']}）"
    )

    return stats


@router.get("/agent/events", tags=["agent"], operation_id="agent_events")
async def agent_events(request: Request, agent_worker=Depends(get_agent_worker)):
    async def event_generator():
        async for event in agent_worker.subscribe():
            if await request.is_disconnected():
                break
            data_str = json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event['type']}\ndata: {data_str}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/chat", tags=["agent"], operation_id="agent_chat")
async def agent_chat(payload: dict, agent_worker=Depends(get_agent_worker)) -> dict:
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息不能为空")
    asyncio.create_task(agent_worker.handle_chat(text))
    return {"status": "ok"}


@router.get("/profiles", tags=["profiles"], operation_id="list_profiles")
async def list_profiles(service: AIMatchingService = Depends(get_ai_matching_service)) -> list[dict]:
    return await service.get_all_profiles()


@router.put("/profiles/{name}", tags=["profiles"], operation_id="save_profile")
async def save_profile(name: str, payload: dict, service: AIMatchingService = Depends(get_ai_matching_service)) -> dict:
    return {"name": name, "content": await service.save_profile(name, payload.get("content", ""))}


@router.post("/profiles/{name}/reset", tags=["profiles"], operation_id="reset_profile")
async def reset_profile(name: str, service: AIMatchingService = Depends(get_ai_matching_service)) -> dict:
    return {"name": name, "content": await service.reset_profile(name)}
