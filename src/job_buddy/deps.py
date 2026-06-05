from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.boss import BossClient, BossDoctorRunner
from job_buddy.config import Settings
from job_buddy.services import (
    AIMatchingService,
    DashboardService,
    DetailWorker,
    FriendService,
    GreetingService,
    JobCollectionService,
    ScrollAndCollectWorker,
    SearchWorker,
    StatisticsService,
    SystemService,
)


async def get_database(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.db


async def get_boss_client(request: Request) -> BossClient:
    return request.app.state.boss_client


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_job_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    boss_client: BossClient = Depends(get_boss_client),
) -> JobCollectionService:
    return JobCollectionService(db, boss_client)


async def get_greeting_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    boss_client: BossClient = Depends(get_boss_client),
) -> GreetingService:
    return GreetingService(db, boss_client)


async def get_friend_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    boss_client: BossClient = Depends(get_boss_client),
) -> FriendService:
    return FriendService(db, boss_client)


async def get_dashboard_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> DashboardService:
    return DashboardService(db)


async def get_system_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
    boss_client: BossClient = Depends(get_boss_client),
) -> SystemService:
    return SystemService(BossDoctorRunner(settings), settings, boss_client, db)


async def get_statistics_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> StatisticsService:
    return StatisticsService(db)


async def get_search_worker(request: Request) -> SearchWorker:
    return request.app.state.search_worker


async def get_detail_worker(request: Request) -> DetailWorker:
    return request.app.state.detail_worker


async def get_scroll_and_collect_worker(request: Request) -> ScrollAndCollectWorker:
    return request.app.state.scroll_and_collect_worker


async def get_ai_matching_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AIMatchingService:
    return AIMatchingService(db, settings)


async def get_ai_matching_worker(request: Request):
    from job_buddy.worker import AIMatchingWorker

    return request.app.state.ai_matching_worker


async def get_agent_worker(request: Request):
    return request.app.state.agent_worker
