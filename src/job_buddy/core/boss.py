import asyncio
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
import time
from urllib import error, parse, request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from job_buddy.core.config import Settings


class BossClientProtocol(Protocol):
    async def search_jobs(self, query: dict[str, Any]) -> list[dict[str, Any]]: ...
    async def greet_job(self, job: dict[str, Any], message: str | None = None) -> dict[str, Any]: ...
    async def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]: ...
    async def healthcheck(self) -> dict[str, Any]: ...


@dataclass
class LocalBossStubClient:
    async def search_jobs(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        keyword = ",".join(query.get("keywords", [])) or "Python"
        return [
            {
                "job_id": "demo-backend-001",
                "title": f"{keyword} Backend Engineer",
                "company": "Demo Tech",
                "city": query.get("city") or "Shanghai",
                "salary": query.get("salary") or "20-30K",
                "experience": query.get("experience") or "3-5 years",
            },
            {
                "job_id": "demo-platform-002",
                "title": f"{keyword} Platform Engineer",
                "company": "Example AI",
                "city": query.get("city") or "Remote",
                "salary": query.get("salary") or "25-35K",
                "experience": query.get("experience") or "5+ years",
            },
        ]

    async def greet_job(self, job: dict[str, Any], message: str | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "job_id": job["source_job_id"],
            "message": message or "你好，我对这个岗位很感兴趣。",
        }

    async def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        now = datetime.now(tz=UTC).isoformat()
        return [
            {
                "conversation_id": "conversation-demo-001",
                "title": "后端工程师",
                "company": "Demo Tech",
                "last_message": "方便发一份简历吗？",
                "unread_count": 1,
                "last_message_at": now,
            }
        ][:limit]

    async def healthcheck(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "local_stub"}


def build_boss_client(settings: Settings) -> BossClientProtocol:
    _ = settings
    return LocalBossStubClient()


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


@dataclass
class CdpStatusResult:
    running: bool
    port: int
    cdp_url: str
    browser: str | None = None
    websocket_url: str | None = None
    pid: int | None = None
    message: str = ""


@dataclass
class BossAuthStatusResult:
    logged_in: bool
    user_name: str | None = None
    login_method: str | None = None
    message: str = ""
    last_error: str | None = None


DEFAULT_CDP_URL = "http://127.0.0.1:9222"
BROWSER_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]
DEFAULT_BOSS_DATA_DIR = Path("data") / "boss-agent-cli"
_PERSISTENT_PATCHRIGHT_SESSIONS: list[tuple[Any, Any]] = []


def resolve_boss_data_dir(settings: Settings) -> Path:
    if settings.boss_data_dir:
        return Path(settings.boss_data_dir).expanduser().resolve()
    return DEFAULT_BOSS_DATA_DIR.resolve()


def close_persistent_patchright_sessions() -> None:
    while _PERSISTENT_PATCHRIGHT_SESSIONS:
        playwright, browser = _PERSISTENT_PATCHRIGHT_SESSIONS.pop()
        try:
            browser.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass


