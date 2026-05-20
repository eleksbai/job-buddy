from fastapi import APIRouter

from job_buddy.routers import boss, web


def build_api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(boss.router)
    router.include_router(web.router)
    return router
