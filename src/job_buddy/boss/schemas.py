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
    user_name: str | None = None
    login_method: str | None = None
    message: str = ""
    last_error: str | None = None
    browser: str | None = None
    last_login_at: datetime | None = None
    last_logout_at: datetime | None = None


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
    message: str | None = None


class FriendListIn(BossSchema):
    page: int = 1


class ChatHistoryIn(BossSchema):
    boss_id: str
    security_id: str
    page: int = 1
    count: int = 20


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


class SearchJobItemOut(BossSchema):
    job_id: str
    security_id: str | None = None
    encrypt_boss_id: str | None = None
    contact: bool | None = None
    title: str = ""
    company: str = ""
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class SearchOut(BossSchema):
    items: list[SearchJobItemOut]
    trace: dict[str, Any] = Field(default_factory=dict)
