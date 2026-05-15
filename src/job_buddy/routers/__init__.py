from fastapi import APIRouter

from job_buddy.routers import conversations, dashboard, health, jobs, system, targets, tasks


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    router.include_router(health.router)
    router.include_router(system.router)
    router.include_router(dashboard.router)
    router.include_router(targets.router)
    router.include_router(jobs.router)
    router.include_router(tasks.router)
    router.include_router(conversations.router)
    return router
