from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class PyObjectId(str):
    @classmethod
    def from_value(cls, value: ObjectId | str) -> str:
        return str(value)


class DocumentModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: str | None = Field(default=None, alias="_id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def to_mongo(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, exclude_none=True)
        if payload.get("_id"):
            payload["_id"] = ObjectId(payload["_id"])
        return payload

    @classmethod
    def from_mongo(cls, payload: dict[str, Any]) -> Self:
        data = dict(payload)
        if "_id" in data:
            data["_id"] = PyObjectId.from_value(data["_id"])
        return cls.model_validate(data)


TASK_TIMEOUT = 300


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


class TargetProfile(DocumentModel):
    name: str
    keywords: list[str] = Field(default_factory=list)
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    greeting_template: str | None = None
    is_active: bool = True


class JobLead(DocumentModel):
    source: str = "boss"
    source_job_id: str
    security_id: str | None = None
    source_friend_id: str | None = None
    contact: bool | None = None
    boss_online: bool | None = None
    boss_active_text: str | None = None
    job_active_time: int | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    match_status: str = "new"
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    detail_payload: dict[str, Any] = Field(default_factory=dict)
    detail_text: str | None = None
    detail_source_url: str | None = None
    detail_fetched_at: datetime | None = None
    last_seen_at: datetime = Field(default_factory=utc_now)
    search_count: int = 1
    last_searched_at: datetime = Field(default_factory=utc_now)
    greeted: bool = False


class JobCollectionRecord(DocumentModel):
    task_id: str
    trace_id: str | None = None
    target_profile_id: str | None = None
    source: str = "boss"
    source_job_id: str
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=utc_now)


class JobCollectionTrace(DocumentModel):
    task_id: str
    target_profile_id: str | None = None
    source: str = "boss"
    engine: str | None = None
    browser: str | None = None
    request_url: str | None = None
    referer: str | None = None
    requested_at: datetime | None = None
    response_received_at: datetime | None = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    request_params: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    result_count: int = 0


class GreetingTask(DocumentModel):
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    target_profile_id: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class GreetingRecord(DocumentModel):
    task_id: str
    job_lead_id: str
    source_job_id: str
    status: str
    message: str | None = None
    response_payload: dict[str, Any] = Field(default_factory=dict)


class FriendMessage(BaseModel):
    message_id: str
    from_id: str
    from_name: str | None = None
    content: str = ""
    msg_type: int | None = None
    sent_at: int | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class FriendRecord(DocumentModel):
    source: str = "boss"
    gid: str = ""
    boss_uid: str | None = None
    friend_source: int | None = None
    relation_type: int | None = None
    read_status: int | None = None
    security_id: str | None = None
    self_id: str | None = None
    source_job_id: str | None = None
    source_friend_id: str
    title: str
    name: str = ""
    company: str | None = None
    avatar: str | None = None
    last_message: str | None = None
    unread_count: int = 0
    last_message_at: str | None = None
    last_message_ts: float | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    messages: list[FriendMessage] = Field(default_factory=list)


class AuthState(DocumentModel):
    provider: str = "zhipin"
    logged_in: bool = False
    user_name: str | None = None
    login_method: str | None = None
    browser: str | None = None
    last_login_at: datetime | None = None
    last_logout_at: datetime | None = None
    last_error: str | None = None
