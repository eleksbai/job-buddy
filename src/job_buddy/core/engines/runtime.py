from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from job_buddy.core.boss import BossOperationError, map_boss_operation_error
from job_buddy.core.config import Settings
from job_buddy.core.engines.models import (
    ChatHistoryRequest,
    EngineConfig,
    EngineState,
    FriendListRequest,
    JobDetailRequest,
    LoginRequest,
    LoginResult,
    SearchRequest,
    SearchResult,
)
from job_buddy.core.engines.patchright import PatchrightEngine


class EngineRuntimeManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._config = self._load_config()
        self._bindings = dict(self._config.get("bindings", {}))
        self._retry_policy = dict(self._config.get("retry_policy", {}))
        self._engine_configs = {
            name: EngineConfig(
                name=name,
                enabled=bool(payload.get("enabled", True)),
                params=dict(payload.get("params", {})),
            )
            for name, payload in self._config.get("engines", {}).items()
        }
        self._engines: dict[str, Any] = {}
        self._states: dict[str, EngineState] = {}

    async def login(self, request: LoginRequest | None = None) -> LoginResult:
        result = await self._execute("login", request or LoginRequest(), "login")
        assert isinstance(result, LoginResult)
        return result

    async def get_auth_status(self) -> LoginResult:
        result = await self._execute("login", None, "get_auth_status")
        assert isinstance(result, LoginResult)
        return result

    async def logout(self) -> LoginResult:
        result = await self._execute("login", None, "logout")
        assert isinstance(result, LoginResult)
        return result

    async def search_jobs(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        result = await self.search(SearchRequest(query=query))
        return [asdict(item) for item in result.items]

    async def search(self, request: SearchRequest) -> SearchResult:
        result = await self._execute("search", request, "search")
        assert isinstance(result, SearchResult)
        return result

    async def detail(self, request: JobDetailRequest) -> dict[str, Any]:
        result = await self._execute("detail", request, "detail")
        assert isinstance(result, dict)
        return result

    async def healthcheck(self) -> dict[str, Any]:
        engine = self._get_engine(self._binding_for("search"))
        try:
            result = await engine.healthcheck()
        except Exception as exc:
            mapped = map_boss_operation_error(exc)
            self._mark_failure(engine.name, mapped)
            raise mapped from exc
        self._mark_health(engine.name, result)
        return result

    async def greet_job(self, job: dict[str, Any], message: str | None = None) -> dict[str, Any]:
        _ = job, message
        raise BossOperationError(
            code="ENGINE_UNAVAILABLE",
            message="当前运行时未实现发送消息能力",
            recoverable=False,
            status_code=501,
        )

    async def list_friends(self, page: int = 1) -> list[dict[str, Any]]:
        result = await self._execute("friend_list", FriendListRequest(page=page), "friend_list")
        assert isinstance(result, list)
        return result

    async def get_chat_history(self, gid: str, security_id: str, page: int = 1, count: int = 20) -> dict[str, Any]:
        result = await self._execute("chat_history", ChatHistoryRequest(gid=gid, security_id=security_id, page=page, count=count), "chat_history")
        assert isinstance(result, dict)
        return result

    async def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.list_friends(page=1)[:limit]

    async def close(self) -> None:
        for engine in self._engines.values():
            close = getattr(engine, "close", None)
            if close is not None:
                await close()

    def state_for(self, engine_name: str) -> EngineState:
        return self._states.setdefault(engine_name, EngineState())

    async def _execute(self, capability: str, payload: Any, method_name: str) -> Any:
        engine = self._get_engine(self._binding_for(capability))
        retries = int(self._retry_policy.get(capability, {}).get("max_retries", 0))

        for attempt in range(retries + 1):
            try:
                method = getattr(engine, method_name)
                result = await method() if payload is None else await method(payload)
                self._mark_success(engine.name, result)
                return result
            except Exception as exc:
                mapped = map_boss_operation_error(exc)
                self._mark_failure(engine.name, mapped)
                if attempt >= retries:
                    raise mapped from exc

        raise BossOperationError(
            code="REQUEST_FAILED",
            message=f"{capability} 执行失败",
            recoverable=True,
            status_code=502,
        )

    def _binding_for(self, capability: str) -> str:
        engine_name = self._bindings.get(capability)
        if not engine_name:
            raise BossOperationError(
                code="ENGINE_UNAVAILABLE",
                message=f"未配置能力 {capability} 对应的采集引擎",
                recoverable=False,
                status_code=500,
            )
        return str(engine_name)

    def _get_engine(self, engine_name: str) -> Any:
        config = self._engine_configs.get(engine_name)
        if config is None:
            raise BossOperationError(
                code="ENGINE_UNAVAILABLE",
                message=f"未找到采集引擎配置: {engine_name}",
                recoverable=False,
                status_code=500,
            )
        if not config.enabled:
            raise BossOperationError(
                code="ENGINE_UNAVAILABLE",
                message=f"采集引擎已禁用: {engine_name}",
                recoverable=False,
                status_code=500,
            )
        if engine_name not in self._engines:
            if engine_name == "patchright":
                self._engines[engine_name] = PatchrightEngine(self.settings, config.params)
            else:
                raise BossOperationError(
                    code="ENGINE_UNAVAILABLE",
                    message=f"未知采集引擎: {engine_name}",
                    recoverable=False,
                    status_code=500,
                )
        return self._engines[engine_name]

    def _mark_success(self, engine_name: str, result: Any) -> None:
        state = self.state_for(engine_name)
        logged_in: bool | None = None
        if isinstance(result, LoginResult):
            logged_in = result.logged_in
        state.mark_success(logged_in=logged_in)

    def _mark_failure(self, engine_name: str, exc: BossOperationError) -> None:
        state = self.state_for(engine_name)
        state.retry_count += 1
        state.last_error = exc.message
        if exc.code in {"AUTH_REQUIRED", "TOKEN_INVALID"}:
            state.logged_in = False
            state.token_valid = False
            state.cookie_valid = False
        if exc.code == "COOKIE_INVALID":
            state.cookie_valid = False
        if exc.code == "ANTI_BOT_BLOCKED":
            state.anti_bot_detected = True

    def _mark_health(self, engine_name: str, payload: dict[str, Any]) -> None:
        state = self.state_for(engine_name)
        logged_in = bool(payload.get("logged_in"))
        if payload.get("status") == "ok":
            state.mark_success(logged_in=logged_in)
        else:
            state.logged_in = logged_in
            state.last_error = payload.get("last_error")
            if payload.get("status") == "auth_required":
                state.token_valid = False
                state.cookie_valid = False

    def _load_config(self) -> dict[str, Any]:
        path = Path(self.settings.collector_config_path).expanduser()
        if not path.is_absolute():
            path = self.settings.project_root / path
        if not path.exists():
            return {
                "engines": {
                    "patchright": {"enabled": True, "params": {}},
                },
                "bindings": {"login": "patchright", "search": "patchright", "detail": "patchright"},
                "retry_policy": {"login": {"max_retries": 0}, "search": {"max_retries": 0}, "detail": {"max_retries": 0}},
            }
        return json.loads(path.read_text(encoding="utf-8"))


def build_engine_runtime(settings: Settings) -> EngineRuntimeManager:
    return EngineRuntimeManager(settings)
