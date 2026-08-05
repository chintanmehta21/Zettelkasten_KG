"""Pure-ASGI middleware classes (PR #115 Scope C).

Replaces the legacy ``@app.middleware("http")`` BaseHTTPMiddleware decorators
which are fundamentally racy against the response-body pump
(encode/starlette#1438, #1715; fastapi#4544; Kludex/starlette#2160). Per the
Starlette maintainer: "BaseHTTPMiddleware has terminal architectural flaws."

Migration semantics MUST match the prior decorator behavior bit-for-bit.
Phase 1A memory release (PostResponseReleaseMiddleware) keeps its
release-post-body-drain invariant; the 50 ms ``call_later`` workaround from
PR #113 is gone because pure-ASGI's ``await self.app(...)`` only returns
after the final body chunk has been pumped, so the gc/malloc_trim race that
motivated the workaround is structurally impossible here.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from website.api._mem_release import aggressive_release as _aggressive_release
from website.features.web_monitor import _hash_id, maybe_fire_app_error_rate

logger = logging.getLogger("website.api._middleware")

_ASGISend = Callable[[dict], Awaitable[None]]
_ASGIReceive = Callable[[], Awaitable[dict]]
_ASGIApp = Callable[[dict, _ASGIReceive, _ASGISend], Awaitable[None]]


def _set_header(
    headers: list[tuple[bytes, bytes]], key: bytes, value: bytes
) -> list[tuple[bytes, bytes]]:
    """Replace any existing entries with `key` (case-insensitive) then append.
    Mirrors Starlette ``MutableHeaders.__setitem__`` so the pure-ASGI
    rewrite is behaviorally identical to ``response.headers[k] = v``.
    """
    key_lower = key.lower()
    out = [(k, v) for k, v in headers if k.lower() != key_lower]
    out.append((key, value))
    return out


def _request_cookies(scope: dict) -> dict[str, str]:
    """Parse the Cookie header from the ASGI scope into a {name: value} dict."""
    cookies: dict[str, str] = {}
    for key, value in scope.get("headers", []):
        if key.lower() == b"cookie":
            for crumb in value.decode("latin-1").split(";"):
                crumb = crumb.strip()
                if "=" in crumb:
                    name, val = crumb.split("=", 1)
                    cookies[name.strip()] = val.strip()
    return cookies


def _request_header(scope: dict, name: bytes) -> str | None:
    """Get a request header by name (case-insensitive). Returns the first match."""
    name_lower = name.lower()
    for key, value in scope.get("headers", []):
        if key.lower() == name_lower:
            return value.decode("latin-1")
    return None


def _state_get(scope: dict, key: str, default=None):
    """Read request.state.<key> via the ASGI scope. Starlette 1.0+ stores
    state as a plain dict at ``scope["state"]`` (the underlying storage that
    ``Request.state`` wraps in a ``State`` view). Older versions stored a
    ``State`` object directly — fall back to attribute access for safety.
    """
    state = scope.get("state")
    if isinstance(state, dict):
        return state.get(key, default)
    if state is None:
        return default
    return getattr(state, key, default)


class AuthStatusHeadersMiddleware:
    """Reflect ``request.state.auth_status`` onto ``X-Auth-Status`` response
    header. WWW-Authenticate is only emitted for ``jwt-dropped-to-anon``
    (RFC 6750 invalid_token semantics; token-missing-but-expected and
    spa-inferred get X-Auth-Status + Cache-Control only — those branches
    have no JWT to label invalid). Cache-Control: private, no-store on
    every tagged response prevents Cloudflare from serving a degraded-anon
    response to a different caller.
    """

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: _ASGIReceive, send: _ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status = _state_get(scope, "auth_status")
                if status:
                    headers = list(message.get("headers", []))
                    headers = _set_header(
                        headers, b"x-auth-status", status.encode("latin-1")
                    )
                    if status == "jwt-dropped-to-anon":
                        headers = _set_header(
                            headers,
                            b"www-authenticate",
                            (
                                b'Bearer error="invalid_token", '
                                b'error_description="JWT silently downgraded to anonymous"'
                            ),
                        )
                    headers = _set_header(
                        headers, b"cache-control", b"private, no-store"
                    )
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class SessionMarkerCookieMiddleware:
    """Set ``zk-session-marker=1`` cookie on every authenticated response
    where the cookie isn't already present in the request — survives a
    localStorage wipe so the client can detect prior-sign-in on next page
    load. Non-HttpOnly (JS reads it on boot); value is just ``"1"`` so an
    XSS reader learns nothing. SameSite=Lax + Secure block cross-site abuse.
    Idempotent: skipped when the request already carries the cookie.
    """

    _COOKIE_NAME = "zk-session-marker"
    # 30 days; Set-Cookie header is exempt from Safari 18.4 ITP 7-day cap.
    _MAX_AGE = 30 * 24 * 60 * 60

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: _ASGIReceive, send: _ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                authenticated = bool(_state_get(scope, "authenticated", False))
                if authenticated:
                    cookies = _request_cookies(scope)
                    if self._COOKIE_NAME not in cookies:
                        cookie_value = (
                            f"{self._COOKIE_NAME}=1; Max-Age={self._MAX_AGE}; "
                            f"Path=/; Secure; SameSite=Lax"
                        ).encode("latin-1")
                        headers = list(message.get("headers", []))
                        # Set-Cookie may appear multiple times — append, don't replace.
                        headers.append((b"set-cookie", cookie_value))
                        message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AnonSessionCookieMiddleware:
    """Set an opaque ``zk_anon_sid`` cookie (uuid4) on UN-authenticated
    responses that don't already carry one, so an anonymous visitor's
    browser-session captures (stored under the canonical Zoro user) can later
    be claimed into their own workspace when they sign in (Item 6 — anon ->
    user zettel claim).

    Contrast with ``SessionMarkerCookieMiddleware`` (set on AUTHED responses,
    non-HttpOnly, value ``"1"``): this cookie is set on ANON responses, is
    **HttpOnly** (JS never needs it — the claim endpoint reads it server-side),
    and carries an opaque random UUID. It is NOT signed/HMAC'd — the DB
    validates it by matching against the persisted ``anon_sid`` on the rows it
    tagged, so a forged value claims nothing.

    Same-request capture: the add-zettel handler runs in the SAME request that
    first mints the sid, but the Set-Cookie only reaches the browser on the
    response. So on ingress (before calling the inner app) we stash the minted
    sid on ``scope["state"]["anon_sid"]`` — Starlette exposes it to handlers as
    ``request.state.anon_sid``, and the capture path tags the just-persisted
    row with it even on the very first anon request.

    Attrs: HttpOnly, Secure, SameSite=Lax, Path=/, Max-Age=30d. Idempotent:
    skipped when the request already carries the cookie (the existing sid is
    already readable via ``request.cookies``).
    """

    _COOKIE_NAME = "zk_anon_sid"
    # 30 days; Set-Cookie header is exempt from Safari 18.4 ITP 7-day cap.
    _MAX_AGE = 30 * 24 * 60 * 60

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: _ASGIReceive, send: _ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cookies = _request_cookies(scope)
        existing = cookies.get(self._COOKIE_NAME)
        minted: str | None = None
        if not existing:
            import uuid as _uuid

            minted = str(_uuid.uuid4())
            # Stash on request.state so the SAME-request capture path can read
            # the freshly-minted sid (the Set-Cookie below only reaches the
            # browser on subsequent requests). Starlette 1.0 lazily backs
            # request.state with scope["state"] (a plain dict).
            state = scope.get("state")
            if not isinstance(state, dict):
                state = {}
                scope["state"] = state
            state["anon_sid"] = minted

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start" and minted is not None:
                # Only set the cookie when the response is un-authenticated.
                # An authed response (e.g. a request that DID carry a valid
                # JWT but no anon cookie) must not be tagged with an anon sid —
                # that visitor is already a real user, not a claim candidate.
                authenticated = bool(_state_get(scope, "authenticated", False))
                # Part B Phase 1: edge-cacheable responses (view=global) must
                # never carry Set-Cookie — a stray cookie forces Cloudflare BYPASS.
                # Routes set suppress_anon_cookie=True on request.state to opt out.
                suppress = bool(_state_get(scope, "suppress_anon_cookie", False))
                if not authenticated and not suppress:
                    cookie_value = (
                        f"{self._COOKIE_NAME}={minted}; Max-Age={self._MAX_AGE}; "
                        f"Path=/; HttpOnly; Secure; SameSite=Lax"
                    ).encode("latin-1")
                    headers = list(message.get("headers", []))
                    # Set-Cookie may appear multiple times — append, don't replace.
                    headers.append((b"set-cookie", cookie_value))
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class Auth401RateMonitorMiddleware:
    """Sliding-window credential-stuffing / scanner detection. On 401
    responses (excluding /api/health and /webhooks/monitor/), fires the
    global rate gate (>=100/5min) and per-IP rate gate (>=30/60s) into the
    Slack alert pipeline. Fire-and-forget: any monitor failure is logged
    at DEBUG and swallowed so middleware never breaks the response.
    """

    _EXEMPT_PREFIXES = ("/api/health", "/webhooks/monitor/")

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: _ASGIReceive, send: _ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        captured_status = [200]

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                captured_status[0] = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if captured_status[0] == 401:
                self._fire(scope)

    @classmethod
    def _fire(cls, scope: dict) -> None:
        try:
            path = scope.get("path", "")
            if path.startswith(cls._EXEMPT_PREFIXES):
                return
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
                    "route_sample": path[:80],
                },
                severity="warning",
                alert_dedup_seconds=15 * 60,
            )
            raw_ip = (
                _request_header(scope, b"cf-connecting-ip")
                or (
                    (_request_header(scope, b"x-forwarded-for") or "")
                    .split(",")[0]
                    .strip()
                )
                or (scope.get("client") or ("", 0))[0]
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


class PostResponseReleaseMiddleware:
    """Phase 1A iter-03 post-response aggressive memory release. Runs
    ``gc.collect() + glibc malloc_trim(0)`` AFTER the inner app finishes
    pumping the response body — in pure-ASGI, ``await self.app(...)``
    returns only after the final ``http.response.body`` (more_body=False)
    is sent, so the gc-mid-stream race from encode/starlette#1438 is
    structurally impossible here. Exempt path prefixes (probes, favicons)
    skip the trim to keep them cheap.
    """

    def __init__(
        self,
        app: _ASGIApp,
        exempt_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.exempt_prefixes = exempt_prefixes

    async def __call__(self, scope: dict, receive: _ASGIReceive, send: _ASGISend) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path.startswith(p) for p in self.exempt_prefixes):
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                _aggressive_release()
            except Exception:  # noqa: BLE001
                logger.exception("post-response release failed")
