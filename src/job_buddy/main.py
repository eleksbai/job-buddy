from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from job_buddy.boss import BossClient, BossOperationError
from job_buddy.config import configure_logging, get_settings
from job_buddy.db import MongoManager, database_lifespan
from job_buddy.routers import build_api_router
from job_buddy.worker import AIMatchingWorker
from job_buddy.services import DetailWorker, ScrollAndCollectWorker, SearchWorker, fail_abandoned_running_tasks
from job_buddy.web.app import register_web

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BossOperationError)
    async def handle_boss_operation_error(request: Request, exc: BossOperationError) -> JSONResponse:
        payload = {
            "detail": exc.message,
            "code": exc.code,
            "recoverable": exc.recoverable,
        }
        if exc.recovery_action:
            payload["recovery_action"] = exc.recovery_action

        if exc.boss_side:
            logger.warning(
                "Boss site error on %s %s: %s (code=%s)",
                request.method,
                request.url.path,
                exc.message,
                exc.code,
            )
        else:
            logger.error(
                "Boss operation failed on %s %s: %s (code=%s)",
                request.method,
                request.url.path,
                exc.message,
                exc.code,
            )

        return JSONResponse(status_code=exc.status_code, content=payload)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    mongo_manager = MongoManager(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with database_lifespan(mongo_manager) as database:
            boss_client = BossClient(settings)
            search_worker = SearchWorker(database, boss_client)
            detail_worker = DetailWorker(database, boss_client)
            scroll_and_collect_worker = ScrollAndCollectWorker(database, boss_client)
            ai_matching_worker = AIMatchingWorker(database, boss_client, settings=settings)
            recovered_tasks = await fail_abandoned_running_tasks(database)
            if recovered_tasks:
                logger.warning("Marked %s abandoned running tasks as failed on startup", recovered_tasks)
            app.state.settings = settings
            app.state.db = database
            app.state.boss_client = boss_client
            app.state.search_worker = search_worker
            app.state.detail_worker = detail_worker
            app.state.scroll_and_collect_worker = scroll_and_collect_worker
            app.state.ai_matching_worker = ai_matching_worker

            try:
                await search_worker.start()
                await detail_worker.start()
                await scroll_and_collect_worker.start()
                await ai_matching_worker.start()
                yield
            finally:
                await ai_matching_worker.stop()
                await scroll_and_collect_worker.stop()
                await detail_worker.stop()
                await search_worker.stop()
                await boss_client.close()

    app = FastAPI(title=settings.app.name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(build_api_router())
    register_web(app)
    app.router.lifespan_context = lifespan
    return app


app = create_app()
