import asyncio

from job_buddy.core.boss import BossDoctorResult, CdpStatusResult
from job_buddy.modules.system import SystemService


class FakeDoctorRunner:
    async def run(self) -> BossDoctorResult:
        return BossDoctorResult(
            ok=True,
            summary="healthy",
            data_dir="/tmp/boss",
            checks=[{"name": "python", "status": "ok", "detail": "Python 3.13", "hint": None}],
            next_actions=["boss status"],
            stderr="",
            exit_code=0,
            error=None,
        )


class FakeCdpController:
    async def get_status(self) -> CdpStatusResult:
        return CdpStatusResult(
            running=True,
            port=9222,
            cdp_url="http://127.0.0.1:9222",
            browser="Chrome",
            websocket_url="ws://127.0.0.1:9222/devtools/browser/demo",
            pid=1234,
            message="CDP 在线",
        )

    async def start_browser(self) -> CdpStatusResult:
        return await self.get_status()

    async def stop_browser(self) -> CdpStatusResult:
        return CdpStatusResult(
            running=False,
            port=9222,
            cdp_url="http://127.0.0.1:9222",
            message="浏览器已关闭",
        )


def test_run_doctor_returns_structured_response():
    service = SystemService(FakeDoctorRunner(), FakeCdpController())

    result = asyncio.run(service.run_doctor())

    assert result.ok is True
    assert result.summary == "healthy"
    assert result.checks[0].name == "python"


def test_get_cdp_status_returns_structured_response():
    service = SystemService(FakeDoctorRunner(), FakeCdpController())

    result = asyncio.run(service.get_cdp_status())

    assert result.running is True
    assert result.port == 9222
