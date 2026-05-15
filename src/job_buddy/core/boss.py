import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from urllib import error, parse, request
from dataclasses import dataclass
from datetime import UTC, datetime
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


DEFAULT_CDP_URL = "http://127.0.0.1:9222"
BROWSER_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]


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

        profile_dir = os.path.join(tempfile.gettempdir(), f"job-buddy-chrome-{self.port}")
        process = await asyncio.create_subprocess_exec(
            browser_bin,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        process.returncode

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
