import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from job_buddy.core.boss import BossOperationError
from job_buddy.core.config import Settings
from job_buddy.core.engines.models import JobDetailRequest, LoginRequest, SearchRequest
from job_buddy.core.engines.patchright import PatchrightEngine


class FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.evaluate_calls: list[str] = []
        self.fail_eval = False
        self.fetch_payload: dict | None = None
        self.last_fetch_url: str | None = None
        self.last_fetch_referer: str | None = None

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
            return self.fetch_payload or {"code": 0, "zpData": {"jobList": []}}
        return 1

    async def wait_for_load_state(self, state: str) -> None:
        _ = state
        return None

    async def bring_to_front(self) -> None:
        return None


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


def test_patchright_uses_resolved_profile_dir_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    engine = PatchrightEngine(Settings())

    assert engine.profile_dir == (tmp_path / "data" / "chrome_profile").resolve()


def test_patchright_expands_env_profile_dir(monkeypatch):
    monkeypatch.setenv("JOB_BUDDY_PROFILE_DIR", "~/.job-buddy/chrome_profile")

    engine = PatchrightEngine(Settings())

    assert engine.profile_dir == (Path.home() / ".job-buddy" / "chrome_profile").resolve()
    assert "~" not in str(engine.profile_dir)


def test_patchright_check_page_health_initializes_once_and_reuses_browser(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())

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

    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: SequenceStarter())

    engine = PatchrightEngine(Settings())

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
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
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

    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: Starter())

    engine = PatchrightEngine(Settings())

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
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]
    engine._page_cache = {"name": "Alice"}

    result = asyncio.run(engine.login(LoginRequest()))

    assert result.logged_in is True
    assert result.user_name == "Alice"
    assert result.login_method == "patchright"
    assert page.goto_calls == [("https://www.zhipin.com/", "domcontentloaded")]


def test_patchright_healthcheck_reports_logged_in_state(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]
    engine._page_cache = {"name": "Alice"}

    result = asyncio.run(engine.healthcheck())

    assert result["status"] == "ok"
    assert result["logged_in"] is True
    assert result["message"] == "已登录"


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
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]
    engine._page_cache = {"name": "Alice"}

    result = asyncio.run(
        engine.search(
            SearchRequest(
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
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    asyncio.run(engine.search(SearchRequest(query={"keywords": ["Python", "FastAPI"], "page": 1})))

    assert page.last_fetch_url is not None
    parsed = urlparse(page.last_fetch_url)
    params = parse_qs(parsed.query)
    assert params["query"] == ["Python FastAPI"]


def test_patchright_search_requires_login(monkeypatch):
    page = FakePage()
    context = FakeContext(page)
    playwright = FakePlaywright(lambda _path: context)
    starter = FakeStarter(playwright)
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
    engine.is_login = _async_result(False)  # type: ignore[method-assign]

    try:
        asyncio.run(engine.search(SearchRequest(query={"query": "python"})))
    except BossOperationError as exc:
        assert exc.code == "AUTH_REQUIRED"
    else:
        raise AssertionError("expected BossOperationError")


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
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(engine.search(SearchRequest(query={"query": "python", "welfare": "双休,五险一金"})))

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
    monkeypatch.setattr("job_buddy.core.engines.patchright.async_playwright", lambda: starter)

    engine = PatchrightEngine(Settings())
    engine.is_login = _async_result(True)  # type: ignore[method-assign]

    result = asyncio.run(
        engine.detail(
            JobDetailRequest(
                job_id="job-1",
                security_id="sec-1",
                job_url="https://www.zhipin.com/job_detail/job-1.html?securityId=sec-1",
                title="Python Backend Engineer",
                company="Demo Tech",
            )
        )
    )

    assert result["job"]["title"] == "Python Backend Engineer"
    assert result["job"]["skills"] == ["Python", "FastAPI"]
    assert result["detail_text"].startswith("职位名称：Python Backend Engineer")
    assert page.last_fetch_url is not None
    parsed = urlparse(page.last_fetch_url)
    params = parse_qs(parsed.query)
    assert params["securityId"] == ["sec-1"]


def _async_result(value):
    async def runner(*args, **kwargs):
        _ = args, kwargs
        return value

    return runner
