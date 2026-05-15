from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = WEB_ROOT / "static"


def register_web(app: FastAPI) -> None:
    app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith(("api", "mcp", "docs", "openapi.json")):
            return FileResponse(STATIC_ROOT / "index.html", status_code=404)
        asset_candidate = STATIC_ROOT / full_path
        if asset_candidate.is_file():
            return FileResponse(asset_candidate)
        return FileResponse(STATIC_ROOT / "index.html")
