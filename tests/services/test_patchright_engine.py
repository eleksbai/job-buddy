import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from job_buddy.boss.client import BossClient, _normalize_job, _normalize_job_detail
from job_buddy.boss.exceptions import BossOperationError
from job_buddy.boss.schemas import ChatHistoryIn, GreetJobIn, JobDetailIn, LoginIn, LoginOut, SearchIn, SendMessageIn
from job_buddy.config import Settings


class FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.evaluate_calls: list[str] = []
        self.fail_eval = False
        self.fetch_payload: dict | None = None
        self.last_fetch_url: str | None = None
        self.last_fetch_referer: str | None = None
        self.last_fetch_body: dict | None = None
        self.last_send_request: dict | None = None

    async def goto(self, url: str, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))

    async def evaluate(self, script: str, *args):
        self.evaluate_calls.append(script)
        if self.fail_eval:
            raise RuntimeError("page closed")
        if "fetch(url" in script:
            payload = args[0]
            self.last_fetch_url = payload["url"]
            self.last_fetch_referer = payload["referer"]
            self.last_fetch_body = payload.get("body")
            return self.fetch_payload or {"code": 0, "zpData": {"jobList": []}}
        if "btn-send" in script or "#chat-input" in script:
            payload = args[0]
            self.last_send_request = payload["request"]
            return {"ok": True, "method": "dom.click.send", "selfId": "self-1", "visibleInConversation": True}
        return 1

    async def wait_for_load_state(self, state: str) -> None:
        _ = state
        return None

    async def wait_for_selector(self, selector: str, **kwargs) -> None:
        _ = selector, kwargs
        return None

    async def content(self) -> str:
        return "<html><body><div class=\"chat-container\"></div></body></html>"

    async def bring_to_front(self) -> None:
        return None

    def on(self, event: str, callback) -> None:
        _ = event, callback

    def remove_listener(self, event: str, callback) -> None:
        _ = event, callback


class FakeMouse:
    async def wheel(self, dx: int, dy: int) -> None:
        _ = dx, dy


class FakeLocator:
    def __init__(self, page: FakePage, selector: str, count: int = 0) -> None:
        self._page = page
        self._selector = selector
        self._count = count

    async def count(self) -> int:
        return self._count

    def nth(self, index: int):
        return FakeNthLocator(self._page, self._selector, index)


class FakeNthLocator:
    def __init__(self, page: FakePage, selector: str, index: int) -> None:
        self._page = page
        self._selector = selector
        self._index = index

    async def click(self) -> None:
        return None

    async def evaluate(self, script: str, *args):
        _ = script, args
        if "closest" in script:
            return f"job-title-{self._index}"
        return 1


class FakeResponse:
    def __init__(self, url: str, data: dict) -> None:
        self.url = url
        self._data = data

    async def json(self) -> dict:
        return self._data


class FakeDetailPage(FakePage):
    def __init__(self) -> None:
        super().__init__()
        self._response_callbacks: list = []
        self.detail_responses: list[dict] = []
        self.job_titles_count = 0
        self.mouse = FakeMouse()
        self._scroll_height_calls = 0

    def on(self, event: str, callback) -> None:
        if event == "response":
            self._response_callbacks.append(callback)

    def remove_listener(self, event: str, callback) -> None:
        if event == "response":
            self._response_callbacks.remove(callback)

    def locator(self, selector: str):
        if "job-title" in selector:
            return FakeLocator(self, selector, self.job_titles_count)
        return FakeLocator(self, selector, 0)

    async def evaluate(self, script: str, *args):
        if "document.body.scrollHeight" in script:
            self._scroll_height_calls += 1
            # Return same height after first call to trigger freeze_count exit
            return 1000 + min(self._scroll_height_calls, 1) * 100
        return await super().evaluate(script, *args)


class FakeContext:
    def __init__(self, page: FakePage | None = None) -> None:
        self.pages = [page] if page is not None else []
        self.browser = object()
        self.close_called = False
        self.new_page_calls = 0

    async def new_page(self) -> FakePage:
        self.new_page_calls += 1
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.close_called = True


