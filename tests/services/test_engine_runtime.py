import asyncio
import json

from job_buddy.core.boss import BossOperationError
from job_buddy.core.engines.models import JobDetailRequest, LoginRequest, LoginResult, SearchJobItem, SearchResult
from job_buddy.core.engines.runtime import EngineRuntimeManager
from job_buddy.core.config import Settings


class FakeEngine:
    name = "patchright"

    def __init__(self) -> None:
        self.login_calls = 0
        self.search_calls = 0
        self.detail_calls = 0

    async def login(self, request: LoginRequest) -> LoginResult:
        _ = request
        self.login_calls += 1
        return LoginResult(logged_in=True, user_name="Alice", login_method="patchright", message="ok")

    async def get_auth_status(self) -> LoginResult:
        return LoginResult(logged_in=True, user_name="Alice", login_method="patchright", message="ok")

    async def logout(self) -> LoginResult:
        return LoginResult(logged_in=False, message="已退出登录")

    async def search(self, request) -> SearchResult:
        self.search_calls += 1
        return SearchResult(items=[SearchJobItem(job_id=request.query["query"], title="demo", company="demo")])

    async def detail(self, request) -> dict:
        self.detail_calls += 1
        return {
            "job_id": request.job_id,
            "security_id": request.security_id,
            "job_url": request.job_url,
            "detail_payload": {"job": {"title": "demo"}},
            "detail_text": "职位名称：demo",
        }

    async def healthcheck(self) -> dict:
        return {"status": "ok", "provider": self.name, "logged_in": True}

    async def close(self) -> None:
        return None


def test_runtime_uses_bound_engine_for_login_search_and_detail(tmp_path):
    config_path = tmp_path / "collector_engines.json"
    config_path.write_text(
        json.dumps(
            {
                "engines": {"patchright": {"enabled": True, "params": {}}},
                "bindings": {"login": "patchright", "search": "patchright", "detail": "patchright"},
                "retry_policy": {"login": {"max_retries": 0}, "search": {"max_retries": 0}, "detail": {"max_retries": 0}},
            }
        ),
        encoding="utf-8",
    )
    runtime = EngineRuntimeManager(Settings(COLLECTOR_CONFIG_PATH=str(config_path)))
    fake_engine = FakeEngine()
    runtime._engines["patchright"] = fake_engine

    login_result = asyncio.run(runtime.login())
    search_result = asyncio.run(runtime.search_jobs({"query": "python"}))
    detail_result = asyncio.run(
        runtime.detail(
            JobDetailRequest(
                job_id="python",
                security_id="sec-1",
                job_url="https://www.zhipin.com/job_detail/python.html?securityId=sec-1",
            )
        )
    )

    assert login_result.logged_in is True
    assert fake_engine.login_calls == 1
    assert fake_engine.search_calls == 1
    assert fake_engine.detail_calls == 1
    assert search_result == [
        {
            "job_id": "python",
            "security_id": None,
            "title": "demo",
            "company": "demo",
            "city": None,
            "salary": None,
            "experience": None,
            "job_url": None,
            "raw_payload": {},
        }
    ]
    assert detail_result["job_id"] == "python"
    assert detail_result["security_id"] == "sec-1"


def test_runtime_marks_state_after_token_invalid_failure(tmp_path):
    config_path = tmp_path / "collector_engines.json"
    config_path.write_text(
        json.dumps(
            {
                "engines": {"patchright": {"enabled": True, "params": {}}},
                "bindings": {"login": "patchright", "search": "patchright"},
                "retry_policy": {"login": {"max_retries": 0}, "search": {"max_retries": 0}, "detail": {"max_retries": 0}},
            }
        ),
        encoding="utf-8",
    )
    runtime = EngineRuntimeManager(Settings(COLLECTOR_CONFIG_PATH=str(config_path)))

    class FailingEngine(FakeEngine):
        async def login(self, request: LoginRequest) -> LoginResult:
            _ = request
            raise BossOperationError(code="TOKEN_INVALID", message="登录态无效", status_code=401)

    runtime._engines["patchright"] = FailingEngine()

    try:
        asyncio.run(runtime.login())
    except BossOperationError as exc:
        assert exc.code == "TOKEN_INVALID"
    else:
        raise AssertionError("expected BossOperationError")

    state = runtime.state_for("patchright")
    assert state.logged_in is False
    assert state.token_valid is False
    assert state.cookie_valid is False
    assert state.last_error == "登录态无效"
    assert state.retry_count == 1


def test_runtime_defaults_login_and_search_to_patchright_when_config_missing(tmp_path, monkeypatch):
    runtime = EngineRuntimeManager(Settings(COLLECTOR_CONFIG_PATH=str(tmp_path / "missing.json")))

    class PatchrightLoginEngine(FakeEngine):
        name = "patchright"

    login_engine = PatchrightLoginEngine()
    runtime._engines["patchright"] = login_engine

    login_result = asyncio.run(runtime.login())
    search_result = asyncio.run(runtime.search_jobs({"query": "python"}))

    assert login_result.logged_in is True
    assert login_engine.login_calls == 1
    assert login_engine.search_calls == 1
    assert login_engine.detail_calls == 0
    assert search_result[0]["job_id"] == "python"
