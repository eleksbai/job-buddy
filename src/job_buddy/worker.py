"""AI matching background worker — periodically evaluates unevaluated jobs."""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.boss import BossClient
from job_buddy.config import Settings
from job_buddy.models import WorkerConfig
from job_buddy.services import AIMatchingService, BaseWorker

logger = logging.getLogger(__name__)


class AIMatchingWorker(BaseWorker):
    worker_name = "ai_matching"

    def __init__(
        self,
        database: AsyncIOMotorDatabase,
        boss_client: BossClient,
        settings: Settings,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        super().__init__(database, boss_client, poll_interval_seconds)
        self.settings = settings

    def default_config(self) -> WorkerConfig:
        return WorkerConfig(
            worker_name="ai_matching",
            interval_seconds=3600,
            batch_size=10,
        )

    async def execute_enabled_worker(self, worker: WorkerConfig) -> WorkerConfig:
        service = AIMatchingService(self.database, self.settings)
        logger.info("executing worker %s start", self.worker_name)
        task = await service.run_evaluation_task(limit=max(1, worker.batch_size))
        logger.info("executing worker %s %s", self.worker_name, task.status)
        return await self.complete_execution(worker, task)
