"""FastAPI application factory for the web frontend.

Serves the static web UI and the /api routes.  In webhook mode, also
handles Telegram webhook forwarding so both services share a single port.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from website.api.routes import router as api_router

logger = logging.getLogger("website.app")

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Zettelkasten Summarizer",
        description="Summarize any link with AI",
        docs_url=None,  # disable /docs in production
        redoc_url=None,
    )

    # API routes
    app.include_router(api_router)

    # Serve static assets (css, js)
    app.mount("/css", StaticFiles(directory=str(STATIC_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(STATIC_DIR / "js")), name="js")

    # Serve index.html at root
    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app
