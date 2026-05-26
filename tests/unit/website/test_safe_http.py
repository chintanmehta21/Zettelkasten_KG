"""Per-hop redirect revalidation tests for the safe_http wrapper.

A `clean` URL on submission can redirect to a private/internal address
(169.254.169.254, 127.0.0.1, blue/green sibling on 127.0.0.1:10001).
Auto-follow-redirects bypasses the original SSRF check; this module is
the fix — every Location header is re-validated against the same private-IP
allowlist before the next hop is followed.
"""

from __future__ import annotations

import pytest
import respx

from website.core.safe_http import (
    MAX_REDIRECT_HOPS,
    RedirectLoopError,
    ResponseTooLargeError,
    UnsafeRedirectError,
    safe_request,
)


@pytest.mark.asyncio
async def test_safe_request_returns_response_when_no_redirect():
    """No redirect — first response is returned as-is."""
    with respx.mock(base_url="https://example.com") as router:
        router.get("/page").respond(200, text="hello")
        response = await safe_request("GET", "https://example.com/page")
    assert response.status_code == 200
    assert response.text == "hello"
    assert str(response.url) == "https://example.com/page"


@pytest.mark.asyncio
async def test_safe_request_follows_external_redirect():
    """302 to another external host — must follow and return final response."""
    with respx.mock() as router:
        router.get("https://example.com/start").respond(
            302, headers={"Location": "https://external.example.org/final"}
        )
        router.get("https://external.example.org/final").respond(200, text="final")
        response = await safe_request("GET", "https://example.com/start")
    assert response.status_code == 200
    assert response.text == "final"
    assert str(response.url) == "https://external.example.org/final"


@pytest.mark.asyncio
async def test_safe_request_rejects_redirect_to_private_ip():
    """The whole reason this module exists: a 302 to a private/internal IP
    must be REFUSED, not silently followed. validate_url() blocks 169.254.169.254
    on submission, but the auto-redirect path bypassed that check — exactly
    the validate-then-fetch TOCTOU window."""
    with respx.mock() as router:
        router.get("https://example.com/start").respond(
            302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
        )
        with pytest.raises(UnsafeRedirectError):
            await safe_request("GET", "https://example.com/start")


@pytest.mark.asyncio
async def test_safe_request_rejects_redirect_to_loopback():
    """Sibling-color attack on the blue/green droplet: 127.0.0.1:10001 is
    the green container when blue is serving (or vice versa). Auto-follow
    redirects could reach it; per-hop validation must block."""
    with respx.mock() as router:
        router.get("https://example.com/start").respond(
            302, headers={"Location": "http://127.0.0.1:10001/api/internal"}
        )
        with pytest.raises(UnsafeRedirectError):
            await safe_request("GET", "https://example.com/start")


@pytest.mark.asyncio
async def test_safe_request_rejects_non_http_redirect_scheme():
    """Scheme allowlist: a redirect to file:// or gopher:// is a known SSRF
    escalation vector. validate_url enforces http(s); per-hop check must too."""
    with respx.mock() as router:
        router.get("https://example.com/start").respond(
            302, headers={"Location": "file:///etc/passwd"}
        )
        with pytest.raises(UnsafeRedirectError):
            await safe_request("GET", "https://example.com/start")


@pytest.mark.asyncio
async def test_safe_request_rejects_redirect_loop():
    """A redirect chain that exceeds MAX_REDIRECT_HOPS must abort. Protects
    against loops + exhaustion attacks.

    ``assert_all_called=False`` because the cap aborts before every mocked
    route is visited (which is exactly the point of the cap).
    """
    with respx.mock(assert_all_called=False) as router:
        # Build a chain longer than the cap — each step redirects to the next.
        chain_len = MAX_REDIRECT_HOPS + 2
        for i in range(chain_len):
            router.get(f"https://example.com/hop{i}").respond(
                302,
                headers={"Location": f"https://example.com/hop{i + 1}"},
            )
        with pytest.raises(RedirectLoopError):
            await safe_request("GET", "https://example.com/hop0")


