from pydantic import BaseModel

from job_buddy.core.boss import BossDoctorRunner, CdpBrowserController


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


class SystemService:
    def __init__(self, doctor_runner: BossDoctorRunner, cdp_controller: CdpBrowserController) -> None:
        self.doctor_runner = doctor_runner
        self.cdp_controller = cdp_controller

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
