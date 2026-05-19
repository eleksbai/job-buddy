import asyncio

from job_buddy.core.boss import BossOperationError
from job_buddy.modules.conversations import ConversationService


class FakeCollection:
    def __init__(self, record: dict | None) -> None:
        self.record = record
        self.last_filter = None

    async def find_one(self, filters: dict):
        self.last_filter = filters
        return self.record


class FakeConversationRepository:
    def __init__(self, record: dict | None) -> None:
        self.collection = FakeCollection(record)


class FakeMessageClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str]] = []

    async def send_message(self, conversation: dict, content: str) -> dict:
        self.calls.append((conversation, content))
        return {"status": "sent", "provider": "patchright"}


def test_send_message_uses_encrypt_job_id_only():
    record = {
        "encrypt_job_id": "encrypt-1",
        "gid": "gid-1",
        "security_id": "sec-1",
        "encrypt_boss_id": "boss-1",
        "raw_payload": {"uid": "uid-1"},
    }
    service = ConversationService.__new__(ConversationService)
    service.conversations = FakeConversationRepository(record)
    service.boss_client = FakeMessageClient()

    result = asyncio.run(service.send_message("encrypt-1", "  你好  "))

    assert service.conversations.collection.last_filter == {"encrypt_job_id": "encrypt-1"}
    assert service.boss_client.calls == [(record, "你好")]
    assert result.status == "sent"
    assert result.gid == "gid-1"


def test_send_message_missing_conversation_returns_404_error():
    service = ConversationService.__new__(ConversationService)
    service.conversations = FakeConversationRepository(None)
    service.boss_client = FakeMessageClient()

    try:
        asyncio.run(service.send_message("encrypt-1", "你好"))
    except BossOperationError as exc:
        assert exc.status_code == 404
        assert "未找到 job_id=encrypt-1 的会话记录" in exc.message
    else:
        raise AssertionError("expected BossOperationError")
