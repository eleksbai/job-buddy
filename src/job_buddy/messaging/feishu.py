from __future__ import annotations

import asyncio
import logging

from lark_oapi.channel import FeishuChannel
from motor.motor_asyncio import AsyncIOMotorDatabase

from job_buddy.config import get_settings
from job_buddy.models import FeishuCredential

logger = logging.getLogger(__name__)


class FeishuChannelManager:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self._database = database
        self._channel: FeishuChannel | None = None
        self._chat_id: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._enabled = False

    async def start(self) -> None:
        settings = get_settings()
        if not settings.feishu.enabled:
            logger.info("Feishu channel disabled by config")
            return

        doc = await self._database["feishu_credentials"].find_one()
        if not doc or not doc.get("app_id"):
            logger.info("No Feishu credentials found in database, channel disabled")
            return

        credential = FeishuCredential.from_mongo(doc)
        self._chat_id = credential.chat_id or None
        self._enabled = True

        self._channel = FeishuChannel(
            app_id=credential.app_id,
            app_secret=credential.app_secret,
        )
        self._channel.on("message", self._on_message)
        self._task = asyncio.create_task(self._channel.connect())
        logger.info("Feishu channel started")

    async def _on_message(self, msg) -> None:
        chat_id = getattr(msg, "chat_id", None)
        if not chat_id:
            return
        if not self._chat_id:
            self._chat_id = chat_id
            await self._database["feishu_credentials"].update_one(
                {}, {"$set": {"chat_id": chat_id}}
            )
            logger.info("Feishu chat_id saved: %s", chat_id)
        await self._channel.send(self._chat_id, {"text": "收到"})

    async def send(self, text: str) -> bool:
        if not self._enabled or not self._channel or not self._chat_id:
            return False
        try:
            await self._channel.send(self._chat_id, {"text": text})
            return True
        except Exception:
            logger.exception("Failed to send Feishu message")
            return False

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._channel = None
        self._enabled = False
        logger.info("Feishu channel stopped")


_manager: FeishuChannelManager | None = None


def set_manager(manager: FeishuChannelManager) -> None:
    global _manager
    _manager = manager


async def send_feishu(message: str) -> bool:
    if _manager is None:
        return False
    return await _manager.send(message)
