"""Tests for the shared upload rate limiter.

The limiter caps batch-upload calls per (user, ip) sliding-window so a
single attacker can't flood the 2 GB droplet with 10 MB upload bodies.
Limit is configurable per route; default is sized for batches (5/min).
"""

from __future__ import annotations

from website.features.functional_gates.upload_rate_limit import (
    UploadRateLimiter,
)


def test_upload_rate_limiter_allows_under_cap():
    limiter = UploadRateLimiter(limit=3, window_seconds=60)
    assert limiter.allow("user-1", "1.2.3.4") is True
    assert limiter.allow("user-1", "1.2.3.4") is True
    assert limiter.allow("user-1", "1.2.3.4") is True


def test_upload_rate_limiter_rejects_at_cap():
    limiter = UploadRateLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        assert limiter.allow("user-1", "1.2.3.4") is True
    assert limiter.allow("user-1", "1.2.3.4") is False


def test_upload_rate_limiter_isolates_per_user():
    """Two distinct users with same IP must not share quota — burst from
    one tenant must not block another. Necessary for the canonical-Zoro
    + authenticated-users coexistence model on a shared droplet."""
    limiter = UploadRateLimiter(limit=2, window_seconds=60)
    for _ in range(2):
        assert limiter.allow("user-a", "1.2.3.4") is True
    # User-a is now at cap; user-b on same IP must still pass.
    assert limiter.allow("user-b", "1.2.3.4") is True


def test_upload_rate_limiter_isolates_per_ip():
    """Two distinct IPs for same user (e.g. multi-device) get isolated
    sliding windows. Cap is per (user, ip) — multi-device users aren't
    artificially throttled."""
    limiter = UploadRateLimiter(limit=2, window_seconds=60)
    for _ in range(2):
        assert limiter.allow("user-1", "1.1.1.1") is True
    assert limiter.allow("user-1", "2.2.2.2") is True


def test_upload_rate_limiter_window_decays(monkeypatch):
    """Calls older than the window must drop out so legitimate users
    aren't permanently throttled."""
    import website.features.functional_gates.upload_rate_limit as mod

    current = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: current[0])

    limiter = UploadRateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("user-1", "1.1.1.1") is True
    assert limiter.allow("user-1", "1.1.1.1") is True
    assert limiter.allow("user-1", "1.1.1.1") is False

    # Advance the clock past the window — the old hits drop out.
    current[0] += 61.0
    assert limiter.allow("user-1", "1.1.1.1") is True
