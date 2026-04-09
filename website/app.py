"""FastAPI application factory for the web frontend.

Serves the static web UI and the /api routes.  In webhook mode, also
handles Telegram webhook forwarding so both services share a single port.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from website.api.nexus import router as nexus_router
from website.api.routes import router as api_router

logger = logging.getLogger("website.app")

STATIC_DIR = Path(__file__).parent / "static"
KG_DIR = Path(__file__).parent / "features" / "knowledge_graph"
MOBILE_DIR = Path(__file__).parent / "mobile"
AUTH_DIR = Path(__file__).parent / "features" / "user_auth"
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
HOME_DIR = Path(__file__).parent / "features" / "user_home"
USER_ZETTELS_DIR = Path(__file__).parent / "features" / "user_zettels"
BROWSER_CACHE_DIR = Path(__file__).parent / "features" / "browser_cache"
FOOTER_DIR = Path(__file__).parent / "footer"
ABOUT_DIR = FOOTER_DIR / "about"
PRICING_DIR = FOOTER_DIR / "pricing"
NEXUS_DIR = Path(__file__).parent / "experimental_features" / "nexus"

# Regex to detect mobile user-agents
_MOBILE_RE = re.compile(
    r"Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|mobile",
    re.IGNORECASE,
)


def _nexus_enabled() -> bool:
    raw_value = os.environ.get("NEXUS_ENABLED", "true").strip().lower()
    return raw_value not in {"0", "false", "no", "off"}


def _is_mobile(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return bool(_MOBILE_RE.search(ua))


def _mount_static_if_exists(app: FastAPI, url: str, directory: Path, name: str) -> None:
    if directory.exists():
        app.mount(url, StaticFiles(directory=str(directory)), name=name)
    else:
        logger.info("Skipping missing static mount %s -> %s", url, directory)


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
    nexus_enabled = _nexus_enabled()

    # API routes
    app.include_router(api_router)
    if nexus_enabled:
        app.include_router(nexus_router)

    # ── Mobile static assets (/m/) ──
    app.mount("/m/css", StaticFiles(directory=str(MOBILE_DIR / "css")), name="m-css")
    app.mount("/m/js", StaticFiles(directory=str(MOBILE_DIR / "js")), name="m-js")

    # ── Desktop static assets ──
    app.mount("/css", StaticFiles(directory=str(STATIC_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(STATIC_DIR / "js")), name="js")

    # Knowledge Graph static assets (shared by both mobile and desktop)
    app.mount("/kg/css", StaticFiles(directory=str(KG_DIR / "css")), name="kg-css")
    app.mount("/kg/js", StaticFiles(directory=str(KG_DIR / "js")), name="kg-js")
    app.mount("/kg/content", StaticFiles(directory=str(KG_DIR / "content")), name="kg-data")

    # User Auth static assets
    app.mount("/auth/css", StaticFiles(directory=str(AUTH_DIR / "css")), name="auth-css")
    app.mount("/auth/js", StaticFiles(directory=str(AUTH_DIR / "js")), name="auth-js")
    app.mount(
        "/browser-cache/js",
        StaticFiles(directory=str(BROWSER_CACHE_DIR / "js")),
        name="browser-cache-js",
    )

    # Home page static assets
    app.mount("/home/css", StaticFiles(directory=str(HOME_DIR / "css")), name="home-css")
    app.mount("/home/js", StaticFiles(directory=str(HOME_DIR / "js")), name="home-js")
    if nexus_enabled:
        _mount_static_if_exists(app, "/home/nexus/css", NEXUS_DIR / "css", "home-nexus-css")
        _mount_static_if_exists(app, "/home/nexus/js", NEXUS_DIR / "js", "home-nexus-js")
    app.mount(
        "/home/zettels/css",
        StaticFiles(directory=str(USER_ZETTELS_DIR / "css")),
        name="home-zettels-css",
    )
    app.mount(
        "/home/zettels/js",
        StaticFiles(directory=str(USER_ZETTELS_DIR / "js")),
        name="home-zettels-js",
    )
    app.mount("/about/css", StaticFiles(directory=str(ABOUT_DIR / "css")), name="about-css")
    app.mount("/about/js", StaticFiles(directory=str(ABOUT_DIR / "js")), name="about-js")
    app.mount(
        "/pricing/css",
        StaticFiles(directory=str(PRICING_DIR / "css")),
        name="pricing-css",
    )
    app.mount("/pricing/js", StaticFiles(directory=str(PRICING_DIR / "js")), name="pricing-js")

    # Shared artifacts (logos, icons, etc.)
    app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")

    # ── Mobile routes ──
    @app.get("/m/")
    async def mobile_index():
        return FileResponse(str(MOBILE_DIR / "index.html"))

    @app.get("/m/knowledge-graph")
    async def mobile_knowledge_graph():
        return FileResponse(str(MOBILE_DIR / "knowledge-graph.html"))

    # ── Desktop routes (auto-redirect mobile browsers) ──
    @app.get("/")
    async def index(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/knowledge-graph")
    async def knowledge_graph(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/knowledge-graph", status_code=302)
        return FileResponse(str(KG_DIR / "index.html"))

    @app.get("/auth/callback")
    async def auth_callback():
        return FileResponse(str(AUTH_DIR / "callback.html"))

    @app.get("/home")
    async def home(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return FileResponse(str(HOME_DIR / "index.html"))

    if nexus_enabled:
        @app.get("/home/nexus")
        async def home_nexus(request: Request):
            if _is_mobile(request):
                return RedirectResponse(url="/m/", status_code=302)
            nexus_index = NEXUS_DIR / "index.html"
            if not nexus_index.exists():
                raise HTTPException(status_code=503, detail="Nexus UI assets are not available")
            return FileResponse(str(nexus_index))

    @app.get("/home/zettels")
    async def user_zettels(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return FileResponse(str(USER_ZETTELS_DIR / "index.html"))

    @app.get("/about")
    async def about(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return FileResponse(str(ABOUT_DIR / "index.html"))

    @app.get("/pricing")
    async def pricing(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return FileResponse(str(PRICING_DIR / "index.html"))

    return app
