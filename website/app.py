"""FastAPI application factory for the web frontend.

Serves the static web UI and the /api routes.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from fastapi.responses import JSONResponse

from website.api.chat_routes import router as chat_router
from website.api.nexus import router as nexus_router
from website.api.routes import router as api_router
from website.api.sandbox_routes import router as sandbox_router
from website.api.zettels_routes import router as zettels_router
from website.features.refresh_button.refresh_routes import router as refresh_button_router
from website.features.summarization_engine.api import router as engine_v2_router
from website.features.user_pricing.routes import router as pricing_router
from website.features.user_profile import router as profile_router
from website.features.web_monitor import (
    _hash_id,
    maybe_fire_app_error_rate,
    router as web_monitor_router,
)
from website.features.web_monitor.App_Errors import notify_app_error
from website.features.web_monitor._env_validation import (
    log_web_monitor_env_warnings,
)
from website.api.admin_routes import router as admin_router
from website.api.meta_routes import router as meta_router
from website.api import _memory_guard
from website.config.page_menus import PAGE_MENUS, MenuItem

logger = logging.getLogger("website.app")

STATIC_DIR = Path(__file__).parent / "static"
KG_DIR = Path(__file__).parent / "features" / "knowledge_graph"
MOBILE_DIR = Path(__file__).parent / "mobile"
AUTH_DIR = Path(__file__).parent / "features" / "user_auth"
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
HOME_DIR = Path(__file__).parent / "features" / "user_home"
USER_ZETTELS_DIR = Path(__file__).parent / "features" / "user_zettels"
USER_PROFILE_DIR = Path(__file__).parent / "features" / "user_profile"
BROWSER_CACHE_DIR = Path(__file__).parent / "features" / "browser_cache"
USER_KASTENS_DIR = Path(__file__).parent / "features" / "user_kastens"
USER_RAG_DIR = Path(__file__).parent / "features" / "user_rag"
USER_PRICING_DIR = Path(__file__).parent / "features" / "user_pricing"
FUNCTIONAL_GATES_DIR = Path(__file__).parent / "features" / "functional_gates"
FOOTER_DIR = Path(__file__).parent / "footer"
ABOUT_DIR = FOOTER_DIR / "about"
PRICING_DIR = FOOTER_DIR / "pricing"
NEXUS_DIR = Path(__file__).parent / "experimental_features" / "nexus"
SUMMARIZATION_ENGINE_DIR = Path(__file__).parent / "features" / "summarization_engine"
HEADER_DIR = Path(__file__).parent / "features" / "header"
_HEADER_PLACEHOLDER = "<!--ZK_HEADER-->"
_FOOTER_PLACEHOLDER = "<!--ZK_FOOTER-->"
_HEADER_DROPDOWN_SLOT = "<!--HEADER_DROPDOWN-->"
_BACK_BTN_SLOT = "<!--BACK_BTN_SLOT-->"
_HTML_CACHE_HEADERS = {"Cache-Control": "no-cache, max-age=0, must-revalidate"}

# Back-button markup matches the static block that used to live in header.html.
# Kept here (not in a fragment file) so the substitution is one read per request.
_BACK_BUTTON_HTML = (
    '<button type="button" class="zk-back-btn" data-zk-back aria-label="Go back">'
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    '<path d="M15 6L9 12L15 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>'
    '</svg>'
    '</button>'
)


def _html_file_response(path: Path) -> FileResponse:
    return FileResponse(str(path), media_type="text/html", headers=_HTML_CACHE_HEADERS)


def _render_link_item(item: MenuItem) -> str:
    """Render a MenuItem to a dropdown link <a>, matching header.html's prior static markup."""
    dom_id = item.get("dom_id")
    id_attr = f' id="{dom_id}"' if dom_id else ""
    labs_html = ""
    if item.get("labs"):
        labs_html = (
            '<span class="home-dropdown-labs" title="Experimental" aria-label="Experimental">'
            '<svg viewBox="0 0 24 24" fill="none" width="14" height="14">'
            '<path d="M9 3h6M10 3v5.5L5.5 18a2 2 0 0 0 1.8 2.9h9.4A2 2 0 0 0 18.5 18L14 8.5V3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"></path>'
            '<path d="M7.5 14h9" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"></path>'
            '</svg>'
            '</span>'
        )
    return (
        f'<a class="home-dropdown-item" href="{item["href"]}"{id_attr} role="menuitem">'
        f'<span class="home-dropdown-icon" aria-hidden="true">{item["icon"]}</span>'
        f'<span class="home-dropdown-label">{item["label"]}</span>'
        f'{labs_html}'
        f'</a>'
    )


