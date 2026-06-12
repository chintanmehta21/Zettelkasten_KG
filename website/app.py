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
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from fastapi.responses import JSONResponse

from website.api.chat_routes import router as chat_router
from website.api.nexus import router as nexus_router
from website.api.routes import router as api_router
from website.api.sandbox_routes import router as sandbox_router
from website.api.zettels_routes import router as zettels_router
from website.features.refresh_button.refresh_routes import router as refresh_button_router
from website.features.summarization_engine.api import router as engine_v2_router
from website.features.user_pricing.routes import router as pricing_router
from website.features.web_monitor import router as web_monitor_router
from website.features.feedback import register as register_feedback
from website.features.web_monitor.App_Errors import notify_app_error
from website.features.web_monitor._env_validation import (
    log_web_monitor_env_warnings,
)
from website.api.admin_routes import router as admin_router
from website.api.meta_routes import router as meta_router
from website.api.profile_routes import router as profile_router
from website.api.quota_routes import router as quota_router
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

# Feature modules can append HTML to the rendered footer via this hook —
# avoids editing website/footer/footer.html for every self-contained feature.
# Each callable receives the footer fragment string and returns a (possibly)
# modified string. See website/features/feedback/__init__.py for usage.
_FOOTER_POST_PROCESSORS: list = []


def register_footer_post_processor(fn) -> None:
    """Allow self-contained features (e.g. website/features/feedback/) to
    inject HTML into the rendered footer without modifying footer.html.
    """
    _FOOTER_POST_PROCESSORS.append(fn)


def _apply_footer_post_processors(footer_html: str) -> str:
    """Apply feature footer hooks while keeping failures non-fatal."""
    for _fn in _FOOTER_POST_PROCESSORS:
        try:
            footer_html = _fn(footer_html)
        except Exception as exc:  # never let a feature crash the page
            logger.warning("footer post-processor raised: %s", exc)
    return footer_html

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
            # Apply self-contained feature post-processors (e.g. feedback loader).
            footer_html = _apply_footer_post_processors(footer_html)
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
    canonical_url: Optional[str] = None,
    request: Optional[Request] = None,
) -> HTMLResponse:
    """Inject mobile shell around a body fragment file.

    Mobile shell owns <head> + header + bottom-tab nav + footer. Body fragment
    file is expected to contain ONLY the in-<main> content (no <html>/<head>/<body>
    wrappers).
    """
    shell = _MOBILE_SHELL.read_text(encoding="utf-8")
    body = body_path.read_text(encoding="utf-8")
    # Separate-mobile-URL canonical: point public /m/* pages at their desktop
    # equivalent so the canonical signal consolidates to one URL.
    canonical_tag = f'<link rel="canonical" href="{canonical_url}">' if canonical_url else ""
    rendered = (
        shell
        .replace("<!--ZK_MOBILE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_PAGE_TITLE-->", page_title)
        .replace("<!--ZK_MOBILE_BODY_CLASS-->", body_class)
        .replace("<!--ZK_MOBILE_CANONICAL-->", canonical_tag)
        .replace("<!--ZK_MOBILE_CONTENT-->", body)
    )

    # Server-side avatar preload — improves first-paint for the user's own
    # avatar. The URL comes from JWT metadata which is OPERATOR-CONTROLLED but
    # has historically carried provider URLs (Google / Gravatar) and could
    # carry an attacker-controlled string if metadata is ever set from an
    # untrusted source. Validate against the curated `/artifacts/avatars/`
    # path pattern before injecting; anything else => no preload.
    avatar_url = _avatar_url_from_request(request) if request else None
    preload_tag = (
        f'<link rel="preload" as="image" type="image/svg+xml" href="{avatar_url}">'
        if _is_curated_avatar_url(avatar_url) else ""
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
        + '\n<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.106" crossorigin></script>'
        + '\n<script src="/auth/js/auth-core.js?v=20260601a"></script>'
        + '\n<script src="/m/js/auth-modal.js?v=20260601a"></script>'
        + '\n<script src="/m/js/avatar.js?v=20260530a"></script>'
    )
    # Mobile pages use a full shell instead of the desktop footer placeholder,
    # so feature footer hooks are inserted directly before the shell closes.
    rendered = rendered.replace("</body>", _apply_footer_post_processors("") + "\n</body>", 1)
    rendered = rendered.replace("</body>", auth_block + "\n</body>", 1)
    return HTMLResponse(content=rendered, headers=_HTML_CACHE_HEADERS)


