import asyncio
from pathlib import Path

from job_buddy.core.boss import BossDoctorResult, BossOperationError
from job_buddy.core.config import Settings
from job_buddy.core.engines.models import LoginResult
from job_buddy.modules.system import AuthState, SystemService


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
        self.local_status = LoginResult(logged_in=False, message="未登录")
        self.login_called = False
        self.logout_called = False
        self.login_error: Exception | None = None

    async def get_auth_status(self) -> LoginResult:
        return self.local_status

    async def login(self, request) -> LoginResult:
        _ = request
        if self.login_error is not None:
            raise self.login_error
        self.login_called = True
        self.local_status = LoginResult(
            logged_in=True,
            user_name="Alice",
            login_method="patchright",
            message="登录成功（扫码登录）",
            browser="Patchright Chromium",
        )
        return self.local_status

    async def logout(self) -> LoginResult:
        self.logout_called = True
        self.local_status = LoginResult(logged_in=False, message="已退出登录")
        return self.local_status


class FakeAuthStateRepository:
    def __init__(self) -> None:
        self.state: AuthState | None = None

    async def get_current(self, provider: str = "zhipin") -> AuthState | None:
        _ = provider
        return self.state

    async def upsert_current(self, state: AuthState) -> AuthState:
        self.state = state
        return state


def test_run_doctor_returns_structured_response():
    service = SystemService(FakeDoctorRunner(), Settings(), FakeRuntime(), FakeAuthStateRepository())

    result = asyncio.run(service.run_doctor())

    assert result.ok is True
    assert result.summary == "healthy"
    assert result.checks[0].name == "python"


def test_login_persists_auth_state():
    runtime = FakeRuntime()
    auth_states = FakeAuthStateRepository()
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, auth_states)

    result = asyncio.run(service.login())

    assert runtime.login_called is True
    assert result.logged_in is True
    assert result.user_name == "Alice"
    assert result.browser == "Patchright Chromium"
    assert auth_states.state is not None
    assert auth_states.state.login_method == "patchright"


def test_logout_clears_auth_state():
    runtime = FakeRuntime()
    auth_states = FakeAuthStateRepository()
    auth_states.state = AuthState(
        logged_in=True,
        user_name="Alice",
        login_method="patchright",
        browser="Patchright Chromium",
    )
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, auth_states)

    result = asyncio.run(service.logout())

    assert runtime.logout_called is True
    assert result.logged_in is False
    assert auth_states.state is not None
    assert auth_states.state.logged_in is False


def test_get_auth_status_hides_historical_identity_when_logged_out():
    runtime = FakeRuntime()
    auth_states = FakeAuthStateRepository()
    auth_states.state = AuthState(
        logged_in=True,
        user_name="Alice",
        login_method="patchright",
        browser="Patchright Chromium",
    )
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, auth_states)

    result = asyncio.run(service.get_auth_status())

    assert result.logged_in is False
    assert result.user_name is None
    assert result.login_method is None


def test_login_maps_auth_errors():
    runtime = FakeRuntime()
    runtime.login_error = AuthRequired()
    service = SystemService(FakeDoctorRunner(), Settings(), runtime, FakeAuthStateRepository())

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
        FakeAuthStateRepository(),
    )

    result = asyncio.run(service.get_logs(limit=1))

    assert result.source == "job-buddy.log"
    assert result.truncated is True
    assert len(result.lines) == 1
    assert result.lines[0].text.endswith("ERROR second")
    assert result.lines[0].level_hint == "error"