def _render_signout_item(item: MenuItem) -> str:
    """Render the signout <button> (always preceded by a divider per the
    original static markup)."""
    dom_id = item.get("dom_id", "menu-signout")
    return (
        '<div class="home-dropdown-divider"></div>'
        f'<button class="home-dropdown-item home-dropdown-signout" id="{dom_id}" role="menuitem">'
        f'<span class="home-dropdown-icon" aria-hidden="true">{item["icon"]}</span>'
        f'<span class="home-dropdown-label">{item["label"]}</span>'
        '</button>'
    )


def _render_dropdown_items(items: list[MenuItem]) -> str:
    """Render a list of MenuItems to the inner HTML of #avatar-dropdown."""
    parts: list[str] = []
    for item in items:
        if item["key"] == "signout":
            parts.append(_render_signout_item(item))
        else:
            parts.append(_render_link_item(item))
    return "".join(parts)


def _render_back_button(show: bool) -> str:
    return _BACK_BUTTON_HTML if show else ""


def _render_with_shell(path: Path, page_key: str | None = None) -> HTMLResponse:
    """Read an HTML page and inject the shared header (with per-page dropdown
    + back-button) and footer at their placeholders.

    Page placeholders: ``<!--ZK_HEADER-->`` / ``<!--ZK_FOOTER-->``.
    Header sub-slots: ``<!--HEADER_DROPDOWN-->`` / ``<!--BACK_BTN_SLOT-->``.

    Per-page items come from ``website.config.page_menus.PAGE_MENUS[page_key]``.
    When ``page_key`` is None, both header sub-slots render empty (legacy path
    for routes not yet migrated).

    Re-reads fragment files on every request so live edits show up without
    restart. Falls back to returning the raw page unchanged if a top-level
    placeholder is absent OR if the fragment file is missing (page renders
    with the literal placeholder still in body — better than 500).
    """
    html = path.read_text(encoding="utf-8")

    if _HEADER_PLACEHOLDER in html:
        try:
            header_html = (HEADER_DIR / "header.html").read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "header.html fragment missing at %s — page rendered without shared header",
                HEADER_DIR,
            )
        else:
            if page_key is None:
                dropdown_html = ""
                back_btn_html = ""
            else:
                menu = PAGE_MENUS[page_key]   # KeyError on unknown page_key — intended
                dropdown_html = _render_dropdown_items(menu["authed"])
                back_btn_html = _render_back_button(menu["show_back_button"])
            header_html = header_html.replace(_HEADER_DROPDOWN_SLOT, dropdown_html)
            header_html = header_html.replace(_BACK_BTN_SLOT, back_btn_html)
            html = html.replace(_HEADER_PLACEHOLDER, header_html)

    if _FOOTER_PLACEHOLDER in html:
        try:
            footer_html = (FOOTER_DIR / "footer.html").read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "footer.html fragment missing at %s — page rendered without shared footer",
                FOOTER_DIR,
            )
        else:
            html = html.replace(_FOOTER_PLACEHOLDER, footer_html)
    return HTMLResponse(content=html, headers=_HTML_CACHE_HEADERS)


# Backward-compat alias; keep callers working while incrementally migrating.
_render_with_header = _render_with_shell

MOBILE_TEMPLATES_DIR = MOBILE_DIR / "templates"
_MOBILE_SHELL = MOBILE_TEMPLATES_DIR / "_shell.html"
_MOBILE_OAUTH_MODAL = MOBILE_TEMPLATES_DIR / "_oauth_modal.html"


