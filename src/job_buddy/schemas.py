from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TimestampedSchema(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime


class TaskTriggerResponse(BaseModel):
    task_id: str
    status: str


class JobLeadRead(TimestampedSchema):
    source: str
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
    match_status: str
    search_count: int
    last_searched_at: datetime | None = None
    detail_fetched_at: datetime | None = None
    fetch_count_list: int = 0
    fetch_count_detail: int = 0
    detail_source_url: str | None = None
    last_seen_at: datetime
    greeted: bool
    raw_payload: dict[str, Any]
    detail_payload: dict[str, Any] = Field(default_factory=dict)
    detail_text: str | None = None


class JobLeadDetailRead(JobLeadRead):
    pass


class JobDetailResponse(BaseModel):
    cached: bool
    job: JobLeadDetailRead


class SearchJobsRequest(BaseModel):
    query: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    education: str | None = None
    scale: str | None = None
    industry: str | None = None
    stage: str | None = None
    job_type: str | None = None
    page: int = 1


class SearchJobsResponse(BaseModel):
    success: bool
    count: int
    items: list[dict[str, Any]]
    error: str | None = None
    code: str | None = None


class JobCollectionRecordRead(TimestampedSchema):
    task_id: str
    trace_id: str | None = None
    source: str
    source_job_id: str
    security_id: str | None = None
    title: str
    company: str
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    job_url: str | None = None
    raw_payload: dict[str, Any]
    collected_at: datetime


class SearchTaskRequest(BaseModel):
    query_override: dict[str, Any] = Field(default_factory=dict)


class GreetTaskRequest(BaseModel):
    source_job_ids: list[str] = Field(default_factory=list)
    greeting_message: str | None = None
    limit: int = 20


class GreetingTaskRead(TimestampedSchema):
    task_type: str
    status: str
    input_payload: dict[str, Any]
    result_summary: dict[str, Any]
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class GreetingRecordRead(TimestampedSchema):
    task_id: str
    job_lead_id: str
    source_job_id: str
    status: str
    message: str | None = None
    response_payload: dict[str, Any]


class TaskDetailResponse(BaseModel):
    task: GreetingTaskRead
    records: list[GreetingRecordRead]


class WorkerConfigUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None
    query: dict[str, Any] | None = None
    page: int | None = None
    page_max: int | None = None
    batch_size: int | None = None


class WorkerConfigRead(TimestampedSchema):
    worker_name: str
    enabled: bool
    interval_seconds: int
    next_run_at: datetime | None = None
    status: str
    last_error: str | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_result_summary: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    page: int
    page_max: int
    batch_size: int


class FriendMessageRead(BaseModel):
    message_id: str
    from_id: str
    from_name: str | None = None
    content: str
    msg_type: int | None = None
    sent_at: int | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class FriendRecordRead(TimestampedSchema):
    source: str
    gid: str
    boss_uid: str | None = None
    friend_source: int | None = None
    relation_type: int | None = None
    read_status: int | None = None
    security_id: str | None = None
    self_id: str | None = None
    source_job_id: str | None = None
    source_friend_id: str
    title: str
    name: str
    company: str | None = None
    avatar: str | None = None
    last_message: str | None = None
    unread_count: int
    last_message_at: str | None = None
    last_message_ts: float | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    messages: list[FriendMessageRead] = Field(default_factory=list)


class FriendMessagesResponse(BaseModel):
    gid: str
    source_friend_id: str
    security_id: str | None = None
    page: int
    count: int
    has_more: bool
    total: int
    messages: list[dict[str, Any]]


class SendMessagePayload(BaseModel):
    content: str


class SendMessageResponse(BaseModel):
    gid: str
    source_friend_id: str
    content: str
    status: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class FriendSyncResponse(BaseModel):
    count: int


class DoctorCheckResponse(BaseModel):
    name: str
    status: str
    detail: str
    hint: str | None = None


class DoctorErrorResponse(BaseModel):
    code: str
    message: str
    recoverable: bool | None = None
    recovery_action: str | None = None


class DoctorResponse(BaseModel):
    ok: bool
    summary: str
    data_dir: str | None = None
    checks: list[DoctorCheckResponse]
    next_actions: list[str]
    stderr: str | None = None
    exit_code: int
    error: DoctorErrorResponse | None = None


class HealthResponse(BaseModel):
    status: str
    mongodb: str
    boss_client: str


class AuthStatusResponse(BaseModel):
    logged_in: bool
    user_name: str | None = None
    city: str | None = None
    ip: str | None = None
    uid: str | None = None
    message: str


class SearchOptionsResponse(BaseModel):
    cities: list[str]
    salary_ranges: list[str]
    experience_levels: list[str]
    education_levels: list[str]
    industries: list[str]
    scales: list[str]
    stages: list[str]
    job_types: list[str]


class LogLineResponse(BaseModel):
    text: str
    level_hint: str = "info"


class LogsResponse(BaseModel):
    lines: list[LogLineResponse]
    truncated: bool
    source: str
    updated_at: datetime


class DataClearResponse(BaseModel):
    deleted_counts: dict[str, int]
    total_deleted: int
