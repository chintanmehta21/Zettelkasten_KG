"""Two-tier billing escalation for Gemini key exhaustion."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class BillingTier(str, Enum):
    FREE = "FREE"
    BILLING = "BILLING"
    HALTED = "HALTED"


def escalate_on_429(
    current: BillingTier,
    *,
    free_keys_exhausted: bool = False,
    billing_exhausted: bool = False,
) -> BillingTier:
    if billing_exhausted:
        return BillingTier.HALTED
    if free_keys_exhausted and current == BillingTier.FREE:
        return BillingTier.BILLING
    return current


def write_halt(path: Path, *, reason: str, state: dict | None = None) -> None:
    payload = {
        "reason": reason,
        "halted_at": datetime.now(timezone.utc).isoformat(),
        "state": state or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def is_halted(path: Path) -> bool:
    return path.exists()