def _render_with_mobile_shell(
    body_path: Path,
    *,
    page_title: str,
    body_class: str = "",
    request: Optional[Request] = None,
) -> HTMLResponse:
    """Inject mobile shell around a body fragment file.

    Mobile shell owns <head> + header + bottom-tab nav + footer. Body fragment
    file is expected to contain ONLY the in-<main> content (no <html>/<head>/<body>
    wrappers).
    """
    shell = _MOBILE_SHELL.read_text(encoding="utf-8")
    body = body_path.read_text(encoding="utf-8")
    rendered = (
        shell
        .replace("<!--ZK_MOBILE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_PAGE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_BODY_CLASS-->", body_class)
        .replace("<!--ZK_MOBILE_CONTENT-->", body)
    )

    # Server-side avatar preload — improves first-paint for the user's own avatar.
    avatar_url = _avatar_url_from_request(request) if request else None
    preload_tag = (
        f'<link rel="preload" as="image" type="image/svg+xml" href="{avatar_url}">'
        if avatar_url else ""
    )
    rendered = rendered.replace("<!--ZK_MOBILE_PRELOAD-->", preload_tag)

    # Inject OAuth modal + auth scripts before </body> (Phase 3).
    # Mobile pages load ONLY auth-core.js — auth.js carries desktop-landing
    # DOM wiring (#login-btn / #user-menu / provider grid) that mobile does
    # not render. /m/ auth chrome is owned by auth-modal.js, which already
    # depends on window.ZKAuth from auth-core.
    # avatar.js (T3) is the shared renderer used by mobile + desktop.
    oauth_modal = _MOBILE_OAUTH_MODAL.read_text(encoding="utf-8")
    auth_block = (
        oauth_modal
        + '\n<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2" crossorigin></script>'
        + '\n<script src="/auth/js/auth-core.js?v=20260524a"></script>'
        + '\n<script src="/m/js/auth-modal.js?v=20260524a"></script>'
        + '\n<script src="/m/js/avatar.js?v=20260525a"></script>'
    )
    rendered = rendered.replace("</body>", auth_block + "\n</body>", 1)
    return HTMLResponse(content=rendered, headers=_HTML_CACHE_HEADERS)


def _avatar_url_from_request(request: Request) -> Optional[str]:
    """Best-effort cookie decode; returns None if unauth or decode fails.

    Used for first-paint avatar preload only — never as an auth source.
    Reuses the same JWT decoder as the API auth path.
    """
    from website.api.auth import _decode_token

    token = None
    for k, v in request.cookies.items():
        if k == "sb-access-token" or (k.startswith("sb-") and k.endswith("-auth-token")):
            token = v
            break
    if not token:
        return None
    try:
        claims = _decode_token(token)
        return (claims.get("user_metadata") or {}).get("avatar_url")
    except Exception:
        return None


# Regex to detect mobile user-agents
_MOBILE_RE = re.compile(
    r"Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|mobile",
    re.IGNORECASE,
)

# SameSite=Lax: survives the Supabase OAuth top-level GET return. httponly=True: no JS consumer in iter 1a (flip when adding a desktop->mobile inverse link).
_DESKTOP_COOKIE = "zk-prefer-desktop"


def _nexus_enabled() -> bool:
    raw_value = os.environ.get("NEXUS_ENABLED", "true").strip().lower()
    return raw_value not in {"0", "false", "no", "off"}


def _is_mobile(request: Request) -> bool:
    # Operator escape: persistent cookie set previously OR ?desktop=1 query param.
    if request.cookies.get(_DESKTOP_COOKIE) == "1":
        return False
    if request.query_params.get("desktop") == "1":
        # First-time escape. Cookie set by the route handler after this check.
        return False
    ua = request.headers.get("user-agent", "")
    return bool(_MOBILE_RE.search(ua))


