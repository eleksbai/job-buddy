import pytest
from fastapi import FastAPI

from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeRuntime:
    async def healthcheck(self) -> dict:
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_health_endpoint():
    app = FastAPI()
    app.include_router(build_api_router())
    app.state.runtime = FakeRuntime()
    app.state.db = None

    async with api_client(app) as client:
        response = await client.get("/web/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
