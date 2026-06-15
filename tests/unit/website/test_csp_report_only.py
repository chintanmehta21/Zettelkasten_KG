"""Pin CSP report-only header + /api/csp-report violation receiver.

CSP report-only mode observes browser violations without breaking pages
(research synthesis 2026-05-26 R3 — "strict CSP is the real XSS defense").
This test file pins:

  - The Caddyfile carries ``Content-Security-Policy-Report-Only`` with the
    minimum directive set needed for our auth + payment flows.
  - The ``report-uri`` points at our backend collector.
  - The collector at ``POST /api/csp-report`` accepts legacy + modern report
    formats, rate-limits per IP, and never 5xx on malformed input.

Once the violation log is quiet for a week and known issues (inline scripts,
KG DOM sinks, summary HTML insertion) are resolved, the Caddyfile flips from
``-Report-Only`` to enforcing ``Content-Security-Policy``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


CADDYFILE = (
    Path(__file__).resolve().parents[3]
    / "ops"
    / "caddy"
    / "Caddyfile"
)


# ────────────────────────────────────────────────────────────────────────────
# Caddyfile header pinning
# ────────────────────────────────────────────────────────────────────────────

def test_caddyfile_has_csp_report_only_header():
    """Caddyfile must declare Content-Security-Policy-Report-Only globally."""
    src = CADDYFILE.read_text(encoding="utf-8")
    assert "Content-Security-Policy-Report-Only" in src, (
        "ops/caddy/Caddyfile must set Content-Security-Policy-Report-Only so "
        "browser violations are observed before enforcing CSP. See research "
        "synthesis 2026-05-26 R3."
    )


def test_csp_includes_critical_directives():
    """CSP must include the directives required for our known surfaces."""
    src = CADDYFILE.read_text(encoding="utf-8")
    # Extract the CSP value — single quoted directives on one line.
    required = [
        "default-src 'self'",                       # baseline lock-down
        "https://cdn.jsdelivr.net",                # supabase-js + KG vendor scripts
        "'self' 'unsafe-inline' https://fonts.googleapis.com",  # style-src (Google Fonts)
        "https://fonts.gstatic.com",               # font-src
        "https://*.supabase.co",                   # connect-src (Auth, REST)
        "https://accounts.google.com",             # OAuth redirect
        "frame-ancestors 'none'",                  # X-Frame-Options parity
        "object-src 'none'",                       # block Flash/applets
        "base-uri 'self'",                         # block <base> injection
        "report-uri /api/csp-report",              # collector wired up (legacy browsers)
        "report-to csp-endpoint",                  # modern Reporting-API collector
        "https://static.cloudflareinsights.com",   # Cloudflare auto-injected analytics
    ]
    for directive in required:
        assert directive in src, (
            f"Caddyfile CSP must include '{directive}' — required for one of "
            "our existing flows (auth / fonts / Supabase / OAuth / payments)."
        )


def test_caddyfile_has_reporting_endpoints_header():
    """Modern Reporting API header must pair with `report-to` directive."""
    src = CADDYFILE.read_text(encoding="utf-8")
    assert "Reporting-Endpoints" in src and "csp-endpoint" in src, (
        "Caddyfile must set 'Reporting-Endpoints: csp-endpoint=\"/api/csp-report\"' "
        "so modern Chrome (96+) routes CSP reports via the Reporting API. "
        "Without it, Chrome ignores `report-uri` when `report-to` is present."
    )


def test_csp_does_not_enforce_yet():
    """Verify we ship REPORT-ONLY first, NOT enforcing — flipping to enforce
    is a separate operator decision after the log is quiet."""
    src = CADDYFILE.read_text(encoding="utf-8")
    # Make sure the enforcing variant is not present alongside.
    # The substring 'Content-Security-Policy ' (with trailing space) would
    # indicate the enforcing header was added in addition to report-only.
    lines_with_csp_directive = [
        line for line in src.split("\n")
        if "Content-Security-Policy" in line
    ]
    enforcing = [
        line for line in lines_with_csp_directive
        if "-Report-Only" not in line and "comment" not in line.lower()
    ]
    # Allow comment lines (lines starting with # after indent) that mention CSP.
    enforcing = [line for line in enforcing if not line.strip().startswith("#")]
    assert not enforcing, (
        f"Found enforcing Content-Security-Policy header(s) — this PR ships "
        f"report-only ONLY. Lines: {enforcing}"
    )


# ────────────────────────────────────────────────────────────────────────────
# /api/csp-report endpoint
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_csp_rate_limit():
    """Reset the per-IP CSP report rate limiter between tests."""
    from website.api.routes import _rate_store
    keys = [k for k in _rate_store if k.startswith("csp_report:")]
    for k in keys:
        _rate_store.pop(k, None)
    yield
    keys2 = [k for k in _rate_store if k.startswith("csp_report:")]
    for k in keys2:
        _rate_store.pop(k, None)


def _client() -> TestClient:
    from website.app import create_app
    return TestClient(create_app())


def test_csp_report_accepts_legacy_format_returns_204():
    """Legacy {csp-report: {...}} body → 204, body logged."""
    body = {
        "csp-report": {
            "document-uri": "https://zettelkasten.in/home",
            "violated-directive": "script-src-elem",
            "blocked-uri": "https://malicious.example/script.js",
            "source-file": "https://zettelkasten.in/home",
            "line-number": 42,
        }
    }
    resp = _client().post(
        "/api/csp-report",
        content=json.dumps(body),
        headers={"Content-Type": "application/csp-report"},
    )
    assert resp.status_code == 204


def test_csp_report_accepts_modern_array_format_returns_204():
    """Modern Reporting API array → 204."""
    body = [
        {
            "type": "csp-violation",
            "body": {
                "documentURL": "https://zettelkasten.in/m/",
                "effectiveDirective": "img-src",
                "blockedURL": "data:image/png;base64,aaaa",
                "lineNumber": 17,
            },
        }
    ]
    resp = _client().post(
        "/api/csp-report",
        content=json.dumps(body),
        headers={"Content-Type": "application/reports+json"},
    )
    assert resp.status_code == 204


def test_csp_report_ignores_malformed_json_returns_204():
    """Malformed body must never 5xx — return 204 silently."""
    resp = _client().post(
        "/api/csp-report",
        content=b"not-json-at-all{{",
        headers={"Content-Type": "application/csp-report"},
    )
    assert resp.status_code == 204


def test_csp_report_ignores_empty_body_returns_204():
    """Empty POST body → 204 silently."""
    resp = _client().post("/api/csp-report")
    assert resp.status_code == 204


def test_csp_report_rate_limit_silently_drops_excess():
    """Per-IP burst → first N succeed (204), excess silently dropped (still 204).
    Never returns 429 because the browser can't act on it."""
    from website.api.routes import _CSP_REPORT_RATE_LIMIT_MAX

    client = _client()
    body = {"csp-report": {"violated-directive": "script-src", "blocked-uri": "x"}}
    # Burn the budget + one over
    for _ in range(_CSP_REPORT_RATE_LIMIT_MAX + 5):
        resp = client.post(
            "/api/csp-report",
            content=json.dumps(body),
            headers={"Content-Type": "application/csp-report"},
        )
        # MUST always be 204 — browsers can't retry, and we don't want CSP
        # reports themselves to become a DDoS amplifier.
        assert resp.status_code == 204


