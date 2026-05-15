from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from job_buddy.core.boss import BossClientProtocol
from job_buddy.modules.common import BaseRepository, DocumentModel, TimestampedSchema


class ConversationRecord(DocumentModel):
    source: str = "boss"
    source_conversation_id: str
    title: str
    company: str | None = None
    last_message: str | None = None
    unread_count: int = 0
    last_message_at: datetime | None = None
    raw_payload: dict = Field(default_factory=dict)


class ConversationRecordRead(TimestampedSchema):
    source: str
    source_conversation_id: str
    title: str
    company: str | None = None
    last_message: str | None = None
    unread_count: int
    last_message_at: str | None = None


class ConversationSyncResponse(BaseModel):
    count: int


class ConversationRepository(BaseRepository[ConversationRecord]):
    collection_name = "conversation_records"
    model_cls = ConversationRecord


class ConversationService:
    def __init__(self, database: AsyncIOMotorDatabase, boss_client: BossClientProtocol) -> None:
        self.conversations = ConversationRepository(database)
        self.boss_client = boss_client

    async def list_conversations(self, limit: int = 100) -> list[ConversationRecord]:
        return await self.conversations.list(limit=limit)

    async def sync_conversations(self, limit: int = 20) -> int:
        raw_conversations = await self.boss_client.list_conversations(limit=limit)
        synced = 0
        for item in raw_conversations:
            await self.conversations.create(
                ConversationRecord(
                    source_conversation_id=item["conversation_id"],
                    title=item["title"],
                    company=item.get("company"),
                    last_message=item.get("last_message"),
                    unread_count=item.get("unread_count", 0),
                    last_message_at=datetime.fromisoformat(item["last_message_at"]) if item.get("last_message_at") else None,
                    raw_payload=item,
                )
            )
            synced += 1
        return synced
