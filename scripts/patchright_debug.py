#!/usr/bin/env python
from __future__ import annotations

import asyncio

from job_buddy.core.config import get_settings
from job_buddy.core.engines.models import LoginRequest
from job_buddy.core.engines.patchright import PatchrightEngine

async def run() -> int:
    settings = get_settings()
    engine = PatchrightEngine(settings)
    await engine.init()
    request = LoginRequest()
    response = await engine.login(request)
    print(response)
    await asyncio.sleep(60)
    await engine.close()

    return 0


if __name__ == "__main__":
    asyncio.run(run())
