from fastapi.testclient import TestClient

from job_buddy.main import create_app


class FakeBossClient:
    async def healthcheck(self) -> dict:
        return {"status": "ok"}


def test_health_endpoint():
    app = create_app()
    app.state.boss_client = FakeBossClient()
    app.state.db = None

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

