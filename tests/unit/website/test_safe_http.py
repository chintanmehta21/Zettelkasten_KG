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