# Exact bound to the 120 on-disk assets (avatar_00..avatar_119): 0\d=00-09,
# [1-9]\d=10-99, 1[01]\d=100-119. Keeps the XSS gate tightly scoped to files
# that exist — a future AVATAR_COUNT bump that forgets to author SVGs fails
# the gate rather than passing dead/preload URLs.
_CURATED_AVATAR_RE = re.compile(
    r"^/artifacts/avatars/avatar_(0\d|[1-9]\d|1[01]\d)\.svg$"
)


def _is_curated_avatar_url(url: Optional[str]) -> bool:
    """True iff *url* matches the curated set under /artifacts/avatars/.

    XSS defense for any path that interpolates an avatar URL into HTML —
    guarantees no attacker-controlled bytes can leak into href/src/preload
    attributes even if metadata is ever set from an untrusted source.
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_CURATED_AVATAR_RE.match(url))


def _avatar_url_from_request(request: Request) -> Optional[str]:
    """Best-effort cookie decode; returns None if unauth or decode fails.

    Used for first-paint avatar preload only — never as an auth source.
    Reuses the same JWT decoder as the API auth path. Note: cookies are NOT
    the primary session store (auth-core.js persists in localStorage), so
    this typically returns None for real signed-in users; preload silently
    no-ops in that case and avatar.js renders post-hydration via /api/me.
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
    except Exception as exc:  # noqa: BLE001 — best-effort preload; never raise
        logger.debug("avatar preload: cookie token decode failed: %s", exc)
        return None


# Regex to detect mobile user-agents
_MOBILE_RE = re.compile(
    r"Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|mobile",
    re.IGNORECASE,
)

