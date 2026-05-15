from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from job_buddy.core.boss import build_boss_client
from job_buddy.core.config import get_settings
from job_buddy.core.database import MongoManager, database_lifespan
from job_buddy.core.logging import configure_logging
from job_buddy.mcp import build_mcp_server
from job_buddy.routers import build_api_router
from job_buddy.web.app import register_web


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.app_log_level)
    mongo_manager = MongoManager(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with database_lifespan(mongo_manager) as database:
            app.state.settings = settings
            app.state.db = database
            app.state.boss_client = build_boss_client(settings)
            yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(build_api_router())
    register_web(app)

    mcp = build_mcp_server(app)
    mcp_app = mcp.http_app(path="/mcp")
    app.router.lifespan_context = lifespan
    app.mount("/mcp", mcp_app)
    return app


app = create_app()
