from fastapi import FastAPI
from fastapi.testclient import TestClient

from job_buddy.deps import get_target_service
from job_buddy.modules.targets import TargetProfile
from job_buddy.routers import build_api_router


class FakeTargetService:
    async def list_targets(self):
        return [
            TargetProfile(
                _id="6825fb1a7d4ce9adcc2d1a11",
                name="Python",
                keywords=["Python"],
                city="Shanghai",
            )
        ]

    async def create_target(self, payload):
        return TargetProfile(_id="6825fb1a7d4ce9adcc2d1a11", **payload.model_dump())


def test_list_targets():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_target_service] = lambda: FakeTargetService()

    with TestClient(app) as client:
        response = client.get("/api/targets")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Python"


def test_create_target():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_target_service] = lambda: FakeTargetService()

    with TestClient(app) as client:
        response = client.post("/api/targets", json={"name": "Data", "keywords": ["Python", "ETL"]})

    assert response.status_code == 201
    assert response.json()["name"] == "Data"
