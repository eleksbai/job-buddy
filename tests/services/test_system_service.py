import asyncio
from pathlib import Path

from bson import ObjectId

from job_buddy.boss.boss import BossDoctorResult
from job_buddy.boss.exceptions import BossOperationError
from job_buddy.boss.schemas import LoginOut
from job_buddy.config import Settings
from job_buddy.models import AuthState
from job_buddy.services import SystemService


class AuthRequired(Exception):
    pass


class FakeDoctorRunner:
    async def run(self) -> BossDoctorResult:
        return BossDoctorResult(
            ok=True,
            summary="healthy",
            data_dir="/tmp/boss",
            checks=[{"name": "python", "status": "ok", "detail": "Python 3.13", "hint": None}],
            next_actions=["确认已登录 BOSS 直聘后再执行搜索"],
            stderr="",
            exit_code=0,
            error=None,
        )


class FakeRuntime:
    def __init__(self) -> None:
        self.local_status = LoginOut(logged_in=False, message="未登录")
        self.login_called = False
        self.logout_called = False
        self.login_error: Exception | None = None

    async def get_auth_status(self) -> LoginOut:
        return self.local_status

    async def login(self, request) -> LoginOut:
        _ = request
        if self.login_error is not None:
            raise self.login_error
        self.login_called = True
        self.local_status = LoginOut(
            logged_in=True,
            user_name="Alice",
            city="上海",
            ip="127.0.0.1",
            uid="uid-1",
            message="登录成功（扫码登录）",
        )
        return self.local_status

    async def logout(self) -> LoginOut:
        self.logout_called = True
        self.local_status = LoginOut(logged_in=False, message="已退出登录")
        return self.local_status


class FakeAuthStateCollection:
    def __init__(self) -> None:
        self.payload: dict | None = None

    @property
    def state(self) -> AuthState | None:
        if self.payload is None:
            return None
        return AuthState.from_mongo(self.payload)

    async def find_one(self, filters: dict) -> dict | None:
        _ = filters
        return self.payload

    async def insert_one(self, payload: dict):
        payload = dict(payload)
        payload["_id"] = ObjectId()
        self.payload = payload
        return type("InsertResult", (), {"inserted_id": payload["_id"]})()

    async def update_one(self, filters: dict, updates: dict):
        _ = filters
        if self.payload is not None:
            self.payload.update(updates["$set"])
        return None


class FakeDeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count
        self.delete_calls = 0

    async def delete_many(self, filters: dict) -> FakeDeleteResult:
        assert filters == {}
        self.delete_calls += 1
        return FakeDeleteResult(self.deleted_count)


class FakeDatabase:
    def __init__(self) -> None:
        self.auth_states = FakeAuthStateCollection()
        self.collections = {
            name: FakeCollection(index + 1)
            for index, name in enumerate(SystemService.data_collection_names)
        }
        self.collections["boss_auth_state"] = self.auth_states

    def __getitem__(self, collection_name: str) -> FakeCollection:
        return self.collections[collection_name]


def test_run_doctor_returns_structured_response():
    service = SystemService(FakeDoctorRunner(), Settings(), FakeRuntime(), FakeDatabase())

    result = asyncio.run(service.run_doctor())

    assert result.ok is True
    assert result.summary == "healthy"
    assert result.checks[0].name == "python"


def test_login_persists_auth_state():
    runtime = FakeRuntime()
    database = FakeDatabase()
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, database)

    result = asyncio.run(service.login())

    assert runtime.login_called is True
    assert result.logged_in is True
    assert result.user_name == "Alice"
    assert result.city == "上海"
    assert result.ip == "127.0.0.1"
    assert result.uid == "uid-1"
    assert database.auth_states.state is not None
    assert database.auth_states.state.uid == "uid-1"


def test_logout_clears_auth_state():
    runtime = FakeRuntime()
    database = FakeDatabase()
    database.auth_states.payload = AuthState(
        logged_in=True,
        user_name="Alice",
        city="上海",
        ip="127.0.0.1",
        uid="uid-1",
    ).to_mongo() | {"_id": ObjectId()}
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, database)

    result = asyncio.run(service.logout())

    assert runtime.logout_called is True
    assert result.logged_in is False
    assert database.auth_states.state is not None
    assert database.auth_states.state.logged_in is False


def test_get_auth_status_hides_historical_identity_when_logged_out():
    runtime = FakeRuntime()
    database = FakeDatabase()
    database.auth_states.payload = AuthState(
        logged_in=True,
        user_name="Alice",
        city="上海",
        ip="127.0.0.1",
        uid="uid-1",
    ).to_mongo() | {"_id": ObjectId()}
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, database)

    result = asyncio.run(service.get_auth_status())

    assert result.logged_in is False
    assert result.user_name is None
    assert result.uid == "uid-1"


def test_login_maps_auth_errors():
    runtime = FakeRuntime()
    runtime.login_error = AuthRequired()
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, FakeDatabase())

    try:
        asyncio.run(service.login())
    except BossOperationError as exc:
        assert exc.code == "AUTH_REQUIRED"
        assert exc.message == "未登录，请先点击页面右上角登录"
    else:
        raise AssertionError("expected BossOperationError")


def test_get_logs_reads_latest_lines(tmp_path: Path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "job-buddy.log"
    log_file.write_text("2026-05-16 INFO first\n2026-05-16 ERROR second\n", encoding="utf-8")

    service = SystemService(
        FakeDoctorRunner(),
        Settings(APP_LOG_DIR=str(log_dir)),
        FakeRuntime(),
        FakeDatabase(),
    )

    result = asyncio.run(service.get_logs(limit=1))

    assert result.source == "job-buddy.log"
    assert result.truncated is True
    assert len(result.lines) == 1
    assert result.lines[0].text.endswith("ERROR second")
    assert result.lines[0].level_hint == "error"


def test_clear_data_deletes_business_collections():
    database = FakeDatabase()
    service = SystemService(FakeDoctorRunner(), Settings(), FakeRuntime(), database)

    result = asyncio.run(service.clear_data())

    assert set(result.deleted_counts) == set(SystemService.data_collection_names)
    assert result.total_deleted == sum(range(1, len(SystemService.data_collection_names) + 1))
    assert all(database.collections[name].delete_calls == 1 for name in SystemService.data_collection_names)
