from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlparse
from typing import Any, Dict

from patchright.async_api import async_playwright

from job_buddy.boss.config import (
    BASE_URL,
    CHAT_HISTORY_URL,
    CITY_CODES,
    DETAIL_URL,
    EDUCATION_CODES,
    EXPERIENCE_CODES,
    FRIEND_LIST_URL,
    GREET_URL,
    INDUSTRY_CODES,
    JOB_TYPE_CODES,
    SALARY_CODES,
    SCALE_CODES,
    SEARCH_URL,
    STAGE_CODES,
    WEB_GEEK_CHAT_URL,
    WEB_GEEK_JOB_URL,
)
from job_buddy.boss.exceptions import BossOperationError
from job_buddy.boss.schemas import (
    ChatHistoryIn,
    ChatHistoryMessageOut,
    ChatHistoryOut,
    FriendListIn,
    FriendListItemOut,
    GreetJobIn,
    GreetJobOut,
    HealthcheckOut,
    JobDetailIn,
    JobDetailBossOut,
    JobDetailCompanyOut,
    JobDetailJobOut,
    JobDetailOut,
    JobDetailPayloadOut,
    LoginIn,
    LoginOut,
    SearchIn,
    SearchJobItemOut,
    SearchOut,
    SendMessageIn,
    SendMessageOut,
)
from job_buddy.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_CONNECTION_MODE = "launch"
DEFAULT_PROFILE_DIR = "data/chrome_profile"
LOGIN_PAGE_URL = "https://www.zhipin.com/web/user/"
HOME_URL = "https://www.zhipin.com/"


def _build_job_url(job_id: str | None, security_id: str | None = None) -> str | None:
    if not job_id:
        return None
    url = f"{BASE_URL}/job_detail/{job_id}.html"
    if security_id:
        return f"{url}?securityId={security_id}"
    return url


def _build_job_detail_url(security_id: str | None) -> str | None:
    if not security_id:
        return None
    return f"{DETAIL_URL}?securityId={security_id}"


