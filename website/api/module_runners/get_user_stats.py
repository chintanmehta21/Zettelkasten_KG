"""Runner for the User Stats endpoint.

Wraps stats fetch + quota / plan composition behind a module-level
semaphore + same-worker singleflight gate. Matches the shape of the
``create_kasten.py`` / ``ask_kasten.py`` siblings (per the user's
structural directive: API facade lives in module_runners, NOT directly
in features/user_stats/).

Returns ``StatsResponse(...).model_dump(mode="json")``. The HTTP route
(``website/api/profile_routes.py``) is a thin adapter over this runner.

Plan tier is passed in by the caller (route resolves from billing). Caps
come from ``website.features.functional_gates.config.PLAN_CAPS[plan]``.
The composed payload is what users see; the underlying RPC stays
PURE-OLTP (no billing reads in the SECURITY DEFINER body).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from website.core.request_context import operation_context

logger = logging.getLogger("website.api.module_runners.get_user_stats")

# Match the upstream runners' concurrency bound. Inside the route layer
# the StatsSemaphore (1 in-flight, 2 queued, 503 backpressure) is the
# user-facing gate; this is the per-process compute limit.
_RUN_GET_USER_STATS_SEMAPHORE = asyncio.Semaphore(2)

# Same-worker singleflight (matches create_kasten.py D4 idiom):
# coalesce concurrent same-key requests on ONE worker into one Future
# hand-off. Cross-worker dedup is the cache layer's job.
_IN_FLIGHT: dict[tuple[str, str], tuple[str, asyncio.Task]] = {}

_FEATURES = ("zettel", "kasten", "rag_question")
_QUOTA_FEATURES_FOR_MAIN_BOARD = ("zettel", "kasten")


# ───────────────────────────────────────────────────────────────────────────
# Lazy facades
# ───────────────────────────────────────────────────────────────────────────


def _StatsResponse(*args: Any, **kwargs: Any) -> Any:  # noqa: N802 — factory facade
    from website.features.user_stats.models import StatsResponse as _impl
    return _impl(*args, **kwargs)


async def _fetch_raw_stats(*args: Any, **kwargs: Any) -> Any:
    from website.features.user_stats.repository import fetch_raw_stats as _impl
    return await _impl(*args, **kwargs)


def _plan_caps_for(plan_tier: str) -> dict[str, Any]:
    """Return ``PLAN_CAPS[plan_tier]`` or {} if absent."""
    try:
        from website.features.functional_gates.config import PLAN_CAPS  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning("PLAN_CAPS import failed: %s", exc)
        return {}
    return dict(PLAN_CAPS.get(plan_tier, {}) or {})


def _request_hash(*, workspace_id: str, profile_id: str, plan_tier: str) -> str:
    fingerprint = {"workspace_id": workspace_id, "profile_id": profile_id, "plan_tier": plan_tier}
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ───────────────────────────────────────────────────────────────────────────
# Quota / plan composition
# ───────────────────────────────────────────────────────────────────────────


def _build_features_payload(
    *, plan_tier: str, caps_for_plan: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build the p_features jsonb input for pricing_get_quota_snapshot_batch."""
    payload: list[dict[str, Any]] = []
    for feature in _FEATURES:
        feature_caps = caps_for_plan.get(feature) or {}
        payload.append({
            "feature": feature,
            "caps": feature_caps,
            "wallet_meter": None,  # v1: no wallet; routes pass None
        })
    return payload


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        return int(value or default)
    return default


def _select_snapshot_period(entry: dict[str, Any]) -> str:
    caps = entry.get("caps")
    used = entry.get("used")
    if not isinstance(caps, dict) or not isinstance(used, dict):
        return str(entry.get("period") or "month")

    remaining_by_period: list[tuple[int, str]] = []
    for period in ("day", "week", "month", "lifetime"):
        cap = caps.get(period)
        if cap is None:
            continue
        remaining_by_period.append((max(0, _as_int(cap) - _as_int(used.get(period))), period))
    if not remaining_by_period:
        return "month"
    return min(remaining_by_period)[1]


def _snapshot_used(entry: dict[str, Any], period: str) -> int:
    used = entry.get("used", 0)
    if isinstance(used, dict):
        return _as_int(used.get(period))
    return _as_int(used)


def _snapshot_available(entry: dict[str, Any]) -> int | None:
    if entry.get("available") is not None:
        return _as_int(entry["available"])
    if entry.get("effective_available") is not None:
        return _as_int(entry["effective_available"])
    return None


