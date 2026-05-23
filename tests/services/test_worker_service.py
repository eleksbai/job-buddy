import asyncio
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
import pytest

from job_buddy.models import GreetingTask, TaskStatus
from job_buddy.schemas import WorkerConfigUpdate
from job_buddy.services import DetailWorker, SearchWorker, WorkerFailException


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


class FakeBossClient:
    def __init__(self) -> None:
        self.goto_job_calls = 0

    async def goto_job(self) -> None:
        self.goto_job_calls += 1


def build_search_worker() -> tuple[SearchWorker, FakeDatabase]:
    database = FakeDatabase()
    worker = SearchWorker(database, boss_client=FakeBossClient())  # type: ignore[arg-type]
    return worker, database


def build_detail_worker() -> tuple[DetailWorker, FakeDatabase]:
    database = FakeDatabase()
    worker = DetailWorker(database, boss_client=FakeBossClient())  # type: ignore[arg-type]
    return worker, database


def test_sync_default_on_startup_creates_disabled_search_worker():
    worker, database = build_search_worker()

    item = asyncio.run(worker.sync_default_on_startup())

    assert item.worker_name == "search"
    assert item.enabled is False
    assert item.next_run_at is None
    assert database["worker_configs"].payloads["search"]["enabled"] is False


def test_sync_default_on_startup_creates_disabled_detail_worker():
    worker, database = build_detail_worker()

    item = asyncio.run(worker.sync_default_on_startup())

    assert item.worker_name == "detail"
    assert item.enabled is False
    assert item.next_run_at is None
    assert database["worker_configs"].payloads["detail"]["enabled"] is False


def test_has_running_task_checks_running_status():
    worker, database = build_search_worker()
    database["greeting_tasks"].payloads.append(
        GreetingTask(task_type="search", status=TaskStatus.RUNNING).model_dump()
    )

    result = asyncio.run(worker.has_running_task())

    assert result is True


def test_start_worker_sets_enabled_and_next_run():
    worker, _ = build_search_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(worker.update_worker(WorkerConfigUpdate(query={"keywords": ["Python"]})))

    item = asyncio.run(worker.start_worker())

    assert item.enabled is True
    assert item.next_run_at is not None


def test_release_worker_clears_error_and_schedules_immediately():
    worker, _ = build_search_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(worker.update_worker(WorkerConfigUpdate(query={"keywords": ["Python"]})))
    asyncio.run(worker.start_worker())
    asyncio.run(
        worker._update_worker_model(
            {
                "status": "error",
                "last_error": "need login",
                "next_run_at": datetime.now(tz=UTC),
            }
        )
    )

    released = asyncio.run(worker.release_worker())

    assert released.enabled is True
    assert released.status == "idle"
    assert released.last_error is None
    assert released.next_run_at is not None


def test_execute_search_worker_delays_after_failed_task(monkeypatch):
    worker, _ = build_search_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(worker.update_worker(WorkerConfigUpdate(query={"keywords": ["Python"]})))
    asyncio.run(worker.start_worker())

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
        asyncio.run(worker.execute())

    updated = asyncio.run(worker.get_worker())
    assert updated.status == "error"
    assert updated.last_error == "need login"
    assert updated.next_run_at is not None


def test_execute_detail_worker_delays_after_failed_task(monkeypatch):
    worker, _ = build_detail_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(worker.start_worker())

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
        asyncio.run(worker.execute())

    updated = asyncio.run(worker.get_worker())
    assert updated.status == "error"
    assert updated.last_error == "detail blocked"
    assert updated.next_run_at is not None


def test_execute_search_worker_uses_interval_for_next_run(monkeypatch):
    worker, _ = build_search_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(worker.update_worker(WorkerConfigUpdate(query={"keywords": ["Python"]}, interval_seconds=45)))
    asyncio.run(worker.start_worker())

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
        asyncio.run(worker.execute())
    after = datetime.now(tz=UTC)

    updated = asyncio.run(worker.get_worker())
    assert updated.status == "error"
    assert updated.last_error == "boom"
    assert updated.next_run_at is not None
    min_expected = before.timestamp() + 45
    max_expected = after.timestamp() + 45
    assert min_expected <= updated.next_run_at.timestamp() <= max_expected