def _normalize_job(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        job_id = str(raw["encryptJobId"])
    except KeyError as exc:
        logger.error(
            "BOSS payload field missing: scene=search field=encryptJobId payload=%s",
            raw,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise BossOperationError(
            code="REQUEST_FAILED",
            message="BOSS 返回字段缺失: encryptJobId",
            recoverable=True,
            status_code=502,
            boss_side=False,
        ) from exc
    security_id = str(raw.get("securityId") or "") or None
    encrypt_boss_id = str(raw.get("encryptBossId") or "") or None
    contact = raw.get("contact") if isinstance(raw.get("contact"), bool) else None
    boss_online = raw.get("bossOnline") if isinstance(raw.get("bossOnline"), bool) else None
    boss_active_text = str(raw.get("activeTimeDesc") or "") or None
    job_active_time = raw.get("activeTime")
    if job_active_time is not None:
        try:
            job_active_time = int(job_active_time)
        except (TypeError, ValueError):
            job_active_time = None
    return {
        "job_id": job_id,
        "security_id": security_id,
        "encrypt_boss_id": encrypt_boss_id,
        "contact": contact,
        "boss_online": boss_online,
        "boss_active_text": boss_active_text,
        "job_active_time": job_active_time,
        "title": str(raw.get("jobName") or ""),
        "company": str(raw.get("brandName") or ""),
        "city": raw.get("cityName"),
        "salary": raw.get("salaryDesc"),
        "experience": raw.get("jobExperience"),
        "job_url": raw.get("jobUrl") or _build_job_url(job_id, security_id),
        "raw_payload": raw,
    }


def _normalize_job_detail(raw: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw)
    try:
        zp_data = payload["zpData"]
        if not isinstance(zp_data, dict):
            raise TypeError("zpData is not a dict")
        job_info_raw = zp_data["jobInfo"]
        if not isinstance(job_info_raw, dict):
            raise TypeError("jobInfo is not a dict")
        job_id = str(job_info_raw["encryptId"])
    except (KeyError, TypeError) as exc:
        field_path = "zpData.jobInfo.encryptId"
        if isinstance(exc, KeyError):
            missing_key = exc.args[0]
            if missing_key == "zpData":
                field_path = "zpData"
            elif missing_key == "jobInfo":
                field_path = "zpData.jobInfo"
            elif missing_key == "encryptId":
                field_path = "zpData.jobInfo.encryptId"
        elif isinstance(exc, TypeError) and "zpData" in str(exc):
            field_path = "zpData"
        logger.error(
            "BOSS payload field missing: scene=detail field=%s payload=%s",
            field_path,
            payload,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise BossOperationError(
            code="REQUEST_FAILED",
            message=f"BOSS 返回字段缺失: {field_path}",
            recoverable=True,
            status_code=502,
            boss_side=False,
        ) from exc
    job_info = dict(job_info_raw)
    brand_info = dict(zp_data.get("brandComInfo") or {})
    boss_info = dict(zp_data.get("bossInfo") or {})
    fallback = dict(fallback or {})
    relation_info = dict(zp_data.get("relationInfo") or {})

    security_id = str(job_info.get("securityId") or fallback.get("security_id") or "") or None
    encrypt_boss_id = str(
        boss_info.get("encryptBossId")
        or payload.get("encryptBossId")
        or fallback.get("encrypt_boss_id")
        or ""
    ) or None
    contact = relation_info.get("beFriend")
    if not isinstance(contact, bool):
        contact = fallback.get("contact")
    boss_online = boss_info.get("bossOnline")
    if not isinstance(boss_online, bool):
        boss_online = fallback.get("boss_online")
    boss_active_text = str(boss_info.get("activeTimeDesc") or fallback.get("boss_active_text") or "") or None
    job_active_time = brand_info.get("activeTime")
    if job_active_time is None:
        job_active_time = fallback.get("job_active_time")
    if job_active_time is not None:
        try:
            job_active_time = int(job_active_time)
        except (TypeError, ValueError):
            job_active_time = None
    job_url = _build_job_url(job_id, security_id) or fallback.get("job_url")

    job = {
        "job_id": job_id,
        "security_id": security_id,
        "title": str(job_info.get("jobName") or fallback.get("title") or ""),
        "salary": str(job_info.get("salaryDesc") or fallback.get("salary") or "") or None,
        "experience": str(job_info.get("experienceName") or job_info.get("jobExperience") or fallback.get(
            "experience") or "") or None,
        "degree": str(job_info.get("degreeName") or job_info.get("jobDegree") or "") or None,
        "city": str(job_info.get("locationName") or fallback.get("city") or "") or None,
        "address": str(job_info.get("address") or "") or None,
        "skills": list(job_info.get("showSkills") or job_info.get("skills") or []),
        "description": str(job_info.get("postDescription") or job_info.get("description") or "") or None,
        "status": str(job_info.get("jobStatusDesc") or "") or None,
        "job_url": job_url,
    }
    company = {
        "name": str(brand_info.get("brandName") or fallback.get("company") or ""),
        "stage": str(brand_info.get("stageName") or brand_info.get("brandStageName") or "") or None,
        "scale": str(brand_info.get("scaleName") or brand_info.get("brandScaleName") or "") or None,
        "industry": str(brand_info.get("industryName") or brand_info.get("brandIndustry") or "") or None,
        "intro": str(brand_info.get("introduce") or brand_info.get("companyDesc") or "") or None,
    }
    boss = {
        "name": str(boss_info.get("name") or boss_info.get("bossName") or "") or None,
        "title": str(boss_info.get("title") or boss_info.get("bossTitle") or "") or None,
        "online": boss_online,
        "active_text": boss_active_text,
    }
    job["active_time"] = job_active_time

    detail_text_parts = []
    for label, value in [
        ("职位名称", job.get("title")),
        ("薪资", job.get("salary")),
        ("经验", job.get("experience")),
        ("学历", job.get("degree")),
        ("城市", job.get("city")),
        ("地址", job.get("address")),
        ("职位状态", job.get("status")),
        ("技能", "、".join(job["skills"]) if job["skills"] else None),
        ("公司", company.get("name")),
        ("公司阶段", company.get("stage")),
        ("公司规模", company.get("scale")),
        ("行业", company.get("industry")),
        ("BOSS", boss.get("name")),
        ("BOSS 职位", boss.get("title")),
        ("BOSS 活跃", boss.get("active_text")),
        ("职位描述", job.get("description")),
        ("公司介绍", company.get("intro")),
    ]:
        if value:
            detail_text_parts.append(f"{label}：{value}")

    return {
        "job_id": job_id,
        "security_id": security_id,
        "encrypt_boss_id": encrypt_boss_id,
        "contact": contact,
        "boss_online": boss_online,
        "boss_active_text": boss_active_text,
        "job_active_time": job_active_time,
        "job_url": job_url,
        "detail_payload": {
            "job": job,
            "company": company,
            "boss": boss,
            "raw_payload": payload,
        },
        "detail_text": "\n".join(detail_text_parts),
        "detail_raw_payload": payload,
    }


def normalize_search_query(
        query: dict[str, Any],
        *,
        city_codes: dict[str, str],
        salary_codes: dict[str, str],
        experience_codes: dict[str, str],
        education_codes: dict[str, str],
        industry_codes: dict[str, str],
        scale_codes: dict[str, str],
        stage_codes: dict[str, str],
        job_type_codes: dict[str, str],
) -> dict[str, Any]:
    normalized = dict(query)
    normalized["query"] = _normalize_query_text(query)
    if not normalized["query"]:
        raise ValueError("搜索关键词不能为空")

    normalized["city"] = _validate_enum_param("city", query.get("city"), city_codes)
    normalized["salary"] = _validate_enum_param("salary", query.get("salary"), salary_codes)
    normalized["experience"] = _validate_enum_param("experience", query.get("experience"), experience_codes)
    normalized["education"] = _validate_enum_param("education", query.get("education"), education_codes)
    normalized["industry"] = _validate_enum_param("industry", query.get("industry"), industry_codes)
    normalized["scale"] = _validate_enum_param("scale", query.get("scale"), scale_codes)
    normalized["stage"] = _validate_enum_param("stage", query.get("stage"), stage_codes)
    normalized["job_type"] = _validate_enum_param("job_type", query.get("job_type"), job_type_codes)
    normalized["welfare"] = _normalize_optional_string(query.get("welfare"))
    normalized["page"] = _normalize_page(query.get("page"))
    return normalized


def filter_jobs_by_welfare(items: list[dict[str, Any]], welfare: str) -> list[dict[str, Any]]:
    labels = [item.strip() for item in welfare.split(",") if item.strip()]
    if not labels:
        return items

    filtered: list[dict[str, Any]] = []
    for item in items:
        raw_payload = item.get("raw_payload", {})
        welfare_list = raw_payload.get("welfareList", []) if isinstance(raw_payload, dict) else []
        if all(label in welfare_list for label in labels):
            filtered.append(item)
    return filtered


@dataclass
class BossDoctorResult:
    ok: bool
    summary: str
    data_dir: str | None
    checks: list[dict]
    next_actions: list[str]
    stderr: str
    exit_code: int
    error: dict | None = None


class BossDoctorRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(self) -> BossDoctorResult:
        data_dir = (self.settings.project_root / "data").resolve()
        profile_dir = Path(self.settings.boss_profile_dir).expanduser()
        if not profile_dir.is_absolute():
            profile_dir = (self.settings.project_root / profile_dir).resolve()
        checks = [
            {"name": "patchright", "status": "ok", "detail": "使用 Patchright 驱动 BOSS 页面", "hint": None},
            {"name": "data_dir", "status": "ok", "detail": str(data_dir), "hint": None},
            {"name": "profile_dir", "status": "ok", "detail": str(profile_dir),
             "hint": "如需隔离浏览器环境可调整 JOB_BUDDY_PROFILE_DIR"},
        ]
        return BossDoctorResult(
            ok=True,
            summary="healthy",
            data_dir=str(data_dir),
            checks=checks,
            next_actions=["确认已登录 BOSS 直聘后再执行搜索"],
            stderr="",
            exit_code=0,
            error=None,
        )


def _find_text_in_body(body: dict) -> str:
    """递归搜索 body 下的第一个 text 字段。"""
    if not isinstance(body, dict):
        return ""
    for key, value in body.items():
        if key == "text" and isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            found = _find_text_in_body(value)
            if found:
                return found
    return ""


def _extract_message_content(m: dict) -> str:
    """从 BOSS 消息 payload 提取可显示的文本内容。"""
    body = m.get("body")
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        # 优先递归查找 body 下的 text 字段
        text = _find_text_in_body(body)
        if text:
            return text
        # 招呼消息 (type=8): 包含 jobDesc.content
        job_desc = body.get("jobDesc") or {}
        if isinstance(job_desc, dict):
            return str(job_desc.get("content") or body.get("headTitle") or "")
        return str(body.get("headTitle") or "")
    return ""


class BossClient:
    name = "bossclient"

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
            profile_hint = f"BossClient 启动浏览器失败（profile={self._profile_dir}）"
            if "Target page, context or browser has been closed" in str(exc):
                profile_hint += "，可能是同一 profile 已有 Chrome 实例占用"
            logger.error(
                "BossClient init failed: profile=%s",
                self._profile_dir,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
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

        await self.page.goto(HOME_URL, wait_until="domcontentloaded")

    async def check_page_health(self) -> None:
        if await self._is_browser_healthy():
            return

        async with self._init_lock:
            if await self._is_browser_healthy():
                return
            await self.close()
            await self.init()

    async def save_page_to_file(self, filename: str = "patchright.html") -> None:
        output = Path("data") / filename
        content = await self.page.content()
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

    async def _extract_inline_scripts(self) -> list[str]:
        return await self.page.evaluate(
            """
                () => Array.from(document.scripts)
                    .filter(s => !s.src)
                    .map(s => s.textContent)
                """
        )

    async def extract_page(self) -> LoginOut:
        inline_scripts = await self._extract_inline_scripts()
        all_text = "###".join(inline_scripts)
        matches = re.findall(r"_PAGE\s*=\s*({.*?})\s*###", all_text, re.S)
        if not matches:
            logger.error("未提取到登录信息")
            raise BossOperationError(code="500", message="未提取到登录信息")
        page_payload = await self.js2dict(matches[0])
        return LoginOut(
            logged_in=bool(page_payload.get("isLogin")),
            user_name=str(page_payload.get("name") or ""),
            city=str(page_payload.get("citySiteName") or ""),
            uid=str(page_payload.get("uid") or ""),
            ip=str(page_payload.get("clientIP") or ""),
        )

    async def login(self, request: LoginIn) -> LoginOut:
        timeout = max(1, int(request.timeout))
        await self.check_page_health()
        await self.page.goto(HOME_URL, wait_until="domcontentloaded")
        await self.page.wait_for_load_state("domcontentloaded")
        login_out = await self.extract_page()
        if login_out.logged_in:
            login_out.message = '已登录'
            return login_out

        try:
            await self._open_login_page(self.page)
            for _ in range(timeout):
                await asyncio.sleep(1)
                await self.page.wait_for_load_state("domcontentloaded")
                login_out = await self.extract_page()
                if login_out.logged_in:
                    login_out.message = '已登录'
                    return login_out

        except BossOperationError:
            raise
        except Exception as exc:
            logger.error(
                "BossClient login failed while opening login page",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"BossClient 打开登录页失败: {exc}",
                recoverable=True,
                status_code=502,
            ) from exc
        login_out.message = '请在当前页面完成扫码登录'
        return login_out

    async def get_auth_status(self) -> LoginOut:
        try:
            await self.check_page_health()
            await self.page.wait_for_load_state("domcontentloaded")
            login_out = await self.extract_page()
            if login_out.logged_in:
                login_out.message = '已登录'
                return login_out
            login_out.message = '未登录，请先点击页面右上角登录'
            return login_out

        except BossOperationError:
            raise
        except Exception:
            logger.error("获取登录状态失败")
            logger.error(traceback.format_exc())
            return LoginOut(logged_in=False, message="获取登录状态失败")

    async def logout(self) -> LoginOut:

        logger.warning("BossClient logout is unavailable")
        raise BossOperationError(
            code="ENGINE_UNAVAILABLE",
            message="BossClient 尚未接管退出登录",
            recoverable=False,
            status_code=501,
        )

    async def search(self, request: SearchIn) -> SearchOut:
        await self.check_page_health()

        trace = self._build_search_trace(request.query)
        payload = await self._search_jobs_payload(trace["request_url"])
        trace["response_received_at"] = datetime.now(tz=UTC).isoformat()
        trace["response_payload"] = payload
        if payload.get("code") not in (None, 0):
            message = str(payload.get("message") or "职位搜索失败")
            logger.warning("BossClient search failed: payload=%s", payload)
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=message,
                recoverable=False,
                status_code=400,
                boss_side=True,
            )

        raw_items = payload.get("zpData", {}).get("jobList", [])
        if not isinstance(raw_items, list):
            logger.warning("BossClient search returned invalid job list payload=%s", payload)
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
            return SearchOut(items=[self._search_item_from_payload(item) for item in raw_items], trace=trace)

        items = [self._search_item_from_payload(self._normalize_raw_job(item)) for item in raw_items]
        trace["result_count"] = len(items)
        return SearchOut(items=items, trace=trace)

    async def detail(self, request: JobDetailIn) -> JobDetailOut:
        await self.check_page_health()

        resolved_security_id = request.security_id or self._extract_security_id(request.job_url)
        if not resolved_security_id:
            logger.warning("BossClient detail missing securityId request=%s", request.model_dump())
            raise BossOperationError(
                code="REQUEST_FAILED",
                message="职位详情缺少 securityId",
                recoverable=True,
                status_code=400,
            )

        request_url = _build_job_detail_url(resolved_security_id)
        if not request_url:
            logger.warning("BossClient detail failed to build request url security_id=%s", resolved_security_id)
            raise BossOperationError(
                code="REQUEST_FAILED",
                message="职位详情链接生成失败",
                recoverable=True,
                status_code=400,
            )

        requested_at = datetime.now(tz=UTC).isoformat()
        payload = await self._fetch_job_detail_payload(request_url)
        response_received_at = datetime.now(tz=UTC).isoformat()
        if payload.get("code") not in (None, 0):
            message = str(payload.get("message") or "职位详情采集失败")
            logger.warning("BossClient detail failed: payload=%s", payload)
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=message,
                recoverable=False,
                status_code=404,
                boss_side=True,
            )

        normalized = _normalize_job_detail(
            payload,
            {
                "job_id": request.job_id,
                "security_id": resolved_security_id,
                "job_url": request.job_url,
                "title": request.title,
                "company": request.company,
            },
        )
        detail_payload = dict(normalized["detail_payload"])
        job_payload = detail_payload.get("job") if isinstance(detail_payload.get("job"), dict) else {}
        company_payload = detail_payload.get("company") if isinstance(detail_payload.get("company"), dict) else {}
        boss_payload = detail_payload.get("boss") if isinstance(detail_payload.get("boss"), dict) else {}
        job_out = JobDetailJobOut(
            job_id=str(job_payload.get("job_id") or normalized.get("job_id") or request.job_id),
            security_id=str(job_payload.get("security_id") or normalized.get("security_id") or resolved_security_id),
            job_url=str(job_payload.get("job_url") or normalized.get("job_url") or request.job_url or ""),
            title=str(job_payload.get("title") or request.title or ""),
            salary=str(job_payload.get("salary") or ""),
            experience=str(job_payload.get("experience") or ""),
            degree=str(job_payload.get("degree") or ""),
            city=str(job_payload.get("city") or ""),
            address=str(job_payload.get("address") or ""),
            skills=[str(item) for item in job_payload.get("skills") or []],
            description=str(job_payload.get("description") or ""),
            status=str(job_payload.get("status") or ""),
            active_time=int(job_payload.get("active_time") or 0),
        )
        company_out = JobDetailCompanyOut(
            name=str(company_payload.get("name") or request.company or ""),
            stage=str(company_payload.get("stage") or ""),
            scale=str(company_payload.get("scale") or ""),
            industry=str(company_payload.get("industry") or ""),
            intro=str(company_payload.get("intro") or ""),
        )
        boss_out = JobDetailBossOut(
            name=str(boss_payload.get("name") or ""),
            title=str(boss_payload.get("title") or ""),
            active_text=str(boss_payload.get("active_text") or ""),
            online=bool(boss_payload.get("online") or False),
        )
        return JobDetailOut(
            engine=self.name,
            browser="Patchright Chromium",
            request_url=request_url,
            requested_at=requested_at,
            response_received_at=response_received_at,
            request_payload={
                "job_id": request.job_id,
                "security_id": resolved_security_id,
                "job_url": request.job_url or "",
                "title": request.title or "",
                "company": request.company or "",
            },
            response_payload=payload,
            job=job_out,
            company=company_out,
            boss=boss_out,
            detail_payload=JobDetailPayloadOut(
                job=job_out,
                company=company_out,
                boss=boss_out,
                raw_payload=detail_payload.get("raw_payload") if isinstance(detail_payload.get("raw_payload"),
                                                                            dict) else {},
            ),
            detail_text=str(normalized.get("detail_text") or ""),
            job_id=str(normalized.get("job_id") or request.job_id),
            security_id=str(normalized.get("security_id") or resolved_security_id),
            encrypt_boss_id=str(normalized.get("encrypt_boss_id") or ""),
            contact=bool(normalized.get("contact") or False),
            boss_online=bool(normalized.get("boss_online") or False),
            boss_active_text=str(normalized.get("boss_active_text") or ""),
            job_active_time=int(normalized.get("job_active_time") or 0),
            job_url=str(normalized.get("job_url") or request.job_url or ""),
            detail_raw_payload=normalized.get("detail_raw_payload") if isinstance(normalized.get("detail_raw_payload"),
                                                                                  dict) else {},
        )

    async def friend_list(self, request: FriendListIn) -> list[FriendListItemOut]:
        await self.check_page_health()

        url = f"{FRIEND_LIST_URL}?page={request.page}"
        payload = await self._fetch_json(url, WEB_GEEK_CHAT_URL)
        if payload.get("code") not in (None, 0):
            message = str(payload.get("message") or "好友列表获取失败")
            logger.warning("BossClient friend list failed: payload=%s", payload)
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=message,
                recoverable=False,
                status_code=400,
                boss_side=True,
            )

        try:
            zp_data = payload["zpData"]
            if not isinstance(zp_data, dict):
                raise TypeError("zpData is not a dict")
            if "result" in zp_data:
                friends = zp_data["result"]
            elif "friendList" in zp_data:
                friends = zp_data["friendList"]
            else:
                raise KeyError("result")
            if not isinstance(friends, list):
                raise TypeError("result is not a list")
        except (KeyError, TypeError) as exc:
            field_path = "zpData.result"
            if isinstance(exc, KeyError) and exc.args[0] == "zpData":
                field_path = "zpData"
            logger.error(
                "BOSS payload field missing: scene=friend_list field=%s payload=%s",
                field_path,
                payload,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"BOSS 返回字段缺失: {field_path}",
                recoverable=True,
                status_code=502,
                boss_side=False,
            ) from exc
        lmi = lambda f: f.get("lastMessageInfo") or {}

        return sorted(
            [
                FriendListItemOut(
                    gid=str(f.get("uid") or ""),
                    job_id=str(f.get("jobId") or ""),
                    encrypt_job_id=str(f.get("encryptJobId") or ""),
                    encrypt_boss_id=str(f.get("encryptBossId") or ""),
                    friend_source=int(f.get("friendSource") or 0),
                    relation_type=int(f.get("relationType") or 0),
                    read_status=int(lmi(f).get("status") or 0),
                    name=str(f.get("name") or ""),
                    title=str(f.get("title") or ""),
                    company=str(f.get("brandName") or f.get("company") or ""),
                    avatar=str(f.get("avatar") or ""),
                    last_message=str(f.get("lastMsg") or lmi(f).get("showText") or ""),
                    last_message_at=str(f.get("lastTime") or lmi(f).get("createTime") or ""),
                    last_message_ts=int(f.get("lastTS") or lmi(f).get("msgTime") or 0),
                    unread_count=int(f.get("unreadMsgCount") or 0),
                    security_id=str(f.get("securityId") or ""),
                    raw_payload=f,
                )
                for f in friends
            ],
            key=lambda x: x.last_message_ts,
            reverse=True,
        )

    async def greet(self, request: GreetJobIn) -> GreetJobOut:
        await self.check_page_health()

        body = {
            "securityId": request.security_id,
            "jobId": request.job_id
        }
        payload = await self._post_json(GREET_URL, WEB_GEEK_CHAT_URL, body)
        if payload.get("code") not in (None, 0):
            message = str(payload.get("message") or "打招呼失败")
            logger.warning("BossClient greet failed: payload=%s", payload)
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=message,
                recoverable=True,
                status_code=400,
                boss_side=True,
            )
        try:
            zp_data = payload["zpData"]
            if not isinstance(zp_data, dict):
                raise TypeError("zpData is not a dict")
            security_id = zp_data["securityId"]
            encrypt_boss_id = zp_data["encBossId"]
        except (KeyError, TypeError) as exc:
            field_path = "zpData.securityId"
            if isinstance(exc, KeyError):
                missing_key = exc.args[0]
                if missing_key == "zpData":
                    field_path = "zpData"
                elif missing_key == "encBossId":
                    field_path = "zpData.encBossId"
            elif "zpData" in str(exc):
                field_path = "zpData"
            logger.error(
                "BOSS payload field missing: scene=greet field=%s payload=%s",
                field_path,
                payload,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"BOSS 返回字段缺失: {field_path}",
                recoverable=True,
                status_code=502,
                boss_side=False,
            ) from exc
        return GreetJobOut(
            job_id=request.job_id,
            security_id=str(security_id),
            encrypt_boss_id=str(encrypt_boss_id),
            raw_payload=payload,
        )

    async def chat_history(self, request: ChatHistoryIn) -> ChatHistoryOut:
        await self.check_page_health()

        url = f"{CHAT_HISTORY_URL}?bossId={request.boss_id}&maxMsgId=0&c={request.count}&page={request.page}&src=0&securityId={request.security_id}"
        payload = await self._fetch_json(url, WEB_GEEK_CHAT_URL)
        if payload.get("code") not in (None, 0):
            message = str(payload.get("message") or "聊天历史获取失败")
            logger.warning("BossClient chat history failed: payload=%s", payload)
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=message,
                recoverable=False,
                status_code=400,
                boss_side=True,
            )
        try:
            zp_data = payload["zpData"]
            if not isinstance(zp_data, dict):
                raise TypeError("zpData is not a dict")
            messages = zp_data["messages"]
            if not isinstance(messages, list):
                raise TypeError("messages is not a list")
        except (KeyError, TypeError) as exc:
            field_path = "zpData.messages"
            if isinstance(exc, KeyError) and exc.args[0] == "zpData":
                field_path = "zpData"
            logger.error(
                "BOSS payload field missing: scene=chat_history field=%s payload=%s",
                field_path,
                payload,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"BOSS 返回字段缺失: {field_path}",
                recoverable=True,
                status_code=502,
                boss_side=False,
            ) from exc
        messages = [m for m in messages if m.get("uncount") == 0]
        return ChatHistoryOut(
            boss_id=request.boss_id,
            security_id=request.security_id,
            page=request.page,
            count=request.count,
            has_more=bool(zp_data.get("hasMore", False)),
            total=len(messages),
            messages=[
                ChatHistoryMessageOut(
                    message_id=str(m.get("mid") or ""),
                    from_id=str((m.get("from") or {}).get("uid") or ""),
                    from_name=str((m.get("from") or {}).get("name") or ""),
                    to_id=str((m.get("to") or {}).get("uid") or ""),
                    to_name=str((m.get("to") or {}).get("name") or ""),
                    content=str(_extract_message_content(m) or ""),
                    type=int(m.get("type") or 0),
                    created_at=int(m.get("time") or 0),
                    received=bool(m.get("received", False)),
                    status=int(m.get("status") or 0),
                    raw_payload=m,
                )
                for m in messages
            ],
            raw_payload=payload,
        )

    async def send_message(self, request: SendMessageIn) -> SendMessageOut:
        await self.check_page_health()

        content = request.content.strip()
        if not content:
            logger.warning("BossClient send message rejected empty content request=%s", request.model_dump())
            raise BossOperationError(
                code="REQUEST_FAILED",
                message="消息内容不能为空",
                recoverable=False,
                status_code=400,
            )

        chat_url = f"{WEB_GEEK_CHAT_URL}?{urlencode({'id': request.boss_id, 'jobId': request.job_id, 'securityId': request.security_id or ''})}"
        await self.page.goto(chat_url, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_load_state("networkidle")
        except Exception:
            pass
        try:
            await self.page.wait_for_selector(".chat-container", state="attached", timeout=10_000)
        except Exception:
            pass
        await asyncio.sleep(2)
        # await self.save_page_to_file("patchright.html")
        result = await self.page.evaluate(
            """
            async ({ request }) => {
                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const escapeHtml = (text) => String(text)
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;");
                const squashText = (text) => String(text || "").replace(/\\s+/g, " ").trim();
                const findVueComponent = (predicate) => {
                    const seen = new Set();
                    const queue = [];
                    for (const el of document.querySelectorAll("*")) {
                        if (el.__vue__) queue.push(el.__vue__);
                    }
                    while (queue.length) {
                        const vm = queue.shift();
                        if (!vm || seen.has(vm)) continue;
                        seen.add(vm);
                        if (predicate(vm)) return vm;
                        try {
                            for (const child of vm.$children || []) queue.push(child);
                        } catch (error) {}
                    }
                    return null;
                };
                const vmName = (vm) => (vm && vm.$options && (vm.$options.name || vm.$options._componentTag)) || "";
                const findVueParent = (el, predicate) => {
                    let current = el;
                    while (current) {
                        const vm = current.__vue__;
                        if (vm && (!predicate || predicate(vm))) return vm;
                        current = current.parentElement;
                    }
                    return null;
                };
                const describeEl = (el) => ({
                    tag: el.tagName,
                    id: el.id || "",
                    className: String(el.className || ""),
                    contenteditable: el.getAttribute("contenteditable") || "",
                    text: squashText(el.innerText || el.value || "").slice(0, 120),
                    vue: vmName(el.__vue__),
                    parentVue: vmName(findVueParent(el)),
                });
                const collectDiagnostics = (log) => {
                    const components = [];
                    const seen = new Set();
                    for (const el of document.querySelectorAll("*")) {
                        const vm = el.__vue__;
                        if (!vm || seen.has(vm)) continue;
                        seen.add(vm);
                        const methods = Object.keys(vm)
                            .filter((key) => typeof vm[key] === "function")
                            .filter((key) => /send|click|chat|friend|boss|geek|message|enter/i.test(key))
                            .slice(0, 12);
                        components.push({
                            name: vmName(vm),
                            className: String(el.className || ""),
                            methods,
                        });
                        if (components.length >= 40) break;
                    }
                    const inputs = Array.from(document.querySelectorAll(
                        "#chat-input, button[type='send'].btn-send, .boss-chat-editor-input, .chat-editor [contenteditable='true'], .chat-conversation [contenteditable='true'], [contenteditable='true'], textarea, input, [class*='editor'], [class*='input']"
                    )).slice(0, 60).map(describeEl);
                    return {
                        href: location.href,
                        readyState: document.readyState,
                        title: document.title,
                        chatConversationText: squashText(document.querySelector(".chat-conversation")?.innerText || "").slice(0, 500),
                        chatUserText: squashText(document.querySelector(".chat-user")?.innerText || "").slice(0, 500),
                        chatUserVue: vmName(document.querySelector(".chat-user")?.__vue__),
                        chatUserItemCount: document.querySelectorAll(".chat-user li, .chat-user .user-item, .chat-user [data-id], .chat-user [data-uid]").length,
                        inputs,
                        components,
                        log,
                    };
                };
                const getChatDom = () => {
                    const input = document.querySelector("#chat-input");
                    const sendButton = document.querySelector("button[type='send'].btn-send");
                    if (!input) return { input: null, sendButton: null, error: "未找到聊天输入框" };
                    if (!sendButton) return { input, sendButton: null, error: "未找到发送按钮" };
                    return { input, sendButton, error: null };
                };
                const waitForChatDom = async () => {
                    for (let i = 0; i < 60; i += 1) {
                        const state = getChatDom();
                        if (!state.error) return state;
                        await sleep(250);
                    }
                    return getChatDom();
                };
                const switchByList = async (log) => {
                    const targetIds = [
                        request.boss_uid,
                        request.boss_id,
                    ].filter(Boolean).map((item) => String(item));
                    const list = document.querySelector(".chat-user");
                    const listVm = list && list.__vue__;
                    const candidateItems = Array.from(document.querySelectorAll(
                        ".chat-user li, .chat-user .user-item, .chat-user [data-id], .chat-user [data-uid]"
                    ));
                    const matchedEl = candidateItems.find((el) => {
                        const text = [el.textContent, el.outerHTML, el.getAttribute("data-id"), el.getAttribute("data-uid")]
                            .filter(Boolean)
                            .join(" ");
                        return targetIds.some((id) => id && text.includes(id));
                    });
                    if (matchedEl) {
                        matchedEl.click();
                        log.push("matched chat list item clicked");
                        await sleep(1200);
                        return true;
                    }
                    if (listVm && typeof listVm.geekClick === "function") {
                        const friendData = {
                            ...request.raw_payload,
                            uid: Number(request.boss_uid),
                            friendId: Number(request.boss_uid),
                            encryptUid: request.boss_id,
                            encryptBossId: request.boss_id,
                            securityId: request.security_id,
                            encryptJobId: request.job_id,
                            jobId: request.job_numeric_id,
                            friendSource: request.friend_source || 0,
                        };
                        try {
                            listVm.geekClick(friendData);
                            log.push("geekClick called");
                            await sleep(1500);
                            return true;
                        } catch (error) {
                            log.push("geekClick failed: " + error.message);
                        }
                    }
                    log.push("chat list switch skipped");
                    return false;
                };
                const resolveSelfId = async () => {
                    if (request.self_id) return String(request.self_id);
                    const pageUid = window._PAGE && (window._PAGE.uid || window._PAGE.userId);
                    if (pageUid) return String(pageUid);
                    try {
                        const response = await fetch("/wapi/zpuser/wap/getUserInfo.json", {
                            method: "GET",
                            credentials: "include",
                            headers: {
                                "Accept": "application/json, text/plain, */*",
                                "X-Requested-With": "XMLHttpRequest",
                            },
                        });
                        const payload = await response.json();
                        const userId = payload && payload.zpData && payload.zpData.userId;
                        if (userId) return String(userId);
                    } catch (error) {}
                    return "";
                };

                const log = [];
                const selfId = await resolveSelfId();
                if (!selfId) {
                    return { ok: false, error: "未获取到当前求职者 uid", log };
                }

                await switchByList(log);
                const state = await waitForChatDom();
                if (state.error) return { ok: false, error: state.error, diagnostics: collectDiagnostics(log), log };
                const { input, sendButton } = state;

                if (input.tagName === "TEXTAREA" || input.tagName === "INPUT") {
                    input.value = request.content;
                } else {
                    input.innerHTML = escapeHtml(request.content);
                }
                input.focus();
                input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: request.content }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
                await sleep(300);
                if (sendButton.disabled || sendButton.classList.contains("disabled")) {
                    log.push("send button disabled before click");
                }
                sendButton.click();
                log.push("send button clicked");
                await sleep(1200);
                const chatText = squashText(document.querySelector(".chat-conversation")?.innerText || "");
                return {
                    ok: true,
                    method: "dom.click.send",
                    selfId,
                    visibleInConversation: chatText.includes(request.content),
                    log,
                };
            }
            """,
            {"request": request.__dict__},
        )
        # await self.save_page_to_file("patchright-after-send.html")
        if not isinstance(result, dict) or not result.get("ok"):
            result_payload = result if isinstance(result, dict) else {}
            message = str(result_payload.get("error") or "发送消息失败")
            diagnostics = result_payload.get("diagnostics")
            if isinstance(diagnostics, dict):
                chat_text = str(diagnostics.get("chatConversationText") or "")
                item_count = diagnostics.get("chatUserItemCount")
                input_count = len(diagnostics.get("inputs") or [])
                message = (
                    f"{message}（chatItems={item_count}, inputs={input_count}, "
                    f"page={diagnostics.get('href')}, text={chat_text[:80]}）"
                )
            logger.warning("BossClient send message failed: payload=%s", result_payload)
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=message,
                recoverable=True,
                recovery_action="打开 BOSS 沟通页后重试",
                status_code=502,
                boss_side=True,
            )

        return SendMessageOut(
            status="sent",
            job_id=request.job_id,
            gid=request.gid,
            self_id=str(result.get("selfId") or request.self_id),
            boss_uid=request.boss_uid,
            boss_id=request.boss_id,
            security_id=str(request.security_id or ""),
            content=content,
            raw_payload=result,
        )

    async def _fetch_json(self, url: str, referer: str) -> dict[str, Any]:
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
            {"url": url, "referer": referer},
        )

    async def _post_json(self, url: str, referer: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self.page.evaluate(
            """
            async ({ url, referer, body }) => {
                const response = await fetch(url, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest",
                        "zp_page_request_id": crypto.randomUUID(),
                    },
                    referrer: referer,
                    body: new URLSearchParams(body).toString(),
                });
                return await response.json();
            }
            """,
            {"url": url, "referer": referer, "body": body},
        )

    async def healthcheck(self) -> HealthcheckOut:
        try:
            await self.check_page_health()
        except BossOperationError as exc:
            return HealthcheckOut(
                status="unavailable",
                provider=self.name,
                logged_in=False,
                message=exc.message,
                last_error=exc.message,
            )

        auth = await self.get_auth_status()
        return HealthcheckOut(
            status="ok" if auth.logged_in else "auth_required",
            provider=self.name,
            logged_in=auth.logged_in,
            message=auth.message,
            last_error="",
        )

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
            logger.error(
                "BossClient open login page failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"BossClient 页面跳转失败: {exc}",
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

    async def _fetch_job_detail_payload(self, request_url: str) -> dict[str, Any]:
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
            logger.warning("BossClient search missing query query=%s", query)
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
                logger.warning("BossClient search has unknown city query=%s", query)
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
        return _normalize_job(raw)

    def _extract_security_id(self, job_url: str | None) -> str | None:
        if not job_url:
            return None
        query = parse_qs(urlparse(job_url).query)
        values = query.get("securityId") or query.get("securityid")
        if not values:
            return None
        value = str(values[0]).strip()
        return value or None

    def _search_item_from_payload(self, payload: dict[str, Any]) -> SearchJobItemOut:
        return SearchJobItemOut(
            job_id=str(payload["job_id"]),
            security_id=str(payload.get("security_id") or ""),
            encrypt_boss_id=str(payload.get("encrypt_boss_id") or ""),
            contact=bool(payload.get("contact") or False),
            boss_online=bool(payload.get("boss_online") or False),
            boss_active_text=str(payload.get("boss_active_text") or ""),
            job_active_time=int(payload.get("job_active_time") or 0),
            title=str(payload["title"]),
            company=str(payload["company"]),
            city=str(payload.get("city") or ""),
            salary=str(payload.get("salary") or ""),
            experience=str(payload.get("experience") or ""),
            job_url=str(payload.get("job_url") or ""),
            raw_payload=dict(payload.get("raw_payload") or payload),
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
        raw = os.environ.get("JOB_BUDDY_PROFILE_DIR") or self.params.get(
            "profile_dir") or self.settings.boss_profile_dir or DEFAULT_PROFILE_DIR
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = self.settings.project_root / path
        return path.resolve()

    async def search_jobs(self, request: SearchIn) -> list[SearchJobItemOut]:
        result = await self.search(request)
        return result.items

    async def get_job_detail(self, request: JobDetailIn) -> JobDetailOut:
        return await self.detail(request)

    async def greet_job(self, request: GreetJobIn) -> GreetJobOut:
        return await self.greet(request)

    async def list_friends(self, request: FriendListIn) -> list[FriendListItemOut]:
        return await self.friend_list(request)

    async def get_chat_history(self, request: ChatHistoryIn) -> ChatHistoryOut:
        return await self.chat_history(request)


def _normalize_query_text(query: dict[str, Any]) -> str:
    query_text = _normalize_optional_string(query.get("query"))
    if query_text:
        return query_text

    keywords = query.get("keywords", [])
    if isinstance(keywords, list):
        return " ".join([str(item).strip() for item in keywords if str(item).strip()])
    return _normalize_optional_string(keywords) or ""


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_enum_param(name: str, value: Any, choices: dict[str, str]) -> str | None:
    normalized = _normalize_optional_string(value)
    if normalized is None:
        return None
    if normalized not in choices:
        raise ValueError(f"非法参数 {name}: {normalized}，请使用系统提供的下拉选项")
    return normalized


def _normalize_page(value: Any) -> int:
    if value in (None, ""):
        return 1
    try:
        page = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"非法参数 page: {value}") from exc
    if page < 1:
        raise ValueError(f"非法参数 page: {value}")
    return page
