#!/usr/bin/env python3
import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "job_buddy.main:app",
        app_dir="src",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8000")),
        reload=True,
        reload_dirs=["src", "tests"],
        reload_excludes=["logs/*", "data/*", ".venv/*"],
    )


if __name__ == "__main__":
    main()
