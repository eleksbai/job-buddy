import pytest
from fastapi import FastAPI

from job_buddy.deps import get_target_service
from job_buddy.models import TargetProfile
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeTargetService:
    async def create_target(self, payload):
        return TargetProfile(_id="6825fb1a7d4ce9adcc2d1a11", **payload.model_dump())


@pytest.mark.asyncio
async def test_create_target():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_target_service] = lambda: FakeTargetService()

    async with api_client(app) as client:
        response = await client.post("/web/targets", json={"name": "Data", "keywords": ["Python", "ETL"]})

    assert response.status_code == 201
    assert response.json()["name"] == "Data"
