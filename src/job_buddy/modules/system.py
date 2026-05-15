from datetime import datetime

from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.core.boss import BossAuthGateway, BossAuthStatusResult, BossDoctorRunner, CdpBrowserController
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


class CdpStatusResponse(BaseModel):
    running: bool
    port: int
    cdp_url: str
    browser: str | None = None
    websocket_url: str | None = None
    pid: int | None = None
    message: str


class BrowserControlResponse(CdpStatusResponse):
    pass


class AuthState(DocumentModel):
    provider: str = "zhipin"
    logged_in: bool = False
    user_name: str | None = None
    login_method: str | None = None
    cdp_url: str
    browser_running: bool = False
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
    cdp_running: bool
    cdp_url: str
    browser: str | None = None
    last_login_at: datetime | None = None
    last_logout_at: datetime | None = None
    message: str
    last_error: str | None = None


class SystemService:
    def __init__(
        self,
        doctor_runner: BossDoctorRunner,
        cdp_controller: CdpBrowserController,
        auth_gateway: BossAuthGateway,
        auth_states: AuthStateRepository,
    ) -> None:
        self.doctor_runner = doctor_runner
        self.cdp_controller = cdp_controller
        self.auth_gateway = auth_gateway
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

    async def get_cdp_status(self) -> CdpStatusResponse:
        status = await self.cdp_controller.get_status()
        return CdpStatusResponse(**status.__dict__)

    async def start_cdp_browser(self) -> BrowserControlResponse:
        status = await self.cdp_controller.start_browser()
        return BrowserControlResponse(**status.__dict__)

    async def stop_cdp_browser(self) -> BrowserControlResponse:
        status = await self.cdp_controller.stop_browser()
        return BrowserControlResponse(**status.__dict__)

    async def get_auth_status(self) -> AuthStatusResponse:
        cdp = await self.cdp_controller.get_status()
        local = await self.auth_gateway.get_status()
        stored = await self.auth_states.get_current()

        state = await self._sync_auth_state(local, cdp, stored)
        return self._build_auth_response(local, cdp, state)

    async def login(self, timeout: int = 120) -> AuthStatusResponse:
        await self.cdp_controller.ensure_running()
        local = await self.auth_gateway.login(timeout=timeout)
        cdp = await self.cdp_controller.get_status()
        stored = await self.auth_states.get_current()
        state = await self._sync_auth_state(local, cdp, stored, mark_login=local.logged_in)
        return self._build_auth_response(local, cdp, state)

    async def logout(self) -> AuthStatusResponse:
        await self.auth_gateway.logout()
        await self.cdp_controller.stop_managed_browser()
        self.cdp_controller.clear_profile()
        cdp = await self.cdp_controller.get_status()
        stored = await self.auth_states.get_current()
        local = BossAuthStatusResult(logged_in=False, message="已退出登录")
        state = await self._sync_auth_state(local, cdp, stored, mark_logout=True)
        return self._build_auth_response(local, cdp, state)

    async def _sync_auth_state(
        self,
        local: BossAuthStatusResult,
        cdp: CdpStatusResponse | BrowserControlResponse | object,
        stored: AuthState | None,
        *,
        mark_login: bool = False,
        mark_logout: bool = False,
    ) -> AuthState:
        current = stored or AuthState(cdp_url=self.cdp_controller.cdp_url)
        now = utc_now()

        payload = AuthState(
            id=current.id,
            provider=current.provider,
            logged_in=local.logged_in,
            user_name=local.user_name,
            login_method=local.login_method if local.logged_in else None,
            cdp_url=self.cdp_controller.cdp_url,
            browser_running=getattr(cdp, "running", False),
            last_login_at=current.last_login_at,
            last_logout_at=current.last_logout_at,
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
        local: BossAuthStatusResult,
        cdp: CdpStatusResponse | BrowserControlResponse | object,
        state: AuthState,
    ) -> AuthStatusResponse:
        return AuthStatusResponse(
            logged_in=local.logged_in,
            user_name=local.user_name or state.user_name,
            login_method=local.login_method or state.login_method,
            cdp_running=getattr(cdp, "running", False),
            cdp_url=self.cdp_controller.cdp_url,
            browser=getattr(cdp, "browser", None),
            last_login_at=state.last_login_at,
            last_logout_at=state.last_logout_at,
            message=local.message,
            last_error=local.last_error or state.last_error,
        )
