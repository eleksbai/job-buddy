from datetime import UTC, datetime

import pytest
from fastapi import FastAPI

from job_buddy.deps import get_worker_service
from job_buddy.models import WorkerConfig
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeWorkerService:
    def __init__(self) -> None:
        now = datetime.now(tz=UTC)
        self.items = {
            "search": WorkerConfig(
                _id="6825fb1a7d4ce9adcc2d1a41",
                worker_name="search",
                enabled=False,
                interval_seconds=60,
                next_run_at=None,
                status="idle",
                query={"keywords": ["Python"]},
                page=1,
                page_max=5,
                batch_size=1,
                created_at=now,
                updated_at=now,
            ),
            "detail": WorkerConfig(
                _id="6825fb1a7d4ce9adcc2d1a42",
                worker_name="detail",
                enabled=False,
                interval_seconds=30,
                next_run_at=None,
                status="idle",
                query={},
                page=1,
                page_max=5,
                batch_size=1,
                created_at=now,
                updated_at=now,
            ),
        }

    async def list_workers(self):
        return list(self.items.values())

    async def get_worker(self, worker_name: str):
        return self.items[worker_name]

    async def update_worker(self, worker_name: str, payload):
        data = payload.model_dump(exclude_none=True)
        current = self.items[worker_name]
        self.items[worker_name] = current.model_copy(update=data)
        return self.items[worker_name]

    async def start_worker(self, worker_name: str):
        current = self.items[worker_name]
        self.items[worker_name] = current.model_copy(update={"enabled": True, "status": "idle"})
        return self.items[worker_name]

    async def stop_worker(self, worker_name: str):
        current = self.items[worker_name]
        self.items[worker_name] = current.model_copy(update={"enabled": False, "status": "idle"})
        return self.items[worker_name]


@pytest.mark.asyncio
async def test_list_workers_returns_default_disabled_configs():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_worker_service] = lambda: FakeWorkerService()

    async with api_client(app) as client:
        response = await client.get("/boss/workers")

    assert response.status_code == 200
    payload = response.json()
    assert {item["worker_name"] for item in payload} == {"search", "detail"}
    assert all(item["enabled"] is False for item in payload)


@pytest.mark.asyncio
async def test_update_search_worker_accepts_query_and_page_max():
    app = FastAPI()
    app.include_router(build_api_router())
    service = FakeWorkerService()
    app.dependency_overrides[get_worker_service] = lambda: service

    async with api_client(app) as client:
        response = await client.put(
            "/boss/workers/search",
            json={"interval_seconds": 45, "page_max": 8, "query": {"keywords": ["Python", "FastAPI"]}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["interval_seconds"] == 45
    assert payload["page_max"] == 8
    assert payload["query"]["keywords"] == ["Python", "FastAPI"]


@pytest.mark.asyncio
async def test_start_and_stop_worker_toggle_enabled():
    app = FastAPI()
    app.include_router(build_api_router())
    service = FakeWorkerService()
    app.dependency_overrides[get_worker_service] = lambda: service

    async with api_client(app) as client:
        start_response = await client.post("/boss/workers/detail/start")
        stop_response = await client.post("/boss/workers/detail/stop")

    assert start_response.status_code == 200
    assert start_response.json()["enabled"] is True
    assert stop_response.status_code == 200
    assert stop_response.json()["enabled"] is False
