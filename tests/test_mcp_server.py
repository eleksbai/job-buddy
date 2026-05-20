from __future__ import annotations

import httpx
import pytest

from job_buddy import mcp_server


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses: dict[tuple[str, str], FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method: str, path: str, params=None, json=None):
        self.calls.append((method, path, params, json))
        key = (method.upper(), path)
        response = self.responses.get(key)
        if response is None:
            raise AssertionError(f"unexpected request: {key}")
        return response


@pytest.mark.asyncio
async def test_job_detail_supports_force_refresh_and_raw(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient(
        {
            ("GET", "/boss/jobs/job-1/detail"): FakeResponse(
                200,
                {
                    "cached": False,
                    "job": {
                        "source_job_id": "job-1",
                        "title": "Python Backend Engineer",
                        "company": "Demo Tech",
                        "contact": True,
                        "boss_online": False,
                        "boss_active_text": "本周活跃",
                        "job_active_time": 1779249002309,
                        "encrypt_boss_id": "boss-1",
                        "detail_text": "职位描述",
                        "detail_payload": {
                            "detail_payload": {
                                "job": {"title": "Python Backend Engineer"},
                                "boss": {"name": "Alice"},
                                "company": {"name": "Demo Tech"},
                            }
                        },
                    },
                },
            )
        }
    )
    monkeypatch.setattr(mcp_server, "_client", lambda: client)

    result = await mcp_server.job_detail("job-1", security_id="sec-1", force_refresh=True, include_raw=True)

    assert result["success"] is True
    assert result["cached"] is False
    assert result["job_active_time"] == 1779249002309
    assert result["boss"]["name"] == "Alice"
    assert result["raw"]["job"]["source_job_id"] == "job-1"
    assert client.calls == [
        ("GET", "/boss/jobs/job-1/detail", {"security_id": "sec-1", "force_refresh": "true"}, None)
    ]


@pytest.mark.asyncio
async def test_search_jobs_returns_agent_friendly_items(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient(
        {
            ("POST", "/boss/jobs/search"): FakeResponse(
                200,
                {
                    "success": True,
                    "count": 1,
                    "items": [
                        {
                            "source_job_id": "job-1",
                            "title": "Python",
                            "company": "Demo",
                            "city": "上海",
                            "salary": "20-30K",
                            "experience": "3-5年",
                            "contact": False,
                            "boss_online": True,
                            "boss_active_text": "刚刚活跃",
                            "job_active_time": 1779249002309,
                            "job_url": "https://example.com/job-1",
                            "encrypt_boss_id": "boss-1",
                        }
                    ],
                },
            )
        }
    )
    monkeypatch.setattr(mcp_server, "_client", lambda: client)

    result = await mcp_server.search_jobs("Python", city="上海")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["items"][0]["boss_active_text"] == "刚刚活跃"
    assert result["items"][0]["job_active_time"] == 1779249002309


@pytest.mark.asyncio
async def test_chat_history_supports_cached_only(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient(
        {
            ("GET", "/boss/friends/boss-1/messages"): FakeResponse(
                200,
                {
                    "gid": "gid-1",
                    "friend_id": "boss-1",
                    "security_id": "sec-1",
                    "page": 1,
                    "count": 100,
                    "total": 1,
                    "has_more": False,
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "from_id": "boss-1",
                            "from_name": "Alice",
                            "content": "你好",
                            "type": 1,
                            "created_at": 1779249002309,
                            "received": True,
                            "status": 1,
                        }
                    ],
                },
            )
        }
    )
    monkeypatch.setattr(mcp_server, "_client", lambda: client)

    result = await mcp_server.chat_history("boss-1", cached_only=True)

    assert result["success"] is True
    assert result["friend"]["security_id"] == "sec-1"
    assert result["messages"][0]["from_name"] == "Alice"
    assert client.calls == [
        ("GET", "/boss/friends/boss-1/messages", {"page": 1, "count": 100, "cached_only": "true"}, None)
    ]


@pytest.mark.asyncio
async def test_create_target_returns_summary(monkeypatch: pytest.MonkeyPatch):
    client = FakeClient(
        {
            ("POST", "/web/targets"): FakeResponse(
                201,
                {
                    "id": "target-1",
                    "name": "Data",
                    "keywords": ["Python", "ETL"],
                    "city": "上海",
                    "salary": "20-30K",
                    "experience": "3-5年",
                    "filters": {"industry": "互联网"},
                    "greeting_template": "你好",
                    "is_active": True,
                    "updated_at": "2026-05-20T10:00:00Z",
                },
            )
        }
    )
    monkeypatch.setattr(mcp_server, "_client", lambda: client)

    result = await mcp_server.create_target(
        name="Data",
        keywords=["Python", "ETL"],
        city="上海",
        filters={"industry": "互联网"},
    )

    assert result["success"] is True
    assert result["target_id"] == "target-1"
    assert result["keywords"] == ["Python", "ETL"]


@pytest.mark.asyncio
async def test_request_json_wraps_http_error(monkeypatch: pytest.MonkeyPatch):
    class ErrorClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method: str, path: str, params=None, json=None):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(mcp_server, "_client", lambda: ErrorClient())

    result = await mcp_server.send_message("boss-1", "你好")

    assert result["success"] is False
    assert "调用 REST API 失败" in result["error"]
