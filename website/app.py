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
KG_DIR = Path(__file__).parent / "knowledge_graph"


def create_app(lifespan=None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        lifespan: Optional async context manager for startup/shutdown events.
                  Used in webhook mode to manage the PTB Application lifecycle.
    """
    kwargs = dict(
        title="Zettelkasten Summarizer",
        description="Summarize any link with AI",
        docs_url=None,
        redoc_url=None,
    )
    if lifespan is not None:
        kwargs["lifespan"] = lifespan

    app = FastAPI(**kwargs)

    # API routes
    app.include_router(api_router)

    # Serve static assets (css, js)
    app.mount("/css", StaticFiles(directory=str(STATIC_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(STATIC_DIR / "js")), name="js")

    # Knowledge Graph static assets
    app.mount("/kg/css", StaticFiles(directory=str(KG_DIR / "css")), name="kg-css")
    app.mount("/kg/js", StaticFiles(directory=str(KG_DIR / "js")), name="kg-js")
    app.mount("/kg/data", StaticFiles(directory=str(KG_DIR / "data")), name="kg-data")

    # Serve index.html at root
    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    # Serve Knowledge Graph page
    @app.get("/knowledge-graph")
    async def knowledge_graph():
        return FileResponse(str(KG_DIR / "index.html"))

    return app
