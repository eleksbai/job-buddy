"""Standalone MCP server that communicates with the Job Buddy FastAPI REST API over HTTP.

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


# ── Auth ────────────────────────────────────────────────────────


@mcp.tool
async def login() -> dict[str, Any]:
    """触发 BOSS直聘 登录流程。会在浏览器中打开登录页面，请扫码登录。"""
    async with _client() as client:
        try:
            resp = await client.post("/api/system/auth/login")
            resp.raise_for_status()
            data = resp.json()
            return {
                "logged_in": data["logged_in"],
                "user_name": data.get("user_name"),
                "message": data.get("message", ""),
            }
        except httpx.HTTPError as exc:
            return {"logged_in": False, "error": f"API unreachable: {exc}"}


@mcp.tool
async def get_auth_status() -> dict[str, Any]:
    """查看当前 BOSS直聘 登录状态。"""
    async with _client() as client:
        try:
            auth_resp = await client.get("/api/system/auth")
            auth_resp.raise_for_status()
            auth_data = auth_resp.json()

            health_resp = await client.get("/health")
            health_resp.raise_for_status()
            health_data = health_resp.json()
        except httpx.HTTPError as exc:
            return {"logged_in": False, "error": f"API unreachable: {exc}"}

        return {
            "logged_in": auth_data["logged_in"],
            "user_name": auth_data.get("user_name"),
            "message": auth_data.get("message", ""),
            "browser": auth_data.get("browser"),
            "boss_client": health_data.get("boss_client", "unknown"),
        }


# ── Search ──────────────────────────────────────────────────────


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
) -> dict[str, Any]:
    """在 BOSS直聘 搜索职位。

    Args:
        query: 搜索关键词，例如 "Python"、"前端开发"
        city: 城市名称，例如 "北京"、"上海"、"深圳"、"杭州"
        salary: 薪资范围，可选: 3K以下, 3-5K, 5-10K, 10-15K, 10-20K, 20-50K, 50K以上
        experience: 经验要求，可选: 应届, 1年以内, 1-3年, 3-5年, 5-10年, 10年以上
        education: 学历要求，可选: 大专, 本科, 硕士, 博士
        scale: 公司规模，可选: 0-20人, 20-99人, 100-499人, 500-999人, 1000-9999人, 10000人以上
        industry: 行业，例如 "互联网"、"金融"、"人工智能"
        stage: 融资阶段，可选: 未融资, 天使轮, A轮, B轮, C轮
        job_type: 职位类型
        page: 页码，默认 1
    """
    payload: dict[str, object] = {"query": query, "page": page}
    if city:
        payload["city"] = city
    if salary:
        payload["salary"] = salary
    if experience:
        payload["experience"] = experience
    if education:
        payload["education"] = education
    if scale:
        payload["scale"] = scale
    if industry:
        payload["industry"] = industry
    if stage:
        payload["stage"] = stage
    if job_type:
        payload["job_type"] = job_type

    async with _client() as client:
        try:
            resp = await client.post("/api/jobs/search", json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"API unreachable: {exc}"}


# ── Detail ──────────────────────────────────────────────────────


@mcp.tool
async def get_job_detail(job_id: str) -> dict[str, Any]:
    """查看职位详情。

    优先从本地缓存获取，缓存未命中时从 BOSS直聘 实时拉取。

    Args:
        job_id: BOSS直聘 职位 ID
    """
    async with _client() as client:
        try:
            resp = await client.get(f"/api/jobs/{job_id}/detail")
            if resp.status_code == 404:
                return {
                    "success": False,
                    "error": f"未找到职位 {job_id}，请先通过 search_jobs 搜索获取",
                }
            resp.raise_for_status()
            data = resp.json()
            job = data.get("job", {})
            return {
                "success": True,
                "cached": data.get("cached", False),
                "job_id": job.get("source_job_id"),
                "title": job.get("title"),
                "company": job.get("company"),
                "city": job.get("city"),
                "salary": job.get("salary"),
                "experience": job.get("experience"),
                "job_url": job.get("job_url"),
                "detail_text": job.get("detail_text"),
                "match_status": job.get("match_status"),
                "greeted": job.get("greeted"),
            }
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"API unreachable: {exc}"}


# ── Database queries ────────────────────────────────────────────


@mcp.tool
async def list_targets(limit: int = 100) -> list[dict[str, Any]]:
    """列出搜索目标配置。"""
    async with _client() as client:
        try:
            resp = await client.get("/api/targets")
            resp.raise_for_status()
            return resp.json()[:limit]
        except httpx.HTTPError as exc:
            return [{"error": f"API unreachable: {exc}"}]


@mcp.tool
async def list_jobs(
    limit: int = 100,
    match_status: str | None = None,
    greeted: bool | None = None,
) -> list[dict[str, Any]]:
    """列出职位线索，可按状态筛选。

    Args:
        limit: 返回数量上限
        match_status: 匹配状态筛选 (new/matched)
        greeted: 是否已打招呼
    """
    params: dict[str, str] = {"limit": str(limit)}
    if match_status:
        params["match_status"] = match_status
    if greeted is not None:
        params["greeted"] = str(greeted).lower()

    async with _client() as client:
        try:
            resp = await client.get("/api/jobs", params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return [{"error": f"API unreachable: {exc}"}]


@mcp.tool
async def list_job_collection_records(limit: int = 100) -> list[dict[str, Any]]:
    """列出职位采集原始记录。"""
    async with _client() as client:
        try:
            resp = await client.get("/api/jobs/collections", params={"limit": str(limit)})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return [{"error": f"API unreachable: {exc}"}]


@mcp.tool
async def list_tasks(limit: int = 100) -> list[dict[str, Any]]:
    """列出异步任务记录。"""
    async with _client() as client:
        try:
            resp = await client.get("/api/tasks", params={"limit": str(limit)})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return [{"error": f"API unreachable: {exc}"}]


@mcp.tool
async def get_task(task_id: str) -> dict[str, Any] | None:
    """查看指定任务的详情。"""
    async with _client() as client:
        try:
            resp = await client.get(f"/api/tasks/{task_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return {"error": f"API unreachable: {exc}"}


@mcp.tool
async def list_conversations(limit: int = 100) -> list[dict[str, Any]]:
    """列出同步的对话记录。"""
    async with _client() as client:
        try:
            resp = await client.get("/api/conversations", params={"limit": str(limit)})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            return [{"error": f"API unreachable: {exc}"}]


@mcp.tool
async def get_system_status() -> dict[str, Any]:
    """查看系统状态和 BOSS直聘 连接状态。"""
    async with _client() as client:
        try:
            resp = await client.get("/health")
            resp.raise_for_status()
            data = resp.json()
            return {
                "status": "ok",
                "boss_client": data.get("boss_client", "unknown"),
            }
        except httpx.HTTPError as exc:
            return {"status": "error", "boss_client": f"API unreachable: {exc}"}


def main() -> None:
    """CLI entry point: runs the MCP server on stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
