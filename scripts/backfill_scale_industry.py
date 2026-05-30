"""一次性回填 JobLead 文档的 scale / industry 字段。

从 detail_payload.company.scale / industry（兼容嵌套层级）提取值写入顶层字段。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 加载 .env
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / ".env"
load_dotenv(env_path)

MONGO_URI = os.getenv("MONGODB_DATABASE_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGODB_DATABASE_NAME", "job_buddy")


def _extract_scale(detail_payload: dict | None) -> str | None:
    if not detail_payload:
        return None
    for dp in (detail_payload.get("detail_payload"), detail_payload):
        if isinstance(dp, dict):
            company = dp.get("company") or {}
            if isinstance(company, dict) and company.get("scale"):
                return str(company["scale"])
    return None


def _extract_industry(detail_payload: dict | None) -> str | None:
    if not detail_payload:
        return None
    for dp in (detail_payload.get("detail_payload"), detail_payload):
        if isinstance(dp, dict):
            company = dp.get("company") or {}
            if isinstance(company, dict) and company.get("industry"):
                return str(company["industry"])
    return None


async def backfill():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db["job_leads"]

    # 选择性处理，一次处理 scale 或 industry 缺失的文档
    count_scale = 0
    count_industry = 0

    async for doc in collection.find(
        {
            "$or": [
                {"scale": {"$exists": False}},
                {"industry": {"$exists": False}},
            ],
            "detail_payload": {"$exists": True},
        }
    ):
        detail = doc.get("detail_payload")
        updates: dict[str, str] = {}

        if "scale" not in doc or doc.get("scale") is None:
            scale_val = _extract_scale(detail)
            if scale_val:
                updates["scale"] = scale_val
                count_scale += 1

        if "industry" not in doc or doc.get("industry") is None:
            industry_val = _extract_industry(detail)
            if industry_val:
                updates["industry"] = industry_val
                count_industry += 1

        if updates:
            await collection.update_one({"_id": doc["_id"]}, {"$set": updates})

    # 对于完全没有 detail_payload 但有 raw_payload 中可能包含行业信息的文档不存在
    # 所以不需要处理。

    print(f"回填完成: scale={count_scale}, industry={count_industry}")
    client.close()


if __name__ == "__main__":
    asyncio.run(backfill())
