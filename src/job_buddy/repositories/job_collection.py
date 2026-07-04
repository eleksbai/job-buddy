from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from job_buddy.boss.schemas import JobDetailOut, SearchJobItemOut
from job_buddy.models import JobCollectionRecord, JobLead, compute_pre_check, utc_now


class JobCollectionRepository:
    """Repository for job collection persistence operations.

    Encapsulates database reads/writes for the scroll-and-collect flow so
    that ``BossClient`` can persist data directly without returning raw
    payloads back to the service layer.
    """

    def __init__(self, jobs: AsyncIOMotorCollection, records: AsyncIOMotorCollection) -> None:
        self.jobs = jobs
        self.records = records

    async def is_recently_collected(self, source_job_id: str, hours: int = 24) -> bool:
        """Return ``True`` if a detail record for *source_job_id* exists within
        the last *hours* hours."""
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        payload = await self.records.find_one(
            {"source_job_id": source_job_id, "collected_at": {"$gte": since}}
        )
        return payload is not None

    async def get_recently_collected_source_job_ids(
        self,
        source_job_ids: list[str],
        hours: int = 24,
    ) -> set[str]:
        """Return the subset of *source_job_ids* that have been collected
        within the last *hours* hours."""
        if not source_job_ids:
            return set()
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        cursor = self.records.find(
            {
                "source_job_id": {"$in": source_job_ids},
                "collected_at": {"$gte": since},
            }
        )
        results = await cursor.to_list(length=len(source_job_ids))
        return {r["source_job_id"] for r in results}

    async def get_source_job_ids_with_recent_details(
        self,
        source_job_ids: list[str],
        hours: int = 24,
    ) -> set[str]:
        """Return the subset of *source_job_ids* whose ``JobLead.detail_fetched_at``
        is within the last *hours* hours."""
        if not source_job_ids:
            return set()
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        cursor = self.jobs.find(
            {
                "source_job_id": {"$in": source_job_ids},
                "detail_fetched_at": {"$gte": since},
            }
        )
        results = await cursor.to_list(length=len(source_job_ids))
        return {r["source_job_id"] for r in results}

    async def save_scroll_record(
        self, task_id: str, item: SearchJobItemOut
    ) -> JobCollectionRecord:
        """Persist a single list-item as a ``JobCollectionRecord``."""
        record = JobCollectionRecord(
            task_id=task_id,
            source_job_id=item.job_id,
            security_id=item.security_id,
            title=item.title,
            company=item.company,
            city=item.city,
            salary=item.salary,
            experience=item.experience,
            job_url=item.job_url,
            raw_payload=item.raw_payload,
        )
        payload = record.to_mongo()
        payload.pop("_id", None)
        result = await self.records.insert_one(payload)
        stored = await self.records.find_one({"_id": result.inserted_id})
        return JobCollectionRecord.from_mongo(stored)

    async def save_detail_record(
        self, task_id: str, detail: JobDetailOut
    ) -> JobCollectionRecord:
        """Persist a single detail result as a ``JobCollectionRecord``."""
        record = JobCollectionRecord(
            task_id=task_id,
            source_job_id=detail.job_id,
            security_id=detail.security_id,
            title=detail.job.title or detail.job_id,
            company=detail.company.name or "",
            city=detail.job.city,
            salary=detail.job.salary,
            experience=detail.job.experience,
            job_url=detail.job_url,
            raw_payload=detail.detail_raw_payload or {},
        )
        payload = record.to_mongo()
        payload.pop("_id", None)
        result = await self.records.insert_one(payload)
        stored = await self.records.find_one({"_id": result.inserted_id})
        return JobCollectionRecord.from_mongo(stored)

    async def upsert_job_lead(
        self,
        detail: JobDetailOut,
    ) -> tuple[JobLead, bool]:
        """Create or update a ``JobLead`` from a ``JobDetailOut``.

        Returns ``(lead, is_created)``.
        """
        existing_payload = await self.jobs.find_one({"source_job_id": detail.job_id})
        if existing_payload is None:
            record = JobLead(
                source_job_id=detail.job_id,
                security_id=detail.job.security_id or None,
                source_friend_id=detail.encrypt_boss_id or None,
                contact=detail.contact,
                boss_online=detail.boss_online,
                boss_active_text=detail.boss_active_text or None,
                job_active_time=detail.job_active_time or None,
                title=detail.job.title or detail.job_id,
                company=detail.company.name or "",
                scale=detail.company.scale or None,
                industry=detail.company.industry or None,
                city=detail.job.city or None,
                salary=detail.job.salary or None,
                experience=detail.job.experience or None,
                job_url=detail.job_url or None,
                match_status="new",
                detail_payload=detail.model_dump(),
                detail_text=detail.detail_text or None,
                detail_source_url=detail.request_url or detail.job_url or None,
                detail_fetched_at=utc_now(),
                raw_payload=detail.detail_raw_payload or {},
                pre_check=compute_pre_check(
                    detail.job.title or detail.job_id,
                    detail.boss_active_text or None,
                    detail.detail_text or None,
                ),
            )
            payload = record.to_mongo()
            payload.pop("_id", None)
            result = await self.jobs.insert_one(payload)
            stored = await self.jobs.find_one({"_id": result.inserted_id})
            return JobLead.from_mongo(stored), True

        existing = JobLead.from_mongo(existing_payload)
        updates: dict[str, Any] = {
            "security_id": detail.job.security_id or existing.security_id,
            "source_friend_id": detail.encrypt_boss_id or existing.source_friend_id,
            "contact": detail.contact if detail.contact is not None else existing.contact,
            "boss_online": detail.boss_online if detail.boss_online is not None else existing.boss_online,
            "boss_active_text": detail.boss_active_text or existing.boss_active_text,
            "job_active_time": (
                detail.job_active_time if detail.job_active_time is not None else existing.job_active_time
            ),
            "title": detail.job.title or existing.title,
            "company": detail.company.name or existing.company,
            "scale": detail.company.scale or existing.scale,
            "industry": detail.company.industry or existing.industry,
            "city": detail.job.city or existing.city,
            "salary": detail.job.salary or existing.salary,
            "experience": detail.job.experience or existing.experience,
            "job_url": detail.job_url or existing.job_url,
            "detail_payload": detail.model_dump(),
            "detail_text": detail.detail_text or existing.detail_text,
            "detail_source_url": detail.request_url or detail.job_url or existing.detail_source_url,
            "detail_fetched_at": utc_now(),
            "last_seen_at": utc_now(),
            "updated_at": utc_now(),
            "pre_check": compute_pre_check(
                detail.job.title or existing.title,
                detail.boss_active_text or existing.boss_active_text,
                detail.detail_text or existing.detail_text,
            ),
        }
        await self.jobs.update_one({"_id": ObjectId(existing.id)}, {"$set": updates})
        stored = await self.jobs.find_one({"_id": ObjectId(existing.id)})
        return JobLead.from_mongo(stored), False

    async def upsert_job_lead_from_search(
        self,
        item: SearchJobItemOut,
    ) -> tuple[JobLead, bool]:
        """Create or update a ``JobLead`` from a ``SearchJobItemOut``.

        Returns ``(lead, is_created)``.
        """
        existing_payload = await self.jobs.find_one({"source_job_id": item.job_id})
        if existing_payload is None:
            record = JobLead(
                source_job_id=item.job_id,
                security_id=item.security_id,
                source_friend_id=item.encrypt_boss_id,
                contact=item.contact,
                boss_online=item.boss_online,
                boss_active_text=item.boss_active_text,
                job_active_time=item.job_active_time,
                title=item.title,
                company=item.company,
                city=item.city,
                salary=item.salary,
                experience=item.experience,
                job_url=item.job_url,
                match_status="new",
                raw_payload=item.raw_payload,
                search_count=1,
                last_searched_at=utc_now(),
                pre_check=compute_pre_check(
                    item.title,
                    item.boss_active_text,
                ),
            )
            payload = record.to_mongo()
            payload.pop("_id", None)
            result = await self.jobs.insert_one(payload)
            stored = await self.jobs.find_one({"_id": result.inserted_id})
            return JobLead.from_mongo(stored), True

        existing = JobLead.from_mongo(existing_payload)
        updates: dict[str, Any] = {
            "security_id": item.security_id,
            "source_friend_id": item.encrypt_boss_id or existing.source_friend_id,
            "contact": item.contact if item.contact is not None else existing.contact,
            "boss_online": item.boss_online if item.boss_online is not None else existing.boss_online,
            "boss_active_text": item.boss_active_text or existing.boss_active_text,
            "job_active_time": (
                item.job_active_time if item.job_active_time is not None else existing.job_active_time
            ),
            "title": item.title,
            "company": item.company,
            "city": item.city,
            "salary": item.salary,
            "experience": item.experience,
            "job_url": item.job_url,
            "raw_payload": item.raw_payload,
            "last_seen_at": utc_now(),
            "last_searched_at": utc_now(),
            "search_count": max(1, existing.search_count) + 1,
            "updated_at": utc_now(),
            "pre_check": compute_pre_check(
                item.title,
                item.boss_active_text or existing.boss_active_text,
            ),
        }
        await self.jobs.update_one({"_id": ObjectId(existing.id)}, {"$set": updates})
        stored = await self.jobs.find_one({"_id": ObjectId(existing.id)})
        return JobLead.from_mongo(stored), False
