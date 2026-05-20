from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = WEB_ROOT / "static"


def register_web(app: FastAPI) -> None:
    app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @app.middleware("http")
    async def spa_fallback(request: Request, call_next):
        response = await call_next(request)
        if response.status_code == 404:
            path = request.url.path
            if not path.startswith(("/boss", "/web", "/docs", "/openapi.json")):
                asset_candidate = STATIC_ROOT / path.lstrip("/")
                if asset_candidate.is_file():
                    return FileResponse(asset_candidate)
                return FileResponse(STATIC_ROOT / "index.html")
        return response
