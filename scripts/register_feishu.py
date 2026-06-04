#!/usr/bin/env python3
"""扫码注册飞书应用，将凭据保存到 MongoDB。"""
import asyncio
from datetime import datetime, timezone

import lark_oapi as lark
from motor.motor_asyncio import AsyncIOMotorClient

from job_buddy.config import get_settings


async def main() -> None:
    result = await lark.aregister_app(
        on_qr_code=lambda info: print(f"\n请用飞书扫码:\n{info['url']}\n"),
    )
    app_id = result["client_id"]
    app_secret = result["client_secret"]
    print(f"App ID: {app_id}")
    print(f"App Secret: {app_secret}")

    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo.uri)

    try:
        db = client[settings.mongo.db]
        await db["feishu_credentials"].delete_many({})
        await db["feishu_credentials"].insert_one({
            "app_id": app_id,
            "app_secret": app_secret,
            "chat_id": "",
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
        })
        print("凭据已保存到 MongoDB")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
