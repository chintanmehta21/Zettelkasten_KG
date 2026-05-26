"""HTTP client wrapper that revalidates every redirect hop.

httpx with ``follow_redirects=True`` validates only the FIRST URL, then
auto-follows ``Location`` headers without re-checking. That's the SSRF
TOCTOU window: a clean-on-submission URL can 302 to a private/internal
address (cloud metadata, blue/green sibling at ``127.0.0.1:10001``, the
Docker bridge network, etc.). This module closes the window by following
redirects manually and re-running ``validate_url`` on each ``Location``.

API:
  * ``safe_request(method, url, *, head_first=False, max_hops=5, ...)``
    — generic manual-redirect wrapper, raises ``UnsafeRedirectError`` on
    forbidden Location, ``RedirectLoopError`` past ``max_hops``.

This wrapper does NOT close the DNS-rebinding race between
``validate_url`` and httpx's TCP-connect resolution — that's the deferred
custom-transport work (Item D of the SSRF hardening audit). The hop-by-hop
gate here addresses the auto-follow redirect bypass, which is the higher
incidence-rate attack surface.
"""

from __future__ import annotations

import logging
from typing import Iterable
from urllib.parse import urljoin

import httpx

from website.core.url_utils import validate_url

logger = logging.getLogger(__name__)

# Max redirect hops before giving up. 5 mirrors the legacy httpx default
# (httpx.Client.max_redirects = 20 is way too permissive for an
# externally-controlled URL; 5 covers legitimate chains like t.co →
# bit.ly → final without leaving room for adversarial exhaustion).
MAX_REDIRECT_HOPS = 5

# 25 MB default body cap — matches summarization-engine's input budget
# (Gemini context, BGE chunker). Bounded so a server streaming gigabytes
# can't exhaust the 2 GB droplet's worker memory. Per-call override via
# the ``max_response_bytes`` kwarg.
DEFAULT_MAX_RESPONSE_BYTES = 25 * 1024 * 1024

# 3xx status codes that trigger a redirect follow. 304 (Not Modified) is
# excluded — it's a conditional-GET response, not a redirect.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class SafeHttpError(Exception):
    """Base for safe_http refusal errors."""


class UnsafeRedirectError(SafeHttpError):
    """A redirect Location pointed at a forbidden destination
    (private IP, non-http scheme, malformed URL)."""


class RedirectLoopError(SafeHttpError):
    """Redirect chain exceeded ``max_hops`` — abort to bound work."""


class ResponseTooLargeError(SafeHttpError):
    """Final response body exceeded ``max_response_bytes`` — abort streaming."""


def _resolve_location(current_url: str, location: str) -> str:
    """Resolve a possibly-relative Location header against the current URL.
    RFC 9110 §10.2.2 allows relative Locations; ``urljoin`` is the canonical
    resolver.
    """
    return urljoin(current_url, location)


async def _follow_with_revalidation(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_hops: int,
    headers: dict[str, str] | None,
    max_response_bytes: int,
) -> httpx.Response:
    """Issue ``method`` against ``url``; on 3xx, validate the Location and
    re-issue. Cap at ``max_hops`` total transitions (the initial request
    counts as hop 0). On the FINAL response, stream the body with a running
    byte-total cap to bound worker memory."""
    current_url = url
    request_headers = dict(headers or {})
    for hop in range(max_hops + 1):
        async with client.stream(
            method, current_url, headers=request_headers
        ) as response:
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    # Spec-broken 3xx with no Location — surface as-is. Need
                    # to materialize the body before the stream closes.
                    await response.aread()
                    return response
                next_url = _resolve_location(current_url, location)
                if not validate_url(next_url):
                    raise UnsafeRedirectError(
                        f"Refused redirect from {current_url!r} to {next_url!r}: "
                        "Location fails post-DNS / scheme allowlist."
                    )
                # Drop Authorization-like headers on cross-host redirects
                # (matches httpx's auto-redirect behavior — defense against
                # credential leak to a different host).
                if _is_cross_host(current_url, next_url):
                    request_headers = {
                        k: v
                        for k, v in request_headers.items()
                        if k.lower() not in _SENSITIVE_HEADERS
                    }
                current_url = next_url
                continue
            # Terminal response — stream body with size cap.
            total = 0
            chunks: list[bytes] = []
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_response_bytes:
                    raise ResponseTooLargeError(
                        f"Response from {current_url!r} exceeded "
                        f"{max_response_bytes} bytes; aborted streaming."
                    )
                chunks.append(chunk)
            # Materialize the body so callers can use .text / .content / .json().
            # aiter_bytes() above already populated _content via httpx internals,
            # but we set it explicitly for predictability across httpx versions.
            response._content = b"".join(chunks)
            return response
    raise RedirectLoopError(
        f"Exceeded {max_hops} redirects starting from {url!r}."
    )


_SENSITIVE_HEADERS: Iterable[str] = frozenset({"authorization", "cookie"})


def _is_cross_host(a: str, b: str) -> bool:
    from urllib.parse import urlparse

    return urlparse(a).netloc.lower() != urlparse(b).netloc.lower()


async def safe_request(
    method: str,
    url: str,
    *,
    head_first: bool = False,
    max_hops: int = MAX_REDIRECT_HOPS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Manual-redirect HTTP request with per-hop SSRF revalidation
    and a streaming response-size cap.

    Args:
      method: Final-request method (``"GET"``, ``"POST"``, ...).
      url: Initial URL — must already pass ``validate_url`` at the caller.
      head_first: If True, try ``HEAD`` first (cheap probe — no body fetch)
        and fall back to ``method`` if the HEAD final response is ``>=400``.
        Matches legacy ``resolve_redirects`` semantics.
      max_hops: Per-call cap on redirect transitions.
      max_response_bytes: Stop reading the final response once total bytes
        exceed this. Raises ``ResponseTooLargeError`` on overflow.
      timeout: Total request timeout per hop.
      headers: Request headers (passed through; Authorization/Cookie are
        dropped on cross-host redirect).

    Raises:
      UnsafeRedirectError: Location failed ``validate_url``.
      RedirectLoopError: chain exceeded ``max_hops``.
      ResponseTooLargeError: final body exceeded ``max_response_bytes``.
      httpx.HTTPError subclasses: connect/timeout/etc.
    """
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=timeout
    ) as client:
        if head_first:
            try:
                resp = await _follow_with_revalidation(
                    client,
                    "HEAD",
                    url,
                    max_hops=max_hops,
                    headers=headers,
                    max_response_bytes=max_response_bytes,
                )
                if resp.status_code < 400:
                    return resp
                # HEAD final = 4xx/5xx → retry as `method` (e.g. GET).
            except httpx.UnsupportedProtocol:
                pass
        return await _follow_with_revalidation(
            client,
            method,
            url,
            max_hops=max_hops,
            headers=headers,
            max_response_bytes=max_response_bytes,
        )
