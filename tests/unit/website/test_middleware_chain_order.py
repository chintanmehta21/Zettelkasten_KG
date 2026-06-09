"""Pin the middleware-registration order produced by ``create_app``.

PR #115 Scope C converted 5 BaseHTTPMiddleware decorators to pure-ASGI
classes. The chain order is correctness-critical (AuthHeaders/SessionMarker/
Auth401 must wrap the response; MemoryGuard must short-circuit BEFORE any
route work happens). A future reorder of ``app.add_middleware`` calls would
silently break the response contract; this test makes any such reorder break
loudly instead.
"""
from __future__ import annotations

from website.app import create_app


# Source-order in create_app (FIFO). Starlette ``add_middleware``
# PREPENDS, so item [0] here is the FIRST added = INNERMOST in the
# request/response chain. Item [-1] is the LAST added = OUTERMOST.
EXPECTED_MIDDLEWARE_ORDER: list[str] = [
    "MemoryGuardMiddleware",
    "PostResponseReleaseMiddleware",
    "AuthStatusHeadersMiddleware",
    "SessionMarkerCookieMiddleware",
    "AnonSessionCookieMiddleware",
    "Auth401RateMonitorMiddleware",
]


def _registered_middleware_names(app) -> list[str]:
    """Return the class names of registered middleware in registration order
    (first registered = first in the list).

    Starlette stores ``user_middleware`` in INSERTION order; ``add_middleware``
    INSERTS at the BEGINNING. So index 0 of ``app.user_middleware`` is the
    LAST added (outermost), and index -1 is the FIRST added (innermost).
    We reverse to match EXPECTED_MIDDLEWARE_ORDER's "innermost first" reading.
    """
    return [m.cls.__name__ for m in reversed(app.user_middleware)]


def test_middleware_registration_order_pinned():
    """Any reorder of ``app.add_middleware`` calls in create_app breaks here.
    If you intentionally changed the order, update EXPECTED_MIDDLEWARE_ORDER
    and verify the response-egress chain semantics still hold (X-Auth-Status
    and Set-Cookie headers set correctly; MemoryGuard short-circuits BEFORE
    PostResponseRelease triggers gc).
    """
    app = create_app()
    names = _registered_middleware_names(app)
    # Filter to just the middleware we care about (Starlette + FastAPI add
    # their own internal ones we don't pin).
    pinned = [n for n in names if n in set(EXPECTED_MIDDLEWARE_ORDER)]
    assert pinned == EXPECTED_MIDDLEWARE_ORDER, (
        f"Middleware chain reordered. Expected (innermost → outermost): "
        f"{EXPECTED_MIDDLEWARE_ORDER}, got {pinned}. "
        f"Full registered chain (innermost → outermost): {names}."
    )


def test_all_expected_middleware_present():
    """Sanity: every name in EXPECTED_MIDDLEWARE_ORDER is actually registered.
    Guards against a stale expectation list outlasting a deleted middleware.
    """
    app = create_app()
    names = set(_registered_middleware_names(app))
    missing = [n for n in EXPECTED_MIDDLEWARE_ORDER if n not in names]
    assert not missing, (
        f"Expected middleware not registered: {missing}. "
        f"Registered: {sorted(names)}"
    )


def test_no_app_level_compression_middleware():
    """Compression is owned by Caddy `encode zstd gzip` + Cloudflare edge Brotli
    (audit 2026-06-04). No ASGI compressor may sit in the app — on 1 vCPU it
    steals event-loop CPU, and a buffering compressor would risk the SSE
    heartbeat stream. This guard fails the build if one is re-added.
    """
    names = {m.cls.__name__ for m in create_app().user_middleware}
    assert "BrotliMiddleware" not in names, "drop brotli-asgi; Caddy/CF compress"
    assert "GZipMiddleware" not in names, "drop GZipMiddleware; Caddy/CF compress"
