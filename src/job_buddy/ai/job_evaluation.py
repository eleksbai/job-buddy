"""AI job matching client — pure AI layer (LLM calls + prompt building)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from job_buddy.config import Settings
from job_buddy.models import JobLead

logger = logging.getLogger(__name__)


def _load_markdown(path: Path) -> str:
    """Read a markdown file and return its content."""
    if not path.exists():
        raise FileNotFoundError(f"Markdown 文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def build_evaluation_prompt(
    job: JobLead,
    resume_text: str,
    criteria_text: str,
) -> str:
    """Build the evaluation prompt for a single job."""
    job_info_parts = [
        f"岗位名称: {job.title}",
        f"公司: {job.company}",
        f"城市: {job.city or '未知'}",
        f"薪资: {job.salary or '未知'}",
        f"经验要求: {job.experience or '未知'}",
    ]
    if job.detail_text:
        job_info_parts.append(f"岗位描述: {job.detail_text}")

    job_info = "\n".join(job_info_parts)

    prompt = f"""你是一位专业的求职顾问。请根据以下信息，评估候选人与岗位的匹配程度。

## 候选人简历
{resume_text}

## 匹配标准
{criteria_text}

## 岗位信息
{job_info}

## 评估要求
请综合考虑候选人的技能、经验与岗位要求的匹配程度，给出客观评估。返回 JSON 格式：

```json
{{
  "match": true/false,
  "score": 0-100 的整数,
  "reasoning": "评估理由（中文，简洁）"
}}
```

match 为 true 表示候选人基本符合岗位要求，false 表示不匹配。score 仅在同为 match=true 的岗位之间用于排序。"""

    return prompt


def build_message_prompt(
    job: JobLead,
    resume_text: str,
    criteria_text: str,
    conversation_style_text: str,
    chat_history: list[dict[str, Any]],
    existing_context: str | None = None,
) -> str:
    """Build the prompt for generating a chat message to a boss."""

    job_info_parts = [
        f"岗位名称: {job.title}",
        f"公司: {job.company}",
        f"城市: {job.city or '未知'}",
        f"薪资: {job.salary or '未知'}",
        f"经验要求: {job.experience or '未知'}",
    ]
    if job.detail_text:
        job_info_parts.append(f"岗位描述: {job.detail_text}")

    job_info = "\n".join(job_info_parts)

    history_text = "无历史对话"
    if chat_history:
        lines = []
        for msg in chat_history[-20:]:
            from_name = msg.get("from_name") or msg.get("from_id", "")
            content = msg.get("content", "")
            msg_type = msg.get("type") or msg.get("msg_type", 0)
            if msg_type == 1:
                lines.append(f"{from_name}: {content}")
        if lines:
            history_text = "\n".join(lines)

    context_hint = ""
    if existing_context and existing_context.strip():
        context_hint = f"\n当前输入框中已有草稿内容，可在此基础上优化或改写：\n{existing_context}"

    prompt = f"""你是一位求职者的 AI 助手，正在帮助用户起草一条发给 BOSS 直聘上的招聘者的消息。

## 沟通风格要求（必须严格遵守）
{conversation_style_text}

## 候选人简历
{resume_text}


## 目标岗位信息
{job_info}

## 已有聊天记录
{history_text}
{context_hint}
## 要求
请严格按照上述"沟通风格要求"生成一条合适的中文消息草稿。

返回 JSON 格式：
```json
{{
  "message": "生成的消息内容",
  "reasoning": "生成这条消息的理由（中文，简洁）"
}}
```"""

    return prompt


class AIMatchingClient:
    """Async client for calling LLM to evaluate job-candidate match."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.ai_api_base_url,
            api_key=settings.ai_api_key,
        )
        self._model = settings.ai_model
        self._temperature = settings.ai_temperature

    async def evaluate(self, prompt: str) -> dict[str, Any]:
        """Send prompt to LLM, return parsed result dict.

        Returns:
            {"match": bool, "score": int, "reasoning": str}
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的求职顾问助手。总是严格按照 JSON 格式输出评估结果。",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        reasoning_content = getattr(response.choices[0].message, "reasoning_content", None)
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        cache_hit_tokens = getattr(usage, "prompt_cache_hit_tokens", None) if usage else None

        if not content:
            logger.warning("LLM returned empty content")
            return {
                "match": False, "score": 0, "reasoning": "AI 返回空结果",
                "reasoning_content": reasoning_content,
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "cache_hit_tokens": cache_hit_tokens,
            }

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON: %s", content[:200])
            return {
                "match": False, "score": 0, "reasoning": f"AI 返回格式异常: {content[:100]}",
                "reasoning_content": reasoning_content,
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "cache_hit_tokens": cache_hit_tokens,
            }

        return {
            "match": bool(result.get("match", False)),
            "score": max(0, min(100, int(result.get("score", 0)))),
            "reasoning": str(result.get("reasoning", "")),
            "reasoning_content": reasoning_content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_hit_tokens": cache_hit_tokens,
        }

    async def generate_message(self, prompt: str) -> dict[str, Any]:
        """Send prompt to LLM, return message generation result.

        Returns:
            {"message": str, "reasoning": str, "reasoning_content": str | None,
             "prompt_tokens": int | None, "completion_tokens": int | None,
             "cache_hit_tokens": int | None}
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的求职沟通助手。总是严格按照 JSON 格式输出消息草稿与理由。",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        reasoning_content = getattr(response.choices[0].message, "reasoning_content", None)
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        cache_hit_tokens = getattr(usage, "prompt_cache_hit_tokens", None) if usage else None

        if not content:
            logger.warning("LLM returned empty content for message generation")
            return {
                "message": "", "reasoning": "AI 返回空结果",
                "reasoning_content": reasoning_content,
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "cache_hit_tokens": cache_hit_tokens,
            }

        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse message generation response as JSON: %s", content[:200])
            return {
                "message": "", "reasoning": f"AI 返回格式异常: {content[:100]}",
                "reasoning_content": reasoning_content,
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "cache_hit_tokens": cache_hit_tokens,
            }

        return {
            "message": str(result.get("message", "")),
            "reasoning": str(result.get("reasoning", "")),
            "reasoning_content": reasoning_content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache_hit_tokens": cache_hit_tokens,
        }