class FakePlaywright:
    def __init__(self, context_factory) -> None:
        self.chromium = self
        self._context_factory = context_factory
        self.launch_calls: list[str] = []
        self.stopped = False

    async def launch_persistent_context(self, *, user_data_dir: str, **kwargs) -> FakeContext:
        _ = kwargs
        self.launch_calls.append(user_data_dir)
        return self._context_factory(user_data_dir)

    async def stop(self) -> None:
        self.stopped = True


class FakeStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright
        self.start_calls = 0

    async def start(self) -> FakePlaywright:
        self.start_calls += 1
        return self.playwright


def test_patchright_uses_resolved_profile_dir_by_default():
    engine = BossClient(Settings())

    assert engine.profile_dir == (Settings().project_root / "data" / "chrome_profile").resolve()


def test_patchright_expands_env_profile_dir(monkeypatch):
    monkeypatch.setenv("JOB_BUDDY_PROFILE_DIR", "~/.job-buddy/chrome_profile")

    engine = BossClient(Settings())

    assert engine.profile_dir == (Path.home() / ".job-buddy" / "chrome_profile").resolve()
    assert "~" not in str(engine.profile_dir)


def test_patchright_check_page_health_initializes_once_and_reuses_browser(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())

    asyncio.run(engine.check_page_health())
    asyncio.run(engine.check_page_health())

    assert starter.start_calls == 1
    assert playwright.launch_calls == [str(engine.profile_dir)]
    assert engine.running is True
    assert engine.page is page
    assert engine.context is context


def test_patchright_check_page_health_restarts_when_page_is_closed(monkeypatch):
    first_page = FakePage()
    first_page.fail_eval = True
    second_page = FakePage()
    contexts = [FakeContext(first_page), FakeContext(second_page)]

    def build_context(_path: str) -> FakeContext:
        return contexts.pop(0)

    playwrights: list[FakePlaywright] = []

    class SequenceStarter:
        async def start(self) -> FakePlaywright:
            playwright = FakePlaywright(build_context)
            playwrights.append(playwright)
            return playwright

    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: SequenceStarter())

    engine = BossClient(Settings())

    asyncio.run(engine.check_page_health())
    first_context = engine.context
    asyncio.run(engine.check_page_health())

    assert len(playwrights) == 2
    assert first_context is not None and first_context.close_called is True
    assert engine.page is second_page
    assert engine.running is True


def test_patchright_close_resets_handles_and_stops_playwright(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    asyncio.run(engine.check_page_health())
    asyncio.run(engine.close())

    assert context.close_called is True
    assert playwright.stopped is True
    assert engine.running is False
    assert engine.page is None
    assert engine.context is None
    assert engine.playwright is None


def test_patchright_init_error_includes_profile_path(monkeypatch, tmp_path):
    profile_dir = tmp_path / "profiles" / "boss"
    monkeypatch.setenv("JOB_BUDDY_PROFILE_DIR", str(profile_dir))

    class FailingPlaywright:
        def __init__(self) -> None:
            self.chromium = self
            self.stopped = False

        async def launch_persistent_context(self, *, user_data_dir: str, **kwargs):
            _ = user_data_dir, kwargs
            raise RuntimeError("Target page, context or browser has been closed")

        async def stop(self) -> None:
            self.stopped = True

    failing = FailingPlaywright()

    class Starter:
        async def start(self) -> FailingPlaywright:
            return failing

    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: Starter())

    engine = BossClient(Settings())

    try:
        asyncio.run(engine.check_page_health())
    except BossOperationError as exc:
        assert exc.code == "REQUEST_FAILED"
        assert str(profile_dir.resolve()) in exc.message
        assert "profile 已有 Chrome 实例占用" in exc.message
    else:
        raise AssertionError("expected BossOperationError")

    assert failing.stopped is True


