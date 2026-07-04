import asyncio
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def _preimport_lark_oapi() -> None:
    import lark_oapi.channel  # noqa: F401  # force ws/client.py module-level init in clean thread


_t = threading.Thread(target=_preimport_lark_oapi, daemon=True)
_t.start()
_t.join()

from job_buddy.boss import BossClient, BossOperationError
from job_buddy.config import configure_logging, get_settings
from job_buddy.db import MongoManager, database_lifespan
from job_buddy.messaging.feishu import FeishuChannelManager, set_manager
from job_buddy.routers import build_api_router
from job_buddy.worker import AIMatchingWorker
from job_buddy.agent import AgentWorker
from job_buddy.services import ScrollAndCollectWorker, fail_abandoned_running_tasks
from job_buddy.web.app import register_web

logger = logging.getLogger(__name__)


def _schedule_force_exit(delay: float = 5.0) -> None:
    """Arm a daemon timer that force-exits if background threads block shutdown."""

    def _force() -> None:
        logger.warning("Force exit: processes still alive after %.0fs", delay)
        os._exit(0)

    timer = threading.Timer(delay, _force)
    timer.daemon = True
    timer.start()
    logger.info("Force-exit guard armed (delay=%.0fs)", delay)


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
            feishu_manager = FeishuChannelManager(database)
            scroll_and_collect_worker = ScrollAndCollectWorker(database, boss_client)
            ai_matching_worker = AIMatchingWorker(database, boss_client, settings=settings)
            agent_worker = AgentWorker(database, boss_client, settings, feishu_manager)
            recovered_tasks = await fail_abandoned_running_tasks(database)
            if recovered_tasks:
                logger.warning("Marked %s abandoned running tasks as failed on startup", recovered_tasks)
            app.state.settings = settings
            app.state.db = database
            app.state.boss_client = boss_client
            app.state.scroll_and_collect_worker = scroll_and_collect_worker
            app.state.ai_matching_worker = ai_matching_worker
            app.state.agent_worker = agent_worker

            set_manager(feishu_manager)
            await feishu_manager.start()

            try:
                await scroll_and_collect_worker.start()
                await ai_matching_worker.start()
                await agent_worker.start()
                yield
            finally:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            agent_worker.stop(),
                            ai_matching_worker.stop(),
                            scroll_and_collect_worker.stop(),
                        ),
                        timeout=30.0,
                    )
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    logger.warning("Workers did not stop gracefully within timeout")
                except Exception:
                    logger.exception("Error during worker shutdown")
                await boss_client.close()
                await feishu_manager.stop()
                _schedule_force_exit()

    app = FastAPI(title=settings.app.name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(build_api_router())
    register_web(app)
    app.router.lifespan_context = lifespan
    return app


app = create_app()
