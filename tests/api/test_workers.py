from datetime import UTC, datetime

import pytest
from fastapi import FastAPI

from job_buddy.deps import get_agent_worker, get_ai_matching_worker, get_scroll_and_collect_worker
from job_buddy.models import WorkerConfig
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeWorker:
    def __init__(self, worker: WorkerConfig) -> None:
        self.worker = worker

    async def get_worker(self) -> WorkerConfig:
        return self.worker

    async def update_worker(self, payload) -> WorkerConfig:
        self.worker = self.worker.model_copy(update=payload.model_dump(exclude_none=True))
        return self.worker

    async def start_worker(self) -> WorkerConfig:
        self.worker = self.worker.model_copy(update={"enabled": True, "status": "idle"})
        return self.worker

    async def stop_worker(self) -> WorkerConfig:
        self.worker = self.worker.model_copy(update={"enabled": False, "status": "idle"})
        return self.worker

    async def release_worker(self) -> WorkerConfig:
        self.worker = self.worker.model_copy(update={"status": "idle", "last_error": None})
        return self.worker


def build_fake_workers():
    now = datetime.now(tz=UTC)
    scroll_and_collect_worker = FakeWorker(
        WorkerConfig(
            _id="6825fb1a7d4ce9adcc2d1a43",
            worker_name="scroll_and_collect",
            enabled=False,
            interval_seconds=60,
            next_run_at=None,
            status="idle",
            query={"schedule_times": ["09:00", "14:00", "18:00"]},
            page=1,
            page_max=5,
            batch_size=100,
            created_at=now,
            updated_at=now,
        )
    )
    ai_matching_worker = FakeWorker(
        WorkerConfig(
            _id="6825fb1a7d4ce9adcc2d1a44",
            worker_name="ai_matching",
            enabled=False,
            interval_seconds=3600,
            next_run_at=None,
            status="idle",
            query={},
            page=1,
            page_max=5,
            batch_size=10,
            created_at=now,
            updated_at=now,
        )
    )
    agent_worker = FakeWorker(
        WorkerConfig(
            _id="6825fb1a7d4ce9adcc2d1a45",
            worker_name="agent",
            enabled=False,
            interval_seconds=3600,
            next_run_at=None,
            status="idle",
            query={"schedule_times": ["09:00", "14:00", "18:00"], "schedule_jitter_minutes": 60, "greet_limit": 10},
            page=1,
            page_max=5,
            batch_size=10,
            created_at=now,
            updated_at=now,
        )
    )
    return scroll_and_collect_worker, ai_matching_worker, agent_worker


@pytest.mark.asyncio
async def test_list_workers_returns_default_disabled_configs():
    app = FastAPI()
    app.include_router(build_api_router())
    scroll_and_collect_worker, ai_matching_worker, agent_worker = build_fake_workers()
    app.dependency_overrides[get_scroll_and_collect_worker] = lambda: scroll_and_collect_worker
    app.dependency_overrides[get_ai_matching_worker] = lambda: ai_matching_worker
    app.dependency_overrides[get_agent_worker] = lambda: agent_worker

    async with api_client(app) as client:
        response = await client.get("/boss/workers")

    assert response.status_code == 200
    payload = response.json()
    assert {item["worker_name"] for item in payload} == {"scroll_and_collect", "ai_matching", "agent"}
    assert all(item["enabled"] is False for item in payload)


@pytest.mark.asyncio
async def test_update_scroll_and_collect_worker_accepts_query():
    app = FastAPI()
    app.include_router(build_api_router())
    scroll_and_collect_worker, ai_matching_worker, agent_worker = build_fake_workers()
    app.dependency_overrides[get_scroll_and_collect_worker] = lambda: scroll_and_collect_worker
    app.dependency_overrides[get_ai_matching_worker] = lambda: ai_matching_worker
    app.dependency_overrides[get_agent_worker] = lambda: agent_worker

    async with api_client(app) as client:
        response = await client.put(
            "/boss/workers/scroll_and_collect",
            json={"interval_seconds": 45, "batch_size": 200, "query": {"schedule_times": ["08:00", "20:00"]}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["interval_seconds"] == 45
    assert payload["batch_size"] == 200
    assert payload["query"]["schedule_times"] == ["08:00", "20:00"]


@pytest.mark.asyncio
async def test_start_and_stop_worker_toggle_enabled():
    app = FastAPI()
    app.include_router(build_api_router())
    scroll_and_collect_worker, ai_matching_worker, agent_worker = build_fake_workers()
    app.dependency_overrides[get_scroll_and_collect_worker] = lambda: scroll_and_collect_worker
    app.dependency_overrides[get_ai_matching_worker] = lambda: ai_matching_worker
    app.dependency_overrides[get_agent_worker] = lambda: agent_worker

    async with api_client(app) as client:
        start_response = await client.post("/boss/workers/scroll_and_collect/start")
        stop_response = await client.post("/boss/workers/scroll_and_collect/stop")

    assert start_response.status_code == 200
    assert start_response.json()["enabled"] is True
    assert stop_response.status_code == 200
    assert stop_response.json()["enabled"] is False


@pytest.mark.asyncio
async def test_release_worker_clears_error():
    app = FastAPI()
    app.include_router(build_api_router())
    scroll_and_collect_worker, ai_matching_worker, agent_worker = build_fake_workers()
    scroll_and_collect_worker.worker = scroll_and_collect_worker.worker.model_copy(update={"enabled": True, "status": "error", "last_error": "boom"})
    app.dependency_overrides[get_scroll_and_collect_worker] = lambda: scroll_and_collect_worker
    app.dependency_overrides[get_ai_matching_worker] = lambda: ai_matching_worker
    app.dependency_overrides[get_agent_worker] = lambda: agent_worker

    async with api_client(app) as client:
        response = await client.post("/boss/workers/scroll_and_collect/release")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "idle"
    assert payload["last_error"] is None


@pytest.mark.asyncio
async def test_invalid_worker_name_returns_not_found():
    app = FastAPI()
    app.include_router(build_api_router())
    scroll_and_collect_worker, ai_matching_worker, agent_worker = build_fake_workers()
    app.dependency_overrides[get_scroll_and_collect_worker] = lambda: scroll_and_collect_worker
    app.dependency_overrides[get_ai_matching_worker] = lambda: ai_matching_worker
    app.dependency_overrides[get_agent_worker] = lambda: agent_worker

    async with api_client(app) as client:
        response = await client.get("/boss/workers/unknown")

    assert response.status_code == 404
