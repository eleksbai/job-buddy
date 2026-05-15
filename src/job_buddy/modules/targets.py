from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from job_buddy.modules.common import BaseRepository, DocumentModel, TimestampedSchema


class TargetProfile(DocumentModel):
    name: str
    keywords: list[str] = Field(default_factory=list)
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    greeting_template: str | None = None
    is_active: bool = True


class TargetProfileCreate(BaseModel):
    name: str
    keywords: list[str] = Field(default_factory=list)
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    greeting_template: str | None = None
    is_active: bool = True


class TargetProfileUpdate(BaseModel):
    name: str | None = None
    keywords: list[str] | None = None
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    filters: dict[str, Any] | None = None
    greeting_template: str | None = None
    is_active: bool | None = None


class TargetProfileRead(TimestampedSchema):
    name: str
    keywords: list[str]
    city: str | None = None
    salary: str | None = None
    experience: str | None = None
    filters: dict[str, Any]
    greeting_template: str | None = None
    is_active: bool


class TargetProfileRepository(BaseRepository[TargetProfile]):
    collection_name = "target_profiles"
    model_cls = TargetProfile


class TargetProfileService:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.repository = TargetProfileRepository(database)

    async def list_targets(self) -> list[TargetProfile]:
        return await self.repository.list(limit=200)

    async def get_target(self, target_id: str) -> TargetProfile:
        target = await self.repository.get(target_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target profile not found.")
        return target

    async def create_target(self, payload: TargetProfileCreate) -> TargetProfile:
        return await self.repository.create(TargetProfile(**payload.model_dump()))

    async def update_target(self, target_id: str, payload: TargetProfileUpdate) -> TargetProfile:
        target = await self.repository.update(target_id, payload.model_dump(exclude_none=True))
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target profile not found.")
        return target

    async def delete_target(self, target_id: str) -> None:
        deleted = await self.repository.delete(target_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target profile not found.")
