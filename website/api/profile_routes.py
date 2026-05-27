"""HTTP route for the User Stats Statistics tab.

Thin adapter over website.api.module_runners.get_user_stats.run_get_user_stats.
Adds the user-facing gates: kill-switch, staged-rollout allowlist, per-user
rate limit, per-worker bounded queue, and ETag / 304 short-circuit.

Plan / billing composition is delegated to the runner. This file owns ONLY
the HTTP-level concerns + the integration-test seams.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from website.api.auth import get_current_user
from website.core.settings import get_settings
from website.features.functional_gates.upload_rate_limit import UploadRateLimiter
from website.features.user_stats.semaphore import (
    SemaphoreFullError,
    StatsSemaphore,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile-stats"])

# Per-worker rate limit: 1 request per 2 seconds per profile_id.
# Consultant adoption #3 — explicit per-user gate to prevent refresh storms
# from a single user starving the global semaphore.
_STATS_RATE_LIMITER = UploadRateLimiter(limit=1, window_seconds=2)

# Per-worker bounded queue (max 1 in-flight + 2 queued) — 503 backpressure.
# Architecture audit §4: 2 GB / 1 vCPU droplet constraint.
_STATS_SEMAPHORE = StatsSemaphore(max_concurrent=1, max_queued=2)


def _resolve_workspace_id(user_sub: str) -> UUID:
    """Resolve the caller's default workspace via Supabase v2 scope helper."""
    from website.core.persist import get_supabase_v2_scope

    scope = get_supabase_v2_scope(user_sub)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No accessible workspace for this user",
        )
    _content_repo, _profile_id, workspace_id = scope
    return UUID(str(workspace_id))


def _is_allowlisted(profile_sub: str, allowlist_csv: str) -> bool:
    """Empty allowlist = open. Else profile_sub must be in the CSV (whitespace-trimmed)."""
    raw = (allowlist_csv or "").strip()
    if not raw:
        return True
    members = {part.strip() for part in raw.split(",") if part.strip()}
    return profile_sub in members


@router.get("/stats")
async def get_profile_stats(
    request: Request,
    response: Response,
    user: Annotated[dict, Depends(get_current_user)],
) -> Any:
    """GET /api/profile/stats — Statistics tab payload.

    Returns the StatsResponse model_dump() JSON (with composed quotas + plan).
    Headers: ETag + Cache-Control + x-stats-cache (hit|miss).
    """
    settings = get_settings()

    # Gate 1 — kill switch
    if not settings.stats_tab_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stats endpoint disabled",
        )

    # Gate 2 — staged-rollout allowlist
    profile_sub = str(user.get("sub", "")).strip()
    if not profile_sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing subject claim",
        )
    if not _is_allowlisted(profile_sub, settings.stats_tab_allowlist):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stats endpoint not enabled for this user",
        )

    # Gate 3 — per-user rate limit
    client_ip = (request.client.host if request.client else "") or ""
    if not _STATS_RATE_LIMITER.allow(profile_sub, client_ip):
        # HTTPException(headers=...) is the only way to attach a Retry-After
        # header to a 429 response — setting it on the injected ``response``
        # is dropped when FastAPI builds its JSONResponse from the exception.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded - retry in 2s",
            headers={"Retry-After": "2"},
        )

    # Gate 4 — per-worker semaphore
    try:
        async with _STATS_SEMAPHORE.acquire():
            return await _serve_stats(request, response, user, profile_sub)
    except SemaphoreFullError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stats endpoint busy - retry in 5s",
            headers={"Retry-After": "5"},
        )


async def _serve_stats(
    request: Request,
    response: Response,
    user: dict,
    profile_sub: str,
) -> Any:
    """Inside semaphore: resolve workspace, dispatch runner, handle ETag."""
    # Resolve workspace_id from auth context (BOLA-safe: server-derived only).
    workspace_id = _resolve_workspace_id(profile_sub)
    profile_id = UUID(profile_sub)

    # TODO(v1.5): replace this default with real plan-tier lookup against
    # billing.pricing_subscriptions or the equivalent functional_gates helper.
    # For v1 the route assumes "free" — caps still come from PLAN_CAPS so
    # quota math is correct; only the tier label shown to users is the gap.
    plan_tier = "free"

    # Authenticated supabase client honoring the caller's JWT (BOLA-safe).
    from website.core.supabase_v2.client import get_v2_user_client
    # The user dict from get_current_user typically holds the bearer token
    # at one of: user["token"], request.headers["Authorization"] (Bearer X).
    auth_header = request.headers.get("authorization", "")
    jwt = ""
    if auth_header.lower().startswith("bearer "):
        jwt = auth_header[7:].strip()
    if not jwt:
        # Defensive: get_current_user should have raised already; keep a
        # narrow guard so a future regression doesn't fall through silently.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    supabase_client = get_v2_user_client(jwt)

    # Dispatch to runner.
    from website.api.module_runners.get_user_stats import run_get_user_stats

    result = await run_get_user_stats(
        workspace_id=workspace_id,
        profile_id=profile_id,
        plan_tier=plan_tier,
        client_action_id=request.headers.get("x-client-action-id", "") or "",
        supabase_client=supabase_client,
    )

    # Pop the runner's _meta out of the response body — it's HTTP metadata.
    meta = result.pop("_meta", {}) if isinstance(result, dict) else {}
    etag = str(meta.get("etag") or "")
    cache_hit = bool(meta.get("cache_hit", False))

    # 304 short-circuit on If-None-Match. Headers must be set on the returned
    # Response — when an endpoint returns a custom Response, FastAPI uses it
    # directly and drops any headers set on the injected ``response`` param.
    if_none_match = (request.headers.get("if-none-match") or "").strip()
    if etag and if_none_match == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                "Cache-Control": "private, max-age=60",
            },
        )

    if etag:
        response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["x-stats-cache"] = "hit" if cache_hit else "miss"
    return result
