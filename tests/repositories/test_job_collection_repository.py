from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId

from job_buddy.boss.schemas import (
    JobDetailBossOut,
    JobDetailCompanyOut,
    JobDetailJobOut,
    JobDetailOut,
    JobDetailPayloadOut,
    SearchJobItemOut,
)
from job_buddy.models import JobLead
from job_buddy.repositories import JobCollectionRepository


class FakeInsertResult:
    def __init__(self, inserted_id: ObjectId) -> None:
        self.inserted_id = inserted_id


class FakeJobLeadCollection:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}

    async def insert_one(self, payload: dict) -> FakeInsertResult:
        inserted_id = ObjectId()
        stored = dict(payload)
        stored["_id"] = inserted_id
        self.payloads[stored["source_job_id"]] = stored
        return FakeInsertResult(inserted_id)

    async def find_one(self, filters: dict) -> dict | None:
        if "source_job_id" in filters:
            return self.payloads.get(filters["source_job_id"])
        if "_id" in filters:
            for payload in self.payloads.values():
                if payload.get("_id") == filters["_id"]:
                    return payload
        return None

    async def update_one(self, filters: dict, updates: dict) -> None:
        payload = await self.find_one(filters)
        if payload is not None:
            payload.update(updates["$set"])


class FakeRecordCollection:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def insert_one(self, payload: dict) -> FakeInsertResult:
        inserted_id = ObjectId()
        stored = dict(payload)
        stored["_id"] = inserted_id
        self.payloads.append(stored)
        return FakeInsertResult(inserted_id)

    async def find_one(self, filters: dict) -> dict | None:
        for payload in self.payloads:
            match = True
            for key, value in filters.items():
                if key == "source_job_id":
                    if payload.get("source_job_id") != value:
                        match = False
                        break
                elif key == "collected_at":
                    if "$gte" in value:
                        collected_at = payload.get("collected_at")
                        if collected_at is None or collected_at < value["$gte"]:
                            match = False
                            break
                elif key == "_id":
                    if payload.get("_id") != value:
                        match = False
                        break
            if match:
                return payload
        return None

    def find(self, filters: dict):
        since = None
        if "collected_at" in filters and "$gte" in filters["collected_at"]:
            since = filters["collected_at"]["$gte"]
        source_job_ids = set()
        if "source_job_id" in filters and "$in" in filters["source_job_id"]:
            source_job_ids = set(filters["source_job_id"]["$in"])

        matched = [
            p
            for p in self.payloads
            if p.get("source_job_id") in source_job_ids
            and (since is None or (p.get("collected_at") is not None and p["collected_at"] >= since))
        ]

        class Cursor:
            def __init__(self, rows: list[dict[str, Any]]) -> None:
                self.rows = rows

            async def to_list(self, length=None):
                _ = length
                return list(self.rows)

        return Cursor(matched)


def _build_repo() -> tuple[JobCollectionRepository, FakeJobLeadCollection, FakeRecordCollection]:
    jobs = FakeJobLeadCollection()
    records = FakeRecordCollection()
    return JobCollectionRepository(jobs, records), jobs, records


def _make_search_item(job_id: str = "job-1") -> SearchJobItemOut:
    return SearchJobItemOut(
        job_id=job_id,
        security_id="sec-1",
        title="Python Engineer",
        company="Demo Tech",
        city="Shanghai",
        salary="20-30K",
        experience="3-5年",
        job_url="https://www.zhipin.com/job_detail/job-1.html",
        raw_payload={"encryptJobId": job_id},
    )


def _make_detail(job_id: str = "job-1") -> JobDetailOut:
    return JobDetailOut(
        engine="patchright",
        browser="Patchright Chromium",
        request_url="https://www.zhipin.com/wapi/zpgeek/job/detail.json",
        requested_at="2026-05-16T13:02:20+00:00",
        response_received_at="2026-05-16T13:02:21+00:00",
        request_payload={},
        response_payload={"code": 0},
        job=JobDetailJobOut(
            job_id=job_id,
            security_id="sec-1",
            job_url="",
            title="Python Engineer",
            salary="20-30K",
            experience="3-5年",
            degree="本科",
            city="上海",
            address="",
            skills=[],
            description="",
            status="在招",
            active_time=0,
        ),
        company=JobDetailCompanyOut(name="Demo Tech", stage="A轮", scale="100-499人", industry="互联网", intro=""),
        boss=JobDetailBossOut(name="Alice", title="招聘经理", active_text="", online=False),
        detail_payload=JobDetailPayloadOut(
            job=JobDetailJobOut(
                job_id=job_id,
                security_id="sec-1",
                job_url="",
                title="Python Engineer",
                salary="20-30K",
                experience="3-5年",
                degree="本科",
                city="上海",
                address="",
                skills=[],
                description="",
                status="在招",
                active_time=0,
            ),
            company=JobDetailCompanyOut(name="Demo Tech", stage="A轮", scale="100-499人", industry="互联网", intro=""),
            boss=JobDetailBossOut(name="Alice", title="招聘经理", active_text="", online=False),
            raw_payload={},
        ),
        detail_text="职位名称：Python Engineer",
        job_id=job_id,
        security_id="sec-1",
        encrypt_boss_id="boss-1",
        contact=False,
        boss_online=False,
        boss_active_text="",
        job_active_time=0,
        job_url="",
        detail_raw_payload={},
    )


