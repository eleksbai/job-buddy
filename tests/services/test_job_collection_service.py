from __future__ import annotations

import asyncio
from typing import Any

from bson import ObjectId

from job_buddy.boss.schemas import HealthcheckOut, JobDetailBossOut, JobDetailCompanyOut, JobDetailIn, JobDetailJobOut, JobDetailOut, JobDetailPayloadOut, SearchJobItemOut, SearchOut
from job_buddy.models import (
    GreetingTask,
    JobCollectionRecord,
    JobCollectionTrace,
    JobLead,
)
from job_buddy.services import JobCollectionService


class AuthRequired(Exception):
    pass


class FakeBossClient:
    def __init__(self) -> None:
        self.logged_in = True
        self.health_message = "已登录"
        self.health_last_error = None
        self.search_error: Exception | None = None
        self.detail_error: Exception | None = None
        self.detail_payload: JobDetailOut | None = None
        self.payloads = [
            [
                {
                    "job_id": "job-1",
                    "security_id": "sec-1",
                    "title": "Python Backend Engineer",
                    "company": "Demo Tech",
                    "city": "Shanghai",
                    "salary": "20-30K",
                    "experience": "3-5年",
                    "job_url": "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
                }
            ],
            [
                {
                    "job_id": "job-1",
                    "security_id": "sec-1",
                    "title": "Python Backend Engineer",
                    "company": "Demo Tech",
                    "city": "Shanghai",
                    "salary": "25-35K",
                    "experience": "3-5年",
                    "job_url": "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
                }
            ],
        ]

    async def search(self, request) -> SearchOut:
        query = request.query
        _ = query
        if self.search_error is not None:
            raise self.search_error
        return SearchOut(
            items=[
                SearchJobItemOut(
                    job_id=item["job_id"],
                    security_id=item.get("security_id"),
                    title=item["title"],
                    company=item["company"],
                    city=item.get("city"),
                    salary=item.get("salary"),
                    experience=item.get("experience"),
                    job_url=item.get("job_url"),
                    raw_payload=dict(item),
                )
                for item in self.payloads.pop(0)
            ],
            trace={
                "engine": "patchright",
                "browser": "Patchright Chromium",
                "request_url": "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query=Python",
                "referer": "https://www.zhipin.com/web/geek/job",
                "requested_at": "2026-05-16T13:02:20+00:00",
                "response_received_at": "2026-05-16T13:02:21+00:00",
                "request_payload": dict(query),
                "request_params": {"query": "Python"},
                "response_payload": {"zpData": {"jobList": self.payloads[0] if self.payloads else []}},
                "result_count": 1,
            },
        )

    async def get_job_detail(self, request: JobDetailIn) -> JobDetailOut:
        _ = request
        if self.detail_error is not None:
            raise self.detail_error
        return self.detail_payload or JobDetailOut(
            engine="patchright",
            browser="Patchright Chromium",
            request_url="https://www.zhipin.com/wapi/zpgeek/job/detail.json?securityId=sec-1",
            requested_at="2026-05-16T13:02:20+00:00",
            response_received_at="2026-05-16T13:02:21+00:00",
            request_payload={"job_id": "job-1", "security_id": "sec-1", "job_url": "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1", "title": "Python Backend Engineer", "company": "Demo Tech"},
            response_payload={"code": 0},
            job=JobDetailJobOut(job_id="job-1", security_id="sec-1", job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1", title="Python Backend Engineer", salary="20-30K", experience="3-5年", degree="本科", city="上海", address="Demo Address", skills=["Python", "FastAPI"], description="Build APIs", status="在招", active_time=1779249002309),
            company=JobDetailCompanyOut(name="Demo Tech", stage="A轮", scale="100-499人", industry="互联网", intro="Demo intro"),
            boss=JobDetailBossOut(name="Alice", title="招聘经理", active_text="本周活跃", online=False),
            detail_payload=JobDetailPayloadOut(
                job=JobDetailJobOut(job_id="job-1", security_id="sec-1", job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1", title="Python Backend Engineer", salary="20-30K", experience="3-5年", degree="本科", city="上海", address="Demo Address", skills=["Python", "FastAPI"], description="Build APIs", status="在招", active_time=1779249002309),
                company=JobDetailCompanyOut(name="Demo Tech", stage="A轮", scale="100-499人", industry="互联网", intro="Demo intro"),
                boss=JobDetailBossOut(name="Alice", title="招聘经理", active_text="本周活跃", online=False),
                raw_payload={"code": 0},
            ),
            detail_text="职位名称：Python Backend Engineer\n公司：Demo Tech\nBOSS 活跃：本周活跃",
            job_id="job-1",
            security_id="sec-1",
            encrypt_boss_id="",
            contact=False,
            boss_online=False,
            boss_active_text="本周活跃",
            job_active_time=1779249002309,
            job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
            detail_raw_payload={"code": 0},
        )

    async def healthcheck(self) -> HealthcheckOut:
        if self.logged_in:
            return HealthcheckOut(status="ok", provider="patchright", logged_in=True, message=self.health_message, last_error=self.health_last_error or "")
        return HealthcheckOut(status="auth_required", provider="patchright", logged_in=False, message=self.health_message, last_error=self.health_last_error or "")


class FakeInsertResult:
    def __init__(self, inserted_id: ObjectId) -> None:
        self.inserted_id = inserted_id


class FakeTaskCollection:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}

    async def insert_one(self, payload: dict) -> FakeInsertResult:
        inserted_id = ObjectId()
        stored = dict(payload)
        stored["_id"] = inserted_id
        self.payloads[str(inserted_id)] = stored
        return FakeInsertResult(inserted_id)

    async def find_one(self, filters: dict) -> dict | None:
        raw_id = filters.get("_id")
        return self.payloads.get(str(raw_id))

    async def update_one(self, filters: dict, updates: dict):
        payload = await self.find_one(filters)
        if payload is not None:
            payload.update(updates["$set"])
        return None


class FakeJobLeadCollection:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}

    @property
    def items(self) -> dict[str, JobLead]:
        return {key: JobLead.from_mongo(value) for key, value in self.payloads.items()}

    async def insert_one(self, payload: dict) -> FakeInsertResult:
        inserted_id = ObjectId()
        stored = dict(payload)
        stored["_id"] = inserted_id
        self.payloads[stored["source_job_id"]] = stored
        return FakeInsertResult(inserted_id)

    async def find_one(self, filters: dict) -> dict | None:
        if "_id" in filters:
            for payload in self.payloads.values():
                if payload.get("_id") == filters["_id"]:
                    return payload
            return None
        if "source_job_id" in filters:
            return self.payloads.get(filters["source_job_id"])
        return None

    async def update_one(self, filters: dict, updates: dict):
        payload = await self.find_one(filters)
        if payload is not None:
            payload.update(updates["$set"])
        return None


