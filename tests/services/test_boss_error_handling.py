import asyncio

from bson import ObjectId

from job_buddy.boss import BossOperationError
from job_buddy.boss.schemas import FriendListIn, FriendListItemOut, GreetJobIn, GreetJobOut, LoginOut
from job_buddy.models import AuthState
from job_buddy.models import GreetingRecord
from job_buddy.services import FriendService, GreetingService


class AuthRequired(Exception):
    pass


class ExplodingFriendClient:
    async def get_auth_status(self) -> LoginOut:
        return LoginOut(logged_in=True, user_name="Alice", city="上海", ip="127.0.0.1", uid="uid-1", message="已登录")

    async def list_friends(self, request: FriendListIn) -> list[FriendListItemOut]:
        _ = request
        raise AuthRequired()


class FakeFriendCollection:
    async def find_one(self, filters: dict):
        _ = filters
        return None

    async def update_one(self, filters: dict, updates: dict, upsert: bool = False):
        _ = filters, updates, upsert
        return None


class ExplodingGreetingClient:
    async def get_auth_status(self) -> LoginOut:
        return LoginOut(logged_in=True, user_name="Alice", city="上海", ip="127.0.0.1", uid="uid-1", message="已登录")

    async def greet_job(self, request: GreetJobIn) -> GreetJobOut:
        _ = request
        raise AuthRequired()


class SuccessfulGreetingClient:
    async def get_auth_status(self) -> LoginOut:
        return LoginOut(logged_in=True, user_name="Alice", city="上海", ip="127.0.0.1", uid="uid-1", message="已登录")

    async def greet_job(self, request: GreetJobIn) -> GreetJobOut:
        return GreetJobOut(job_id=request.job_id, security_id=request.security_id, encrypt_boss_id="boss-1", raw_payload={})


class FakeAuthStateCollection:
    def __init__(self) -> None:
        self.payload: dict | None = None

    async def find_one(self, filters: dict):
        _ = filters
        return self.payload

    async def insert_one(self, payload: dict):
        payload = dict(payload)
        payload["_id"] = ObjectId()
        self.payload = payload
        return type("InsertResult", (), {"inserted_id": payload["_id"]})()

    async def update_one(self, filters: dict, updates: dict):
        _ = filters
        if self.payload is not None:
            self.payload.update(updates["$set"])
        return None


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
        self.payload = {
            "_id": self.job_id,
            "source_job_id": "source-job-1",
            "security_id": "sec-1",
            "title": "Python Backend Engineer",
            "company": "Demo Tech",
        }

    def find(self, filters: dict):
        _ = filters
        return FakeJobCursor([self.payload])

    async def find_one(self, filters: dict):
        if filters.get("_id") == self.job_id:
            return self.payload
        if filters.get("source_job_id") == self.payload["source_job_id"]:
            return self.payload
        return None

    async def update_one(self, filters: dict, updates: dict):
        self.updated.append((str(filters["_id"]), updates["$set"]))
        if filters.get("_id") == self.job_id:
            self.payload.update(updates["$set"])
        return None


def test_sync_friends_maps_auth_errors():
    service = FriendService.__new__(FriendService)
    service.boss_client = ExplodingFriendClient()
    service.friends = FakeFriendCollection()
    service.auth_states = FakeAuthStateCollection()

    try:
        asyncio.run(service.sync_friends())
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
    service.auth_states = FakeAuthStateCollection()

    task = asyncio.run(service.run_greetings(target=None, source_job_ids=[], greeting_message=None, limit=5))

    assert task.status.value == "failed"
    assert task.result_summary == {"total": 1, "succeeded": 0, "failed": 1}
    assert service.records.items[0].response_payload == {"error": "未登录，请先点击页面右上角登录"}
    assert service.jobs.updated == []


def test_run_greetings_marks_job_as_greeted_and_keeps_match_status_after_success():
    service = GreetingService.__new__(GreetingService)
    service.boss_client = SuccessfulGreetingClient()
    service.tasks = FakeTaskCollection()
    service.records = FakeGreetingRecordCollection()
    service.jobs = FakeJobCollection()
    service.auth_states = FakeAuthStateCollection()

    task = asyncio.run(service.run_greetings(target=None, source_job_ids=[], greeting_message=None, limit=5))

    assert task.status.value == "succeeded"
    assert service.jobs.updated[-1][1]["greeted"] is True
    assert service.jobs.updated[-1][1]["contact"] is True
    assert service.jobs.updated[-1][1]["source_friend_id"] == "boss-1"
    assert "match_status" not in service.jobs.updated[-1][1]


def test_run_greetings_accepts_source_job_id_list():
    service = GreetingService.__new__(GreetingService)
    service.boss_client = SuccessfulGreetingClient()
    service.tasks = FakeTaskCollection()
    service.records = FakeGreetingRecordCollection()
    service.jobs = FakeJobCollection()
    service.auth_states = FakeAuthStateCollection()

    task = asyncio.run(
        service.run_greetings(
            target=None,
            source_job_ids=["source-job-1"],
            greeting_message=None,
            limit=1,
        )
    )

    assert task.status.value == "succeeded"
    assert service.records.items[0].source_job_id == "source-job-1"
    assert service.jobs.updated[-1][1]["greeted"] is True
