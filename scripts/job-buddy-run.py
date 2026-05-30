#!/usr/bin/env python3
import asyncio
import os
import sys

import uvicorn


def main() -> None:
    # Workaround: PyCharm's _patch_asyncio doesn't forward loop_factory,
    # so restore the original asyncio.run before uvicorn starts.
    try:
        asyncio.run = asyncio.runners.run
    except AttributeError:
        pass

    app_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    sys.path.insert(0, app_dir)
    os.chdir(app_dir)
    config = uvicorn.Config(
        "job_buddy.main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8000")),
        reload=False,
    )
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
