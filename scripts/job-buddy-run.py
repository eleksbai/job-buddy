#!/usr/bin/env python3
import asyncio
import os
import sys

import uvicorn
import uvicorn.server


# Workaround: PyCharm debugger patches asyncio.run() but the wrapper
# doesn't forward Python 3.12+'s `loop_factory` kwarg, which uvicorn
# uses.  Replace uvicorn's internal asyncio_run with one that manages
# the event loop directly, avoiding asyncio.run() entirely.
def _asyncio_run(coro, *, loop_factory=None, debug=False):
    _ = loop_factory, debug
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


uvicorn.server.asyncio_run = _asyncio_run


def main() -> None:
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
