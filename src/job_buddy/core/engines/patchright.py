from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import urlencode
from pathlib import Path
from typing import Any
from datetime import UTC, datetime

from patchright.async_api import async_playwright

from job_buddy.core.boss import BossOperationError, filter_jobs_by_welfare
from job_buddy.core.config import Settings
from job_buddy.core.engines.models import LoginRequest, LoginResult, SearchJobItem, SearchRequest, SearchResult
from job_buddy.core.zhipin_api import (
    CITY_CODES,
    EDUCATION_CODES,
    EXPERIENCE_CODES,
    INDUSTRY_CODES,
    JOB_TYPE_CODES,
    SALARY_CODES,
    SCALE_CODES,
    SEARCH_URL,
    STAGE_CODES,
    WEB_GEEK_JOB_URL,
    normalize_job,
)

DEFAULT_CONNECTION_MODE = "launch"
DEFAULT_PROFILE_DIR = "data/chrome_profile"
LOGIN_PAGE_URL = "https://www.zhipin.com/web/user/"
HOME_URL = "https://www.zhipin.com/"


class PatchrightEngine:
    name = "patchright"

    def __init__(self, settings: Settings, params: dict[str, Any] | None = None) -> None:
        self.settings = settings
        self.params = params or {}
        self.page: Any | None = None
        self.context: Any | None = None
        self.browser: Any | None = None
        self.playwright: Any | None = None
        self._connection_mode = DEFAULT_CONNECTION_MODE
        self._profile_dir = self._resolve_profile_dir()
        self._init_lock = asyncio.Lock()
        self.running = False
        self._page_cache: dict[str, Any] = {}

    @property
    def profile_dir(self) -> Path:
        return self._profile_dir

    async def init(self) -> None:
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        playwright = await async_playwright().start()
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                channel="chrome",
                headless=False,
                slow_mo=300,
                no_viewport=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            )
        except Exception as exc:
            await self._safe_stop_playwright(playwright)
            profile_hint = f"PatchrightEngine 启动浏览器失败（profile={self._profile_dir}）"
            if "Target page, context or browser has been closed" in str(exc):
                profile_hint += "，可能是同一 profile 已有 Chrome 实例占用"
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"{profile_hint}: {exc}",
                recoverable=True,
                status_code=502,
            ) from exc

        page = context.pages[0] if getattr(context, "pages", None) else await context.new_page()
        self.playwright = playwright
        self.context = context
        self.browser = getattr(context, "browser", None)
        self.page = page
        self.running = True

    async def check_page_health(self) -> None:
        if await self._is_browser_healthy():
            return

        async with self._init_lock:
            if await self._is_browser_healthy():
                return
            await self.close()
            await self.init()

    def page_to_file(self, content: str) -> None:
        output = Path("data/patchright.html")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")

    async def js2dict(self, text: str) -> Any:
        return await self.page.evaluate(
            """
            (text) => {
                return Function("return (" + text + ")")();
            }
            """,
            text,
        )

    async def is_login(self) -> bool:
        await self.page.wait_for_load_state("domcontentloaded")
        page = await self.extract_page()
        return bool(page.get("isLogin"))

    async def _extract_inline_scripts(self) -> list[str]:
        return await self.page.evaluate(
            """
                () => Array.from(document.scripts)
                    .filter(s => !s.src)
                    .map(s => s.textContent)
                """
        )

    async def extract_page(self) -> dict[str, Any]:
        inline_scripts = await self._extract_inline_scripts()
        all_text = "###".join(inline_scripts)
        matches = re.findall(r"_PAGE\s*=\s*({.*?})\s*###", all_text, re.S)
        if not matches:
            self._page_cache = {}
            return {}
        page_payload = await self.js2dict(matches[0])
        self._page_cache = page_payload if isinstance(page_payload, dict) else {}
        return self._page_cache

    async def login(self, request: LoginRequest) -> LoginResult:
        _ = request
        await self.check_page_health()
        await self.page.goto(HOME_URL, wait_until="domcontentloaded")
        if await self.is_login():
            return self._build_logged_in_result()

        try:
            await self._open_login_page(self.page)
            for _ in range(180):
                await asyncio.sleep(10)
                if await self.is_login():
                    return self._build_logged_in_result()
        except BossOperationError:
            raise
        except Exception as exc:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"PatchrightEngine 打开登录页失败: {exc}",
                recoverable=True,
                status_code=502,
            ) from exc

        return await self._build_login_result()

    async def get_auth_status(self) -> LoginResult:
        try:
            await self.check_page_health()
            await self.page.goto(HOME_URL, wait_until="domcontentloaded")
            if await self.is_login():
                return self._build_logged_in_result()
        except BossOperationError:
            raise
        except Exception:
            return await self._build_login_result()
        return await self._build_login_result()

    async def logout(self) -> LoginResult:
        raise BossOperationError(
            code="ENGINE_UNAVAILABLE",
            message="PatchrightEngine 尚未接管退出登录",
            recoverable=False,
            status_code=501,
        )

    async def search(self, request: SearchRequest) -> SearchResult:
        await self.check_page_health()
        login_status = await self.get_auth_status()
        if not login_status.logged_in:
            raise BossOperationError(
                code="AUTH_REQUIRED",
                message="未登录，请先点击页面右上角登录",
                recoverable=True,
                recovery_action="login",
                status_code=401,
            )

        trace = self._build_search_trace(request.query)
        payload = await self._search_jobs_payload(trace["request_url"])
        trace["response_received_at"] = datetime.now(tz=UTC).isoformat()
        trace["response_payload"] = payload
        if payload.get("code") not in (None, 0):
            message = str(payload.get("message") or "职位搜索失败")
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=message,
                recoverable=True,
                status_code=502,
            )

        raw_items = payload.get("zpData", {}).get("jobList", [])
        if not isinstance(raw_items, list):
            raise BossOperationError(
                code="REQUEST_FAILED",
                message="职位搜索结果格式错误",
                recoverable=True,
                status_code=502,
            )

        welfare = request.query.get("welfare")
        if welfare:
            raw_items = filter_jobs_by_welfare(
                [self._normalize_raw_job(item) for item in raw_items],
                str(welfare),
            )
            trace["result_count"] = len(raw_items)
            return SearchResult(items=[self._search_item_from_payload(item) for item in raw_items], trace=trace)

        items = [self._search_item_from_payload(self._normalize_raw_job(item)) for item in raw_items]
        trace["result_count"] = len(items)
        return SearchResult(items=items, trace=trace)

    async def healthcheck(self) -> dict[str, Any]:
        try:
            await self.check_page_health()
        except BossOperationError as exc:
            return {
                "status": "unavailable",
                "provider": self.name,
                "logged_in": False,
                "message": exc.message,
                "last_error": exc.message,
            }

        auth = await self.get_auth_status()
        return {
            "status": "ok" if auth.logged_in else "auth_required",
            "provider": self.name,
            "logged_in": auth.logged_in,
            "message": auth.message,
            "last_error": auth.last_error,
        }

    async def close(self) -> None:
        context = self.context
        playwright = self.playwright
        self.running = False
        self.context = None
        self.page = None
        self.browser = None
        self.playwright = None

        if context is not None:
            close = getattr(context, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

        await self._safe_stop_playwright(playwright)

    async def _open_login_page(self, page: Any) -> None:
        try:
            bring_to_front = getattr(page, "bring_to_front", None)
            if bring_to_front is not None:
                await bring_to_front()
            await page.goto(LOGIN_PAGE_URL, wait_until="domcontentloaded")
        except Exception as exc:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"PatchrightEngine 页面跳转失败: {exc}",
                recoverable=True,
                status_code=502,
            ) from exc

    async def _search_jobs_payload(self, request_url: str) -> dict[str, Any]:
        return await self.page.evaluate(
            """
            async ({ url, referer }) => {
                const response = await fetch(url, {
                    method: "GET",
                    credentials: "include",
                    headers: {
                        "Accept": "application/json, text/plain, */*",
                        "X-Requested-With": "XMLHttpRequest",
                        "zp_page_request_id": crypto.randomUUID(),
                    },
                    referrer: referer,
                });
                return await response.json();
            }
            """,
            {
                "url": request_url,
                "referer": WEB_GEEK_JOB_URL,
            },
        )

    def _build_search_trace(self, query: dict[str, Any]) -> dict[str, Any]:
        params = self._build_search_params(query)
        return {
            "engine": self.name,
            "browser": "Patchright Chromium",
            "requested_at": datetime.now(tz=UTC).isoformat(),
            "request_payload": dict(query),
            "request_params": params,
            "request_url": f"{SEARCH_URL}?{urlencode(params)}",
            "referer": WEB_GEEK_JOB_URL,
        }

    def _build_search_params(self, query: dict[str, Any]) -> dict[str, Any]:
        query_text = self._normalize_query_text(query)
        if not query_text:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message="搜索关键词不能为空",
                recoverable=True,
                status_code=400,
            )

        params: dict[str, Any] = {"query": query_text, "page": int(query.get("page", 1))}
        if city := query.get("city"):
            code = CITY_CODES.get(str(city))
            if code is None:
                raise BossOperationError(
                    code="REQUEST_FAILED",
                    message=f"未知城市: {city}",
                    recoverable=True,
                    status_code=400,
            )
            params["city"] = code
        if salary := query.get("salary"):
            if code := SALARY_CODES.get(str(salary)):
                params["salary"] = code
        if experience := query.get("experience"):
            if code := EXPERIENCE_CODES.get(str(experience)):
                params["experience"] = code
        if education := query.get("education"):
            if code := EDUCATION_CODES.get(str(education)):
                params["degree"] = code
        if scale := query.get("scale"):
            if code := SCALE_CODES.get(str(scale)):
                params["scale"] = code
        if industry := query.get("industry"):
            if code := INDUSTRY_CODES.get(str(industry)):
                params["industry"] = code
        if stage := query.get("stage"):
            if code := STAGE_CODES.get(str(stage)):
                params["stage"] = code
        if job_type := query.get("job_type"):
            if code := JOB_TYPE_CODES.get(str(job_type)):
                params["jobType"] = code
        return params

    def _normalize_query_text(self, query: dict[str, Any]) -> str:
        query_text = str(query.get("query") or "").strip()
        if query_text:
            return query_text

        keywords = query.get("keywords")
        if isinstance(keywords, list):
            return " ".join(str(item).strip() for item in keywords if str(item).strip())
        if keywords is None:
            return ""
        return str(keywords).strip()

    def _normalize_raw_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        return normalize_job(raw)

    def _search_item_from_payload(self, payload: dict[str, Any]) -> SearchJobItem:
        return SearchJobItem(
            job_id=str(payload["job_id"]),
            security_id=payload.get("security_id"),
            title=str(payload["title"]),
            company=str(payload["company"]),
            city=payload.get("city"),
            salary=payload.get("salary"),
            experience=payload.get("experience"),
            job_url=payload.get("job_url"),
            raw_payload=dict(payload.get("raw_payload") or payload),
        )

    async def _build_login_result(self) -> LoginResult:
        return LoginResult(
            logged_in=False,
            login_method="patchright",
            message="已通过 Patchright 启动浏览器并打开 BOSS 登录页，请在当前页面完成扫码登录",
            browser="Patchright Chromium",
        )

    def _build_logged_in_result(self) -> LoginResult:
        return LoginResult(
            logged_in=True,
            user_name=self._page_cache.get("name"),
            login_method="patchright",
            message="已登录",
            browser="Patchright Chromium",
        )

    async def _is_browser_healthy(self) -> bool:
        if not self.running or self.page is None or self.context is None or self.playwright is None:
            return False
        try:
            await self.page.evaluate("() => 1")
        except Exception:
            return False
        return True

    async def _safe_stop_playwright(self, playwright: Any | None) -> None:
        if playwright is None:
            return
        stop = getattr(playwright, "stop", None)
        if stop is None:
            return
        try:
            await stop()
        except Exception:
            pass

    def _resolve_profile_dir(self) -> Path:
        raw = os.environ.get("JOB_BUDDY_PROFILE_DIR") or self.params.get("profile_dir") or DEFAULT_PROFILE_DIR
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()
