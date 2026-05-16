from datetime import UTC, datetime

import pytest
from fastapi import FastAPI

from job_buddy.deps import get_greeting_service
from job_buddy.modules.jobs import GreetingTask
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeGreetingService:
    async def list_tasks(self, limit: int):
        _ = limit
        return [
            GreetingTask(
                _id="6825fb1a7d4ce9adcc2d1a41",
                task_type="search",
                status="failed",
                input_payload={"keywords": ["Python"]},
                result_summary={"fetched": 1},
                error_message="非法参数 city: Shanghai",
                started_at=datetime(2026, 5, 15, 14, 4, 26, 697000, tzinfo=UTC),
                finished_at=datetime(2026, 5, 15, 14, 4, 26, 705000, tzinfo=UTC),
            )
        ]


@pytest.mark.asyncio
async def test_list_tasks_serializes_datetime_fields():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_greeting_service] = lambda: FakeGreetingService()

    async with api_client(app) as client:
        response = await client.get("/api/tasks")

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["started_at"].startswith("2026-05-15T14:04:26")
    assert payload["finished_at"].startswith("2026-05-15T14:04:26")
    assert payload["error_message"] == "非法参数 city: Shanghai"