def test_patchright_login_returns_logged_in_result(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.extract_page = _async_result(LoginOut(logged_in=True, user_name="Alice", message="已登录"))  # type: ignore[method-assign]

    result = asyncio.run(engine.login(LoginIn()))

    assert result.logged_in is True
    assert result.user_name == "Alice"
    assert result.city == ""
    assert result.ip == ""
    assert result.uid == ""
    assert page.goto_calls == [
        ("https://www.zhipin.com/", "domcontentloaded"),
        ("https://www.zhipin.com/", "domcontentloaded"),
    ]


def test_patchright_healthcheck_reports_logged_in_state(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.extract_page = _async_result(LoginOut(logged_in=True, user_name="Alice", message="已登录"))  # type: ignore[method-assign]

    result = asyncio.run(engine.healthcheck())

    assert result.status == "ok"
    assert result.logged_in is True
    assert result.message == "已登录"


def test_patchright_search_fetches_jobs_via_browser_context(monkeypatch):
    page = FakePage()
    page.fetch_payload = {
        "code": 0,
        "zpData": {
            "jobList": [
                {
                    "encryptJobId": "job-1",
                    "securityId": "sec-1",
                    "jobName": "Python Backend Engineer",
                    "brandName": "Demo Tech",
                    "cityName": "上海",
                    "salaryDesc": "20-30K",
                    "jobExperience": "3-5年",
                    "jobUrl": "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
                    "welfareList": ["双休", "五险一金"],
                }
            ]
        },
    }
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]
    engine._page_cache = {"name": "Alice"}

    result = asyncio.run(
        engine.search(
            SearchIn(
                query={
                    "query": "python",
                    "city": "上海",
                    "salary": "20-30K",
                    "experience": "3-5年",
                    "page": 2,
                }
            )
        )
    )

    assert len(result.items) == 1
    assert result.items[0].job_id == "job-1"
    assert result.items[0].job_url == "https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1"
    assert page.last_fetch_url is not None
    parsed = urlparse(page.last_fetch_url)
    params = parse_qs(parsed.query)
    assert params["query"] == ["python"]
    assert params["page"] == ["2"]
    assert "city" in params
    assert "experience" in params
    assert page.last_fetch_referer == "https://www.zhipin.com/web/geek/job"


def test_patchright_search_accepts_keywords_array(monkeypatch):
    page = FakePage()
    page.fetch_payload = {"code": 0, "zpData": {"jobList": []}}
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    asyncio.run(engine.search(SearchIn(query={"keywords": ["Python", "FastAPI"], "page": 1})))

    assert page.last_fetch_url is not None
    parsed = urlparse(page.last_fetch_url)
    params = parse_qs(parsed.query)
    assert params["query"] == ["Python FastAPI"]


def test_patchright_search_does_not_require_login_inside_client(monkeypatch):
    page = FakePage()
    page.fetch_payload = {"code": 0, "zpData": {"jobList": []}}
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(False)  # type: ignore[method-assign]

    result = asyncio.run(engine.search(SearchIn(query={"query": "python"})))

    assert result.items == []
    assert page.last_fetch_url is not None


def test_patchright_greet_warns_with_payload_on_business_error(monkeypatch, caplog):
    page = FakePage()
    page.fetch_payload = {"code": 1, "message": "打招呼失败", "zpData": {"securityId": "sec-1"}}
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    with caplog.at_level("WARNING"):
        with pytest.raises(BossOperationError) as exc_info:
            asyncio.run(engine.greet(GreetJobIn(job_id="job-1", security_id="sec-1")))

    assert exc_info.value.message == "打招呼失败"
    assert "BossClient greet failed" in caplog.text
    assert "securityId" in caplog.text


def test_patchright_search_filters_by_welfare(monkeypatch):
    page = FakePage()
    page.fetch_payload = {
        "code": 0,
        "zpData": {
            "jobList": [
                {
                    "encryptJobId": "job-1",
                    "securityId": "sec-1",
                    "jobName": "Python Backend Engineer",
                    "brandName": "Demo Tech",
                    "cityName": "上海",
                    "salaryDesc": "20-30K",
                    "jobExperience": "3-5年",
                    "welfareList": ["双休", "五险一金"],
                },
                {
                    "encryptJobId": "job-2",
                    "securityId": "sec-2",
                    "jobName": "Platform Engineer",
                    "brandName": "Other Tech",
                    "cityName": "上海",
                    "salaryDesc": "25-35K",
                    "jobExperience": "5-10年",
                    "welfareList": ["单休"],
                },
            ]
        },
    }
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(engine.search(SearchIn(query={"query": "python", "welfare": "双休,五险一金"})))

    assert [item.job_id for item in result.items] == ["job-1"]


def test_patchright_detail_fetches_job_detail(monkeypatch):
    page = FakePage()
    page.fetch_payload = {
        "code": 0,
        "zpData": {
            "jobInfo": {
                "encryptId": "job-1",
                "securityId": "sec-1",
                "jobName": "Python Backend Engineer",
                "salaryDesc": "20-30K",
                "experienceName": "3-5年",
                "degreeName": "本科",
                "locationName": "上海",
                "address": "Demo Address",
                "showSkills": ["Python", "FastAPI"],
                "postDescription": "Build APIs",
                "jobStatusDesc": "在招",
            },
            "brandComInfo": {
                "brandName": "Demo Tech",
                "stageName": "A轮",
                "scaleName": "100-499人",
                "industryName": "互联网",
                "introduce": "Demo intro",
            },
            "bossInfo": {"name": "Alice", "title": "招聘经理"},
        },
    }
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(
        engine.detail(
            JobDetailIn(
                job_id="job-1",
                security_id="sec-1",
                job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
                title="Python Backend Engineer",
                company="Demo Tech",
            )
        )
    )

    assert result.job.title == "Python Backend Engineer"
    assert result.job.skills == ["Python", "FastAPI"]
    assert result.detail_text.startswith("职位名称：Python Backend Engineer")
    assert page.last_fetch_url is not None
    parsed = urlparse(page.last_fetch_url)
    params = parse_qs(parsed.query)
    assert params["securityId"] == ["sec-1"]


def test_patchright_greet_posts_browser_request(monkeypatch):
    page = FakePage()
    page.fetch_payload = {
        "code": 0,
        "zpData": {
            "ok": True,
            "securityId": "sec-1",
            "encBossId": "boss-1",
        },
    }
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(engine.greet(GreetJobIn(job_id="job-1", security_id="sec-1")))

    assert result.job_id == "job-1"
    assert result.security_id == "sec-1"
    assert page.last_fetch_url == "https://www.zhipin.com/wapi/zpgeek/friend/add.json"
    assert page.last_fetch_referer == "https://www.zhipin.com/web/geek/chat"
    assert page.last_fetch_body == {"securityId": "sec-1", "jobId": "job-1"}


def test_normalize_job_logs_payload_when_encrypt_job_id_missing(caplog):
    with caplog.at_level("ERROR"):
        with pytest.raises(BossOperationError) as exc_info:
            _normalize_job({"jobName": "Python Backend Engineer"})

    assert exc_info.value.message == "BOSS 返回字段缺失: encryptJobId"
    assert isinstance(exc_info.value.__cause__, KeyError)
    assert "scene=search" in caplog.text
    assert "encryptJobId" in caplog.text
    assert "Python Backend Engineer" in caplog.text
    assert "KeyError: 'encryptJobId'" in caplog.text


def test_normalize_job_detail_logs_payload_when_encrypt_id_missing(caplog):
    payload = {"zpData": {"jobInfo": {"securityId": "sec-1"}}}

    with caplog.at_level("ERROR"):
        with pytest.raises(BossOperationError) as exc_info:
            _normalize_job_detail(payload, {"job_id": "job-1", "security_id": "sec-1"})

    assert exc_info.value.message == "BOSS 返回字段缺失: zpData.jobInfo.encryptId"
    assert isinstance(exc_info.value.__cause__, KeyError)
    assert "scene=detail" in caplog.text
    assert "zpData.jobInfo.encryptId" in caplog.text
    assert "securityId" in caplog.text
    assert "KeyError: 'encryptId'" in caplog.text


def test_patchright_greet_logs_payload_when_security_id_missing(monkeypatch, caplog):
    page = FakePage()
    page.fetch_payload = {"code": 0, "zpData": {"encBossId": "boss-1"}}
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    with caplog.at_level("ERROR"):
        with pytest.raises(BossOperationError) as exc_info:
            asyncio.run(engine.greet(GreetJobIn(job_id="job-1", security_id="sec-1")))

    assert exc_info.value.message == "BOSS 返回字段缺失: zpData.securityId"
    assert isinstance(exc_info.value.__cause__, KeyError)
    assert "scene=greet" in caplog.text
    assert "encBossId" in caplog.text
    assert "KeyError: 'securityId'" in caplog.text


def test_patchright_chat_history_logs_payload_when_messages_missing(monkeypatch, caplog):
    page = FakePage()
    page.fetch_payload = {"code": 0, "zpData": {"hasMore": False}}
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    with caplog.at_level("ERROR"):
        with pytest.raises(BossOperationError) as exc_info:
            asyncio.run(engine.chat_history(ChatHistoryIn(boss_id="boss-1", security_id="sec-1", page=1, count=20)))

    assert exc_info.value.message == "BOSS 返回字段缺失: zpData.messages"
    assert isinstance(exc_info.value.__cause__, KeyError)
    assert "scene=chat_history" in caplog.text
    assert "hasMore" in caplog.text
    assert "KeyError: 'messages'" in caplog.text


def test_patchright_send_message_uses_geek_chat_page(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(
        engine.send_message(
            SendMessageIn(
                job_id="encrypt-1",
                gid="gid-1",
                self_id="self-1",
                boss_uid="uid-1",
                boss_id="boss-1",
                security_id="sec-1",
                content="你好",
                raw_payload={"uid": "uid-1"},
            )
        )
    )

    assert page.goto_calls[-1][0].startswith("https://www.zhipin.com/web/geek/chat?")
    assert page.goto_calls[-1][1] == "domcontentloaded"
    assert page.last_send_request["job_id"] == "encrypt-1"
    assert page.last_send_request["content"] == "你好"
    assert result.status == "sent"
    assert result.raw_payload["method"] == "dom.click.send"


def _async_result(value):
    async def runner(*args, **kwargs):
        _ = args, kwargs
        return value

    return runner


def test_job_detail_by_click_collects_details(monkeypatch):
    monkeypatch.setattr("job_buddy.boss.client.random", lambda: 0.0)
    monkeypatch.setattr("job_buddy.boss.client.asyncio.sleep", lambda delay: _async_result(None)())
    page = FakeDetailPage()
    page.job_titles_count = 2
    page.detail_responses = [
        {
            "code": 0,
            "zpData": {
                "jobInfo": {
                    "encryptId": "job-1",
                    "securityId": "sec-1",
                    "jobName": "Python Engineer",
                    "salaryDesc": "20-30K",
                    "experienceName": "3-5年",
                    "degreeName": "本科",
                    "locationName": "上海",
                    "address": "Demo Address",
                    "showSkills": ["Python"],
                    "postDescription": "Build APIs",
                    "jobStatusDesc": "在招",
                },
                "brandComInfo": {
                    "brandName": "Demo Tech",
                    "stageName": "A轮",
                    "scaleName": "100-499人",
                    "industryName": "互联网",
                    "introduce": "Demo intro",
                },
                "bossInfo": {"name": "Alice", "title": "招聘经理"},
            },
        },
        {
            "code": 0,
            "zpData": {
                "jobInfo": {
                    "encryptId": "job-2",
                    "securityId": "sec-2",
                    "jobName": "Go Engineer",
                    "salaryDesc": "30-40K",
                    "experienceName": "5-10年",
                    "degreeName": "本科",
                    "locationName": "北京",
                    "address": "Beijing Address",
                    "showSkills": ["Go"],
                    "postDescription": "Build services",
                    "jobStatusDesc": "在招",
                },
                "brandComInfo": {
                    "brandName": "Other Tech",
                    "stageName": "B轮",
                    "scaleName": "500-999人",
                    "industryName": "软件",
                    "introduce": "Other intro",
                },
                "bossInfo": {"name": "Bob", "title": "技术总监"},
            },
        },
    ]

    def trigger_responses():
        for callback in page._response_callbacks:
            for resp in page.detail_responses:
                callback(FakeResponse("https://www.zhipin.com/wapi/zpgeek/job/detail.json", resp))

    original_click = FakeNthLocator.click

    async def patched_click(self):
        await original_click(self)
        trigger_responses()

    monkeypatch.setattr(FakeNthLocator, "click", patched_click)

    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(engine.job_detail_by_click())

    assert len(result) == 2
    assert result[0].job.title == "Python Engineer"
    assert result[1].job.title == "Go Engineer"


def test_job_detail_by_click_dedupes_by_job_id(monkeypatch):
    monkeypatch.setattr("job_buddy.boss.client.random", lambda: 0.0)
    monkeypatch.setattr("job_buddy.boss.client.asyncio.sleep", lambda delay: _async_result(None)())
    page = FakeDetailPage()
    page.job_titles_count = 2
    page.detail_responses = [
        {
            "code": 0,
            "zpData": {
                "jobInfo": {
                    "encryptId": "job-1",
                    "securityId": "sec-1",
                    "jobName": "Python Engineer",
                    "salaryDesc": "20-30K",
                    "experienceName": "3-5年",
                    "degreeName": "本科",
                    "locationName": "上海",
                    "address": "Demo Address",
                    "showSkills": ["Python"],
                    "postDescription": "Build APIs",
                    "jobStatusDesc": "在招",
                },
                "brandComInfo": {
                    "brandName": "Demo Tech",
                    "stageName": "A轮",
                    "scaleName": "100-499人",
                    "industryName": "互联网",
                    "introduce": "Demo intro",
                },
                "bossInfo": {"name": "Alice", "title": "招聘经理"},
            },
        },
        {
            "code": 0,
            "zpData": {
                "jobInfo": {
                    "encryptId": "job-1",
                    "securityId": "sec-1",
                    "jobName": "Python Engineer Updated",
                    "salaryDesc": "25-35K",
                    "experienceName": "3-5年",
                    "degreeName": "本科",
                    "locationName": "上海",
                    "address": "Demo Address",
                    "showSkills": ["Python"],
                    "postDescription": "Build APIs",
                    "jobStatusDesc": "在招",
                },
                "brandComInfo": {
                    "brandName": "Demo Tech",
                    "stageName": "A轮",
                    "scaleName": "100-499人",
                    "industryName": "互联网",
                    "introduce": "Demo intro",
                },
                "bossInfo": {"name": "Alice", "title": "招聘经理"},
            },
        },
    ]

    def trigger_responses():
        for callback in page._response_callbacks:
            for resp in page.detail_responses:
                callback(FakeResponse("https://www.zhipin.com/wapi/zpgeek/job/detail.json", resp))

    original_click = FakeNthLocator.click

    async def patched_click(self):
        await original_click(self)
        trigger_responses()

    monkeypatch.setattr(FakeNthLocator, "click", patched_click)

    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(engine.job_detail_by_click())

    assert len(result) == 1
    assert result[0].job_id == "job-1"


def test_job_detail_by_click_skips_invalid_response(monkeypatch, caplog):
    monkeypatch.setattr("job_buddy.boss.client.random", lambda: 0.0)
    monkeypatch.setattr("job_buddy.boss.client.asyncio.sleep", lambda delay: _async_result(None)())
    page = FakeDetailPage()
    page.job_titles_count = 2
    page.detail_responses = [
        {"code": 0, "zpData": {}},
        {
            "code": 0,
            "zpData": {
                "jobInfo": {
                    "encryptId": "job-2",
                    "securityId": "sec-2",
                    "jobName": "Go Engineer",
                    "salaryDesc": "30-40K",
                    "experienceName": "5-10年",
                    "degreeName": "本科",
                    "locationName": "北京",
                    "address": "Beijing Address",
                    "showSkills": ["Go"],
                    "postDescription": "Build services",
                    "jobStatusDesc": "在招",
                },
                "brandComInfo": {
                    "brandName": "Other Tech",
                    "stageName": "B轮",
                    "scaleName": "500-999人",
                    "industryName": "软件",
                    "introduce": "Other intro",
                },
                "bossInfo": {"name": "Bob", "title": "技术总监"},
            },
        },
    ]

    def trigger_responses():
        for callback in page._response_callbacks:
            for resp in page.detail_responses:
                callback(FakeResponse("https://www.zhipin.com/wapi/zpgeek/job/detail.json", resp))

    original_click = FakeNthLocator.click

    async def patched_click(self):
        await original_click(self)
        trigger_responses()

    monkeypatch.setattr(FakeNthLocator, "click", patched_click)

    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.boss.client.async_playwright", lambda: starter)

    engine = BossClient(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(engine.job_detail_by_click())

    assert len(result) == 1
    assert result[0].job_id == "job-2"
    assert "handle response error" in caplog.text
