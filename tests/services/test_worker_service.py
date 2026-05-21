import asyncio
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from job_buddy.config import BOSS_ERROR_RETRY_DELAY_SECONDS
from job_buddy.models import GreetingTask, TaskStatus, WorkerConfig
from job_buddy.schemas import WorkerConfigUpdate
from job_buddy.services import WorkerService


class FakeInsertResult:
    def __init__(self, inserted_id: ObjectId) -> None:
        self.inserted_id = inserted_id


class FakeWorkerConfigCollection:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}

    async def find_one(self, filters: dict) -> dict | None:
        if "worker_name" in filters:
            return self.payloads.get(filters["worker_name"])
        raw_id = filters.get("_id")
        for payload in self.payloads.values():
            if payload.get("_id") == raw_id:
                return payload
        return None

    async def insert_one(self, payload: dict) -> FakeInsertResult:
        inserted_id = ObjectId()
        stored = dict(payload)
        stored["_id"] = inserted_id
        self.payloads[stored["worker_name"]] = stored
        return FakeInsertResult(inserted_id)

    async def update_one(self, filters: dict, updates: dict):
        payload = await self.find_one(filters)
        if payload is not None:
            payload.update(updates["$set"])
        return None

    def find(self, filters: dict):
        _ = filters
        items = list(self.payloads.values())

        class Cursor:
            def __init__(self, rows):
                self.rows = rows

            def sort(self, field, direction):
                reverse = direction < 0
                self.rows = sorted(self.rows, key=lambda item: item.get(field) or "", reverse=reverse)
                return self

            def limit(self, count):
                self.rows = self.rows[:count]
                return self

            async def to_list(self, length=None):
                _ = length
                return list(self.rows)

        return Cursor(items)


class FakeTaskCollection:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def count_documents(self, filters: dict) -> int:
        status = filters.get("status")
        return sum(1 for item in self.payloads if item.get("status") == status)


class FakeDatabase:
    def __init__(self) -> None:
        self.collections = {
            "worker_configs": FakeWorkerConfigCollection(),
            "greeting_tasks": FakeTaskCollection(),
        }

    def __getitem__(self, name: str):
        return self.collections[name]


def build_service() -> tuple[WorkerService, FakeDatabase]:
    database = FakeDatabase()
    service = WorkerService(database, boss_client=None)  # type: ignore[arg-type]
    return service, database


def test_sync_defaults_on_startup_creates_disabled_workers():
    service, database = build_service()

    items = asyncio.run(service.sync_defaults_on_startup())

    assert {item.worker_name for item in items} == {"search", "detail"}
    assert all(item.enabled is False for item in items)
    assert all(item.next_run_at is None for item in items)
    assert database["worker_configs"].payloads["search"]["enabled"] is False


def test_has_running_task_checks_running_status():
    service, database = build_service()
    database["greeting_tasks"].payloads.append(
        GreetingTask(task_type="search", status=TaskStatus.RUNNING).model_dump()
    )

    result = asyncio.run(service.has_running_task())

    assert result is True


def test_start_worker_sets_enabled_and_next_run():
    service, _ = build_service()
    asyncio.run(service.sync_defaults_on_startup())
    asyncio.run(service.update_worker("search", WorkerConfigUpdate(query={"keywords": ["Python"]})))

    worker = asyncio.run(service.start_worker("search"))

    assert worker.enabled is True
    assert worker.next_run_at is not None


