from datetime import datetime

import pytest
from fastapi import FastAPI

from job_buddy.deps import get_system_service
from job_buddy.modules.system import (
    AuthStatusResponse,
    DoctorCheckResponse,
    DoctorResponse,
    LogsResponse,
    LogLineResponse,
    SearchOptionsResponse,
)
from job_buddy.routers import build_api_router
from tests.api._client import api_client


class FakeSystemService:
    async def run_doctor(self) -> DoctorResponse:
        return DoctorResponse(
            ok=True,
            summary="healthy",
            data_dir="/tmp/boss",
            checks=[DoctorCheckResponse(name="python", status="ok", detail="Python 3.13")],
            next_actions=["确认已登录 BOSS 直聘后再执行搜索"],
            stderr=None,
            exit_code=0,
            error=None,
        )

    async def get_auth_status(self) -> AuthStatusResponse:
        return AuthStatusResponse(
            logged_in=True,
            user_name="Alice",
            login_method="patchright",
            browser="Patchright Chromium",
            last_login_at=None,
            last_logout_at=None,
            message="已登录",
            last_error=None,
        )

    async def login(self, timeout: int = 120) -> AuthStatusResponse:
        _ = timeout
        return await self.get_auth_status()

    async def logout(self) -> AuthStatusResponse:
        return AuthStatusResponse(
            logged_in=False,
            user_name=None,
            login_method=None,
            browser=None,
            last_login_at=None,
            last_logout_at=None,
            message="已退出登录",
            last_error=None,
        )

    async def get_search_options(self) -> SearchOptionsResponse:
        return SearchOptionsResponse(
            cities=["上海", "北京"],
            salary_ranges=["20-30K"],
            experience_levels=["3-5年"],
            education_levels=["本科"],
            industries=["互联网"],
            scales=["100-499人"],
            stages=["A轮"],
            job_types=["全职"],
        )

    async def get_logs(self, limit: int = 200) -> LogsResponse:
        _ = limit
        return LogsResponse(
            lines=[
                LogLineResponse(text="2026-05-16 21:00:00 INFO [app.py:1] ready", level_hint="info"),
                LogLineResponse(text="2026-05-16 21:00:01 ERROR [app.py:2] failed", level_hint="error"),
            ],
            truncated=False,
            source="job-buddy.log",
            updated_at=datetime.fromisoformat("2026-05-16T21:00:01+08:00"),
        )


@pytest.mark.asyncio
async def test_run_boss_doctor():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    async with api_client(app) as client:
        response = await client.get("/api/system/doctor")

    assert response.status_code == 200
    assert response.json()["summary"] == "healthy"


@pytest.mark.asyncio
async def test_get_auth_status():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    async with api_client(app) as client:
        response = await client.get("/api/system/auth")

    assert response.status_code == 200
    assert response.json()["logged_in"] is True
    assert response.json()["user_name"] == "Alice"


@pytest.mark.asyncio
async def test_logout_auth():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    async with api_client(app) as client:
        response = await client.post("/api/system/auth/logout")

    assert response.status_code == 200
    assert response.json()["logged_in"] is False


@pytest.mark.asyncio
async def test_login_auth():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    async with api_client(app) as client:
        response = await client.post("/api/system/auth/login")

    assert response.status_code == 200
    assert response.json()["login_method"] == "patchright"


@pytest.mark.asyncio
async def test_get_search_options():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    async with api_client(app) as client:
        response = await client.get("/api/system/search-options")

    assert response.status_code == 200
    assert "上海" in response.json()["cities"]


@pytest.mark.asyncio
async def test_get_logs():
    app = FastAPI()
    app.include_router(build_api_router())
    app.dependency_overrides[get_system_service] = lambda: FakeSystemService()

    async with api_client(app) as client:
        response = await client.get("/api/system/logs?limit=50")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "job-buddy.log"
    assert payload["lines"][1]["level_hint"] == "error"
