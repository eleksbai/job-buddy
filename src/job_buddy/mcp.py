from fastapi import FastAPI

from job_buddy.modules.conversations import ConversationRepository
from job_buddy.modules.jobs import GreetingTaskRepository, JobCollectionRecordRepository, JobLeadRepository
from job_buddy.modules.targets import TargetProfileRepository


def build_mcp_server(app: FastAPI):
    from fastmcp import FastMCP

    mcp = FastMCP("Job Buddy MCP")

    @mcp.tool
    async def list_targets(limit: int = 100) -> list[dict]:
        repository = TargetProfileRepository(app.state.db)
        items = await repository.list(limit=limit)
        return [item.model_dump() for item in items]

    @mcp.tool
    async def list_jobs(limit: int = 100) -> list[dict]:
        repository = JobLeadRepository(app.state.db)
        items = await repository.list(limit=limit)
        return [item.model_dump() for item in items]

    @mcp.tool
    async def list_job_collection_records(limit: int = 100) -> list[dict]:
        repository = JobCollectionRecordRepository(app.state.db)
        items = await repository.list(limit=limit)
        return [item.model_dump() for item in items]

    @mcp.tool
    async def list_tasks(limit: int = 100) -> list[dict]:
        repository = GreetingTaskRepository(app.state.db)
        items = await repository.list(limit=limit)
        return [item.model_dump() for item in items]

    @mcp.tool
    async def get_task(task_id: str) -> dict | None:
        repository = GreetingTaskRepository(app.state.db)
        task = await repository.get(task_id)
        return task.model_dump() if task else None

    @mcp.tool
    async def list_conversations(limit: int = 100) -> list[dict]:
        repository = ConversationRepository(app.state.db)
        items = await repository.list(limit=limit)
        return [item.model_dump() for item in items]

    @mcp.tool
    async def get_system_status() -> dict:
        client_status = await app.state.runtime.healthcheck()
        return {
            "status": "ok",
            "mongodb": app.state.settings.mongodb_db,
            "boss_client": client_status,
        }

    return mcp