def test_csp_report_caps_body_size():
    """Huge bodies must be truncated — not OOM the parser."""
    from website.api.routes import _CSP_REPORT_MAX_BYTES

    # 100 KB body — well over the 8 KB cap
    huge = json.dumps({"csp-report": {"blocked-uri": "x" * (_CSP_REPORT_MAX_BYTES * 12)}})
    assert len(huge.encode()) > _CSP_REPORT_MAX_BYTES
    resp = _client().post(
        "/api/csp-report",
        content=huge,
        headers={"Content-Type": "application/csp-report"},
    )
    # Will likely 204 because the truncated bytes won't parse as JSON.
    # The critical assertion: NO 5xx.
    assert resp.status_code == 204


def test_csp_report_204_responses_carry_empty_body():
    """Every 204 path must return an EMPTY body — a 204 with content is the prod bug.

    Root cause of the ``website.app:Unhandled exception on /api/csp-report``
    spam: the handler returned ``JSONResponse(content=None, status_code=204)``,
    which serialises ``None`` to a 4-byte ``b"null"`` body. RFC 9110 §6.4.1
    forbids a body on 204, and the real ASGI server enforces it — h11 raises
    ``LocalProtocolError: Too much data for declared Content-Length`` (httptools:
    ``RuntimeError: Response content longer than Content-Length``) when the body
    is pumped, surfacing as the unhandled-exception log plus an asyncio
    ``protocol.data_received() call failed`` from the corrupted keep-alive
    connection. TestClient's httpx transport does NOT enforce 204-no-body, so
    the status-only assertions above stay green while prod throws — this pins
    the empty body across all three return paths (normal / malformed / drop).
    """
    from website.api.routes import _CSP_REPORT_RATE_LIMIT_MAX

    client = _client()
    legacy = {"csp-report": {"violated-directive": "script-src", "blocked-uri": "x"}}

    # Path 1 — normal report accepted + logged.
    r_ok = client.post(
        "/api/csp-report",
        content=json.dumps(legacy),
        headers={"Content-Type": "application/csp-report"},
    )
    assert r_ok.status_code == 204
    assert r_ok.content == b"", f"204 (normal) must have empty body, got {r_ok.content!r}"

    # Path 2 — malformed JSON early-return.
    r_bad = client.post(
        "/api/csp-report",
        content=b"not-json-at-all{{",
        headers={"Content-Type": "application/csp-report"},
    )
    assert r_bad.status_code == 204
    assert r_bad.content == b"", f"204 (malformed) must have empty body, got {r_bad.content!r}"

    # Path 3 — per-IP rate-limit silent drop.
    last = r_ok
    for _ in range(_CSP_REPORT_RATE_LIMIT_MAX + 5):
        last = client.post(
            "/api/csp-report",
            content=json.dumps(legacy),
            headers={"Content-Type": "application/csp-report"},
        )
    assert last.status_code == 204
    assert last.content == b"", f"204 (rate-limited drop) must have empty body, got {last.content!r}"
