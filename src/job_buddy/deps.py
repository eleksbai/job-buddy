from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.core.boss import BossClientProtocol, BossDoctorRunner
from job_buddy.core.config import Settings
from job_buddy.modules.conversations import ConversationService
from job_buddy.modules.dashboard import DashboardService
from job_buddy.modules.jobs import JobCollectionService
from job_buddy.modules.system import SystemService
from job_buddy.modules.targets import TargetProfileService
from job_buddy.modules.tasks import GreetingService


def get_database(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.db


def get_boss_client(request: Request) -> BossClientProtocol:
    return request.app.state.boss_client


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_target_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> TargetProfileService:
    return TargetProfileService(db)


def get_job_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    boss_client: BossClientProtocol = Depends(get_boss_client),
) -> JobCollectionService:
    return JobCollectionService(db, boss_client)


def get_greeting_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    boss_client: BossClientProtocol = Depends(get_boss_client),
) -> GreetingService:
    return GreetingService(db, boss_client)


def get_conversation_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    boss_client: BossClientProtocol = Depends(get_boss_client),
) -> ConversationService:
    return ConversationService(db, boss_client)


def get_dashboard_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> DashboardService:
    return DashboardService(db)


def get_system_service(settings: Settings = Depends(get_settings)) -> SystemService:
    return SystemService(BossDoctorRunner(settings))
