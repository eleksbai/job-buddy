from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class PyObjectId(str):
    @classmethod
    def from_value(cls, value: ObjectId | str) -> str:
        return str(value)


class DocumentModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: str | None = Field(default=None, alias="_id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def to_mongo(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, exclude_none=True)
        if payload.get("_id"):
            payload["_id"] = ObjectId(payload["_id"])
        return payload

    @classmethod
    def from_mongo(cls, payload: dict[str, Any]) -> "DocumentModel":
        data = dict(payload)
        if "_id" in data:
            data["_id"] = PyObjectId.from_value(data["_id"])
        return cls.model_validate(data)


TASK_TIMEOUT = 300  # 5 minutes


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


class TimestampedSchema(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime


class TaskTriggerResponse(BaseModel):
    task_id: str
    status: str


ModelT = TypeVar("ModelT", bound=DocumentModel)


class BaseRepository(Generic[ModelT]):
    collection_name: str
    model_cls: type[ModelT]

    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.collection: AsyncIOMotorCollection = database[self.collection_name]

    async def list(self, filters: dict[str, Any] | None = None, limit: int = 100) -> list[ModelT]:
        cursor = self.collection.find(filters or {}).sort("updated_at", -1).limit(limit)
        return [self.model_cls.from_mongo(item) for item in await cursor.to_list(length=limit)]

    async def get(self, entity_id: str) -> ModelT | None:
        payload = await self.collection.find_one({"_id": ObjectId(entity_id)})
        if not payload:
            return None
        return self.model_cls.from_mongo(payload)

    async def create(self, entity: ModelT) -> ModelT:
        payload = entity.to_mongo()
        payload.pop("_id", None)
        result = await self.collection.insert_one(payload)
        stored = await self.collection.find_one({"_id": result.inserted_id})
        return self.model_cls.from_mongo(stored)

    async def update(self, entity_id: str, updates: dict[str, Any]) -> ModelT | None:
        updates["updated_at"] = utc_now()
        await self.collection.update_one({"_id": ObjectId(entity_id)}, {"$set": updates})
        return await self.get(entity_id)

    async def delete(self, entity_id: str) -> bool:
        result = await self.collection.delete_one({"_id": ObjectId(entity_id)})
        return result.deleted_count > 0

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        return await self.collection.count_documents(filters or {})
