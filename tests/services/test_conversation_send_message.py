import asyncio

from job_buddy.boss import BossOperationError
from job_buddy.boss.schemas import SendMessageIn
from job_buddy.services import FriendService


class FakeCollection:
    def __init__(self, record: dict | None) -> None:
        self.record = record
        self.last_filter = None

    async def find_one(self, filters: dict):
        self.last_filter = filters
        return self.record


class FakeFriendRepository:
    def __init__(self, record: dict | None) -> None:
        self.record = FakeCollection(record)
        self.updated: list[tuple[dict, dict]] = []

    async def find_one(self, filters: dict):
        return await self.record.find_one(filters)

    async def update_one(self, filters: dict, updates: dict):
        self.updated.append((filters, updates))
        return None


class FakeMessageClient:
    def __init__(self) -> None:
        self.calls: list[SendMessageIn] = []
        self.friends_payload: list[dict] = []

    async def send_message(self, request: SendMessageIn) -> dict:
        self.calls.append(request)
        return {"status": "sent", "provider": "patchright"}

    async def list_friends(self, page: int = 1) -> list[dict]:
        _ = page
        return list(self.friends_payload)


def test_send_friend_message_uses_encrypt_boss_id():
    record = {
        "_id": "friend-1",
        "encrypt_job_id": "encrypt-1",
        "gid": "gid-1",
        "boss_uid": "gid-1",
        "self_id": "uid-2",
        "security_id": "sec-1",
        "encrypt_boss_id": "boss-1",
        "raw_payload": {"uid": "uid-1"},
    }
    service = FriendService.__new__(FriendService)
    service.friends = FakeFriendRepository(record)
    service.boss_client = FakeMessageClient()

    result = asyncio.run(service.send_friend_message("boss-1", "  你好  "))

    assert service.friends.record.last_filter == {"encrypt_boss_id": "boss-1"}
    assert service.boss_client.calls == [
        SendMessageIn(
            job_id="encrypt-1",
            gid="gid-1",
            self_id="uid-2",
            boss_uid="gid-1",
            boss_id="boss-1",
            security_id="sec-1",
            content="你好",
            raw_payload={"uid": "uid-1"},
        )
    ]
    assert result.status == "sent"
    assert result.gid == "gid-1"
    assert result.friend_id == "boss-1"


def test_send_friend_message_missing_friend_returns_404_error():
    service = FriendService.__new__(FriendService)
    service.friends = FakeFriendRepository(None)
    service.boss_client = FakeMessageClient()

    try:
        asyncio.run(service.send_friend_message("boss-1", "你好"))
    except BossOperationError as exc:
        assert exc.status_code == 404
        assert "未找到 friend_id=boss-1 的好友记录" in exc.message
    else:
        raise AssertionError("expected BossOperationError")


def test_send_friend_message_syncs_friends_before_failing_missing_friend():
    record = {
        "_id": "friend-1",
        "encrypt_job_id": "encrypt-1",
        "gid": "gid-1",
        "boss_uid": "gid-1",
        "self_id": "uid-2",
        "security_id": "sec-1",
        "encrypt_boss_id": "boss-1",
        "raw_payload": {"uid": "uid-1"},
    }
    service = FriendService.__new__(FriendService)
    service.friends = FakeFriendRepository(None)
    service.boss_client = FakeMessageClient()
    service.boss_client.friends_payload = [
        {
            "gid": "gid-1",
            "friend_source": 0,
            "relation_type": 2,
            "read_status": 1,
            "job_id": 123,
            "encrypt_job_id": "encrypt-1",
            "encrypt_boss_id": "boss-1",
            "security_id": "sec-1",
            "name": "Alice",
            "title": "HR",
            "company": "Demo Tech",
            "avatar": None,
            "last_message": None,
            "unread_count": 0,
            "raw_payload": {"uid": "uid-1"},
        }
    ]

    async def update_one(filters: dict, updates: dict, upsert: bool = False):
        _ = upsert
        service.friends.updated.append((filters, updates))
        if filters == {"encrypt_boss_id": "boss-1"}:
            service.friends.record.record = record | updates["$set"]
        return None

    service.friends.update_one = update_one

    result = asyncio.run(service.send_friend_message("boss-1", "你好"))

    assert service.boss_client.calls
    assert result.friend_id == "boss-1"
