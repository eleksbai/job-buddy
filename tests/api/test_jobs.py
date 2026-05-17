import pytest
from fastapi import FastAPI

from job_buddy.deps import get_job_service
from job_buddy.modules.jobs import JobCollectionRecord, JobLead
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeJobService:
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

    async def get_job_detail(self, source_job_id):
        _ = source_job_id
        return (
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
                detail_payload={"job": {"title": "Python Backend Engineer"}},
                detail_text="职位名称：Python Backend Engineer",
                detail_source_url="https://www.zhipin.com/wapi/zpgeek/job/detail.json?securityId=sec-1",
            ),
            False,
        )


@pytest.mark.asyncio
async def test_list_jobs_includes_job_url():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_job_service] = lambda: FakeJobService()

    async with api_client(app) as client:
        response = await client.get("/api/jobs")

    assert response.status_code == 200
    assert response.json()[0]["job_url"] == "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1"
    assert response.json()[0]["search_count"] == 1
    assert response.json()[0]["last_searched_at"] is not None


@pytest.mark.asyncio
async def test_list_job_collection_records():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_job_service] = lambda: FakeJobService()

    async with api_client(app) as client:
        response = await client.get("/api/jobs/collections")

    assert response.status_code == 200
    assert response.json()[0]["task_id"] == "task-1"
    assert response.json()[0]["job_url"] == "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1"


@pytest.mark.asyncio
async def test_get_job_detail():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_job_service] = lambda: FakeJobService()

    async with api_client(app) as client:
        response = await client.get("/api/jobs/job-1/detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cached"] is False
    assert payload["job"]["source_job_id"] == "job-1"
    assert payload["job"]["detail_text"] == "职位名称：Python Backend Engineer"
