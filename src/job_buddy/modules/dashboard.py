from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.modules.conversations import ConversationRepository
from job_buddy.modules.jobs import GreetingTaskRepository, JobLeadRepository
from job_buddy.modules.targets import TargetProfileRepository


class DashboardService:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.targets = TargetProfileRepository(database)
        self.jobs = JobLeadRepository(database)
        self.tasks = GreetingTaskRepository(database)
        self.conversations = ConversationRepository(database)

    async def get_summary(self) -> dict[str, int]:
        return {
            "targets": await self.targets.count(),
            "jobs": await self.jobs.count(),
            "tasks": await self.tasks.count(),
            "conversations": await self.conversations.count(),
        }