class FakeJobCollectionRecordCollection:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    @property
    def items(self) -> list[JobCollectionRecord]:
        return [JobCollectionRecord.from_mongo(payload) for payload in self.payloads]

    async def insert_one(self, payload: dict) -> FakeInsertResult:
        inserted_id = ObjectId()
        stored = dict(payload)
        stored["_id"] = inserted_id
        self.payloads.append(stored)
        return FakeInsertResult(inserted_id)

    async def find_one(self, filters: dict) -> dict | None:
        for payload in self.payloads:
            if payload.get("_id") == filters.get("_id"):
                return payload
        return None


class FakeJobCollectionTraceCollection:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    @property
    def items(self) -> list[JobCollectionTrace]:
        return [JobCollectionTrace.from_mongo(payload) for payload in self.payloads]

    async def insert_one(self, payload: dict) -> FakeInsertResult:
        inserted_id = ObjectId()
        stored = dict(payload)
        stored["_id"] = inserted_id
        self.payloads.append(stored)
        return FakeInsertResult(inserted_id)

    async def find_one(self, filters: dict) -> dict | None:
        for payload in self.payloads:
            if payload.get("_id") == filters.get("_id"):
                return payload
        return None


def build_service() -> tuple[
    JobCollectionService,
    FakeJobLeadCollection,
    FakeJobCollectionRecordCollection,
    FakeJobCollectionTraceCollection,
]:
    service = JobCollectionService.__new__(JobCollectionService)
    service.boss_client = FakeBossClient()
    service.tasks = FakeTaskCollection()
    service.jobs = FakeJobLeadCollection()
    service.records = FakeJobCollectionRecordCollection()
    service.traces = FakeJobCollectionTraceCollection()
    return service, service.jobs, service.records, service.traces


