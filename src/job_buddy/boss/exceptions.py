from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, NoReturn

logger = logging.getLogger(__name__)


@dataclass
class BossOperationError(Exception):
    code: str
    message: str
    recoverable: bool = True
    recovery_action: str | None = None
    status_code: int = 502
    boss_side: bool = False

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
        logger.warning("BOSS healthcheck failed: %s", health)
        raise BossOperationError(
            code=code,
            message=message,
            recoverable=True,
            recovery_action="login",
            status_code=401,
        )
