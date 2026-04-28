"""Ops-only diagnostic endpoints. iter-03 mem-bounded §2.8.

Mounted at /api/admin/*. Auth gated against the single-tenant allowlist at
ops/deploy/expected_users.json (the file the Phase 2D `kg_users` allowlist
gate also reads). Non-allowlisted users get 404 to avoid leaking the
existence of admin endpoints.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from website.api._proc_stats import read_proc_stats
from website.api.auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"], include_in_schema=False)

_ALLOWLIST_PATH = (
    Path(__file__).resolve().parents[2] / "ops" / "deploy" / "expected_users.json"
)


def _load_admin_allowlist() -> set[str]:
    try:
        return set(
            json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))["allowed_auth_ids"]
        )
    except Exception:  # noqa: BLE001 — file may be absent in tests/dev
        return set()


def _require_admin(user: dict) -> None:
    allowed = _load_admin_allowlist()
    if not allowed or user.get("sub") not in allowed:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/_proc_stats")
async def proc_stats(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    _require_admin(user)
    return read_proc_stats()
