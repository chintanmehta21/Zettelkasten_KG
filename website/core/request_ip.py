"""Real-client-IP extraction for rate-limit / abuse-detection keying.

App container binds ``127.0.0.1:10000`` (or :10001 on green) behind a Caddy
container that terminates TLS. ``request.client.host`` is therefore the
bridge IP, identical for every client — so rate limiters keyed on it
collapse all anonymous traffic into one bucket and a single attacker can
deny service for everyone.

Resolution order matches the existing pattern in ``website/app.py``:
  1. ``cf-connecting-ip`` — Cloudflare's authoritative client IP (set by CF
     on every request that transits its edge). Trusted because Caddy and the
     app are not directly reachable from the public internet (DO Reserved IP
     points at Cloudflare).
  2. First hop of ``x-forwarded-for`` — set by Caddy / Cloudflare. The
     leftmost address is the original client; rightward entries are proxies.
  3. ``request.client.host`` — the TCP peer, last-resort.
  4. ``"unknown"`` — neither headers nor peer available (test scaffolds,
     Server-Sent Events without proxy headers, etc.).
"""

from __future__ import annotations

from typing import Any


def real_client_ip(request: Any) -> str:
    """Return the best-effort real client IP for rate-limit keying.

    ``request`` is duck-typed — only needs ``.headers`` (mapping) and
    ``.client.host`` (or ``.client is None``). Works with FastAPI/Starlette
    ``Request`` and with the lightweight ``SimpleNamespace`` test fixtures.
    """
    headers = getattr(request, "headers", {}) or {}
    cf = (headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    xff = headers.get("x-forwarded-for") or ""
    first = xff.split(",")[0].strip() if xff else ""
    if first:
        return first
    client = getattr(request, "client", None)
    peer = getattr(client, "host", None) if client else None
    return peer or "unknown"
