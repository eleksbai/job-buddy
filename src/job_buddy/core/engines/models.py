from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
class FriendListRequest:
    page: int = 1


@dataclass
class ChatHistoryRequest:
    boss_id: str
    security_id: str
    page: int = 1
    count: int = 20


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


@dataclass
class EngineState:
    logged_in: bool = False
    token_valid: bool | None = None
    cookie_valid: bool | None = None
    anti_bot_detected: bool = False
    last_error: str | None = None
    last_success_at: datetime | None = None
    retry_count: int = 0

    def mark_success(self, *, logged_in: bool | None = None) -> None:
        if logged_in is not None:
            self.logged_in = logged_in
            self.token_valid = logged_in
            self.cookie_valid = logged_in
        self.anti_bot_detected = False
        self.last_error = None
        self.retry_count = 0
        self.last_success_at = datetime.now(tz=UTC)


@dataclass
class EngineConfig:
    name: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)
