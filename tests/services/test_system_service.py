import asyncio

from job_buddy.core.boss import BossAuthStatusResult, BossDoctorResult, CdpStatusResult
from job_buddy.modules.system import AuthState, SystemService


class FakeDoctorRunner:
    async def run(self) -> BossDoctorResult:
        return BossDoctorResult(
            ok=True,
            summary="healthy",
            data_dir="/tmp/boss",
            checks=[{"name": "python", "status": "ok", "detail": "Python 3.13", "hint": None}],
            next_actions=["boss status"],
            stderr="",
            exit_code=0,
            error=None,
        )


class FakeCdpController:
    def __init__(self) -> None:
        self.running = True
        self.ensure_called = False
        self.stop_managed_called = False
        self.clear_profile_called = False

    async def get_status(self) -> CdpStatusResult:
        return CdpStatusResult(
            running=self.running,
            port=9222,
            cdp_url="http://127.0.0.1:9222",
            browser="Chrome" if self.running else None,
            websocket_url="ws://127.0.0.1:9222/devtools/browser/demo" if self.running else None,
            pid=1234 if self.running else None,
            message="CDP 在线" if self.running else "CDP 未运行",
        )

    async def start_browser(self) -> CdpStatusResult:
        self.running = True
        return await self.get_status()

    async def stop_browser(self) -> CdpStatusResult:
        self.running = False
        return await self.get_status()

    async def ensure_running(self) -> CdpStatusResult:
        self.ensure_called = True
        self.running = True
        return await self.get_status()

    async def stop_managed_browser(self) -> CdpStatusResult:
        self.stop_managed_called = True
        self.running = False
        return await self.get_status()

    def clear_profile(self) -> None:
        self.clear_profile_called = True

    @property
    def cdp_url(self) -> str:
        return "http://127.0.0.1:9222"


class FakeAuthGateway:
    def __init__(self) -> None:
        self.local_status = BossAuthStatusResult(logged_in=False, message="未登录")
        self.login_called = False
        self.logout_called = False

    async def get_status(self) -> BossAuthStatusResult:
        return self.local_status

    async def login(self, timeout: int = 120) -> BossAuthStatusResult:
        _ = timeout
        self.login_called = True
        self.local_status = BossAuthStatusResult(
            logged_in=True,
            user_name="Alice",
            login_method="cdp",
            message="登录成功（CDP 扫码）",
        )
        return self.local_status

    async def logout(self) -> None:
        self.logout_called = True
        self.local_status = BossAuthStatusResult(logged_in=False, message="已退出登录")


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
    service = SystemService(FakeDoctorRunner(), FakeCdpController(), FakeAuthGateway(), FakeAuthStateRepository())

    result = asyncio.run(service.run_doctor())

    assert result.ok is True
    assert result.summary == "healthy"
    assert result.checks[0].name == "python"


def test_get_cdp_status_returns_structured_response():
    service = SystemService(FakeDoctorRunner(), FakeCdpController(), FakeAuthGateway(), FakeAuthStateRepository())

    result = asyncio.run(service.get_cdp_status())

    assert result.running is True
    assert result.port == 9222


def test_login_persists_auth_state():
    cdp_controller = FakeCdpController()
    auth_gateway = FakeAuthGateway()
    auth_states = FakeAuthStateRepository()
    service = SystemService(FakeDoctorRunner(), cdp_controller, auth_gateway, auth_states)

    result = asyncio.run(service.login())

    assert cdp_controller.ensure_called is True
    assert auth_gateway.login_called is True
    assert result.logged_in is True
    assert result.user_name == "Alice"
    assert auth_states.state is not None
    assert auth_states.state.login_method == "cdp"


def test_logout_clears_auth_state_and_profile():
    cdp_controller = FakeCdpController()
    auth_gateway = FakeAuthGateway()
    auth_states = FakeAuthStateRepository()
    auth_states.state = AuthState(
        cdp_url="http://127.0.0.1:9222",
        logged_in=True,
        user_name="Alice",
        login_method="cdp",
    )
    service = SystemService(FakeDoctorRunner(), cdp_controller, auth_gateway, auth_states)

    result = asyncio.run(service.logout())

    assert auth_gateway.logout_called is True
    assert cdp_controller.stop_managed_called is True
    assert cdp_controller.clear_profile_called is True
    assert result.logged_in is False
    assert auth_states.state is not None
    assert auth_states.state.logged_in is False
