from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from job_buddy.core.boss import BossOperationError
from job_buddy.core.config import get_settings
from job_buddy.core.database import MongoManager, database_lifespan
from job_buddy.core.engines import build_engine_runtime
from job_buddy.core.logging import configure_logging
from job_buddy.routers import build_api_router
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
            cause = exc.__cause__
            exc_info = None
            if cause is not None:
                exc_info = (type(cause), cause, cause.__traceback__)
            else:
                exc_info = (type(exc), exc, exc.__traceback__)
            logger.error(
                "Boss operation failed on %s %s\n%s",
                request.method,
                request.url.path,
                exc.message,
                exc_info=exc_info,
            )

        return JSONResponse(status_code=exc.status_code, content=payload)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    mongo_manager = MongoManager(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with database_lifespan(mongo_manager) as database:
            runtime = build_engine_runtime(settings)
            app.state.settings = settings
            app.state.db = database
            app.state.runtime = runtime

            try:
                yield
            finally:
                await runtime.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(build_api_router())
    register_web(app)
    app.router.lifespan_context = lifespan
    return app


app = create_app()