def test_search_jobs_writes_collection_records_and_deduped_leads():
    service, jobs, records, traces = build_service()

    first = asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))
    second = asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))

    assert first.result_summary["collected"] == 1
    assert first.result_summary["dedup_created"] == 1
    assert first.result_summary["dedup_updated"] == 0

    assert second.result_summary["collected"] == 1
    assert second.result_summary["dedup_created"] == 0
    assert second.result_summary["dedup_updated"] == 1

    assert len(records.items) == 2
    assert len(traces.items) == 2
    assert records.items[0].trace_id == traces.items[0].id
    assert len(jobs.items) == 1
    assert jobs.items["job-1"].salary == "25-35K"
    assert jobs.items["job-1"].job_url == "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1"
    assert jobs.items["job-1"].search_count == 2
    assert jobs.items["job-1"].last_searched_at is not None
    assert traces.items[0].request_url == "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query=Python"
    assert traces.items[0].browser == "Patchright Chromium"


def test_search_jobs_fails_fast_when_login_state_is_invalid():
    service, jobs, records, traces = build_service()
    service.boss_client.logged_in = False
    service.boss_client.health_message = "登录态无效，请重新登录"
    service.boss_client.health_last_error = "userinfo failed"

    task = asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))

    assert task.status.value == "failed"
    assert task.error_message == "登录态无效，请重新登录"
    assert len(records.items) == 0
    assert len(traces.items) == 0
    assert len(jobs.items) == 0


def test_search_jobs_maps_auth_errors_from_runtime():
    service, jobs, records, traces = build_service()
    service.boss_client.search_error = AuthRequired()

    task = asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))

    assert task.status.value == "failed"
    assert task.error_message == "未登录，请先点击页面右上角登录"
    assert len(records.items) == 0
    assert len(traces.items) == 0
    assert len(jobs.items) == 0


def test_get_job_detail_returns_cached_detail_without_refetching():
    service, jobs, records, traces = build_service()
    asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))
    jobs.payloads["job-1"]["detail_payload"] = {"job": {"title": "Python Backend Engineer"}}
    jobs.payloads["job-1"]["detail_text"] = "职位名称：Python Backend Engineer"

    result, cached = asyncio.run(service.get_job_detail("job-1"))

    assert cached is True
    assert result.detail_text == "职位名称：Python Backend Engineer"
    assert result.detail_payload["job"]["title"] == "Python Backend Engineer"
    assert len(records.items) == 1
    assert len(traces.items) == 1


def test_get_job_detail_fetches_and_persists_detail_when_missing():
    service, jobs, records, traces = build_service()
    asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))

    result, cached = asyncio.run(service.get_job_detail("job-1"))

    assert cached is False
    assert result.detail_text == "职位名称：Python Backend Engineer\n公司：Demo Tech\nBOSS 活跃：本周活跃"
    assert result.detail_payload["detail_payload"]["job"]["title"] == "Python Backend Engineer"
    assert result.detail_source_url == "https://www.zhipin.com/wapi/zpgeek/job/detail.json?securityId=sec-1"
    assert result.detail_fetched_at is not None
    assert result.job_active_time == 1779249002309
    assert result.boss_active_text == "本周活跃"
    assert jobs.items["job-1"].detail_payload["detail_payload"]["company"]["name"] == "Demo Tech"
