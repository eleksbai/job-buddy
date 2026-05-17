import asyncio

from job_buddy.core.boss import BossOperationError
from job_buddy.modules.conversations import ConversationService
from job_buddy.modules.tasks import GreetingRecord, GreetingService


class AuthRequired(Exception):
    pass


class ExplodingConversationClient:
    async def list_conversations(self, limit: int = 20) -> list[dict]:
        _ = limit
        raise AuthRequired()


class FakeConversationRepository:
    async def create(self, record):
        return record


class ExplodingGreetingClient:
    async def greet_job(self, job: dict, message: str | None = None) -> dict:
        _ = job, message
        raise AuthRequired()


class FakeTaskRepository:
    def __init__(self) -> None:
        self.task = None

    async def create(self, task):
        task.id = "task-1"
        self.task = task
        return task

    async def get(self, entity_id: str):
        _ = entity_id
        return self.task

    async def update(self, task_id: str, updates: dict):
        _ = task_id
        for key, value in updates.items():
            setattr(self.task, key, value)
        return self.task


class FakeGreetingRecordRepository:
    def __init__(self) -> None:
        self.items: list[GreetingRecord] = []

    async def create(self, record: GreetingRecord) -> GreetingRecord:
        self.items.append(record)
        return record


class FakeJob:
    def __init__(self) -> None:
        self.id = "job-1"
        self.source_job_id = "source-job-1"
        self.title = "Python Backend Engineer"
        self.company = "Demo Tech"


class FakeJobRepository:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict]] = []

    async def list_filtered(self, greeted: bool = False, limit: int = 20):
        _ = greeted, limit
        return [FakeJob()]

    async def update(self, entity_id: str, updates: dict):
        self.updated.append((entity_id, updates))
        return None


def test_sync_conversations_maps_auth_errors():
    service = ConversationService.__new__(ConversationService)
    service.boss_client = ExplodingConversationClient()
    service.conversations = FakeConversationRepository()

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
    service.tasks = FakeTaskRepository()
    service.records = FakeGreetingRecordRepository()
    service.jobs = FakeJobRepository()

    task = asyncio.run(service.run_greetings(target=None, job_ids=[], greeting_message=None, limit=5))

    assert task.status.value == "failed"
    assert task.result_summary == {"total": 1, "succeeded": 0, "failed": 1}
    assert service.records.items[0].response_payload == {"error": "未登录，请先点击页面右上角登录"}
    assert service.jobs.updated == []
