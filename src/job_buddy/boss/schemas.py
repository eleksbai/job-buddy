from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BossSchema(BaseModel):
    model_config = {"extra": "forbid"}


class LoginIn(BossSchema):
    timeout: int = 120


class LoginOut(BossSchema):
    logged_in: bool
    user_name: str = ""
    login_method: str = ""
    message: str = ""
    last_error: str = ""
    browser: str = ""
    last_login_at: datetime | None = None
    last_logout_at: datetime | None = None


class HealthcheckOut(BossSchema):
    status: str
    provider: str
    logged_in: bool
    message: str = ""
    last_error: str = ""


class SearchIn(BossSchema):
    query: dict[str, Any]


class JobDetailIn(BossSchema):
    job_id: str
    security_id: str | None = None
    job_url: str | None = None
    title: str | None = None
    company: str | None = None


class GreetJobIn(BossSchema):
    job_id: str
    security_id: str


class FriendListIn(BossSchema):
    page: int = 1


class ChatHistoryIn(BossSchema):
    boss_id: str
    security_id: str
    page: int = 1
    count: int = 20


class JobDetailJobOut(BossSchema):
    job_id: str
    security_id: str = ""
    job_url: str = ""
    title: str = ""
    salary: str = ""
    experience: str = ""
    degree: str = ""
    city: str = ""
    address: str = ""
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    status: str = ""
    active_time: int = 0


class JobDetailCompanyOut(BossSchema):
    name: str = ""
    stage: str = ""
    scale: str = ""
    industry: str = ""
    intro: str = ""


class JobDetailBossOut(BossSchema):
    name: str = ""
    title: str = ""
    active_text: str = ""
    online: bool = False


class JobDetailPayloadOut(BossSchema):
    job: JobDetailJobOut
    company: JobDetailCompanyOut
    boss: JobDetailBossOut
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class JobDetailOut(BossSchema):
    engine: str
    browser: str
    request_url: str
    requested_at: str
    response_received_at: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    job: JobDetailJobOut
    company: JobDetailCompanyOut
    boss: JobDetailBossOut
    detail_payload: JobDetailPayloadOut
    detail_text: str = ""
    job_id: str
    security_id: str = ""
    encrypt_boss_id: str = ""
    contact: bool = False
    boss_online: bool = False
    boss_active_text: str = ""
    job_active_time: int = 0
    job_url: str = ""
    detail_raw_payload: dict[str, Any] = Field(default_factory=dict)


class FriendListItemOut(BossSchema):
    gid: str
    job_id: str = ""
    encrypt_job_id: str = ""
    encrypt_boss_id: str = ""
    friend_source: int = 0
    relation_type: int = 0
    read_status: int = 0
    name: str = ""
    title: str = ""
    company: str = ""
    avatar: str = ""
    last_message: str = ""
    last_message_at: str = ""
    last_message_ts: int = 0
    unread_count: int = 0
    security_id: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class GreetJobOut(BossSchema):
    job_id: str
    security_id: str
    encrypt_boss_id: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ChatHistoryMessageOut(BossSchema):
    message_id: str
    from_id: str
    from_name: str
    to_id: str
    to_name: str
    content: str
    type: int
    created_at: int
    received: bool
    status: int
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ChatHistoryOut(BossSchema):
    boss_id: str
    security_id: str
    page: int
    count: int
    has_more: bool
    total: int
    messages: list[ChatHistoryMessageOut] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class SendMessageIn(BossSchema):
    job_id: str
    job_numeric_id: int | None = None
    gid: str
    self_id: str
    boss_uid: str
    boss_id: str
    friend_source: int = 0
    security_id: str | None
    content: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class SendMessageOut(BossSchema):
    status: str
    job_id: str
    gid: str
    self_id: str
    boss_uid: str
    boss_id: str
    security_id: str
    content: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class SearchJobItemOut(BossSchema):
    job_id: str
    security_id: str = ""
    encrypt_boss_id: str = ""
    contact: bool = False
    boss_online: bool = False
    boss_active_text: str = ""
    job_active_time: int = 0
    title: str = ""
    company: str = ""
    city: str = ""
    salary: str = ""
    experience: str = ""
    job_url: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class SearchOut(BossSchema):
    items: list[SearchJobItemOut]
    trace: dict[str, Any] = Field(default_factory=dict)
