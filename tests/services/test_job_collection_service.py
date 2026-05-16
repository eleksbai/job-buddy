from __future__ import annotations

import asyncio

from job_buddy.core.engines.models import SearchJobItem, SearchResult
from job_buddy.modules.jobs import (
    GreetingTask,
    JobCollectionRecord,
    JobCollectionTrace,
    JobCollectionService,
    JobLead,
)


class AuthRequired(Exception):
    pass


class FakeBossClient:
    def __init__(self) -> None:
        self.logged_in = True
        self.health_message = "已登录"
        self.health_last_error = None
        self.search_error: Exception | None = None
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

    async def search(self, request) -> SearchResult:
        query = request.query
        _ = query
        if self.search_error is not None:
            raise self.search_error
        return SearchResult(
            items=[
                SearchJobItem(
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

    async def healthcheck(self) -> dict:
        if self.logged_in:
            return {
                "status": "ok",
                "provider": "patchright",
                "logged_in": True,
                "message": self.health_message,
                "last_error": self.health_last_error,
            }
        return {
            "status": "auth_required",
            "provider": "patchright",
            "logged_in": False,
            "message": self.health_message,
            "last_error": self.health_last_error,
        }


class FakeTaskRepository:
    def __init__(self) -> None:
        self.items: dict[str, GreetingTask] = {}
        self.counter = 0

    async def create(self, task: GreetingTask) -> GreetingTask:
        self.counter += 1
        task.id = f"task-{self.counter}"
        self.items[task.id] = task
        return task

    async def update(self, task_id: str, updates: dict) -> GreetingTask | None:
        task = self.items.get(task_id)
        if task is None:
            return None
        for key, value in updates.items():
            setattr(task, key, value)
        return task


class FakeJobLeadRepository:
    def __init__(self) -> None:
        self.items: dict[str, JobLead] = {}
        self.counter = 0

    async def get_by_source_job_id(self, source_job_id: str) -> JobLead | None:
        return self.items.get(source_job_id)

    async def create(self, job: JobLead) -> JobLead:
        self.counter += 1
        job.id = f"lead-{self.counter}"
        self.items[job.source_job_id] = job
        return job

    async def update(self, entity_id: str, updates: dict) -> JobLead | None:
        for item in self.items.values():
            if item.id == entity_id:
                for key, value in updates.items():
                    setattr(item, key, value)
                return item
        return None


class FakeJobCollectionRecordRepository:
    def __init__(self) -> None:
        self.items: list[JobCollectionRecord] = []

    async def create(self, record: JobCollectionRecord) -> JobCollectionRecord:
        record.id = f"record-{len(self.items) + 1}"
        self.items.append(record)
        return record


class FakeJobCollectionTraceRepository:
    def __init__(self) -> None:
        self.items: list[JobCollectionTrace] = []

    async def create(self, trace: JobCollectionTrace) -> JobCollectionTrace:
        trace.id = f"trace-{len(self.items) + 1}"
        self.items.append(trace)
        return trace


def build_service() -> tuple[
    JobCollectionService,
    FakeJobLeadRepository,
    FakeJobCollectionRecordRepository,
    FakeJobCollectionTraceRepository,
]:
    service = JobCollectionService.__new__(JobCollectionService)
    service.runtime = FakeBossClient()
    service.tasks = FakeTaskRepository()
    service.jobs = FakeJobLeadRepository()
    service.records = FakeJobCollectionRecordRepository()
    service.traces = FakeJobCollectionTraceRepository()
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
    assert records.items[0].trace_id == "trace-1"
    assert len(jobs.items) == 1
    assert jobs.items["job-1"].salary == "25-35K"
    assert jobs.items["job-1"].job_url == "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1"
    assert jobs.items["job-1"].search_count == 2
    assert jobs.items["job-1"].last_searched_at is not None
    assert traces.items[0].request_url == "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query=Python"
    assert traces.items[0].browser == "Patchright Chromium"


def test_search_jobs_fails_fast_when_not_logged_in():
    service, jobs, records, traces = build_service()
    service.runtime.logged_in = False
    service.runtime.health_message = "未登录，请先点击页面右上角登录"

    task = asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))

    assert task.status.value == "failed"
    assert task.error_message == "未登录，请先点击页面右上角登录"
    assert len(records.items) == 0
    assert len(traces.items) == 0
    assert len(jobs.items) == 0


def test_search_jobs_fails_fast_when_login_state_is_invalid():
    service, jobs, records, traces = build_service()
    service.runtime.logged_in = False
    service.runtime.health_message = "登录态无效，请重新登录"
    service.runtime.health_last_error = "userinfo failed"

    task = asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))

    assert task.status.value == "failed"
    assert task.error_message == "登录态无效，请重新登录"
    assert len(records.items) == 0
    assert len(traces.items) == 0
    assert len(jobs.items) == 0


def test_search_jobs_maps_auth_errors_from_runtime():
    service, jobs, records, traces = build_service()
    service.runtime.search_error = AuthRequired()

    task = asyncio.run(service.search_jobs(query={"keywords": ["Python"]}))

    assert task.status.value == "failed"
    assert task.error_message == "未登录，请先点击页面右上角登录"
    assert len(records.items) == 0
    assert len(traces.items) == 0
    assert len(jobs.items) == 0
