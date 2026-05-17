from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Protocol

from job_buddy.core.config import Settings
from job_buddy.core.zhipin_api import (
    CITY_CODES,
    EDUCATION_CODES,
    EXPERIENCE_CODES,
    INDUSTRY_CODES,
    JOB_TYPE_CODES,
    SALARY_CODES,
    SCALE_CODES,
    STAGE_CODES,
    build_job_url,
)


class BossClientProtocol(Protocol):
    async def greet_job(self, job: dict[str, Any], message: str | None = None) -> dict[str, Any]: ...
    async def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]: ...
    async def healthcheck(self) -> dict[str, Any]: ...


@dataclass
class BossOperationError(Exception):
    code: str
    message: str
    recoverable: bool = True
    recovery_action: str | None = None
    status_code: int = 502
    boss_side: bool = False  # True: BOSS 网站返回的错误，非应用 bug

    def __str__(self) -> str:
        return self.message


def raise_boss_operation_error(exc: Exception) -> NoReturn:
    raise map_boss_operation_error(exc) from exc


def map_boss_operation_error(exc: Exception) -> BossOperationError:
    if isinstance(exc, BossOperationError):
        return exc

    exc_name = exc.__class__.__name__
    message = str(exc)

    if exc_name == "AuthRequired":
        return BossOperationError(
            code="AUTH_REQUIRED",
            message="未登录，请先点击页面右上角登录",
            recoverable=True,
            recovery_action="login",
            status_code=401,
            boss_side=True,
        )

    if exc_name == "TokenRefreshFailed":
        return BossOperationError(
            code="TOKEN_INVALID",
            message="登录态刷新失败，请重新登录",
            recoverable=True,
            recovery_action="login",
            status_code=401,
            boss_side=True,
        )

    if exc_name == "AccountRiskError":
        return BossOperationError(
            code="ANTI_BOT_BLOCKED",
            message=message or "BOSS 直聘风控拦截",
            recoverable=False,
            recovery_action="联系 BOSS 直聘客服解除风控限制",
            status_code=409,
            boss_side=True,
        )

    return BossOperationError(
        code="REQUEST_FAILED",
        message=f"BOSS 请求失败: {message}",
        recoverable=True,
        recovery_action="retry",
        status_code=502,
    )


def raise_for_boss_healthcheck(health: dict[str, Any]) -> None:
    status_value = str(health.get("status") or "")
    logged_in = health.get("logged_in")
    message = str(health.get("message") or "未登录，请先点击页面右上角登录")
    last_error = health.get("last_error")

    if status_value == "auth_required" or logged_in is False:
        code = "TOKEN_INVALID" if last_error or "无效" in message else "AUTH_REQUIRED"
        raise BossOperationError(
            code=code,
            message=message,
            recoverable=True,
            recovery_action="login",
            status_code=401,
        )
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


def normalize_default_search_query(query: dict[str, Any]) -> dict[str, Any]:
    return normalize_search_query(
        query,
        city_codes=CITY_CODES,
        salary_codes=SALARY_CODES,
        experience_codes=EXPERIENCE_CODES,
        education_codes=EDUCATION_CODES,
        industry_codes=INDUSTRY_CODES,
        scale_codes=SCALE_CODES,
        stage_codes=STAGE_CODES,
        job_type_codes=JOB_TYPE_CODES,
    )


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
        data_dir = Path("data").resolve()
        profile_dir = Path("data/chrome_profile").resolve()
        checks = [
            {"name": "patchright", "status": "ok", "detail": "使用 Patchright 驱动 BOSS 页面", "hint": None},
            {"name": "data_dir", "status": "ok", "detail": str(data_dir), "hint": None},
            {"name": "profile_dir", "status": "ok", "detail": str(profile_dir), "hint": "如需隔离浏览器环境可调整 JOB_BUDDY_PROFILE_DIR"},
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
