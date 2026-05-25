"""Per-tier health telemetry surfaced on ``/api/health`` (PR #91).

Each tier in the YouTube transcript chain records its last successful run
and its last failure here. ``/api/health`` exposes a snapshot under the
``yt_tier_health`` key so operators can see chain degradation before users
hit 422s.

Threading model: this is **per-worker, in-process state**. Gunicorn runs
with ``--preload`` + 2 workers, so each child has its own ``_TIER_HEALTH``
dict (forks share the initial dict via copy-on-write, but writes diverge).
That is fine for a debugging probe — operators check ``/api/health`` per
container, and Caddy load-balances across workers so each is sampled.
Cross-worker aggregation belongs to Prometheus (see ``safe_metrics``),
not this lightweight per-tier last-seen tracker.
"""
from __future__ import annotations

import time
from typing import Any


# Per-process tier-health table. Keyed by ``TierSpec.name``.
_TIER_HEALTH: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.time()  # epoch seconds; JSON-safe


def record_success(name: str, latency_ms: int) -> None:
    """Record a successful tier completion.

    Always-on, non-load-bearing. Failures here are silently swallowed
    (the dict is a debugging probe, never the request critical path)."""
    try:
        entry = _TIER_HEALTH.setdefault(name, _new_entry())
        entry["last_success_at"] = _now()
        entry["last_success_latency_ms"] = int(latency_ms)
        entry["success_count"] = entry.get("success_count", 0) + 1
    except Exception:
        # Best-effort telemetry; never fatal.
        pass


def record_failure(name: str, reason: str) -> None:
    """Record a failed tier attempt (timeout, exception, or success=False)."""
    try:
        entry = _TIER_HEALTH.setdefault(name, _new_entry())
        entry["last_error_at"] = _now()
        entry["last_error_reason"] = (reason or "")[:200]
        entry["error_count"] = entry.get("error_count", 0) + 1
    except Exception:
        pass


def snapshot() -> dict[str, Any]:
    """Return a JSON-safe snapshot for ``/api/health``.

    Returns an empty dict if no tier has reported yet (fresh container).
    Each entry has: ``last_success_at`` (epoch s), ``last_success_latency_ms``,
    ``last_error_at`` (epoch s), ``last_error_reason``, ``success_count``,
    ``error_count``.
    """
    # Shallow copy so subsequent writes don't mutate the returned snapshot.
    return {name: dict(entry) for name, entry in _TIER_HEALTH.items()}


def reset() -> None:
    """Test-only: clear the per-process tier-health table."""
    _TIER_HEALTH.clear()


def _new_entry() -> dict[str, Any]:
    return {
        "last_success_at": None,
        "last_success_latency_ms": None,
        "last_error_at": None,
        "last_error_reason": None,
        "success_count": 0,
        "error_count": 0,
    }
