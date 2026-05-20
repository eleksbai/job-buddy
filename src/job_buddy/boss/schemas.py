from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LoginRequest:
    timeout: int = 120


@dataclass
class LoginResult:
    logged_in: bool
    user_name: str | None = None
    login_method: str | None = None
    message: str = ""
    last_error: str | None = None
    browser: str | None = None
    last_login_at: datetime | None = None
    last_logout_at: datetime | None = None


@dataclass
class SearchRequest:
    query: dict[str, Any]


@dataclass
class JobDetailRequest:
    job_id: str
    security_id: str | None = None
    job_url: str | None = None
    title: str | None = None
    company: str | None = None


@dataclass
class GreetJobRequest:
    job_id: str
    security_id: str
    message: str | None = None


@dataclass
class FriendListRequest:
    page: int = 1


@dataclass
class ChatHistoryRequest:
    boss_id: str
    security_id: str
    page: int = 1
    count: int = 20


@dataclass
class SendMessageRequest:
    job_id: str
    gid: str
    self_id: str
    boss_uid: str
    boss_id: str
    security_id: str | None
    content: str
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchJobItem:
    job_id: str
    security_id: str | None = None
    title: str = ""
    company: str = ""
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    items: list[SearchJobItem]
    trace: dict[str, Any] = field(default_factory=dict)
