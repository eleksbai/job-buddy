#!/usr/bin/env python3
import asyncio
import logging
import os
import sys

import uvicorn
import uvicorn.server

logger = logging.getLogger("job-buddy")


# Workaround: PyCharm debugger patches asyncio.run() but the wrapper
# doesn't forward Python 3.12+'s `loop_factory` kwarg, which uvicorn
# uses.  Replace uvicorn's internal asyncio_run with asyncio.Runner
# which handles proper cleanup (task cancellation, async generator
# shutdown, executor shutdown) on exit, avoiding hanging threads.
def _asyncio_run(coro, *, loop_factory=None, debug=False):
    with asyncio.Runner(loop_factory=loop_factory, debug=debug) as runner:
        return runner.run(coro)


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
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, exiting")
    except Exception:
        logger.exception("Server exited with error")
        raise
    finally:
        _join_threads(timeout=3)


def _join_threads(timeout: float = 3) -> None:
    """Join leftover non-daemon threads so they don't block process exit."""
    import threading
    remaining = [
        t for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon
    ]
    if not remaining:
        return
    logger.info("Waiting up to %.0fs for %d leftover thread(s): %s",
                timeout, len(remaining), [t.name for t in remaining])
    for t in remaining:
        t.join(timeout=timeout)
    still_alive = [t.name for t in remaining if t.is_alive()]
    if still_alive:
        logger.warning(
            "%d thread(s) still alive after %.0fs, forcing exit: %s",
            len(still_alive), timeout, still_alive,
        )
        os._exit(0)


if __name__ == "__main__":
    main()
