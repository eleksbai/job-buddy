import pytest
from fastapi import FastAPI

from job_buddy.deps import get_conversation_service
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeConversationService:
    def __init__(self) -> None:
        self.sent: tuple[str, str] | None = None

    async def send_message(self, job_id: str, content: str):
        self.sent = (job_id, content)
        return {
            "gid": "gid-1",
            "job_id": job_id,
            "content": content,
            "status": "sent",
            "raw_payload": {"provider": "patchright"},
        }


@pytest.mark.asyncio
async def test_send_chat_message_routes_to_conversation_service():
    app = FastAPI()
    service = FakeConversationService()
    app.include_router(build_api_router())
    app.dependency_overrides[get_conversation_service] = lambda: service

    async with api_client(app) as client:
        response = await client.post("/api/conversations/encrypt-1/messages/send", json={"content": "你好"})

    assert response.status_code == 200
    assert service.sent == ("encrypt-1", "你好")
    assert response.json()["status"] == "sent"
