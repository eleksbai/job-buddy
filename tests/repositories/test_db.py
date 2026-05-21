import pytest

from job_buddy.config import Settings
from job_buddy.db import MongoManager


class FakeMotorClient:
    def __init__(self, uri: str, **kwargs) -> None:
        self.uri = uri
        self.kwargs = kwargs
        self.closed = False

    def __getitem__(self, name: str):
        return {"database": name}

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_mongo_manager_connect_enables_tz_aware(monkeypatch):
    captured: dict[str, object] = {}

    def build_client(uri: str, **kwargs):
        client = FakeMotorClient(uri, **kwargs)
        captured["client"] = client
        return client

    monkeypatch.setattr("job_buddy.db.AsyncIOMotorClient", build_client)
    manager = MongoManager(Settings(MONGODB_URI="mongodb://example:27017", MONGODB_DB="job_buddy_test"))

    database = await manager.connect()

    client = captured["client"]
    assert isinstance(client, FakeMotorClient)
    assert client.uri == "mongodb://example:27017"
    assert client.kwargs["tz_aware"] is True
    assert database == {"database": "job_buddy_test"}
