import asyncio
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
import pytest

from job_buddy.models import GreetingTask, TaskStatus, WorkerConfig
from job_buddy.schemas import WorkerConfigUpdate
from job_buddy.services import WorkerFailException, WorkerScheduler, WorkerService


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


def build_scheduler() -> WorkerScheduler:
    return WorkerScheduler(database=FakeDatabase(), boss_client=None)  # type: ignore[arg-type]


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

    with pytest.raises(WorkerFailException):
        asyncio.run(service.execute_worker("search"))

    worker = asyncio.run(service.get_worker("search"))
    assert worker.status == "error"
    assert worker.last_error == "need login"
    assert worker.next_run_at is not None


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

    with pytest.raises(WorkerFailException):
        asyncio.run(service.execute_worker("detail"))

    worker = asyncio.run(service.get_worker("detail"))
    assert worker.status == "error"
    assert worker.last_error == "detail blocked"
    assert worker.next_run_at is not None


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
    with pytest.raises(WorkerFailException):
        asyncio.run(service.execute_worker("search"))
    after = datetime.now(tz=UTC)

    worker = asyncio.run(service.get_worker("search"))
    assert worker.status == "error"
    assert worker.last_error == "boom"
    assert worker.next_run_at is not None
    min_expected = before.timestamp() + 45
    max_expected = after.timestamp() + 45
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
    with pytest.raises(WorkerFailException):
        asyncio.run(service.execute_worker("detail"))
    after = datetime.now(tz=UTC)

    worker = asyncio.run(service.get_worker("detail"))
    assert worker.status == "error"
    assert worker.last_error == "1 failed"
    assert worker.next_run_at is not None
    min_expected = before.timestamp() + 30
    max_expected = after.timestamp() + 30
    assert min_expected <= worker.next_run_at.timestamp() <= max_expected


def test_execute_worker_runtime_error_updates_worker_before_raising(monkeypatch):
    service, _ = build_service()
    asyncio.run(service.sync_defaults_on_startup())
    asyncio.run(service.update_worker("search", WorkerConfigUpdate(query={"keywords": ["Python"]}, interval_seconds=60)))
    asyncio.run(service.start_worker("search"))

    class FakeJobCollectionService:
        def __init__(self, database, boss_client) -> None:
            _ = database, boss_client

        async def search_jobs(self, query):
            _ = query
            raise RuntimeError("network boom")

    monkeypatch.setattr("job_buddy.services.JobCollectionService", FakeJobCollectionService)

    before = datetime.now(tz=UTC)
    with pytest.raises(WorkerFailException):
        asyncio.run(service.execute_worker("search"))
    after = datetime.now(tz=UTC)

    worker = asyncio.run(service.get_worker("search"))
    assert worker.status == "error"
    assert worker.last_error == "network boom"
    assert worker.next_run_at is not None
    min_expected = before.timestamp() + 60
    max_expected = after.timestamp() + 60
    assert min_expected <= worker.next_run_at.timestamp() <= max_expected


def test_scheduler_exponential_backoff_starts_from_two_hours(monkeypatch):
    scheduler = build_scheduler()
    sleep_calls: list[float] = []
    run_once_calls = {"count": 0}

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        if len(sleep_calls) >= 2:
            scheduler._stopped.set()

    async def fake_run_once() -> None:
        run_once_calls["count"] += 1
        raise WorkerFailException()

    monkeypatch.setattr("job_buddy.services.random.random", lambda: 0.0)
    monkeypatch.setattr("job_buddy.services.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "run_once", fake_run_once)

    asyncio.run(scheduler._run())

    assert run_once_calls["count"] == 1
    assert sleep_calls == [3.0, 2 * 60 * 60]


def test_scheduler_exponential_backoff_doubles_on_consecutive_failures_and_resets_after_success(monkeypatch):
    scheduler = build_scheduler()
    sleep_calls: list[float] = []
    run_outcomes = iter(["fail", "fail", "success", "fail"])
    run_once_calls = {"count": 0}

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def fake_run_once() -> None:
        run_once_calls["count"] += 1
        outcome = next(run_outcomes)
        if run_once_calls["count"] == 4:
            scheduler._stopped.set()
        if outcome == "fail":
            raise WorkerFailException()

    async def fake_wait_for(awaitable, timeout):
        _ = timeout
        awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr("job_buddy.services.random.random", lambda: 0.0)
    monkeypatch.setattr("job_buddy.services.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("job_buddy.services.asyncio.wait_for", fake_wait_for)
    monkeypatch.setattr(scheduler, "run_once", fake_run_once)

    asyncio.run(scheduler._run())

    assert run_once_calls["count"] == 4
    assert sleep_calls == [
        3.0,
        2 * 60 * 60,
        3.0,
        4 * 60 * 60,
        3.0,
        3.0,
        2 * 60 * 60,
    ]
