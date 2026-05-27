"""Stats repository -- wraps the SECURITY DEFINER RPCs + in-process LRU cache.

Public API:
    await fetch_raw_stats(workspace_id, profile_id, *, supabase_client=None)
        -> tuple[StatsResponse, str, bool]
        # returns (response, etag, cache_hit_flag)
        # response is PURE-OLTP -- quota / plan fields are None.

ETag derivation:
    sha256("{workspace_id}|{latest_zettel_at}|{latest_chat_at}|{latest_kg_edge_at}|{caps_config_version}")
    (first 16 hex chars)

The caps_config_version sentinel comes from PLAN_CAPS in
website.features.functional_gates.config -- bumping caps invalidates
all client ETags deterministically.

The cache key is (workspace_id, etag). A cache miss runs the full
profile_stats_v1 RPC and stores the result under the new ETag.

This module does NOT compose quota -- that's the runner's job (Task 4.5).
The route's get_user_stats runner reads the (raw, etag, cache_hit) tuple
and adds quota snapshots before serving to the client.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from website.features.user_stats.cache import StatsCache
from website.features.user_stats.models import StatsResponse

log = logging.getLogger(__name__)

# Per-worker LRU. 256 entries x ~10 KB each = ~2.5 MB ceiling. 60s TTL is
# the upper bound -- clients with stale ETag will still get a cache hit
# inside the 60s window but a new ETag (because the probe re-fires) will
# bypass the cache. So 60s is "max staleness without DB change".
_CACHE = StatsCache(max_entries=256, ttl_seconds=60.0)


def _caps_config_version() -> str:
    """Read the PLAN_CAPS config version sentinel.

    Looks for an explicit ``PLAN_CAPS_VERSION`` module attribute in
    ``website.features.functional_gates.config``. If absent, hashes the
    PLAN_CAPS dict itself (deterministic -- sorted keys + repr-stable
    values) so any cap edit busts the ETag automatically.

    Returns a short hex string suitable for inclusion in the ETag input.
    """
    try:
        from website.features.functional_gates import config as caps_config  # type: ignore
    except Exception:
        # Functional gates not loadable -- return a stable fallback so the
        # ETag still produces a stable value (matches "no caps configured").
        return "no-caps"

    explicit_version = getattr(caps_config, "PLAN_CAPS_VERSION", None)
    if explicit_version is not None:
        return str(explicit_version)

    plan_caps = getattr(caps_config, "PLAN_CAPS", None)
    if plan_caps is None:
        return "no-caps"
    try:
        # Stable hash: repr(sorted dict) is deterministic on Python 3.7+.
        canonical = repr(sorted(plan_caps.items()))
    except Exception:
        canonical = repr(plan_caps)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def _compute_etag(
    *,
    workspace_id: str,
    latest_zettel_at: str | None,
    latest_chat_at: str | None,
    latest_kg_edge_at: str | None,
    caps_version: str,
) -> str:
    """Stable 16-hex-char ETag for (workspace, upstream-state, caps-state)."""
    parts = [
        workspace_id,
        latest_zettel_at or "",
        latest_chat_at or "",
        latest_kg_edge_at or "",
        caps_version,
    ]
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


async def _probe_etag(supabase_client: Any, workspace_id: str) -> tuple[str, dict]:
    """Call core.profile_stats_etag_probe_v1 -> (etag, probe_dict)."""
    probe = supabase_client.schema("core").rpc(
        "profile_stats_etag_probe_v1",
        {"p_workspace_id": workspace_id},
    ).execute()
    probe_data = probe.data or {}
    etag = _compute_etag(
        workspace_id=workspace_id,
        latest_zettel_at=str(probe_data.get("latest_zettel_at") or ""),
        latest_chat_at=str(probe_data.get("latest_chat_at") or ""),
        latest_kg_edge_at=str(probe_data.get("latest_kg_edge_at") or ""),
        caps_version=_caps_config_version(),
    )
    return etag, probe_data


async def _fetch_full_payload(supabase_client: Any, workspace_id: str) -> dict:
    """Call core.profile_stats_v1 -> raw payload dict."""
    res = supabase_client.schema("core").rpc(
        "profile_stats_v1",
        {"p_workspace_id": workspace_id},
    ).execute()
    payload = res.data
    if payload is None:
        raise RuntimeError("profile_stats_v1 returned no payload")
    return payload


async def fetch_raw_stats(
    workspace_id: str,
    profile_id: str,  # accepted for future use; not consumed by raw fetch
    *,
    supabase_client: Any,
) -> tuple[StatsResponse, str, bool]:
    """Fetch raw PURE-OLTP stats with ETag short-circuit.

    Returns (StatsResponse with quota/plan = None, etag, cache_hit_flag).

    The route layer composes quota / plan on top of the returned response
    before serving to the client.
    """
    if supabase_client is None:
        raise ValueError("supabase_client is required (use authenticated user client)")

    etag, _probe = await _probe_etag(supabase_client, workspace_id)

    cached = await _CACHE.get(workspace_id, etag)
    if cached is not None:
        return StatsResponse.model_validate(cached), etag, True

    payload = await _fetch_full_payload(supabase_client, workspace_id)
    parsed = StatsResponse.model_validate(payload)
    await _CACHE.set(workspace_id, etag, payload)
    return parsed, etag, False


async def _reset_cache_for_tests() -> None:
    """Test helper -- drop all cache entries to prevent cross-test contamination."""
    await _CACHE.clear()
