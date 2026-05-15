from fastapi import FastAPI
from fastapi.testclient import TestClient

from job_buddy.deps import get_system_service
from job_buddy.modules.system import (
    AuthStatusResponse,
    BrowserControlResponse,
    CdpStatusResponse,
    DoctorCheckResponse,
    DoctorResponse,
)
from job_buddy.routers import build_api_router


class FakeSystemService:
    async def run_doctor(self) -> DoctorResponse:
        return DoctorResponse(
            ok=True,
            summary="healthy",
            data_dir="/tmp/boss",
            checks=[DoctorCheckResponse(name="python", status="ok", detail="Python 3.13")],
            next_actions=["boss status"],
            stderr=None,
            exit_code=0,
            error=None,
        )

    async def get_cdp_status(self) -> CdpStatusResponse:
        return CdpStatusResponse(
            running=True,
            port=9222,
            cdp_url="http://127.0.0.1:9222",
            browser="Chrome",
            websocket_url="ws://127.0.0.1:9222/devtools/browser/demo",
            pid=1234,
            message="CDP 在线",
        )

    async def get_auth_status(self) -> AuthStatusResponse:
        return AuthStatusResponse(
            logged_in=True,
            user_name="Alice",
            login_method="cdp",
            cdp_running=True,
            cdp_url="http://127.0.0.1:9222",
            browser="Chrome",
            last_login_at=None,
            last_logout_at=None,
            message="已登录",
            last_error=None,
        )

    async def login(self, timeout: int = 120) -> AuthStatusResponse:
        _ = timeout
        return await self.get_auth_status()

    async def logout(self) -> AuthStatusResponse:
        return AuthStatusResponse(
            logged_in=False,
            user_name=None,
            login_method=None,
            cdp_running=False,
            cdp_url="http://127.0.0.1:9222",
            browser=None,
            last_login_at=None,
            last_logout_at=None,
            message="已退出登录",
            last_error=None,
        )

    async def start_cdp_browser(self) -> BrowserControlResponse:
        return BrowserControlResponse(
            running=True,
            port=9222,
            cdp_url="http://127.0.0.1:9222",
            browser="Chrome",
            websocket_url="ws://127.0.0.1:9222/devtools/browser/demo",
            pid=1234,
            message="浏览器已启动",
        )

    async def stop_cdp_browser(self) -> BrowserControlResponse:
        return BrowserControlResponse(
            running=False,
            port=9222,
            cdp_url="http://127.0.0.1:9222",
            browser=None,
            websocket_url=None,
            pid=None,
            message="浏览器已关闭",
        )


def test_run_boss_doctor():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.get("/api/system/doctor")

    assert response.status_code == 200
    assert response.json()["summary"] == "healthy"


def test_get_cdp_status():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.get("/api/system/cdp")

    assert response.status_code == 200
    assert response.json()["running"] is True


def test_get_auth_status():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.get("/api/system/auth")

    assert response.status_code == 200
    assert response.json()["logged_in"] is True
    assert response.json()["user_name"] == "Alice"


def test_logout_auth():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.post("/api/system/auth/logout")

    assert response.status_code == 200
    assert response.json()["logged_in"] is False


def test_login_auth():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.post("/api/system/auth/login")

    assert response.status_code == 200
    assert response.json()["login_method"] == "cdp"


def test_stop_cdp_browser():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.post("/api/system/cdp/stop")

    assert response.status_code == 200
    assert response.json()["running"] is False
