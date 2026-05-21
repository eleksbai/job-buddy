from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from job_buddy.config import Settings


class MongoManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncIOMotorClient | None = None

    @property
    def client(self) -> AsyncIOMotorClient:
        if self._client is None:
            raise RuntimeError("Mongo client has not been initialized.")
        return self._client

    @property
    def database(self) -> AsyncIOMotorDatabase:
        return self.client[self._settings.mongodb_db]

    async def connect(self) -> AsyncIOMotorDatabase:
        self._client = AsyncIOMotorClient(self._settings.mongodb_uri, tz_aware=True)
        return self.database

    async def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


@asynccontextmanager
async def database_lifespan(manager: MongoManager) -> AsyncIterator[AsyncIOMotorDatabase]:
    database = await manager.connect()
    try:
        yield database
    finally:
        await manager.disconnect()
