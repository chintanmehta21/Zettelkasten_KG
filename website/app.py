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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from website.api.chat_routes import router as chat_router
from website.api.nexus import router as nexus_router
from website.api.routes import router as api_router
from website.api.sandbox_routes import router as sandbox_router
from website.features.summarization_engine.api import router as engine_v2_router

logger = logging.getLogger("website.app")

STATIC_DIR = Path(__file__).parent / "static"
KG_DIR = Path(__file__).parent / "features" / "knowledge_graph"
MOBILE_DIR = Path(__file__).parent / "mobile"
AUTH_DIR = Path(__file__).parent / "features" / "user_auth"
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
HOME_DIR = Path(__file__).parent / "features" / "user_home"
USER_ZETTELS_DIR = Path(__file__).parent / "features" / "user_zettels"
BROWSER_CACHE_DIR = Path(__file__).parent / "features" / "browser_cache"
USER_KASTENS_DIR = Path(__file__).parent / "features" / "user_kastens"
USER_RAG_DIR = Path(__file__).parent / "features" / "user_rag"
FOOTER_DIR = Path(__file__).parent / "footer"
ABOUT_DIR = FOOTER_DIR / "about"
PRICING_DIR = FOOTER_DIR / "pricing"
NEXUS_DIR = Path(__file__).parent / "experimental_features" / "nexus"
SUMMARIZATION_ENGINE_DIR = Path(__file__).parent / "features" / "summarization_engine"
HEADER_DIR = Path(__file__).parent / "features" / "header"
_HEADER_PLACEHOLDER = "<!--ZK_HEADER-->"


def _render_with_header(path: Path) -> HTMLResponse:
    """Read an HTML page and inject the shared site header at the placeholder.

    The placeholder is the literal comment ``<!--ZK_HEADER-->``. Re-reads on every
    request so live edits to header.html show up without restart. Falls back to
    returning the raw page unchanged if the placeholder or header file is absent.
    """
    html = path.read_text(encoding="utf-8")
    if _HEADER_PLACEHOLDER in html:
        header_html = (HEADER_DIR / "header.html").read_text(encoding="utf-8")
        html = html.replace(_HEADER_PLACEHOLDER, header_html)
    return HTMLResponse(content=html)

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
    app.include_router(engine_v2_router)
    app.include_router(chat_router)
    app.include_router(sandbox_router)
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
    app.mount(
        "/home/kastens/css",
        StaticFiles(directory=str(USER_KASTENS_DIR / "css")),
        name="home-kastens-css",
    )
    app.mount(
        "/home/kastens/js",
        StaticFiles(directory=str(USER_KASTENS_DIR / "js")),
        name="home-kastens-js",
    )
    app.mount(
        "/home/rag/css",
        StaticFiles(directory=str(USER_RAG_DIR / "css")),
        name="home-rag-css",
    )
    app.mount(
        "/home/rag/js",
        StaticFiles(directory=str(USER_RAG_DIR / "js")),
        name="home-rag-js",
    )
    _mount_static_if_exists(
        app,
        "/home/rag/content",
        USER_RAG_DIR / "content",
        "home-rag-content",
    )
    app.mount("/about/css", StaticFiles(directory=str(ABOUT_DIR / "css")), name="about-css")
    app.mount("/about/js", StaticFiles(directory=str(ABOUT_DIR / "js")), name="about-js")
    app.mount(
        "/pricing/css",
        StaticFiles(directory=str(PRICING_DIR / "css")),
        name="pricing-css",
    )
    app.mount("/pricing/js", StaticFiles(directory=str(PRICING_DIR / "js")), name="pricing-js")

    # Shared site header (single source of truth for inner-page header markup)
    app.mount("/header/css", StaticFiles(directory=str(HEADER_DIR / "css")), name="header-css")
    app.mount("/header/js", StaticFiles(directory=str(HEADER_DIR / "js")), name="header-js")

    # Shared artifacts (logos, icons, etc.)
    app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")
    app.mount(
        "/summarization-engine/css",
        StaticFiles(directory=str(SUMMARIZATION_ENGINE_DIR / "ui" / "css")),
        name="summarization-engine-css",
    )
    app.mount(
        "/summarization-engine/js",
        StaticFiles(directory=str(SUMMARIZATION_ENGINE_DIR / "ui" / "js")),
        name="summarization-engine-js",
    )

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
            return _render_with_header(nexus_index)

    @app.get("/home/zettels")
    async def user_zettels(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return _render_with_header(USER_ZETTELS_DIR / "index.html")

    @app.get("/home/kastens")
    async def user_kastens(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return FileResponse(str(USER_KASTENS_DIR / "index.html"))

    @app.get("/home/rag")
    async def user_rag(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        return FileResponse(str(USER_RAG_DIR / "index.html"))

    @app.get("/summarization-engine")
    async def summarization_engine_dashboard(request: Request):
        return FileResponse(str(SUMMARIZATION_ENGINE_DIR / "ui" / "index.html"))

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