@pytest.mark.asyncio
async def test_is_recently_collected_returns_true_within_window():
    repo, _jobs, records = _build_repo()
    records.payloads.append(
        {
            "_id": ObjectId(),
            "source_job_id": "job-1",
            "collected_at": datetime.now(tz=UTC),
        }
    )

    result = await repo.is_recently_collected("job-1", hours=24)

    assert result is True


@pytest.mark.asyncio
async def test_is_recently_collected_returns_false_outside_window():
    repo, _jobs, records = _build_repo()
    records.payloads.append(
        {
            "_id": ObjectId(),
            "source_job_id": "job-1",
            "collected_at": datetime.now(tz=UTC) - timedelta(hours=25),
        }
    )

    result = await repo.is_recently_collected("job-1", hours=24)

    assert result is False


@pytest.mark.asyncio
async def test_get_recently_collected_source_job_ids_filters_by_time():
    repo, _jobs, records = _build_repo()
    now = datetime.now(tz=UTC)
    records.payloads.append({"_id": ObjectId(), "source_job_id": "job-1", "collected_at": now})
    records.payloads.append({"_id": ObjectId(), "source_job_id": "job-2", "collected_at": now - timedelta(hours=25)})

    result = await repo.get_recently_collected_source_job_ids(["job-1", "job-2", "job-3"], hours=24)

    assert result == {"job-1"}


@pytest.mark.asyncio
async def test_save_scroll_record_creates_record():
    repo, _jobs, records = _build_repo()
    item = _make_search_item("job-1")

    record = await repo.save_scroll_record("task-1", item)

    assert record.source_job_id == "job-1"
    assert record.task_id == "task-1"
    assert len(records.payloads) == 1


@pytest.mark.asyncio
async def test_save_detail_record_creates_record():
    repo, _jobs, records = _build_repo()
    detail = _make_detail("job-1")

    record = await repo.save_detail_record("task-1", detail)

    assert record.source_job_id == "job-1"
    assert record.task_id == "task-1"
    assert len(records.payloads) == 1


@pytest.mark.asyncio
async def test_upsert_job_lead_creates_when_missing():
    repo, jobs, _records = _build_repo()
    detail = _make_detail("job-1")

    lead, is_created = await repo.upsert_job_lead(detail, target=None)

    assert is_created is True
    assert lead.source_job_id == "job-1"
    assert lead.title == "Python Engineer"
    assert jobs.payloads["job-1"]["match_status"] == "new"


@pytest.mark.asyncio
async def test_upsert_job_lead_updates_when_existing():
    repo, jobs, _records = _build_repo()
    detail = _make_detail("job-1")
    await repo.upsert_job_lead(detail, target=None)

    detail.job.title = "Senior Python Engineer"
    lead, is_created = await repo.upsert_job_lead(detail, target=None)

    assert is_created is False
    assert lead.title == "Senior Python Engineer"


@pytest.mark.asyncio
async def test_upsert_job_lead_from_search_creates_when_missing():
    repo, jobs, _records = _build_repo()
    item = _make_search_item("job-1")

    lead, is_created = await repo.upsert_job_lead_from_search(item, target=None)

    assert is_created is True
    assert lead.source_job_id == "job-1"
    assert lead.search_count == 1


@pytest.mark.asyncio
async def test_upsert_job_lead_from_search_increments_search_count():
    repo, jobs, _records = _build_repo()
    item = _make_search_item("job-1")
    await repo.upsert_job_lead_from_search(item, target=None)

    item.salary = "30-40K"
    lead, is_created = await repo.upsert_job_lead_from_search(item, target=None)

    assert is_created is False
    assert lead.search_count == 2
    assert lead.salary == "30-40K"