def login_via_browser_persistent(*, timeout: int = 120) -> dict[str, Any]:
    from boss_agent_cli.auth.browser import HOME_URL, LOGIN_PAGE_URL, _POST_LOGIN_WAIT, _extract_stoken
    from patchright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)

    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.new_page()
        page.goto(LOGIN_PAGE_URL, wait_until="domcontentloaded")
        print("已打开 BOSS 直聘登录页。", file=sys.stderr)
        print(f"请扫码或手机号登录（超时 {timeout} 秒）...", file=sys.stderr)

        login_detected = False

        def _on_response(response: Any) -> None:
            nonlocal login_detected
            url = response.url
            if (
                url.startswith("https://www.zhipin.com/wapi/zppassport/qrcode/loginConfirm")
                or url.startswith("https://www.zhipin.com/wapi/zppassport/qrcode/dispatcher")
                or url.startswith("https://www.zhipin.com/wapi/zppassport/login/phoneV2")
            ):
                login_detected = True

        page.on("response", _on_response)

        deadline = time.time() + timeout
        while time.time() < deadline and not login_detected:
            try:
                cookies_list = context.cookies()
                if any(c["name"] == "wt2" for c in cookies_list):
                    login_detected = True
                    break
            except Exception:
                pass
            time.sleep(1)

        if not login_detected:
            raise TimeoutError(f"扫码登录超时（{timeout}秒）")

        print("检测到登录成功，正在提取凭证...", file=sys.stderr)
        time.sleep(_POST_LOGIN_WAIT)

        page.goto(HOME_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        cookies_list = context.cookies()
        cookies = {c["name"]: c["value"] for c in cookies_list}
        user_agent = page.evaluate("navigator.userAgent")
        stoken = _extract_stoken(page)

        result: dict[str, Any] = {
            "cookies": cookies,
            "stoken": stoken,
            "user_agent": user_agent,
        }

        # Keep the independent browser open after login.
        _PERSISTENT_PATCHRIGHT_SESSIONS.append((pw, browser))
        return result
    except Exception:
        try:
            browser.close()
        finally:
            pw.stop()
        raise


class BossDoctorRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_command(self) -> list[str]:
        if shutil.which(self.settings.boss_cli_bin):
            command = [self.settings.boss_cli_bin]
        else:
            command = [sys.executable, "-m", "boss_agent_cli.main"]

        if self.settings.boss_data_dir:
            command.extend(["--data-dir", self.settings.boss_data_dir])
        if self.settings.boss_cdp_url:
            command.extend(["--cdp-url", self.settings.boss_cdp_url])

        command.extend(["--json", "doctor"])
        return command

    async def run(self) -> BossDoctorResult:
        process = await asyncio.create_subprocess_exec(
            *self.build_command(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        payload = self._parse_payload(stdout_text)
        data = payload.get("data") or {}
        hints = payload.get("hints") or {}

        return BossDoctorResult(
            ok=bool(payload.get("ok")),
            summary=data.get("summary", "unknown"),
            data_dir=data.get("data_dir"),
            checks=data.get("checks", []),
            next_actions=hints.get("next_actions", []),
            stderr=stderr_text,
            exit_code=process.returncode or 0,
            error=payload.get("error"),
        )

    def _parse_payload(self, stdout_text: str) -> dict:
        if not stdout_text:
            return {
                "ok": False,
                "data": {"summary": "broken", "data_dir": None, "checks": []},
                "error": {"code": "empty_output", "message": "boss doctor 未返回可解析内容"},
                "hints": {"next_actions": ["检查 boss 命令是否可执行，再重试诊断"]},
            }

        try:
            return json.loads(stdout_text)
        except json.JSONDecodeError:
            for line in reversed([line for line in stdout_text.splitlines() if line.strip()]):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        return {
            "ok": False,
            "data": {"summary": "broken", "data_dir": None, "checks": []},
            "error": {"code": "invalid_output", "message": stdout_text},
            "hints": {"next_actions": ["检查 boss doctor 输出格式是否发生变化"]},
        }


class CdpBrowserController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def cdp_url(self) -> str:
        return self.settings.boss_cdp_url or DEFAULT_CDP_URL

    @property
    def port(self) -> int:
        parsed = parse.urlparse(self.cdp_url)
        if parsed.port:
            return parsed.port
        return 9222

    @property
    def data_dir(self) -> Path:
        return resolve_boss_data_dir(self.settings)

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "cdp-profile"

    @property
    def pid_file(self) -> Path:
        return self.data_dir / "cdp-browser.pid"

    async def get_status(self) -> CdpStatusResult:
        payload = await asyncio.to_thread(self._probe_cdp)
        pid = await self._find_listener_pid() if payload else None
        return CdpStatusResult(
            running=payload is not None,
            port=self.port,
            cdp_url=self.cdp_url,
            browser=payload.get("Browser") if payload else None,
            websocket_url=payload.get("webSocketDebuggerUrl") if payload else None,
            pid=pid,
            message="CDP 在线" if payload else "CDP 未运行",
        )

    async def start_browser(self) -> CdpStatusResult:
        current = await self.get_status()
        if current.running:
            current.message = "浏览器已运行"
            return current

        browser_bin = self._find_browser_executable()
        if not browser_bin:
            return CdpStatusResult(
                running=False,
                port=self.port,
                cdp_url=self.cdp_url,
                message="未找到可用的 Chrome/Chromium 浏览器",
            )

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            browser_bin,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        self.pid_file.write_text(str(process.pid), encoding="utf-8")

        for _ in range(20):
            await asyncio.sleep(0.5)
            status = await self.get_status()
            if status.running:
                status.message = "浏览器已启动"
                return status

        return CdpStatusResult(
            running=False,
            port=self.port,
            cdp_url=self.cdp_url,
            message="浏览器已启动，但 CDP 尚未就绪",
        )

    async def ensure_running(self) -> CdpStatusResult:
        current = await self.get_status()
        if current.running:
            current.message = "浏览器已运行"
            return current
        return await self.start_browser()

    async def stop_browser(self) -> CdpStatusResult:
        current = await self.get_status()
        if not current.running:
            current.message = "浏览器未运行"
            return current

        pid = current.pid or await self._find_listener_pid()
        if pid is None:
            current.message = "未能定位监听默认 CDP 端口的浏览器进程"
            return current

        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass

        for _ in range(10):
            await asyncio.sleep(0.5)
            status = await self.get_status()
            if not status.running:
                status.message = "浏览器已关闭"
                return status

        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass

        for _ in range(6):
            await asyncio.sleep(0.5)
            status = await self.get_status()
            if not status.running:
                status.message = "浏览器已强制关闭"
                return status

        status = await self.get_status()
        status.message = "浏览器关闭失败"
        return status

    async def stop_managed_browser(self) -> CdpStatusResult:
        pid = self._read_managed_pid()
        if pid is None:
            status = await self.get_status()
            status.message = "未发现受管浏览器"
            return status

        for signal in (15, 9):
            try:
                os.kill(pid, signal)
            except ProcessLookupError:
                break

            for _ in range(10):
                await asyncio.sleep(0.5)
                status = await self.get_status()
                if not status.running:
                    self.pid_file.unlink(missing_ok=True)
                    status.message = "浏览器已关闭"
                    return status

        self.pid_file.unlink(missing_ok=True)
        status = await self.get_status()
        status.message = "浏览器关闭失败"
        return status

    def clear_profile(self) -> None:
        shutil.rmtree(self.profile_dir, ignore_errors=True)
        self.pid_file.unlink(missing_ok=True)

    def _probe_cdp(self) -> dict[str, Any] | None:
        try:
            with request.urlopen(f"{self.cdp_url}/json/version", timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict) and payload.get("webSocketDebuggerUrl"):
                    return payload
        except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return None
        return None

    async def _find_listener_pid(self) -> int | None:
        process = await asyncio.create_subprocess_exec(
            "ss",
            "-ltnp",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        output = stdout.decode("utf-8", errors="replace")
        port_marker = f":{self.port}"
        for line in output.splitlines():
            if port_marker not in line:
                continue
            match = re.search(r"pid=(\d+)", line)
            if match:
                return int(match.group(1))
        return None

    def _find_browser_executable(self) -> str | None:
        for candidate in BROWSER_CANDIDATES:
            path = shutil.which(candidate)
            if path:
                return path
        return None

    def _read_managed_pid(self) -> int | None:
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return None


class BossAuthGateway:
    method_map = {
        "Cookie 提取": "cookie",
        "CDP 扫码": "cdp",
        "QR httpx 登录": "qr_httpx",
        "扫码登录": "patchright",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.data_dir = resolve_boss_data_dir(settings)

    @property
    def cdp_url(self) -> str | None:
        return self.settings.boss_cdp_url or DEFAULT_CDP_URL

    async def get_status(self) -> BossAuthStatusResult:
        return await asyncio.to_thread(self._get_status_sync)

    async def login(self, timeout: int = 120) -> BossAuthStatusResult:
        return await asyncio.to_thread(self._login_sync, timeout)

    async def logout(self) -> None:
        await asyncio.to_thread(self._logout_sync)

    def _get_status_sync(self) -> BossAuthStatusResult:
        auth = self._build_auth_manager()
        token = auth.check_status()
        if token is None:
            return BossAuthStatusResult(logged_in=False, message="未登录")

        try:
            user_name = self._fetch_user_name(auth)
            return BossAuthStatusResult(
                logged_in=True,
                user_name=user_name,
                message="已登录",
            )
        except Exception as exc:
            return BossAuthStatusResult(
                logged_in=False,
                message="检测到本地登录态，但校验失败",
                last_error=str(exc),
            )

    def _login_sync(self, timeout: int) -> BossAuthStatusResult:
        from boss_agent_cli.auth.browser import login_via_cdp, probe_cdp
        from boss_agent_cli.auth.cookie_extract import extract_cookies
        from boss_agent_cli.auth.qr_login import qr_login_httpx

        auth = self._build_auth_manager()
        method = "未知"
        token: dict[str, Any] | None = None

        auth._logger.info("尝试从本地浏览器提取 Cookie...")
        token = extract_cookies(None)
        if token and self._has_primary_cookie(token):
            if auth._verify_cookie(token):
                method = "Cookie 提取"
                self._save_token(auth, token)
                user_name = self._fetch_user_name(auth)
                return BossAuthStatusResult(
                    logged_in=True,
                    user_name=user_name,
                    login_method=self.method_map[method],
                    message=f"登录成功（{method}）",
                )
            auth._logger.info("提取的 Cookie 已失效，降级到 CDP")
        else:
            auth._logger.info("未能从浏览器提取 Cookie，降级到 CDP")

        if probe_cdp(self.cdp_url):
            auth._logger.info("检测到 CDP 可用，尝试 CDP 登录...")
            try:
                token = login_via_cdp(cdp_url=self.cdp_url, timeout=timeout)
                method = "CDP 扫码"
                self._save_token(auth, token)
                user_name = self._fetch_user_name(auth)
                return BossAuthStatusResult(
                    logged_in=True,
                    user_name=user_name,
                    login_method=self.method_map[method],
                    message=f"登录成功（{method}）",
                )
            except Exception as exc:
                auth._logger.info(f"CDP 登录失败（{exc}），降级到 QR httpx")
        else:
            auth._logger.info("CDP 不可用，尝试 QR 纯 httpx 登录")

        try:
            token = qr_login_httpx(timeout=timeout)
            method = "QR httpx 登录"
            self._save_token(auth, token)
            user_name = self._fetch_user_name(auth)
            return BossAuthStatusResult(
                logged_in=True,
                user_name=user_name,
                login_method=self.method_map[method],
                message=f"登录成功（{method}）",
            )
        except Exception as exc:
            auth._logger.info(f"QR httpx 登录失败（{exc}），降级到 patchright")

        token = login_via_browser_persistent(timeout=timeout)
        method = "扫码登录"
        self._save_token(auth, token)
        user_name = self._fetch_user_name(auth)
        return BossAuthStatusResult(
            logged_in=True,
            user_name=user_name,
            login_method=self.method_map[method],
            message=f"登录成功（{method}）",
        )

    def _logout_sync(self) -> None:
        auth = self._build_auth_manager()
        auth.logout()
        close_persistent_patchright_sessions()

    def _build_auth_manager(self) -> Any:
        from boss_agent_cli.auth.manager import AuthManager

        self.data_dir.mkdir(parents=True, exist_ok=True)
        signature = inspect.signature(AuthManager)
        kwargs: dict[str, Any] = {}
        if "platform" in signature.parameters:
            kwargs["platform"] = "zhipin"
        return AuthManager(self.data_dir, **kwargs)

    def _fetch_user_name(self, auth: Any) -> str | None:
        from boss_agent_cli.api.client import BossClient

        with BossClient(auth, cdp_url=self.cdp_url) as client:
            payload = client.user_info()

        if payload.get("code") != 0:
            message = payload.get("message") or "用户信息获取失败"
            raise RuntimeError(str(message))

        data = payload.get("zpData") or {}
        return data.get("name") or data.get("geekName")

    def _save_token(self, auth: Any, token: dict[str, Any]) -> None:
        auth._store.save(token)
        auth._token = token

    def _has_primary_cookie(self, token: dict[str, Any]) -> bool:
        cookies = token.get("cookies", {})
        if not isinstance(cookies, dict):
            return False
        return bool(cookies.get("wt2"))
