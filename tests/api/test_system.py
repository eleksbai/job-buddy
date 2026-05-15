from fastapi import FastAPI
from fastapi.testclient import TestClient

from job_buddy.deps import get_system_service
from job_buddy.modules.system import DoctorCheckResponse, DoctorResponse
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


def test_run_boss_doctor():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    with TestClient(app) as client:
        response = client.get("/api/system/doctor")

    assert response.status_code == 200
    assert response.json()["summary"] == "healthy"
