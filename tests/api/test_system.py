from fastapi import FastAPI
from fastapi.testclient import TestClient

from job_buddy.deps import get_system_service
from job_buddy.modules.system import BrowserControlResponse, CdpStatusResponse, DoctorCheckResponse, DoctorResponse
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


def test_stop_cdp_browser():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.post("/api/system/cdp/stop")

    assert response.status_code == 200
    assert response.json()["running"] is False