def _maybe_set_desktop_cookie(request: Request, response: HTMLResponse) -> HTMLResponse:
    """If the request opted into desktop via ?desktop=1, persist a 30-day cookie."""
    if request.query_params.get("desktop") == "1" and request.cookies.get(_DESKTOP_COOKIE) != "1":
        response.set_cookie(
            key=_DESKTOP_COOKIE,
            value="1",
            max_age=60 * 60 * 24 * 30,  # 30 days
            path="/",
            samesite="lax",
            httponly=True,
        )
    return response


def _mount_static_if_exists(app: FastAPI, url: str, directory: Path, name: str) -> None:
    if directory.exists():
        app.mount(url, StaticFiles(directory=str(directory)), name=name)
    else:
        logger.info("Skipping missing static mount %s -> %s", url, directory)


async def _jwks_prewarm() -> None:
    """Hydrate PyJWKClient cache so the first JWT validation post-deploy doesn't
    pay a cold network fetch (which would trigger ``get_optional_user``'s
    silent-drop-to-anon path on a Supabase JWKS edge-cache miss). Soft-fails:
    a 5s ceiling via ``asyncio.wait_for`` keeps a hung JWKS endpoint from
    blocking startup; lazy fetch on first real request retries automatically.
    """
    import asyncio

    try:
        from website.api.auth import _get_jwks_client

        jwks_client = _get_jwks_client()
        if jwks_client is None:
            return
        await asyncio.wait_for(
            asyncio.to_thread(jwks_client.get_signing_keys),
            timeout=5.0,
        )
        logger.info("JWKS pre-warm complete")
    except asyncio.TimeoutError:
        logger.warning("JWKS pre-warm timed out (5s); lazy fetch will retry")
    except Exception as exc:  # noqa: BLE001 — pre-warm must never block startup
        logger.warning("JWKS pre-warm failed (non-fatal): %s", exc)