@pytest.mark.asyncio
async def test_safe_request_follows_relative_location():
    """A relative Location header (RFC 9110 §10.2.2 allows them since 2014)
    must be resolved against the request URL before validation."""
    with respx.mock() as router:
        router.get("https://example.com/start").respond(
            302, headers={"Location": "/final"}
        )
        router.get("https://example.com/final").respond(200, text="ok")
        response = await safe_request("GET", "https://example.com/start")
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.asyncio
async def test_safe_request_rejects_oversize_response():
    """Defense against runaway server bodies: a 100 MB response (or any
    response above ``max_response_bytes``) must abort mid-stream, not
    accumulate gigabytes in worker memory. Caps the response-size attack
    surface on the 2 GB droplet."""
    oversize_body = b"x" * (3 * 1024 * 1024)  # 3 MB
    with respx.mock() as router:
        router.get("https://example.com/big").respond(200, content=oversize_body)
        with pytest.raises(ResponseTooLargeError):
            await safe_request(
                "GET",
                "https://example.com/big",
                max_response_bytes=1 * 1024 * 1024,  # 1 MB cap
            )


@pytest.mark.asyncio
async def test_safe_request_rejects_initial_private_ip_url():
    """If the caller forgets to pre-validate, the wrapper must still refuse
    a direct private/loopback URL — closes the latent footgun. Per-hop check
    only kicks in on Location headers; the first hop needs its own gate."""
    with pytest.raises(UnsafeRedirectError):
        await safe_request("GET", "http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_safe_request_validate_initial_opt_out():
    """A trusted-host caller can opt out of the initial check (e.g., for a
    known-good URL that's already validated upstream). Test uses a normal
    URL to confirm opt-out doesn't break the happy path."""
    with respx.mock() as router:
        router.get("https://example.com/ok").respond(200, text="ok")
        response = await safe_request(
            "GET", "https://example.com/ok", validate_initial=False
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_safe_request_passes_response_under_cap():
    """A response below the cap must be returned intact and readable."""
    small = b"hello world"
    with respx.mock() as router:
        router.get("https://example.com/small").respond(200, content=small)
        response = await safe_request(
            "GET",
            "https://example.com/small",
            max_response_bytes=1 * 1024 * 1024,
        )
    assert response.status_code == 200
    assert response.content == small
    assert response.text == "hello world"


@pytest.mark.asyncio
async def test_safe_request_decodes_gzip_response():
    """Regression for the 2026-05-26 brotli/gzip prod failure: ``aiter_bytes``
    returns decoded bytes, so the reconstructed Response must drop
    ``Content-Encoding``/``Content-Length`` or httpx tries to re-decode
    the already-decoded content (``httpx.DecodingError``). Wikipedia, Google,
    and most modern CDNs serve gzip/br by default — without this strip the
    entire generic-web ingestion path 5xxs.
    """
    import gzip
    import httpx

    plain = b"hello content-encoded world\n" * 200
    gzipped = gzip.compress(plain)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=[
                (b"content-encoding", b"gzip"),
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(gzipped)).encode()),
            ],
            content=gzipped,
        )

    # Patch the AsyncClient ctor used inside safe_request so we route through
    # a MockTransport that returns the gzipped payload.
    import website.core.safe_http as safe_http_mod

    original_client = safe_http_mod.httpx.AsyncClient

    def _client_with_mock(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    safe_http_mod.httpx.AsyncClient = _client_with_mock
    try:
        response = await safe_request(
            "GET", "https://example.com/gz", validate_initial=False
        )
    finally:
        safe_http_mod.httpx.AsyncClient = original_client

    # The body must be the decoded plaintext, accessible without
    # raising DecodingError. The Content-Encoding header is preserved on
    # the response (matches httpx.get() behaviour — _content is the
    # decoded buffer and the decoder short-circuits on subsequent reads).
    assert response.status_code == 200
    assert response.content == plain
    assert response.text == plain.decode()
    assert response.headers["content-encoding"] == "gzip"


@pytest.mark.asyncio
async def test_safe_request_decodes_brotli_response():
    """Same regression as gzip, but for brotli — the Google failure case."""
    import brotli  # type: ignore[import-not-found]
    import httpx

    plain = b"brotli compressed payload " * 200
    br_bytes = brotli.compress(plain)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=[
                (b"content-encoding", b"br"),
                (b"content-type", b"text/plain; charset=utf-8"),
            ],
            content=br_bytes,
        )

    import website.core.safe_http as safe_http_mod

    original_client = safe_http_mod.httpx.AsyncClient

    def _client_with_mock(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    safe_http_mod.httpx.AsyncClient = _client_with_mock
    try:
        response = await safe_request(
            "GET", "https://example.com/br", validate_initial=False
        )
    finally:
        safe_http_mod.httpx.AsyncClient = original_client

    assert response.content == plain
    assert response.text == plain.decode()
    assert response.headers["content-encoding"] == "br"


@pytest.mark.asyncio
async def test_safe_request_passes_identity_unchanged():
    """No Content-Encoding header — the strip should be a no-op and the body
    should round-trip exactly."""
    import httpx

    plain = b"plain body, no encoding"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=[(b"content-type", b"text/plain")],
            content=plain,
        )

    import website.core.safe_http as safe_http_mod

    original_client = safe_http_mod.httpx.AsyncClient

    def _client_with_mock(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    safe_http_mod.httpx.AsyncClient = _client_with_mock
    try:
        response = await safe_request(
            "GET", "https://example.com/plain", validate_initial=False
        )
    finally:
        safe_http_mod.httpx.AsyncClient = original_client

    assert response.content == plain
    assert response.text == plain.decode()


@pytest.mark.asyncio
async def test_safe_request_head_first_falls_back_to_get():
    """resolve_redirects callers issue HEAD first (faster); some servers
    405/403 on HEAD. The wrapper must still produce a usable final URL
    via GET — same behavior as the legacy resolve_redirects path."""
    with respx.mock() as router:
        router.head("https://example.com/page").respond(405)
        router.get("https://example.com/page").respond(200, text="body")
        response = await safe_request(
            "GET", "https://example.com/page", head_first=True
        )
    # Final response is the GET fallback.
    assert response.status_code == 200
    assert response.text == "body"


@pytest.mark.asyncio
async def test_safe_request_scrubs_cookie_on_cross_host_redirect():
    """Pin the cross-host sensitive-header scrub at safe_http.py:111-116.
    3-hop chain: same-host hop preserves Cookie; cross-host hop strips it.
    Untested before PR #115 — the gap that would have shipped a silent
    credential leak if the netloc check ever regressed.
    """
    import httpx

    captured: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({k.lower(): v for k, v in request.headers.items()})
        url = str(request.url)
        if url == "https://a.example.com/start":
            return httpx.Response(
                302, headers={"location": "https://a.example.com/mid"}
            )
        if url == "https://a.example.com/mid":
            return httpx.Response(
                302, headers={"location": "https://b.example.com/end"}
            )
        if url == "https://b.example.com/end":
            return httpx.Response(200, content=b"ok")
        raise AssertionError(f"unexpected url {url}")

    import website.core.safe_http as safe_http_mod

    original_client = safe_http_mod.httpx.AsyncClient

    def _client_with_mock(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    safe_http_mod.httpx.AsyncClient = _client_with_mock
    try:
        response = await safe_request(
            "GET",
            "https://a.example.com/start",
            headers={"Cookie": "session=abc123", "Authorization": "Bearer t", "User-Agent": "ua"},
            validate_initial=False,
        )
    finally:
        safe_http_mod.httpx.AsyncClient = original_client

    assert response.status_code == 200
    assert len(captured) == 3
    # Hop 1: initial request carries the sensitive headers.
    assert captured[0].get("cookie") == "session=abc123"
    assert captured[0].get("authorization") == "Bearer t"
    # Hop 2: same-host 302 → defense doesn't fire, both still present.
    assert captured[1].get("cookie") == "session=abc123"
    assert captured[1].get("authorization") == "Bearer t"
    # Hop 3: cross-host 302 → cookie + authorization scrubbed; non-sensitive preserved.
    assert "cookie" not in captured[2]
    assert "authorization" not in captured[2]
    assert captured[2].get("user-agent") == "ua"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [307, 308, 302, 303])
async def test_safe_request_preserves_method_through_redirect(status):
    """Pin: POST stays POST through ALL 3xx — including 302/303 where
    httpx.follow_redirects=True would rewrite to GET (per RFC 7231 §6.4).
    The wrapper deliberately keeps the caller's method so we never make
    a network call we didn't intend. Security-relevant: an attacker can't
    coerce a credentialed POST to leak as a GET to a different endpoint.
    """
    import httpx

    captured_methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_methods.append(request.method)
        url = str(request.url)
        if url == "https://example.com/post":
            return httpx.Response(
                status, headers={"location": "https://example.com/final"}
            )
        if url == "https://example.com/final":
            return httpx.Response(200, content=b"ok")
        raise AssertionError(f"unexpected url {url}")

    import website.core.safe_http as safe_http_mod

    original_client = safe_http_mod.httpx.AsyncClient

    def _client_with_mock(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    safe_http_mod.httpx.AsyncClient = _client_with_mock
    try:
        response = await safe_request(
            "POST", "https://example.com/post", validate_initial=False,
        )
    finally:
        safe_http_mod.httpx.AsyncClient = original_client

    assert response.status_code == 200
    assert captured_methods == ["POST", "POST"]