def test_execute_detail_worker_marks_partial_success_as_error(monkeypatch):
    worker, _ = build_detail_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(worker.start_worker())

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
        asyncio.run(worker.execute())
    after = datetime.now(tz=UTC)

    updated = asyncio.run(worker.get_worker())
    assert updated.status == "error"
    assert updated.last_error == "1 failed"
    assert updated.next_run_at is not None
    min_expected = before.timestamp() + 30
    max_expected = after.timestamp() + 30
    assert min_expected <= updated.next_run_at.timestamp() <= max_expected


def test_execute_worker_runtime_error_updates_worker_before_raising(monkeypatch):
    worker, _ = build_search_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(worker.update_worker(WorkerConfigUpdate(query={"keywords": ["Python"]}, interval_seconds=60)))
    asyncio.run(worker.start_worker())

    class FakeJobCollectionService:
        def __init__(self, database, boss_client) -> None:
            _ = database, boss_client

        async def search_jobs(self, query):
            _ = query
            raise RuntimeError("network boom")

    monkeypatch.setattr("job_buddy.services.JobCollectionService", FakeJobCollectionService)

    before = datetime.now(tz=UTC)
    with pytest.raises(WorkerFailException):
        asyncio.run(worker.execute())
    after = datetime.now(tz=UTC)

    updated = asyncio.run(worker.get_worker())
    assert updated.status == "error"
    assert updated.last_error == "network boom"
    assert updated.next_run_at is not None
    min_expected = before.timestamp() + 60
    max_expected = after.timestamp() + 60
    assert min_expected <= updated.next_run_at.timestamp() <= max_expected


def test_search_worker_success_advances_page_and_wraps(monkeypatch):
    worker, _ = build_search_worker()
    asyncio.run(worker.sync_default_on_startup())
    asyncio.run(
        worker.update_worker(
            WorkerConfigUpdate(
                query={"keywords": ["Python"]},
                page=2,
                page_max=2,
            )
        )
    )
    asyncio.run(worker.start_worker())

    class FakeJobCollectionService:
        def __init__(self, database, boss_client) -> None:
            _ = database, boss_client

        async def search_jobs(self, query):
            assert query["page"] == 2
            return GreetingTask(
                task_type="search",
                status=TaskStatus.SUCCEEDED,
                result_summary={"total": 1},
            )

    monkeypatch.setattr("job_buddy.services.JobCollectionService", FakeJobCollectionService)

    updated = asyncio.run(worker.execute())

    assert updated.status == "idle"
    assert updated.page == 1
    assert updated.last_result_summary == {"total": 1}
    assert worker.boss_client.goto_job_calls == 1


def test_worker_exponential_backoff_starts_from_two_hours(monkeypatch):
    worker, _ = build_search_worker()
    sleep_calls: list[float] = []
    run_once_calls = {"count": 0}

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        if len(sleep_calls) >= 2:
            worker._stopped.set()

    async def fake_run_once() -> None:
        run_once_calls["count"] += 1
        raise WorkerFailException()

    monkeypatch.setattr("job_buddy.services.random.random", lambda: 0.0)
    monkeypatch.setattr("job_buddy.services.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(worker, "run_once", fake_run_once)

    asyncio.run(worker._run())

    assert run_once_calls["count"] == 1
    assert sleep_calls == [3.0, 2 * 60 * 60]


def test_worker_exponential_backoff_resets_after_success(monkeypatch):
    worker, _ = build_search_worker()
    sleep_calls: list[float] = []
    run_outcomes = iter(["fail", "fail", "success", "fail"])
    run_once_calls = {"count": 0}

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def fake_run_once() -> None:
        run_once_calls["count"] += 1
        outcome = next(run_outcomes)
        if run_once_calls["count"] == 4:
            worker._stopped.set()
        if outcome == "fail":
            raise WorkerFailException()

    async def fake_wait_for(awaitable, timeout):
        _ = timeout
        awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr("job_buddy.services.random.random", lambda: 0.0)
    monkeypatch.setattr("job_buddy.services.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("job_buddy.services.asyncio.wait_for", fake_wait_for)
    monkeypatch.setattr(worker, "run_once", fake_run_once)

    asyncio.run(worker._run())

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