def create_app(lifespan=None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        lifespan: Optional async context manager for startup/shutdown events.
                  Used by ``website.main`` for the proc-stats logger task.
                  When None, a minimal default lifespan runs the JWKS pre-warm
                  at startup so tests / non-prod entrypoints exercise it too.
    """
    if lifespan is None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _default_lifespan(_app: FastAPI):
            await _jwks_prewarm()
            yield

        lifespan = _default_lifespan

    kwargs = dict(
        title="Zettelkasten Summarizer",
        description="Summarize any link with AI",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app = FastAPI(**kwargs)

    # X7 (Phase 4 / Task 4.4): pre-warm tldextract's PSL during gunicorn's
    # --preload step so all workers share the parsed tree via fork() COW
    # (instead of each worker re-materializing ~5 MB on its first request).
    # `suffix_list_urls=()` blocks any network fetch — fully offline call.
    try:
        from website.features.kg_features.pseudo_tags import _extract
        _extract("https://example.com")
    except Exception as exc:  # noqa: BLE001
        logger.warning("tldextract PSL pre-warm failed (non-fatal): %s", exc)

    # Phase 4 / Task 4.6 (O1+O2+O4): /api/metrics Prometheus exposition.
    # Mounted only when prometheus_client is importable so unit tests that
    # don't install ops/requirements still build a valid app. Multiprocess
    # exposition is handled via PROMETHEUS_MULTIPROC_DIR (set in the
    # Dockerfile) + gunicorn's child_exit hook (ops/gunicorn.conf.py).
    try:
        from prometheus_client import make_asgi_app
        app.mount("/api/metrics", make_asgi_app())
    except Exception as exc:  # noqa: BLE001
        logger.warning("/api/metrics Prometheus mount skipped: %s", exc)

    nexus_enabled = _nexus_enabled()

    # WAVE-D WM-14: log a warning at boot for each unset SLACK_WEBHOOK_* env
    # var so missing webhook config is visible BEFORE the first event would
    # have fired. Non-fatal — channels degrade to log-only on missing vars.
    # m-3: suppress under pytest so the per-test ``create_app`` calls in the
    # mocked CI lane don't drown the log stream with stub-env warnings.
    if not os.getenv("PYTEST_CURRENT_TEST"):
        log_web_monitor_env_warnings()

    # WAVE-C 1c-A.4 (D-KG-8): payload compression with Accept-Encoding
    # negotiation. brotli-asgi serves br when supported, falls back to gzip,
    # else identity. Compresses /api/graph (often >100KB) by ~3-5x. Threshold
    # = 1024 bytes so tiny health-check responses skip compression.
    try:
        from brotli_asgi import BrotliMiddleware

        app.add_middleware(BrotliMiddleware, minimum_size=1024, quality=4)
    except ImportError:
        # Fallback: stdlib GZipMiddleware. Lower compression ratio but no
        # extra dep. Logged once at startup so the deploy bot can flag.
        from fastapi.middleware.gzip import GZipMiddleware

        app.add_middleware(GZipMiddleware, minimum_size=1024)
        logger.info("brotli-asgi unavailable — using GZipMiddleware fallback")

    # API routes
    app.include_router(api_router)
    app.include_router(zettels_router)
    app.include_router(refresh_button_router)
    app.include_router(engine_v2_router)
    app.include_router(chat_router)
    app.include_router(sandbox_router)
    app.include_router(pricing_router)
    app.include_router(profile_router)
    app.include_router(web_monitor_router)
    app.include_router(admin_router)
    app.include_router(meta_router)
    if nexus_enabled:
        app.include_router(nexus_router)
    # iter-03 mem-bounded §2.9: install AFTER routers so middleware wraps every route.
    _memory_guard.install(app)

    # iter-03 §B (2026-04-29): post-response aggressive memory release.
    # Runs gc.collect() + glibc malloc_trim(0) AFTER each response is sent
    # to the client (no user-perceived latency impact). Targets the
    # ~180-430 MB per-query native residual that gc alone cannot free
    # (ONNX internal buffers, Gemini/Supabase httpx body buffers, glibc
    # arena freelist). Exempts /api/health* and /favicon.* so cheap probes
    # don't pay the trim cost. Safe on non-glibc platforms (no-op).
    from website.api._mem_release import aggressive_release as _aggressive_release

    _RELEASE_EXEMPT_PREFIXES = (
        "/api/health",
        "/favicon.",
    )

    @app.middleware("http")
    async def _post_response_release(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if not any(path.startswith(p) for p in _RELEASE_EXEMPT_PREFIXES):
            try:
                _aggressive_release()
            except Exception:  # noqa: BLE001 — never let release break the response
                logger.exception("post-response release failed")
        return response

    # iter-03 §B (2026-04-29): convert intra-request stage-2 memory pressure
    # to a clean 503 with Retry-After. The middleware above only sees RSS at
    # request dispatch; once a query is admitted, stage-2 may discover the
    # baseline has crept above the ceiling (residual from prior queries on
    # this worker) and refuse to allocate the forward-pass tensors. That
    # raises MemoryPressureError; we convert here so eval/clients get the
    # same Retry-After=5 contract as the dispatch-time guard.
    from website.features.rag_pipeline.rerank.cascade import MemoryPressureError

    @app.exception_handler(MemoryPressureError)
    async def _on_memory_pressure(request: Request, exc: MemoryPressureError):
        logger.warning(
            "stage-2 memory pressure shedding: %s path=%s",
            exc, request.url.path,
        )
        return JSONResponse(
            {"error": "server_under_memory_pressure", "retry_after_seconds": 5},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    # ── Prajeet 2026-05-25 §4.a: surface JWT-drop-to-anon to the client ──
    # ``get_optional_user`` silently maps bad-JWT requests to anonymous (and
    # downstream ``_effective_user_id`` to Zoro). The dep now tags
    # ``request.state.auth_status``; this middleware reflects the tag onto
    # the response as ``X-Auth-Status: jwt-dropped-to-anon`` so the frontend
    # can force a re-auth modal instead of submitting under the wrong user.
    # Legitimate anonymous traffic (no Authorization header) leaves the
    # marker unset and the header absent — observability noise stays zero.
    @app.middleware("http")
    async def _auth_drop_status_header(request: Request, call_next):
        response = await call_next(request)
        try:
            status = getattr(request.state, "auth_status", None)
        except AttributeError:
            status = None
        if status:
            response.headers["X-Auth-Status"] = status
            # RFC 6750 §3: convey JWT-failure semantics to clients via
            # WWW-Authenticate. Matches Auth0/Okta conventions.
            response.headers["WWW-Authenticate"] = (
                'Bearer error="invalid_token", '
                'error_description="JWT silently downgraded to anonymous"'
            )
            # Cloudflare cache-security: an anon response carrying X-Auth-Status
            # MUST NOT be cached and re-served to another caller.
            response.headers["Cache-Control"] = "private, no-store"
        return response

    # ── C13: 401 rate monitor (credential-stuffing / scanner detection) ──
    # Sliding-window counter on global + per-IP 401 responses. Out-of-path
    # of auth.py (hot path stays fast); runs at response-egress time as a
    # cheap status-code check + rate-gate tick. Hashed IP only — never the
    # raw client address (daily-rotated salt; matches OWASP cred-stuffing
    # alert payload contract).
    @app.middleware("http")
    async def _auth_401_rate_monitor(request: Request, call_next):
        response = await call_next(request)
        try:
            if response.status_code == 401 and not request.url.path.startswith(
                ("/api/health", "/webhooks/monitor/")
            ):
                # Global rate: ≥ 100 401s / 5 min = credential-stuffing pattern.
                maybe_fire_app_error_rate(
                    dedup_key="auth_401_global_burst",
                    threshold=100,
                    window_seconds=5 * 60,
                    route="middleware.auth_401_rate",
                    exc_type="AuthBurstDetected",
                    message="High 401 rate across /api/* — possible credential stuffing",
                    fields={
                        "external_service": "self",
                        "scope": "global",
                        "route_sample": request.url.path[:80],
                    },
                    severity="warning",
                    alert_dedup_seconds=15 * 60,
                )
                # Per-IP rate: ≥ 30 401s / 60 s = single scanner. Daily-rotated
                # salt makes the IP hash unreversible across days but stable
                # within one alert window.
                raw_ip = (
                    request.headers.get("cf-connecting-ip")
                    or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
                    or (request.client.host if request.client else "")
                )
                if raw_ip:
                    import time as _t

                    day_salt = str(int(_t.time()) // 86400)
                    ip_hash = _hash_id(f"{raw_ip}:{day_salt}", prefix_len=12)
                    maybe_fire_app_error_rate(
                        dedup_key=f"auth_401_per_ip:{ip_hash}",
                        threshold=30,
                        window_seconds=60,
                        route="middleware.auth_401_rate",
                        exc_type="ScannerBurstDetected",
                        message="High 401 rate from one IP — likely scanner",
                        fields={
                            "external_service": "self",
                            "scope": "per_ip",
                            "ip_hash": ip_hash,
                        },
                        severity="warning",
                        alert_dedup_seconds=15 * 60,
                    )
        except Exception:  # noqa: BLE001 — middleware must never break response
            logger.debug("auth 401 rate monitor failed", exc_info=True)
        return response

    # ── Unhandled-exception alerting ──
    # Any uncaught error in a request handler fans out to the #app-errors
    # Slack channel via notify_app_error, then returns a generic 500 to the
    # client. Missing SLACK_WEBHOOK_APP_ERRORS falls back to a logged warning
    # (see post_to_slack); the handler itself never raises on Slack failure.
    @app.exception_handler(RequestValidationError)
    async def _on_request_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path != "/api/zettels/add":
            return await request_validation_exception_handler(request, exc)
        return JSONResponse(
            {
                "type": "https://zettelkasten.in/problems/errors/invalid-add-zettel-request",
                "title": "Invalid Add Zettel request",
                "status": 422,
                "detail": "The Add Zettel request body did not match the API contract.",
                "instance": "/api/zettels/add",
                "errors": jsonable_encoder(exc.errors()),
            },
            status_code=422,
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def _on_unhandled_exception(request: Request, exc: Exception):
        try:
            await notify_app_error(
                route=request.url.path,
                exc_type=type(exc).__name__,
                message=str(exc)[:400],
                request_id=request.headers.get("x-request-id"),
            )
        except Exception:  # noqa: BLE001 — never let alerting break the response path
            logger.exception("web_monitor: alert dispatch failed")
        logger.exception("Unhandled exception on %s", request.url.path)
        return JSONResponse({"error": "internal_server_error"}, status_code=500)

    # ── Mobile static assets (/m/) ──
    app.mount("/m/css", StaticFiles(directory=str(MOBILE_DIR / "css")), name="m-css")
    app.mount("/m/js", StaticFiles(directory=str(MOBILE_DIR / "js")), name="m-js")

    # ── Desktop static assets ──
    app.mount("/css", StaticFiles(directory=str(STATIC_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(STATIC_DIR / "js")), name="js")
    # PWA icons (manifest.webmanifest + SW SHELL_URLS reference /static/icons/*).
    # Narrow mount — only the icons subdir, not all of /static.
    _icons_dir = STATIC_DIR / "icons"
    if _icons_dir.is_dir():
        app.mount(
            "/static/icons",
            StaticFiles(directory=str(_icons_dir)),
            name="static-icons",
        )

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

    # refresh_button feature static (shared between user_home + user_zettels)
    _refresh_button_static = Path(__file__).parent / "features" / "refresh_button" / "static"
    if _refresh_button_static.exists():
        app.mount(
            "/refresh-button/static",
            StaticFiles(directory=str(_refresh_button_static)),
            name="refresh-button-static",
        )
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
    # /profile static (Trash recovery surface; exec/DB_delete_zettel_refine--1a).
    _mount_static_if_exists(app, "/profile/css", USER_PROFILE_DIR / "css", "profile-css")
    _mount_static_if_exists(app, "/profile/js",  USER_PROFILE_DIR / "js",  "profile-js")
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
    app.mount(
        "/user-pricing/css",
        StaticFiles(directory=str(USER_PRICING_DIR / "css")),
        name="user-pricing-css",
    )
    app.mount(
        "/user-pricing/js",
        StaticFiles(directory=str(USER_PRICING_DIR / "js")),
        name="user-pricing-js",
    )
    _mount_static_if_exists(
        app,
        "/functional-gates/css",
        FUNCTIONAL_GATES_DIR / "css",
        "functional-gates-css",
    )
    _mount_static_if_exists(
        app,
        "/functional-gates/js",
        FUNCTIONAL_GATES_DIR / "js",
        "functional-gates-js",
    )

    # Shared site header (single source of truth for inner-page header markup)
    app.mount("/header/css", StaticFiles(directory=str(HEADER_DIR / "css")), name="header-css")
    app.mount("/header/js", StaticFiles(directory=str(HEADER_DIR / "js")), name="header-js")

    # Self-hosted third-party vendor assets (KaTeX, etc.) — no CDN.
    _mount_static_if_exists(
        app, "/vendor", STATIC_DIR / "vendor", "vendor"
    )

    # Avatars — long-cache immutable static files (60 SVGs under /artifacts/avatars/).
    # Mounted BEFORE the broad /artifacts catch-all so this subpath is matched first.
    AVATARS_DIR = Path(__file__).parent / "artifacts" / "avatars"

    class _ImmutableStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):  # type: ignore[override]
            resp = await super().get_response(path, scope)
            if resp.status_code == 200:
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp

    app.mount("/artifacts/avatars", _ImmutableStaticFiles(directory=str(AVATARS_DIR)), name="avatars")

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

    # ── Favicon ──
    # Browsers auto-fetch /favicon.ico on every page load; without a route the
    # request 404s on every navigation (visible in the DevTools console).
    # Serve a single SVG asset for both /favicon.ico and /favicon.svg with
    # long browser cache headers — the icon never changes per request.
    _favicon_path = STATIC_DIR / "favicon.svg"

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon_ico():
        return FileResponse(
            str(_favicon_path),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon_svg():
        return FileResponse(
            str(_favicon_path),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    # ── PWA manifest + service worker ──
    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def pwa_manifest():
        path = STATIC_DIR / "manifest.webmanifest"
        return FileResponse(
            str(path),
            media_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/sw.js", include_in_schema=False)
    async def pwa_service_worker():
        path = STATIC_DIR / "sw.js"
        return FileResponse(
            str(path),
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache, max-age=0",
                "Service-Worker-Allowed": "/",
            },
        )

    # ── Mobile routes ──
    @app.get("/m/")
    async def mobile_index(request: Request):
        return _render_with_mobile_shell(
            MOBILE_DIR / "index.html",
            page_title="Summarize",
            request=request,
        )

    @app.get("/m/knowledge-graph")
    async def mobile_knowledge_graph(request: Request):
        return _render_with_mobile_shell(
            MOBILE_DIR / "knowledge-graph.html",
            page_title="Knowledge Graph",
            body_class="kg-body",
            request=request,
        )

    # ── Desktop routes (auto-redirect mobile browsers) ──
    @app.get("/")
    async def index(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(STATIC_DIR / "index.html")
        return _maybe_set_desktop_cookie(request, response)

    @app.get("/knowledge-graph")
    async def knowledge_graph(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/knowledge-graph", status_code=302)
        # KG ships its own dedicated <header class="kg-header">; the shared
        # zk-header was carved out in PR1 of the shared-header refactor.
        response = _html_file_response(KG_DIR / "index.html")
        return _maybe_set_desktop_cookie(request, response)

    @app.get("/auth/callback")
    async def auth_callback():
        return _html_file_response(AUTH_DIR / "callback.html")

    @app.get("/home")
    async def home(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(HOME_DIR / "index.html", page_key="home")
        return _maybe_set_desktop_cookie(request, response)

    if nexus_enabled:
        @app.get("/home/nexus")
        async def home_nexus(request: Request):
            if _is_mobile(request):
                return RedirectResponse(url="/m/", status_code=302)
            nexus_index = NEXUS_DIR / "index.html"
            if not nexus_index.exists():
                raise HTTPException(status_code=503, detail="Nexus UI assets are not available")
            response = _render_with_shell(nexus_index, page_key="nexus")
            return _maybe_set_desktop_cookie(request, response)

    @app.get("/home/zettels")
    async def user_zettels(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_ZETTELS_DIR / "index.html", page_key="zettels")
        return _maybe_set_desktop_cookie(request, response)

    @app.get("/profile")
    async def user_profile(request: Request):
        """Profile page — Trash recovery surface (exec/DB_delete_zettel_refine--1a)."""
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_PROFILE_DIR / "index.html", page_key="profile")
        return _maybe_set_desktop_cookie(request, response)

    @app.get("/home/kastens")
    async def user_kastens(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_KASTENS_DIR / "index.html", page_key="kastens")
        return _maybe_set_desktop_cookie(request, response)

    @app.get("/home/rag")
    async def user_rag(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_RAG_DIR / "index.html", page_key="rag")
        return _maybe_set_desktop_cookie(request, response)

    @app.get("/summarization-engine")
    async def summarization_engine_dashboard(request: Request):
        return _html_file_response(SUMMARIZATION_ENGINE_DIR / "ui" / "index.html")

    @app.get("/about")
    async def about(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(ABOUT_DIR / "index.html")
        return _maybe_set_desktop_cookie(request, response)

    @app.get("/pricing")
    async def pricing(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        # No server-side Slack alert here — the GET path is public and
        # would fire on curl / health checks / docker-internal probes. The
        # alert is now driven by ``POST /api/monitor/pricing-visit`` which
        # the page JS fires once it has a Supabase JWT in localStorage.
        # That auth gate is what filters synthetic traffic out.
        response = _render_with_shell(PRICING_DIR / "index.html", page_key="pricing")
        return _maybe_set_desktop_cookie(request, response)

    return app
