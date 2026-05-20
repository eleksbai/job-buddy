import pytest
from fastapi import FastAPI

from job_buddy.deps import get_friend_service
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeFriendService:
    def __init__(self) -> None:
        self.sent: tuple[str, str] | None = None

    async def send_friend_message(self, friend_id: str, content: str):
        self.sent = (friend_id, content)
        return {
            "gid": "gid-1",
            "friend_id": friend_id,
            "content": content,
            "status": "sent",
            "raw_payload": {"provider": "patchright"},
        }


@pytest.mark.asyncio
async def test_send_friend_message_routes_to_friend_service():
    app = FastAPI()
    service = FakeFriendService()
    app.include_router(build_api_router())
    app.dependency_overrides[get_friend_service] = lambda: service

    async with api_client(app) as client:
        response = await client.post("/boss/friends/boss-1/messages/send", json={"content": "你好"})

    assert response.status_code == 200
    assert service.sent == ("boss-1", "你好")
    assert response.json()["status"] == "sent"
