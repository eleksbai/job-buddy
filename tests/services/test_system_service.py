import asyncio

from job_buddy.core.boss import BossDoctorResult
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


def test_run_doctor_returns_structured_response():
    service = SystemService(FakeDoctorRunner())

    result = asyncio.run(service.run_doctor())

    assert result.ok is True
    assert result.summary == "healthy"
    assert result.checks[0].name == "python"
