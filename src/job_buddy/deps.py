from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.boss import BossClient, BossDoctorRunner
from job_buddy.config import Settings
from job_buddy.services import (
    ConversationService,
    DashboardService,
    GreetingService,
    JobCollectionService,
    SystemService,
    TargetProfileService,
)


async def get_database(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.db


async def get_boss_client(request: Request) -> BossClient:
    return request.app.state.boss_client


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_target_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> TargetProfileService:
    return TargetProfileService(db)


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


async def get_conversation_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    boss_client: BossClient = Depends(get_boss_client),
) -> ConversationService:
    return ConversationService(db, boss_client)


async def get_dashboard_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> DashboardService:
    return DashboardService(db)


async def get_system_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
    boss_client: BossClient = Depends(get_boss_client),
) -> SystemService:
    return SystemService(BossDoctorRunner(settings), settings, boss_client, db)
