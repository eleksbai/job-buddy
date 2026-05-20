"""Standalone MCP server that communicates with the Job Buddy REST API over HTTP.

Run with:
    API_BASE_URL=http://localhost:8000 uv run job-buddy-mcp

The server uses stdio transport for maximum MCP client compatibility.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = httpx.Timeout(30.0)

mcp = FastMCP("Job Buddy MCP")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT)


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _error_result(error: str, status_code: int | None = None, raw: Any | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"success": False, "error": error}
    if status_code is not None:
        result["status_code"] = status_code
    if raw is not None:
        result["raw"] = raw
    return result


def _request_error_message(method: str, path: str, exc: httpx.HTTPError) -> str:
    return f"调用 REST API 失败: {method.upper()} {path}: {exc}"


async def _request_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | list[Any] | None, dict[str, Any] | None]:
    async with _client() as client:
        try:
            response = await client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            return False, None, _error_result(_request_error_message(method, path, exc))

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if response.is_success:
        return True, payload, None

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error") or payload.get("message")
    else:
        detail = None
    message = str(detail or f"请求失败: {response.status_code}")
    return False, payload, _error_result(message, status_code=response.status_code, raw=payload)


def _attach_raw(result: dict[str, Any], raw: Any, include_raw: bool) -> dict[str, Any]:
    if include_raw:
        result["raw"] = raw
    return result


def _summarize_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_job_id": job.get("source_job_id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "city": job.get("city"),
        "salary": job.get("salary"),
        "experience": job.get("experience"),
        "contact": job.get("contact"),
        "boss_online": job.get("boss_online"),
        "boss_active_text": job.get("boss_active_text"),
        "job_active_time": job.get("job_active_time"),
        "job_url": job.get("job_url"),
        "source_friend_id": job.get("source_friend_id"),
        "match_status": job.get("match_status"),
        "greeted": job.get("greeted"),
        "search_count": job.get("search_count"),
        "detail_fetched_at": job.get("detail_fetched_at"),
        "last_seen_at": job.get("last_seen_at"),
    }


def _summarize_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": target.get("id"),
        "name": target.get("name"),
        "keywords": target.get("keywords", []),
        "city": target.get("city"),
        "salary": target.get("salary"),
        "experience": target.get("experience"),
        "filters": target.get("filters", {}),
        "greeting_template": target.get("greeting_template"),
        "is_active": target.get("is_active"),
        "updated_at": target.get("updated_at"),
    }


def _summarize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("id"),
        "task_type": task.get("task_type"),
        "status": task.get("status"),
        "target_profile_id": task.get("target_profile_id"),
        "input_payload": task.get("input_payload", {}),
        "result_summary": task.get("result_summary", {}),
        "error_message": task.get("error_message"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "updated_at": task.get("updated_at"),
    }


def _summarize_greeting_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": record.get("id"),
        "task_id": record.get("task_id"),
        "job_lead_id": record.get("job_lead_id"),
        "source_job_id": record.get("source_job_id"),
        "status": record.get("status"),
        "message": record.get("message"),
        "response_payload": record.get("response_payload", {}),
    }


def _summarize_friend(friend: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_friend_id": friend.get("source_friend_id"),
        "name": friend.get("name"),
        "title": friend.get("title"),
        "company": friend.get("company"),
        "source_job_id": friend.get("source_job_id"),
        "security_id": friend.get("security_id"),
        "self_id": friend.get("self_id"),
        "last_message": friend.get("last_message"),
        "last_message_at": friend.get("last_message_at"),
        "unread_count": friend.get("unread_count"),
    }


def _summarize_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": message.get("message_id"),
        "from_id": message.get("from_id"),
        "from_name": message.get("from_name"),
        "content": message.get("content"),
        "type": message.get("type", message.get("msg_type")),
        "created_at": message.get("created_at", message.get("sent_at")),
        "received": message.get("received"),
        "status": message.get("status"),
    }


def _summarize_collection_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": record.get("id"),
        "task_id": record.get("task_id"),
        "target_profile_id": record.get("target_profile_id"),
        "source_job_id": record.get("source_job_id"),
        "security_id": record.get("security_id"),
        "title": record.get("title"),
        "company": record.get("company"),
        "city": record.get("city"),
        "salary": record.get("salary"),
        "experience": record.get("experience"),
        "job_url": record.get("job_url"),
        "collected_at": record.get("collected_at"),
    }


@mcp.tool
async def auth_status(include_raw: bool = False) -> dict[str, Any]:
    """查看当前登录状态和 BOSS 客户端健康状态。"""
    auth_ok, auth_payload, auth_error = await _request_json("GET", "/boss/system/auth")
    if not auth_ok:
        return auth_error or _error_result("获取登录状态失败")

    health_ok, health_payload, health_error = await _request_json("GET", "/web/health")
    if not health_ok:
        return health_error or _error_result("获取系统状态失败")

    auth_data = auth_payload if isinstance(auth_payload, dict) else {}
    health_data = health_payload if isinstance(health_payload, dict) else {}
    result = {
        "success": True,
        "logged_in": auth_data.get("logged_in"),
        "user_name": auth_data.get("user_name"),
        "login_method": auth_data.get("login_method"),
        "browser": auth_data.get("browser"),
        "message": auth_data.get("message"),
        "last_error": auth_data.get("last_error"),
        "boss_client": health_data.get("boss_client"),
        "service_status": health_data.get("status"),
        "mongodb": health_data.get("mongodb"),
    }
    return _attach_raw(result, {"auth": auth_payload, "health": health_payload}, include_raw)


@mcp.tool
async def login(include_raw: bool = False) -> dict[str, Any]:
    """触发 BOSS 登录流程。"""
    ok, payload, error = await _request_json("POST", "/boss/system/auth/login")
    if not ok:
        return error or _error_result("登录失败")
    data = payload if isinstance(payload, dict) else {}
    result = {
        "success": True,
        "logged_in": data.get("logged_in"),
        "user_name": data.get("user_name"),
        "message": data.get("message"),
        "browser": data.get("browser"),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def logout(include_raw: bool = False) -> dict[str, Any]:
    """退出当前 BOSS 登录状态。"""
    ok, payload, error = await _request_json("POST", "/boss/system/auth/logout")
    if not ok:
        return error or _error_result("退出登录失败")
    data = payload if isinstance(payload, dict) else {}
    result = {
        "success": True,
        "logged_in": data.get("logged_in"),
        "user_name": data.get("user_name"),
        "message": data.get("message"),
        "last_logout_at": data.get("last_logout_at"),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def doctor(include_raw: bool = False) -> dict[str, Any]:
    """运行 BOSS 诊断并返回关键摘要。"""
    ok, payload, error = await _request_json("GET", "/boss/system/doctor")
    if not ok:
        return error or _error_result("诊断失败")
    data = payload if isinstance(payload, dict) else {}
    result = {
        "success": True,
        "ok": data.get("ok"),
        "summary": data.get("summary"),
        "next_actions": data.get("next_actions", []),
        "checks": data.get("checks", []),
        "error_info": data.get("error"),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def system_health(include_raw: bool = False) -> dict[str, Any]:
    """查看服务健康状态。"""
    ok, payload, error = await _request_json("GET", "/web/health")
    if not ok:
        return error or _error_result("获取系统状态失败")
    data = payload if isinstance(payload, dict) else {}
    result = {
        "success": True,
        "status": data.get("status"),
        "mongodb": data.get("mongodb"),
        "boss_client": data.get("boss_client"),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def search_options(include_raw: bool = False) -> dict[str, Any]:
    """获取职位搜索可用筛选项。"""
    ok, payload, error = await _request_json("GET", "/web/system/search-options")
    if not ok:
        return error or _error_result("获取搜索选项失败")
    data = payload if isinstance(payload, dict) else {}
    result = {"success": True, **data}
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def recent_logs(limit: int = 200, include_raw: bool = False) -> dict[str, Any]:
    """查看最近日志。"""
    ok, payload, error = await _request_json("GET", "/web/system/logs", params={"limit": limit})
    if not ok:
        return error or _error_result("获取日志失败")
    data = payload if isinstance(payload, dict) else {}
    lines = data.get("lines", []) if isinstance(data.get("lines"), list) else []
    result = {
        "success": True,
        "count": len(lines),
        "lines": [line.get("text") if isinstance(line, dict) else str(line) for line in lines],
        "truncated": data.get("truncated"),
        "source": data.get("source"),
        "updated_at": data.get("updated_at"),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def clear_data(include_raw: bool = False) -> dict[str, Any]:
    """清空业务数据集合。"""
    ok, payload, error = await _request_json("POST", "/web/system/data/clear")
    if not ok:
        return error or _error_result("清空数据失败")
    data = payload if isinstance(payload, dict) else {}
    result = {
        "success": True,
        "deleted_counts": data.get("deleted_counts", {}),
        "total_deleted": data.get("total_deleted", 0),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def search_jobs(
    query: str,
    city: str | None = None,
    salary: str | None = None,
    experience: str | None = None,
    education: str | None = None,
    scale: str | None = None,
    industry: str | None = None,
    stage: str | None = None,
    job_type: str | None = None,
    page: int = 1,
    include_raw: bool = False,
) -> dict[str, Any]:
    """搜索职位并返回 agent 友好的职位摘要。"""
    payload = _compact_dict(
        {
            "query": query,
            "city": city,
            "salary": salary,
            "experience": experience,
            "education": education,
            "scale": scale,
            "industry": industry,
            "stage": stage,
            "job_type": job_type,
            "page": page,
        }
    )
    ok, response_payload, error = await _request_json("POST", "/boss/jobs/search", json=payload)
    if not ok:
        return error or _error_result("搜索职位失败")
    data = response_payload if isinstance(response_payload, dict) else {}
    items = data.get("items", []) if isinstance(data.get("items"), list) else []
    result = {
        "success": bool(data.get("success", True)),
        "count": data.get("count", len(items)),
        "items": [_summarize_job(item) for item in items if isinstance(item, dict)],
        "error": data.get("error"),
        "code": data.get("code"),
    }
    return _attach_raw(result, response_payload, include_raw)


@mcp.tool
async def job_detail(
    source_job_id: str,
    security_id: str | None = None,
    force_refresh: bool = False,
    include_raw: bool = False,
) -> dict[str, Any]:
    """查看职位详情，支持强制重新从 BOSS 拉取。"""
    params = _compact_dict({"security_id": security_id, "force_refresh": str(force_refresh).lower()})
    ok, payload, error = await _request_json("GET", f"/boss/jobs/{source_job_id}/detail", params=params)
    if not ok:
        return error or _error_result(f"获取职位详情失败: {source_job_id}")
    data = payload if isinstance(payload, dict) else {}
    job = data.get("job", {}) if isinstance(data.get("job"), dict) else {}
    detail_payload = job.get("detail_payload", {}) if isinstance(job.get("detail_payload"), dict) else {}
    sections = detail_payload.get("detail_payload", {}) if isinstance(detail_payload.get("detail_payload"), dict) else {}
    result = {
        "success": True,
        "cached": data.get("cached"),
        **_summarize_job(job),
        "detail_text": job.get("detail_text"),
        "job": sections.get("job"),
        "boss": sections.get("boss"),
        "company": sections.get("company"),
        "detail_payload": detail_payload,
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def list_jobs(
    limit: int = 100,
    match_status: str | None = None,
    greeted: bool | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """列出本地职位池。"""
    params = _compact_dict({"limit": limit, "match_status": match_status, "greeted": greeted})
    ok, payload, error = await _request_json("GET", "/boss/jobs", params=params)
    if not ok:
        return error or _error_result("获取职位列表失败")
    items = payload if isinstance(payload, list) else []
    result = {
        "success": True,
        "count": len(items),
        "items": [_summarize_job(item) for item in items if isinstance(item, dict)],
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def job_collection_records(
    limit: int = 100,
    task_id: str | None = None,
    target_profile_id: str | None = None,
    source_job_id: str | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """查看职位采集记录。"""
    params = _compact_dict(
        {
            "limit": limit,
            "task_id": task_id,
            "target_profile_id": target_profile_id,
            "source_job_id": source_job_id,
        }
    )
    ok, payload, error = await _request_json("GET", "/boss/jobs/collections", params=params)
    if not ok:
        return error or _error_result("获取职位采集记录失败")
    items = payload if isinstance(payload, list) else []
    result = {
        "success": True,
        "count": len(items),
        "items": [_summarize_collection_record(item) for item in items if isinstance(item, dict)],
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def list_friends(include_raw: bool = False) -> dict[str, Any]:
    """列出好友记录摘要。"""
    ok, payload, error = await _request_json("GET", "/boss/friends")
    if not ok:
        return error or _error_result("获取好友列表失败")
    items = payload if isinstance(payload, list) else []
    result = {
        "success": True,
        "count": len(items),
        "items": [_summarize_friend(item) for item in items if isinstance(item, dict)],
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def sync_friends(include_raw: bool = False) -> dict[str, Any]:
    """同步好友列表。"""
    ok, payload, error = await _request_json("POST", "/boss/friends/sync")
    if not ok:
        return error or _error_result("同步好友失败")
    data = payload if isinstance(payload, dict) else {}
    count = data.get("count", 0)
    result = {
        "success": True,
        "count": count,
        "message": f"已同步 {count} 条好友记录",
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def chat_history(
    source_friend_id: str,
    page: int = 1,
    count: int = 100,
    cached_only: bool = False,
    include_raw: bool = False,
) -> dict[str, Any]:
    """查看或同步与指定好友的聊天记录。"""
    params = {"page": page, "count": count, "cached_only": str(cached_only).lower()}
    ok, payload, error = await _request_json("GET", f"/boss/friends/{source_friend_id}/messages", params=params)
    if not ok:
        return error or _error_result(f"获取聊天记录失败: {source_friend_id}")
    data = payload if isinstance(payload, dict) else {}
    messages = data.get("messages", []) if isinstance(data.get("messages"), list) else []
    result = {
        "success": True,
        "friend": {
            "source_friend_id": data.get("source_friend_id"),
            "gid": data.get("gid"),
            "security_id": data.get("security_id"),
        },
        "page": data.get("page"),
        "count": data.get("count"),
        "total": data.get("total"),
        "has_more": data.get("has_more"),
        "messages": [_summarize_message(message) for message in messages if isinstance(message, dict)],
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def send_message(source_friend_id: str, content: str, include_raw: bool = False) -> dict[str, Any]:
    """向指定好友发送消息。"""
    ok, payload, error = await _request_json(
        "POST",
        f"/boss/friends/{source_friend_id}/messages/send",
        json={"content": content},
    )
    if not ok:
        return error or _error_result(f"发送消息失败: {source_friend_id}")
    data = payload if isinstance(payload, dict) else {}
    result = {
        "success": True,
        "source_friend_id": data.get("source_friend_id"),
        "gid": data.get("gid"),
        "content": data.get("content"),
        "status": data.get("status"),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def start_search_task(
    target_profile_id: str | None = None,
    query_override: dict[str, Any] | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """触发职位搜索任务。"""
    payload = {
        "target_profile_id": target_profile_id,
        "query_override": query_override or {},
    }
    ok, response_payload, error = await _request_json("POST", "/boss/tasks/search", json=payload)
    if not ok:
        return error or _error_result("启动搜索任务失败")
    data = response_payload if isinstance(response_payload, dict) else {}
    result = {
        "success": True,
        "task_id": data.get("task_id"),
        "status": data.get("status"),
    }
    return _attach_raw(result, response_payload, include_raw)


@mcp.tool
async def start_greet_task(
    target_profile_id: str | None = None,
    source_job_ids: list[str] | None = None,
    greeting_message: str | None = None,
    limit: int = 20,
    include_raw: bool = False,
) -> dict[str, Any]:
    """触发批量打招呼任务。"""
    payload = {
        "target_profile_id": target_profile_id,
        "source_job_ids": source_job_ids or [],
        "greeting_message": greeting_message,
        "limit": limit,
    }
    ok, response_payload, error = await _request_json("POST", "/boss/tasks/greet", json=payload)
    if not ok:
        return error or _error_result("启动打招呼任务失败")
    data = response_payload if isinstance(response_payload, dict) else {}
    result = {
        "success": True,
        "task_id": data.get("task_id"),
        "status": data.get("status"),
    }
    return _attach_raw(result, response_payload, include_raw)


@mcp.tool
async def list_tasks(limit: int = 100, include_raw: bool = False) -> dict[str, Any]:
    """列出任务。"""
    ok, payload, error = await _request_json("GET", "/boss/tasks", params={"limit": limit})
    if not ok:
        return error or _error_result("获取任务列表失败")
    items = payload if isinstance(payload, list) else []
    result = {
        "success": True,
        "count": len(items),
        "items": [_summarize_task(item) for item in items if isinstance(item, dict)],
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def task_detail(task_id: str, include_raw: bool = False) -> dict[str, Any]:
    """查看任务详情。"""
    ok, payload, error = await _request_json("GET", f"/boss/tasks/{task_id}")
    if not ok:
        return error or _error_result(f"获取任务详情失败: {task_id}")
    data = payload if isinstance(payload, dict) else {}
    task = data.get("task", {}) if isinstance(data.get("task"), dict) else {}
    records = data.get("records", []) if isinstance(data.get("records"), list) else []
    result = {
        "success": True,
        "task": _summarize_task(task),
        "records": [_summarize_greeting_record(record) for record in records if isinstance(record, dict)],
        "count": len(records),
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def list_targets(include_raw: bool = False) -> dict[str, Any]:
    """列出目标配置。"""
    ok, payload, error = await _request_json("GET", "/web/targets")
    if not ok:
        return error or _error_result("获取目标列表失败")
    items = payload if isinstance(payload, list) else []
    result = {
        "success": True,
        "count": len(items),
        "items": [_summarize_target(item) for item in items if isinstance(item, dict)],
    }
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def target_detail(target_id: str, include_raw: bool = False) -> dict[str, Any]:
    """查看单个目标配置。"""
    ok, payload, error = await _request_json("GET", f"/web/targets/{target_id}")
    if not ok:
        return error or _error_result(f"获取目标详情失败: {target_id}")
    data = payload if isinstance(payload, dict) else {}
    result = {"success": True, **_summarize_target(data)}
    return _attach_raw(result, payload, include_raw)


@mcp.tool
async def create_target(
    name: str,
    keywords: list[str] | None = None,
    city: str | None = None,
    salary: str | None = None,
    experience: str | None = None,
    filters: dict[str, Any] | None = None,
    greeting_template: str | None = None,
    is_active: bool = True,
    include_raw: bool = False,
) -> dict[str, Any]:
    """创建目标配置。"""
    payload = {
        "name": name,
        "keywords": keywords or [],
        "city": city,
        "salary": salary,
        "experience": experience,
        "filters": filters or {},
        "greeting_template": greeting_template,
        "is_active": is_active,
    }
    ok, response_payload, error = await _request_json("POST", "/web/targets", json=payload)
    if not ok:
        return error or _error_result("创建目标失败")
    data = response_payload if isinstance(response_payload, dict) else {}
    result = {"success": True, **_summarize_target(data)}
    return _attach_raw(result, response_payload, include_raw)


@mcp.tool
async def update_target(
    target_id: str,
    name: str | None = None,
    keywords: list[str] | None = None,
    city: str | None = None,
    salary: str | None = None,
    experience: str | None = None,
    filters: dict[str, Any] | None = None,
    greeting_template: str | None = None,
    is_active: bool | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """更新目标配置。"""
    payload = _compact_dict(
        {
            "name": name,
            "keywords": keywords,
            "city": city,
            "salary": salary,
            "experience": experience,
            "filters": filters,
            "greeting_template": greeting_template,
            "is_active": is_active,
        }
    )
    ok, response_payload, error = await _request_json("PUT", f"/web/targets/{target_id}", json=payload)
    if not ok:
        return error or _error_result(f"更新目标失败: {target_id}")
    data = response_payload if isinstance(response_payload, dict) else {}
    result = {"success": True, **_summarize_target(data)}
    return _attach_raw(result, response_payload, include_raw)


@mcp.tool
async def delete_target(target_id: str) -> dict[str, Any]:
    """删除目标配置。"""
    ok, payload, error = await _request_json("DELETE", f"/web/targets/{target_id}")
    if not ok:
        return error or _error_result(f"删除目标失败: {target_id}")
    return {"success": True, "target_id": target_id, "message": "目标已删除", "raw": payload}


def main() -> None:
    """CLI entry point: runs the MCP server on stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
