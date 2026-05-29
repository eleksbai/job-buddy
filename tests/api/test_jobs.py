import pytest
from fastapi import FastAPI

from job_buddy.deps import get_job_service, get_target_service
from job_buddy.models import JobCollectionRecord, JobLead
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeJobService:
    def __init__(self) -> None:
        self.detail_calls: list[tuple[str, str | None, bool]] = []
        self.scroll_search_payloads: list[dict] = []

    async def list_jobs(self, match_status, greeted, limit):
        _ = match_status, greeted, limit
        return [
            JobLead(
                _id="6825fb1a7d4ce9adcc2d1a31",
                source_job_id="job-1",
                security_id="sec-1",
                title="Python Backend Engineer",
                company="Demo Tech",
                city="Shanghai",
                salary="20-30K",
                experience="3-5年",
                job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
            )
        ]

    async def list_collection_records(self, task_id, target_profile_id, source_job_id, limit):
        _ = task_id, target_profile_id, source_job_id, limit
        return [
            JobCollectionRecord(
                _id="6825fb1a7d4ce9adcc2d1a32",
                task_id="task-1",
                source_job_id="job-1",
                security_id="sec-1",
                title="Python Backend Engineer",
                company="Demo Tech",
                city="Shanghai",
                salary="20-30K",
                experience="3-5年",
                job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
            )
        ]

    async def get_job_detail(self, source_job_id, security_id=None, force_refresh=False):
        self.detail_calls.append((source_job_id, security_id, force_refresh))
        return (
            JobLead(
                _id="6825fb1a7d4ce9adcc2d1a31",
                source_job_id="job-1",
                security_id="sec-1",
                source_friend_id="boss-1",
                contact=False,
                boss_online=False,
                boss_active_text="本周活跃",
                job_active_time=1779249002309,
                title="Python Backend Engineer",
                company="Demo Tech",
                city="Shanghai",
                salary="20-30K",
                experience="3-5年",
                job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
                detail_payload={"job": {"title": "Python Backend Engineer"}},
                detail_text="职位名称：Python Backend Engineer",
                detail_source_url="https://www.zhipin.com/wapi/zpgeek/job/detail.json?securityId=sec-1",
            ),
            False,
        )

    async def search_jobs_by_scroll(self, query, target=None):
        _ = target
        self.scroll_search_payloads.append(dict(query))
        from job_buddy.models import GreetingTask

        return GreetingTask(_id="6825fb1a7d4ce9adcc2d1a33", task_type="search", status="running")

    async def collect_job_details_by_click(self, target=None):
        _ = target
        from job_buddy.models import GreetingTask

        return GreetingTask(_id="6825fb1a7d4ce9adcc2d1a34", task_type="detail_click", status="running")

    async def scroll_and_collect_jobs(self, query, target=None):
        _ = target
        self.scroll_and_collect_payloads = [dict(query)]
        from job_buddy.models import GreetingTask

        return GreetingTask(_id="6825fb1a7d4ce9adcc2d1a35", task_type="scroll_and_detail", status="running")


class FakeTargetService:
    async def get_target(self, target_id):
        _ = target_id
        raise AssertionError("unexpected target lookup")


@pytest.mark.asyncio
async def test_list_jobs_includes_job_url():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_job_service] = lambda: FakeJobService()

    async with api_client(app) as client:
        response = await client.get("/boss/jobs")

    assert response.status_code == 200
    assert response.json()[0]["job_url"] == "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1"
    assert response.json()[0]["source_job_id"] == "job-1"
    assert response.json()[0]["search_count"] == 1
    assert response.json()[0]["last_searched_at"] is not None


@pytest.mark.asyncio
async def test_get_job_detail_includes_contact_state():
    app = FastAPI()
    app.include_router(build_api_router())
    service = FakeJobService()
    app.dependency_overrides[get_job_service] = lambda: service
    app.dependency_overrides[get_target_service] = lambda: FakeTargetService()

    async with api_client(app) as client:
        response = await client.get("/boss/jobs/job-1/detail")

    assert response.status_code == 200
    assert response.json()["job"]["contact"] is False
    assert response.json()["job"]["source_friend_id"] == "boss-1"
    assert service.detail_calls == [("job-1", None, False)]


@pytest.mark.asyncio
async def test_get_job_detail_supports_force_refresh():
    app = FastAPI()
    app.include_router(build_api_router())
    service = FakeJobService()
    app.dependency_overrides[get_job_service] = lambda: service

    async with api_client(app) as client:
        response = await client.get("/boss/jobs/job-1/detail?security_id=sec-1&force_refresh=true")

    assert response.status_code == 200
    assert service.detail_calls == [("job-1", "sec-1", True)]


@pytest.mark.asyncio
async def test_trigger_scroll_search_task_uses_scroll_service_entry():
    app = FastAPI()
    app.include_router(build_api_router())
    service = FakeJobService()
    app.dependency_overrides[get_job_service] = lambda: service
    app.dependency_overrides[get_target_service] = lambda: FakeTargetService()

    async with api_client(app) as client:
        response = await client.post("/boss/tasks/search/scroll", json={"query_override": {"keywords": ["Python"]}})

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert service.scroll_search_payloads == [{"keywords": ["Python"]}]


@pytest.mark.asyncio
async def test_trigger_detail_click_task_uses_detail_click_service_entry():
    app = FastAPI()
    app.include_router(build_api_router())
    service = FakeJobService()
    app.dependency_overrides[get_job_service] = lambda: service
    app.dependency_overrides[get_target_service] = lambda: FakeTargetService()

    async with api_client(app) as client:
        response = await client.post("/boss/tasks/search/detail-click", json={"query_override": {}})

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["task_id"] is not None


@pytest.mark.asyncio
async def test_trigger_scroll_and_detail_task_uses_scroll_and_detail_service_entry():
    app = FastAPI()
    app.include_router(build_api_router())
    service = FakeJobService()
    app.dependency_overrides[get_job_service] = lambda: service
    app.dependency_overrides[get_target_service] = lambda: FakeTargetService()

    async with api_client(app) as client:
        response = await client.post("/boss/tasks/search/scroll-and-detail", json={"query_override": {"keywords": ["Python"]}})

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["task_id"] is not None
    assert service.scroll_and_collect_payloads == [{"keywords": ["Python"]}]