def _snapshots_to_quota_dict(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map billing quota snapshots to the compact UI quota contract."""
    out: dict[str, dict[str, Any]] = {}
    for entry in snapshots or []:
        feature = entry.get("feature")
        if not feature:
            continue
        period = _select_snapshot_period(entry)
        out[feature] = {
            "used": _snapshot_used(entry, period),
            "available": _snapshot_available(entry),
            "period": period,
        }
    return out


async def _fetch_quota_snapshots(
    *,
    supabase_client: Any,
    profile_id: str,
    features_payload: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Call billing.pricing_get_quota_snapshot_batch via the supabase client.

    Fail-open on infra error — return [] so the route can serve raw stats
    without quotas rather than 500 the user.
    """
    try:
        res = supabase_client.schema("billing").rpc(
            "pricing_get_quota_snapshot_batch",
            {
                "p_profile_id": profile_id,
                "p_features": features_payload,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("pricing_get_quota_snapshot_batch failed: %s", exc)
        return []
    data = res.data
    if not data:
        return []
    return list(data)


def _compose_payload(
    *,
    raw_payload: dict[str, Any],
    plan_tier: str,
    quotas: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge quota / plan onto the raw payload in-place-safely."""
    composed = dict(raw_payload)  # shallow copy
    # main_board: zettels_quota + kastens_quota
    main_board = dict(composed.get("main_board") or {})
    if "zettel" in quotas:
        main_board["zettels_quota"] = quotas["zettel"]
    if "kasten" in quotas:
        main_board["kastens_quota"] = quotas["kasten"]
    composed["main_board"] = main_board
    # general.plan: tier only (period_end deferred — route may add)
    general = dict(composed.get("general") or {})
    general["plan"] = {"tier": plan_tier, "period_end": None}
    composed["general"] = general
    return composed


# ───────────────────────────────────────────────────────────────────────────
# Public coroutine
# ───────────────────────────────────────────────────────────────────────────


async def run_get_user_stats(
    *,
    workspace_id: UUID,
    profile_id: UUID,
    plan_tier: str = "free",
    client_action_id: str = "",
    supabase_client: Any | None = None,
) -> dict[str, Any]:
    """Fetch + compose user stats. See module docstring."""
    if supabase_client is None:
        raise ValueError("supabase_client is required")

    workspace_str = str(workspace_id)
    profile_str = str(profile_id)
    plan_tier = (plan_tier or "free").strip().lower() or "free"
    action_id = client_action_id or f"stats:{workspace_str}"

    cache_key = (profile_str, action_id)
    request_hash = _request_hash(
        workspace_id=workspace_str, profile_id=profile_str, plan_tier=plan_tier
    )

    in_flight = _IN_FLIGHT.get(cache_key)
    if in_flight is not None:
        running_hash, running_task = in_flight
        if running_hash == request_hash:
            return await asyncio.shield(running_task)
        # Different body for same key — fall through to fresh execution.

    async def _execute() -> dict[str, Any]:
        async with _RUN_GET_USER_STATS_SEMAPHORE:
            with operation_context(action_id):
                # Step 1: raw stats (cache-aware in repository).
                response, etag, cache_hit = await _fetch_raw_stats(
                    workspace_str, profile_str, supabase_client=supabase_client
                )

                # Step 2: caps + batched quota snapshot.
                caps_for_plan = _plan_caps_for(plan_tier)
                features_payload = _build_features_payload(
                    plan_tier=plan_tier, caps_for_plan=caps_for_plan
                )
                snapshots = await _fetch_quota_snapshots(
                    supabase_client=supabase_client,
                    profile_id=profile_str,
                    features_payload=features_payload,
                )
                quotas = _snapshots_to_quota_dict(snapshots)

                # Step 3: compose final payload.
                composed = _compose_payload(
                    raw_payload=response.model_dump(mode="json"),
                    plan_tier=plan_tier,
                    quotas=quotas,
                )

                # Step 4: re-validate with StatsResponse (catches any drift).
                final = _StatsResponse(**composed)
                final_dict = final.model_dump(mode="json")
                final_dict["_meta"] = {"etag": etag, "cache_hit": cache_hit}
                return final_dict

    task = asyncio.ensure_future(_execute())
    _IN_FLIGHT[cache_key] = (request_hash, task)
    try:
        return await asyncio.shield(task)
    finally:
        _IN_FLIGHT.pop(cache_key, None)


# ───────────────────────────────────────────────────────────────────────────
# CLI (mirrors summarization.py / ask_kasten.py — debugging / Phase-E seed)
# ───────────────────────────────────────────────────────────────────────────


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip():
            os.environ.setdefault(key.strip(), value)


def _load_local_env() -> None:
    root = Path.cwd()
    for candidate in (root / ".env", root / ".env.v2", root / "supabase" / ".env"):
        _load_env_file(candidate)
    os.environ.setdefault("DB_SCHEMA_VERSION", "v2")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch + compose user stats for the given workspace + profile.",
    )
    parser.add_argument("--workspace-id", required=True, help="Workspace UUID")
    parser.add_argument("--profile-id", required=True, help="Profile (auth user) UUID")
    parser.add_argument("--plan-tier", default="free", choices=["free", "basic", "max"])
    parser.add_argument("--client-action-id", default="cli-get-user-stats")
    parser.add_argument("--load-env", action="store_true", help="Load .env files first")
    return parser.parse_args()


async def _cli() -> int:
    args = _parse_args()
    if args.load_env:
        _load_local_env()
    from website.core.supabase_v2.client import get_v2_client
    result = await run_get_user_stats(
        workspace_id=UUID(args.workspace_id),
        profile_id=UUID(args.profile_id),
        plan_tier=args.plan_tier,
        client_action_id=args.client_action_id,
        supabase_client=get_v2_client(),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_cli()))