# SE + social crawlers must reach canonical desktop pages: Googlebot's
# mobile-first UA carries "Mobile" and would otherwise 302 -> /m/ home.
_CRAWLER_RE = re.compile(
    r"Googlebot|Google-InspectionTool|Storebot-Google|GoogleOther|"
    r"bingbot|BingPreview|Slurp|DuckDuckBot|Baiduspider|YandexBot|Sogou|"
    r"Applebot|PetalBot|AhrefsBot|SemrushBot|"
    r"facebookexternalhit|Facebot|Twitterbot|LinkedInBot|Slackbot|"
    r"WhatsApp|TelegramBot|Discordbot|Pinterest|redditbot",
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
    if _CRAWLER_RE.search(ua):
        return False  # bots get desktop canonical pages, never the /m/ redirect
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

    # API routes
    app.include_router(api_router)
    app.include_router(zettels_router)
    app.include_router(refresh_button_router)
    app.include_router(engine_v2_router)
    app.include_router(chat_router)
    app.include_router(sandbox_router)
    app.include_router(pricing_router)
    app.include_router(web_monitor_router)
    app.include_router(admin_router)
    app.include_router(meta_router)
    app.include_router(profile_router)
    app.include_router(quota_router)
    if nexus_enabled:
        app.include_router(nexus_router)

    # Feedback feature (website/features/feedback/) — self-contained module.
    # Registers POST /api/feedback/submit + /api/feedback/health, mounts
    # /feedback-ui static, and appends its loader <script>/<link> tags to
    # the rendered footer via register_footer_post_processor().
    register_feedback(app)
    # iter-03 mem-bounded §2.9: install AFTER routers so middleware wraps every route.
    _memory_guard.install(app)

    # iter-03 §B (2026-04-29): post-response aggressive memory release.
    # Runs gc.collect() + glibc malloc_trim(0) AFTER each response is sent
    # to the client (no user-perceived latency impact). Targets the
    # ~180-430 MB per-query native residual that gc alone cannot free
    # (ONNX internal buffers, Gemini/Supabase httpx body buffers, glibc
    # arena freelist). Exempts /api/health* and /favicon.* so cheap probes
    # don't pay the trim cost. Safe on non-glibc platforms (no-op).
    # PR #115 (Scope C): pure-ASGI — `await self.app(...)` only returns
    # after body drain, so the prior 50ms `call_later` workaround for the
    # h11 Content-Length race is no longer needed.
    from website.api._middleware import PostResponseReleaseMiddleware
    app.add_middleware(
        PostResponseReleaseMiddleware,
        exempt_prefixes=("/api/health", "/favicon."),
    )

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

    # ── Prajeet 2026-05-25/26: surface auth degradation to the client ──
    # ``get_optional_user`` silently maps degraded-auth requests to anonymous
    # (and downstream ``_effective_user_id`` to Zoro). The dep tags
    # ``request.state.auth_status`` for two cases — AuthStatusHeadersMiddleware
    # reflects the tag onto the response as ``X-Auth-Status: <value>``.
    # Legitimate anonymous traffic (no Authorization AND no Zk-Auth-Intent
    # hint) leaves the marker unset and the header absent — observability
    # stays silent. Converted to pure-ASGI in PR #115 (Scope C).
    from website.api._middleware import AuthStatusHeadersMiddleware
    app.add_middleware(AuthStatusHeadersMiddleware)

    # ── Phase 1.5 Item 3: zk-session-marker cookie ──
    # Survives a localStorage wipe so the client can detect "was signed in
    # before but my session storage is gone" on the next page load. Set on
    # EVERY authenticated response (idempotent — only emitted when the
    # cookie isn't already present in the request, so it's a one-time
    # ``Set-Cookie`` per browser per 30-day window). Non-HttpOnly because
    # JS reads it on boot to gate the re-auth banner; the cookie value is
    # just ``"1"`` (no secret), so an XSS reader learns nothing useful.
    # Server-set is critical: per Safari 18.4 WebKit policy (still active
    # 2025), ``document.cookie`` writes are capped at 7 days for ITP-flagged
    # sites; ``Set-Cookie`` response headers are exempt and persist for
    # the full Max-Age. SameSite=Lax + Secure block cross-site abuse.
    # Converted to pure-ASGI in PR #115 (Scope C).
    from website.api._middleware import SessionMarkerCookieMiddleware
    app.add_middleware(SessionMarkerCookieMiddleware)

    # ── Item 6: zk_anon_sid cookie (anon → user zettel claim) ──
    # Opaque uuid4 set on UN-authenticated responses that lack it, so an
    # anonymous visitor's Zoro-stored captures can later be claimed into their
    # own workspace at sign-in. HttpOnly (the claim endpoint reads it server-
    # side; JS never needs it) + Secure + SameSite=Lax + Max-Age=30d. Unsigned —
    # the DB validates it by matching the persisted anon_sid, so a forged value
    # claims nothing. Mirrors SessionMarkerCookieMiddleware's egress shape but
    # inverts the auth predicate (anon, not authed) and adds HttpOnly. Also
    # stashes the freshly-minted sid on request.state for same-request capture
    # tagging in the add-zettel path.
    from website.api._middleware import AnonSessionCookieMiddleware
    app.add_middleware(AnonSessionCookieMiddleware)

    # ── C13: 401 rate monitor (credential-stuffing / scanner detection) ──
    # Sliding-window counter on global + per-IP 401 responses. Out-of-path
    # of auth.py (hot path stays fast); runs at response-egress time as a
    # cheap status-code check + rate-gate tick. Hashed IP only — never the
    # raw client address (daily-rotated salt; matches OWASP cred-stuffing
    # alert payload contract). Converted to pure-ASGI in PR #115 (Scope C).
    from website.api._middleware import Auth401RateMonitorMiddleware
    app.add_middleware(Auth401RateMonitorMiddleware)

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

    # Avatars — long-cache immutable static files (the curated SVG preset set
    # under /artifacts/avatars/; GET /api/avatars is the source of truth for the count).
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
    _favicon_ico_path = STATIC_DIR / "favicon.ico"

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon_ico():
        # Real multi-size .ico (16/32/48) for Google SERP + legacy /favicon.ico
        # auto-discovery; the SVG is still offered via the rel=icon links in <head>.
        return FileResponse(
            str(_favicon_ico_path),
            media_type="image/x-icon",
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

    @app.get("/robots.txt", include_in_schema=False)
    async def robots_txt():
        # Wildcard allow keeps Googlebot/Bingbot + answer-engine/citation bots
        # (OAI-SearchBot, PerplexityBot, Claude-SearchBot, *-User) fully crawlable.
        # Only AI *training* crawlers are denied (per-bot groups → Googlebot is
        # never in scope of a Disallow). Google-Extended/Applebot-Extended are
        # training tokens distinct from Googlebot/Applebot — blocking them does
        # not affect Search/Siri indexing.
        body = (
            "User-agent: *\n"
            "Allow: /\n\n"
            + "".join(
                f"User-agent: {bot}\nDisallow: /\n\n"
                for bot in (
                    "GPTBot",
                    "Google-Extended",
                    "ClaudeBot",
                    "anthropic-ai",
                    "CCBot",
                    "Bytespider",
                    "Applebot-Extended",
                    "Meta-ExternalAgent",
                )
            )
            + "Sitemap: https://zettelkasten.in/sitemap.xml\n"
        )
        return PlainTextResponse(body)

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap_xml():
        # Public, indexable URLs only; private app pages are CSR shells behind
        # auth and are intentionally omitted.
        paths = ("/", "/about", "/pricing", "/knowledge-graph",
                 "/privacy", "/terms", "/data-security")
        locs = "".join(
            f"<url><loc>https://zettelkasten.in{p}</loc></url>" for p in paths
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{locs}</urlset>"
        )
        return Response(content=xml, media_type="application/xml")

    # ── Mobile routes ──
    @app.get("/m/")
    async def mobile_index(request: Request):
        return _render_with_mobile_shell(
            MOBILE_DIR / "index.html",
            page_title="Summarize",
            canonical_url="https://zettelkasten.in/",
            request=request,
        )

    @app.get("/m/knowledge-graph")
    async def mobile_knowledge_graph(request: Request):
        return _render_with_mobile_shell(
            MOBILE_DIR / "knowledge-graph.html",
            page_title="Knowledge Graph",
            body_class="kg-body",
            canonical_url="https://zettelkasten.in/knowledge-graph",
            request=request,
        )

    @app.get("/m/zettels")
    async def mobile_zettels(request: Request):
        # Auth gate is client-side: zettels.js calls /api/zettels with a Bearer
        # token from window.getAuthToken(). Server-side cookie gates do NOT
        # work here because the Supabase JS client persists the session in
        # localStorage (storageKey 'zk-auth-token' in auth-core.js), not in
        # cookies. The client renders an anon-banner + "Sign in" CTA when the
        # API returns 401 (see zettels.js).
        return _render_with_mobile_shell(
            MOBILE_DIR / "zettels.html",
            page_title="Zettels",
            body_class="m-zettels",
            request=request,
        )

    @app.get("/m/kastens")
    async def mobile_kastens(request: Request):
        # See mobile_zettels above for the auth-gate rationale.
        return _render_with_mobile_shell(
            MOBILE_DIR / "kastens.html",
            page_title="Kastens",
            body_class="m-kastens",
            request=request,
        )

    @app.get("/m/profile")
    async def mobile_profile(request: Request):
        return _render_with_mobile_shell(
            MOBILE_DIR / "profile.html",
            page_title="Profile",
            body_class="m-profile",
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

    # Standalone, server-rendered legal pages. Distinct crawlable URLs (no
    # login, no redirect — intentionally NOT UA-gated like /about) on the
    # verified domain, as required for Google OAuth brand verification. The
    # /about modal keeps its own mirror of this copy in about.js (keep both in
    # sync); these pages are what Google + the direct links resolve to.
    @app.get("/privacy")
    async def privacy_page(request: Request):
        from website.core.legal_content import render_legal_page_html

        return HTMLResponse(render_legal_page_html("privacy"))

    @app.get("/terms")
    async def terms_page(request: Request):
        from website.core.legal_content import render_legal_page_html

        return HTMLResponse(render_legal_page_html("terms"))

    @app.get("/data-security")
    async def data_security_page(request: Request):
        from website.core.legal_content import render_legal_page_html

        return HTMLResponse(render_legal_page_html("security"))

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
