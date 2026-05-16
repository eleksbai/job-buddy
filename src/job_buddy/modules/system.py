from collections import deque
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from job_buddy.core.boss import (
    BossDoctorRunner,
    map_boss_operation_error,
)
from job_buddy.core.config import Settings
from job_buddy.core.engines.models import LoginRequest, LoginResult
from job_buddy.core.engines.runtime import EngineRuntimeManager
from job_buddy.core.zhipin_api import (
    CITY_CODES,
    EDUCATION_CODES,
    EXPERIENCE_CODES,
    INDUSTRY_CODES,
    JOB_TYPE_CODES,
    SALARY_CODES,
    SCALE_CODES,
    STAGE_CODES,
)
from job_buddy.modules.common import BaseRepository, DocumentModel, utc_now


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


class AuthState(DocumentModel):
    provider: str = "zhipin"
    logged_in: bool = False
    user_name: str | None = None
    login_method: str | None = None
    browser: str | None = None
    last_login_at: datetime | None = None
    last_logout_at: datetime | None = None
    last_error: str | None = None


class AuthStateRepository(BaseRepository[AuthState]):
    collection_name = "boss_auth_state"
    model_cls = AuthState

    async def get_current(self, provider: str = "zhipin") -> AuthState | None:
        payload = await self.collection.find_one({"provider": provider})
        if not payload:
            return None
        return self.model_cls.from_mongo(payload)

    async def upsert_current(self, state: AuthState) -> AuthState:
        existing = await self.get_current(provider=state.provider)
        payload = state.to_mongo()
        payload.pop("_id", None)
        payload["updated_at"] = utc_now()

        if existing is None:
            result = await self.collection.insert_one(payload)
            stored = await self.collection.find_one({"_id": result.inserted_id})
            return self.model_cls.from_mongo(stored)

        await self.collection.update_one({"_id": existing.to_mongo()["_id"]}, {"$set": payload})
        refreshed = await self.get(existing.id)
        if refreshed is None:
            raise RuntimeError("failed to refresh auth state")
        return refreshed


class AuthStatusResponse(BaseModel):
    logged_in: bool
    user_name: str | None = None
    login_method: str | None = None
    browser: str | None = None
    last_login_at: datetime | None = None
    last_logout_at: datetime | None = None
    message: str
    last_error: str | None = None


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


class SystemService:
    def __init__(
        self,
        doctor_runner: BossDoctorRunner,
        settings: Settings,
        runtime: EngineRuntimeManager,
        auth_states: AuthStateRepository,
    ) -> None:
        self.doctor_runner = doctor_runner
        self.settings = settings
        self.runtime = runtime
        self.auth_states = auth_states

    async def run_doctor(self) -> DoctorResponse:
        result = await self.doctor_runner.run()
        return DoctorResponse(
            ok=result.ok,
            summary=result.summary,
            data_dir=result.data_dir,
            checks=[DoctorCheckResponse(**check) for check in result.checks],
            next_actions=result.next_actions,
            stderr=result.stderr or None,
            exit_code=result.exit_code,
            error=DoctorErrorResponse(**result.error) if result.error else None,
        )

    async def get_auth_status(self) -> AuthStatusResponse:
        try:
            local = await self.runtime.get_auth_status()
        except Exception as exc:
            raise map_boss_operation_error(exc) from exc
        stored = await self.auth_states.get_current()

        state = await self._sync_auth_state(local, stored)
        return self._build_auth_response(local, state)

    async def login(self, timeout: int = 120) -> AuthStatusResponse:
        try:
            local = await self.runtime.login(LoginRequest(timeout=timeout))
        except Exception as exc:
            raise map_boss_operation_error(exc) from exc
        stored = await self.auth_states.get_current()
        state = await self._sync_auth_state(local, stored, mark_login=local.logged_in)
        return self._build_auth_response(local, state)

    async def logout(self) -> AuthStatusResponse:
        try:
            local = await self.runtime.logout()
        except Exception as exc:
            raise map_boss_operation_error(exc) from exc
        stored = await self.auth_states.get_current()
        state = await self._sync_auth_state(local, stored, mark_logout=True)
        return self._build_auth_response(local, state)

    async def get_search_options(self) -> SearchOptionsResponse:
        return SearchOptionsResponse(
            cities=sorted(CITY_CODES.keys()),
            salary_ranges=sorted(SALARY_CODES.keys()),
            experience_levels=sorted(EXPERIENCE_CODES.keys()),
            education_levels=sorted(EDUCATION_CODES.keys()),
            industries=sorted(INDUSTRY_CODES.keys()),
            scales=sorted(SCALE_CODES.keys()),
            stages=sorted(STAGE_CODES.keys()),
            job_types=sorted(JOB_TYPE_CODES.keys()),
        )

    async def get_logs(self, limit: int = 200) -> LogsResponse:
        log_file = Path(self.settings.app_log_dir).expanduser() / self.settings.app_log_file
        lines: deque[str] = deque(maxlen=limit)
        truncated = False

        if log_file.exists():
            total_lines = 0
            with log_file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    total_lines += 1
                    lines.append(line.rstrip("\n"))
            truncated = total_lines > limit

        return LogsResponse(
            lines=[LogLineResponse(text=line, level_hint=_detect_log_level(line)) for line in lines],
            truncated=truncated,
            source=log_file.name,
            updated_at=utc_now(),
        )

    async def _sync_auth_state(
        self,
        local: LoginResult,
        stored: AuthState | None,
        *,
        mark_login: bool = False,
        mark_logout: bool = False,
    ) -> AuthState:
        current = stored or AuthState()
        now = utc_now()

        payload = AuthState(
            id=current.id,
            provider=current.provider,
            logged_in=local.logged_in,
            user_name=local.user_name,
            login_method=local.login_method if local.logged_in else None,
            browser=local.browser,
            last_login_at=local.last_login_at or current.last_login_at,
            last_logout_at=local.last_logout_at or current.last_logout_at,
            last_error=local.last_error,
            created_at=current.created_at,
            updated_at=now,
        )

        if mark_login:
            payload.last_login_at = now
            payload.last_logout_at = current.last_logout_at
            payload.last_error = None
        elif mark_logout:
            payload.last_logout_at = now
            payload.last_error = None
        elif not local.logged_in:
            payload.login_method = None

        return await self.auth_states.upsert_current(payload)

    def _build_auth_response(
        self,
        local: LoginResult,
        state: AuthState,
    ) -> AuthStatusResponse:
        user_name = local.user_name if local.logged_in else None
        login_method = local.login_method if local.logged_in else None
        return AuthStatusResponse(
            logged_in=local.logged_in,
            user_name=user_name,
            login_method=login_method,
            browser=local.browser or state.browser,
            last_login_at=local.last_login_at or state.last_login_at,
            last_logout_at=local.last_logout_at or state.last_logout_at,
            message=local.message,
            last_error=local.last_error or state.last_error,
        )


def _detect_log_level(line: str) -> str:
    upper_line = line.upper()
    if " ERROR " in upper_line:
        return "error"
    if " WARNING " in upper_line or " WARN " in upper_line:
        return "warn"
    if " DEBUG " in upper_line:
        return "debug"
    return "info"