def test_execute_search_worker_delays_two_hours_after_boss_error(monkeypatch):
    service, _ = build_service()
    asyncio.run(service.sync_defaults_on_startup())
    asyncio.run(service.update_worker("search", WorkerConfigUpdate(query={"keywords": ["Python"]})))
    asyncio.run(service.start_worker("search"))

    class FakeJobCollectionService:
        def __init__(self, database, boss_client) -> None:
            _ = database, boss_client

        async def search_jobs(self, query):
            _ = query
            return GreetingTask(
                task_type="search",
                status=TaskStatus.FAILED,
                error_message="need login",
                result_summary={},
            )

    monkeypatch.setattr("job_buddy.services.JobCollectionService", FakeJobCollectionService)

    before = datetime.now(tz=UTC)
    worker = asyncio.run(service.execute_worker("search"))
    after = datetime.now(tz=UTC)

    assert worker.status == "error"
    assert worker.last_error == "need login"
    assert worker.next_run_at is not None
    min_expected = before.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    max_expected = after.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    assert min_expected <= worker.next_run_at.timestamp() <= max_expected


def test_execute_detail_worker_delays_two_hours_after_boss_error(monkeypatch):
    service, _ = build_service()
    asyncio.run(service.sync_defaults_on_startup())
    asyncio.run(service.start_worker("detail"))

    class FakeJobCollectionService:
        def __init__(self, database, boss_client) -> None:
            _ = database, boss_client

        async def run_detail_sync(self, limit):
            _ = limit
            return GreetingTask(
                task_type="detail_sync",
                status=TaskStatus.FAILED,
                error_message="detail blocked",
                result_summary={},
            )

    monkeypatch.setattr("job_buddy.services.JobCollectionService", FakeJobCollectionService)

    before = datetime.now(tz=UTC)
    worker = asyncio.run(service.execute_worker("detail"))
    after = datetime.now(tz=UTC)

    assert worker.status == "error"
    assert worker.last_error == "detail blocked"
    assert worker.next_run_at is not None
    min_expected = before.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    max_expected = after.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    assert min_expected <= worker.next_run_at.timestamp() <= max_expected


def test_execute_worker_delays_two_hours_for_non_success_task(monkeypatch):
    service, _ = build_service()
    asyncio.run(service.sync_defaults_on_startup())
    asyncio.run(service.update_worker("search", WorkerConfigUpdate(query={"keywords": ["Python"], "page": 1}, interval_seconds=45)))
    asyncio.run(service.start_worker("search"))

    class FakeJobCollectionService:
        def __init__(self, database, boss_client) -> None:
            _ = database, boss_client

        async def search_jobs(self, query):
            _ = query
            return GreetingTask(
                task_type="search",
                status=TaskStatus.FAILED,
                error_message="boom",
                result_summary={},
            )

    monkeypatch.setattr("job_buddy.services.JobCollectionService", FakeJobCollectionService)

    before = datetime.now(tz=UTC)
    worker = asyncio.run(service.execute_worker("search"))
    after = datetime.now(tz=UTC)

    assert worker.status == "error"
    assert worker.last_error == "boom"
    assert worker.next_run_at is not None
    min_expected = before.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    max_expected = after.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    assert min_expected <= worker.next_run_at.timestamp() <= max_expected


def test_execute_worker_delays_two_hours_for_partial_success(monkeypatch):
    service, _ = build_service()
    asyncio.run(service.sync_defaults_on_startup())
    asyncio.run(service.start_worker("detail"))

    class FakeJobCollectionService:
        def __init__(self, database, boss_client) -> None:
            _ = database, boss_client

        async def run_detail_sync(self, limit):
            _ = limit
            return GreetingTask(
                task_type="detail_sync",
                status=TaskStatus.PARTIAL_SUCCESS,
                error_message="1 failed",
                result_summary={"total": 2, "succeeded": 1, "failed": 1},
            )

    monkeypatch.setattr("job_buddy.services.JobCollectionService", FakeJobCollectionService)

    before = datetime.now(tz=UTC)
    worker = asyncio.run(service.execute_worker("detail"))
    after = datetime.now(tz=UTC)

    assert worker.status == "idle"
    assert worker.last_error == "1 failed"
    assert worker.next_run_at is not None
    min_expected = before.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    max_expected = after.timestamp() + BOSS_ERROR_RETRY_DELAY_SECONDS
    assert min_expected <= worker.next_run_at.timestamp() <= max_expected
