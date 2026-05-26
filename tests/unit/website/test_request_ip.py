"""Real-client-IP extractor tests.

The app runs behind a Caddy container that terminates TLS and proxies to
``127.0.0.1:10000`` (or :10001 on green). ``request.client.host`` is therefore
the Caddy bridge IP, identical across all clients. Rate limiters keyed on
that IP collapse all anonymous traffic into one bucket — a single attacker
denies service for everyone.

This helper reads the real IP in the same order as
``website/app.py:565-568``: Cloudflare's ``cf-connecting-ip`` first
(authoritative when CF is in front), then the first hop of
``x-forwarded-for``, then ``request.client.host`` as the last-resort.
"""

from __future__ import annotations

from types import SimpleNamespace

from website.core.request_ip import real_client_ip


def _request(headers: dict[str, str], peer: str | None = "1.2.3.4"):
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=peer) if peer is not None else None,
    )


def test_real_client_ip_prefers_cf_connecting_ip():
    req = _request({"cf-connecting-ip": "203.0.113.1", "x-forwarded-for": "10.0.0.1"})
    assert real_client_ip(req) == "203.0.113.1"


def test_real_client_ip_falls_back_to_xff_first_hop():
    """X-Forwarded-For carries the chain. The leftmost is the client; the
    rest are intermediate proxies. Use [0]."""
    req = _request({"x-forwarded-for": "203.0.113.5, 10.0.0.1, 10.0.0.2"})
    assert real_client_ip(req) == "203.0.113.5"


def test_real_client_ip_falls_back_to_peer():
    req = _request({}, peer="10.0.0.99")
    assert real_client_ip(req) == "10.0.0.99"


def test_real_client_ip_returns_unknown_when_nothing_available():
    req = _request({}, peer=None)
    assert real_client_ip(req) == "unknown"


def test_real_client_ip_strips_xff_whitespace():
    req = _request({"x-forwarded-for": "   203.0.113.10   , 10.0.0.1"})
    assert real_client_ip(req) == "203.0.113.10"
