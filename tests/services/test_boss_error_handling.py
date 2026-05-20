import asyncio

from bson import ObjectId

from job_buddy.boss import BossOperationError
from job_buddy.models import GreetingRecord
from job_buddy.services import ConversationService, GreetingService


class AuthRequired(Exception):
    pass


class ExplodingConversationClient:
    async def list_friends(self, page: int = 1) -> list[dict]:
        _ = page
        raise AuthRequired()

    async def list_conversations(self, limit: int = 20) -> list[dict]:
        _ = limit
        raise AuthRequired()


class FakeConversationCollection:
    async def update_one(self, filters: dict, updates: dict, upsert: bool = False):
        _ = filters, updates, upsert
        return None


class ExplodingGreetingClient:
    async def greet_job(self, job: dict, message: str | None = None) -> dict:
        _ = job, message
        raise AuthRequired()


class FakeTaskCollection:
    def __init__(self) -> None:
        self.task: dict | None = None

    async def insert_one(self, payload: dict):
        payload = dict(payload)
        payload["_id"] = ObjectId()
        self.task = payload
        return type("InsertResult", (), {"inserted_id": payload["_id"]})()

    async def find_one(self, filters: dict):
        _ = filters
        return self.task

    async def update_one(self, filters: dict, updates: dict):
        _ = filters
        if self.task is not None:
            self.task.update(updates["$set"])
        return None


class FakeGreetingRecordCollection:
    def __init__(self) -> None:
        self.items: list[GreetingRecord] = []
        self.payloads: list[dict] = []

    async def insert_one(self, payload: dict):
        payload = dict(payload)
        payload["_id"] = ObjectId()
        self.payloads.append(payload)
        self.items.append(GreetingRecord.from_mongo(payload))
        return type("InsertResult", (), {"inserted_id": payload["_id"]})()

    async def find_one(self, filters: dict):
        if not self.payloads:
            return None
        return self.payloads[-1]


class FakeJob:
    def __init__(self) -> None:
        self.id = "job-1"
        self.source_job_id = "source-job-1"
        self.security_id = "sec-1"
        self.title = "Python Backend Engineer"
        self.company = "Demo Tech"


class FakeJobCursor:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def sort(self, *args, **kwargs):
        _ = args, kwargs
        return self

    def limit(self, limit: int):
        self._items = self._items[:limit]
        return self

    async def to_list(self, length=None):
        _ = length
        return self._items


class FakeJobCollection:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict]] = []
        self.job_id = ObjectId()

    def find(self, filters: dict):
        _ = filters
        return FakeJobCursor(
            [
                {
                    "_id": self.job_id,
                    "source_job_id": "source-job-1",
                    "security_id": "sec-1",
                    "title": "Python Backend Engineer",
                    "company": "Demo Tech",
                }
            ]
        )

    async def update_one(self, filters: dict, updates: dict):
        self.updated.append((str(filters["_id"]), updates["$set"]))
        return None


def test_sync_conversations_maps_auth_errors():
    service = ConversationService.__new__(ConversationService)
    service.boss_client = ExplodingConversationClient()
    service.conversations = FakeConversationCollection()

    try:
        asyncio.run(service.sync_conversations())
    except BossOperationError as exc:
        assert exc.code == "AUTH_REQUIRED"
        assert exc.message == "未登录，请先点击页面右上角登录"
    else:
        raise AssertionError("expected BossOperationError")


def test_run_greetings_records_mapped_auth_errors():
    service = GreetingService.__new__(GreetingService)
    service.boss_client = ExplodingGreetingClient()
    service.tasks = FakeTaskCollection()
    service.records = FakeGreetingRecordCollection()
    service.jobs = FakeJobCollection()

    task = asyncio.run(service.run_greetings(target=None, job_ids=[], greeting_message=None, limit=5))

    assert task.status.value == "failed"
    assert task.result_summary == {"total": 1, "succeeded": 0, "failed": 1}
    assert service.records.items[0].response_payload == {"error": "未登录，请先点击页面右上角登录"}
    assert service.jobs.updated == []
