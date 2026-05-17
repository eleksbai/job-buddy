from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from job_buddy.core.boss import BossClientProtocol, BossOperationError, map_boss_operation_error
from job_buddy.modules.common import BaseRepository, DocumentModel, TimestampedSchema, utc_now

_CST = timezone(timedelta(hours=8))


def _format_last_time(ts_ms: float) -> str:
    """从毫秒时间戳推导中文显示文本：今天 14:30 / 昨天 09:15 / 前天 18:00 / 5月3日 10:00"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=_CST)
    now = datetime.now(tz=_CST)
    today = now.date()
    date = dt.date()
    hm = dt.strftime("%H:%M")
    if date == today:
        return f"今天 {hm}"
    if date == today - timedelta(days=1):
        return f"昨天 {hm}"
    if date == today - timedelta(days=2):
        return f"前天 {hm}"
    if date.year == today.year:
        return f"{date.month}月{date.day}日 {hm}"
    return f"{date.year}年{date.month}月{date.day}日 {hm}"


class ConversationRecord(DocumentModel):
    source: str = "boss"
    source_conversation_id: str  # friend_id or gid
    gid: str = ""
    security_id: str | None = None
    job_id: int | None = None
    encrypt_job_id: str | None = None
    encrypt_boss_id: str | None = None
    title: str
    name: str = ""
    company: str | None = None
    avatar: str | None = None
    last_message: str | None = None
    unread_count: int = 0
    last_message_at: str | None = None
    last_message_ts: float | None = None
    raw_payload: dict = Field(default_factory=dict)


class ConversationRecordRead(TimestampedSchema):
    source: str
    source_conversation_id: str
    gid: str
    security_id: str | None = None
    job_id: int | None = None
    encrypt_job_id: str | None = None
    encrypt_boss_id: str | None = None
    title: str
    name: str
    company: str | None = None
    avatar: str | None = None
    last_message: str | None = None
    unread_count: int
    last_message_at: str | None = None
    last_message_ts: float | None = None
    raw_payload: dict = Field(default_factory=dict)


class ChatMessage(DocumentModel):
    conversation_id: str  # gid
    message_id: str
    from_id: str
    content: str = ""
    msg_type: int | None = None
    sent_at: int | None = None  # BOSS 消息发送时间（毫秒时间戳）
    raw_payload: dict = Field(default_factory=dict)


class ChatMessageRead(TimestampedSchema):
    conversation_id: str
    message_id: str
    from_id: str
    content: str
    msg_type: int | None = None
    sent_at: int | None = None


class ChatHistoryResponse(BaseModel):
    gid: str
    security_id: str | None = None
    page: int
    count: int
    has_more: bool
    total: int
    messages: list[dict]


class ConversationSyncResponse(BaseModel):
    count: int


class ConversationRepository(BaseRepository[ConversationRecord]):
    collection_name = "conversation_records"
    model_cls = ConversationRecord


class ChatMessageRepository(BaseRepository[ChatMessage]):
    collection_name = "chat_messages"
    model_cls = ChatMessage


class ConversationService:
    def __init__(self, database: AsyncIOMotorDatabase, boss_client: BossClientProtocol) -> None:
        self.conversations = ConversationRepository(database)
        self.messages = ChatMessageRepository(database)
        self.boss_client = boss_client

    async def list_conversations(self) -> list[ConversationRecord]:
        now_cst = datetime.now(tz=_CST)
        today_start = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        filters = {"updated_at": {"$gte": today_start, "$lt": tomorrow_start}}
        return await self.conversations.list(filters=filters, sort_by="last_message_ts")

    async def get_chat_history(
        self, job_id: int, page: int = 1, count: int = 20
    ) -> ChatHistoryResponse:
        conv = await self.conversations.collection.find_one({"job_id": job_id})
        if not conv:
            raise BossOperationError(
                code="REQUEST_FAILED",
                message=f"未找到 job_id={job_id} 的会话记录",
                recoverable=False,
                status_code=404,
            )

        gid = conv.get("gid", "")
        security_id = conv.get("security_id")
        boss_id = conv.get("encrypt_boss_id")

        try:
            result = await self.boss_client.get_chat_history(
                boss_id=boss_id, security_id=security_id, page=page, count=count
            )
        except Exception as exc:
            raise map_boss_operation_error(exc) from exc

        messages = result.get("messages", [])
        msg_coll = self.messages.collection
        for m in messages:
            existing = await msg_coll.find_one({"message_id": m["message_id"]})
            if not existing:
                await self.messages.create(
                    ChatMessage(
                        conversation_id=gid,
                        message_id=m["message_id"],
                        from_id=m["from_id"],
                        content=m.get("content", ""),
                        msg_type=m.get("type"),
                        sent_at=m.get("created_at"),
                        raw_payload=m.get("raw_payload", m),
                    )
                )

        return ChatHistoryResponse(
            gid=gid,
            security_id=security_id,
            page=result["page"],
            count=result["count"],
            has_more=result["has_more"],
            total=result["total"],
            messages=messages,
        )

    async def sync_conversations(self) -> int:
        try:
            friends = await self.boss_client.list_friends(page=1)
        except Exception as exc:
            raise map_boss_operation_error(exc) from exc

        coll = self.conversations.collection
        synced = 0
        for item in friends:
            job_id = item.get("job_id")
            friend_id = item.get("friend_id") or item.get("gid", "")
            if not job_id and not friend_id:
                continue

            last_message_ts = None
            if item.get("last_message_ts"):
                try:
                    last_message_ts = float(item["last_message_ts"])
                except (ValueError, TypeError):
                    pass

            last_message_at = _format_last_time(last_message_ts) if last_message_ts else None

            filter_doc = {"job_id": job_id} if job_id else {"source_conversation_id": friend_id}

            await coll.update_one(
                filter_doc,
                {"$set": {
                    "source_conversation_id": friend_id,
                    "gid": item.get("gid", ""),
                    "job_id": job_id,
                    "encrypt_job_id": item.get("encrypt_job_id"),
                    "encrypt_boss_id": item.get("encrypt_boss_id"),
                    "security_id": item.get("security_id"),
                    "name": item.get("name", ""),
                    "title": item.get("title", ""),
                    "company": item.get("company"),
                    "avatar": item.get("avatar"),
                    "last_message": item.get("last_message"),
                    "unread_count": item.get("unread_count", 0),
                    "last_message_at": last_message_at,
                    "last_message_ts": last_message_ts,
                    "raw_payload": item.get("raw_payload", item),
                    "updated_at": utc_now(),
                }},
                upsert=True,
            )
            synced += 1
        return synced
