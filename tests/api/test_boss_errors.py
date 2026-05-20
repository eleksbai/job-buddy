import pytest
from fastapi import FastAPI

from job_buddy.boss import BossOperationError
from job_buddy.deps import get_friend_service, get_system_service
from job_buddy.main import register_exception_handlers
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FailingFriendService:
    async def sync_friends(self) -> int:
        raise BossOperationError(
            code="AUTH_REQUIRED",
            message="未登录，请先点击页面右上角登录",
            recoverable=True,
            recovery_action="login",
            status_code=401,
        )


class FailingSystemService:
    async def login(self, timeout: int = 120):
        _ = timeout
        raise BossOperationError(
            code="ANTI_BOT_BLOCKED",
            message="BOSS 直聘风控拦截",
            recoverable=False,
            recovery_action="联系 BOSS 直聘客服解除风控限制",
            status_code=409,
        )


@pytest.mark.asyncio
async def test_sync_friends_returns_structured_auth_error():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_api_router())
    app.dependency_overrides[get_friend_service] = lambda: FailingFriendService()

    async with api_client(app) as client:
        response = await client.post("/boss/friends/sync")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "未登录，请先点击页面右上角登录",
        "code": "AUTH_REQUIRED",
        "recoverable": True,
        "recovery_action": "login",
    }


@pytest.mark.asyncio
async def test_login_auth_returns_structured_account_risk_error():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FailingSystemService()

    async with api_client(app) as client:
        response = await client.post("/boss/system/auth/login")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "BOSS 直聘风控拦截",
        "code": "ANTI_BOT_BLOCKED",
        "recoverable": False,
        "recovery_action": "联系 BOSS 直聘客服解除风控限制",
    }


@pytest.mark.asyncio
async def test_boss_error_handler_logs_raw_message(caplog):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FailingSystemService()

    with caplog.at_level("ERROR"):
        async with api_client(app) as client:
            response = await client.post("/boss/system/auth/login")

    assert response.status_code == 409
    assert "Boss operation failed on POST /boss/system/auth/login" in caplog.text
    assert "BOSS 直聘风控拦截" in caplog.text


@pytest.mark.asyncio
async def test_boss_error_handler_logs_underlying_traceback(caplog):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        try:
            raise RuntimeError("browser closed")
        except RuntimeError as cause:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message="BOSS 请求失败: browser closed\nCall log:\n- browser launch",
                recoverable=True,
                recovery_action="retry",
                status_code=502,
            ) from cause

    with caplog.at_level("ERROR"):
        async with api_client(app) as client:
            response = await client.get("/boom")

    assert response.status_code == 502
    assert "BOSS 请求失败: browser closed" in caplog.text
    assert "Call log:" in caplog.text
    assert "RuntimeError: browser closed" in caplog.text
