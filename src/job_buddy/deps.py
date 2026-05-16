from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.core.boss import BossDoctorRunner
from job_buddy.core.config import Settings
from job_buddy.core.engines.runtime import EngineRuntimeManager
from job_buddy.modules.conversations import ConversationService
from job_buddy.modules.dashboard import DashboardService
from job_buddy.modules.jobs import JobCollectionService
from job_buddy.modules.system import AuthStateRepository, SystemService
from job_buddy.modules.targets import TargetProfileService
from job_buddy.modules.tasks import GreetingService


async def get_database(request: Request) -> AsyncIOMotorDatabase:
    return request.app.state.db


async def get_runtime(request: Request) -> EngineRuntimeManager:
    return request.app.state.runtime


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_target_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> TargetProfileService:
    return TargetProfileService(db)


async def get_job_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    runtime: EngineRuntimeManager = Depends(get_runtime),
) -> JobCollectionService:
    return JobCollectionService(db, runtime)


async def get_greeting_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    runtime: EngineRuntimeManager = Depends(get_runtime),
) -> GreetingService:
    return GreetingService(db, runtime)


async def get_conversation_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    runtime: EngineRuntimeManager = Depends(get_runtime),
) -> ConversationService:
    return ConversationService(db, runtime)


async def get_dashboard_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> DashboardService:
    return DashboardService(db)


async def get_system_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
    runtime: EngineRuntimeManager = Depends(get_runtime),
) -> SystemService:
    return SystemService(
        BossDoctorRunner(settings),
        settings,
        runtime,
        AuthStateRepository(db),
    )
