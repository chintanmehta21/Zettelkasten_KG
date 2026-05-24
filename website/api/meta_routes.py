"""GET /api/meta/* — metadata endpoints (source registry, etc.).

Phase 4 Task 4.1 — first endpoint is /api/meta/source-types, served from
``website.core.source_registry``. Frontend pulls this at boot so adding a
new source type is a one-file change (the Python registry).
"""
from __future__ import annotations

from fastapi import APIRouter, Response

from website.core.source_registry import to_wire_dict


router = APIRouter(prefix="/api/meta")


@router.get("/source-types")
async def source_types(response: Response) -> dict:
    """Return the source-type registry as JSON.

    Cached for one year (immutable per deploy SHA — frontend busts on app
    update via the static asset cache-busters, so the cached JSON does NOT
    persist across deploys).
    """
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return to_wire_dict()
