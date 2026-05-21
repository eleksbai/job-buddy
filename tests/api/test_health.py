import pytest
from fastapi import FastAPI

from job_buddy.boss.schemas import HealthcheckOut
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeRuntime:
    async def healthcheck(self) -> HealthcheckOut:
        return HealthcheckOut(status="ok", provider="bossclient", logged_in=True, message="已登录", last_error="")


@pytest.mark.asyncio
async def test_health_endpoint():
    app = FastAPI()
    app.include_router(build_api_router())
    app.state.boss_client = FakeRuntime()
    app.state.db = None

    async with api_client(app) as client:
        response = await client.get("/web/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
