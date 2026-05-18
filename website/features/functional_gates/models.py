"""Typed models for functional_gates results."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

GateSource = Literal["plan", "wallet", "none"]
DedupBranch = Literal["fresh", "same_user_noop", "cross_user_hit"]


@dataclass(frozen=True)
class GateDecision:
    """Outcome of a reserve-and-consume call.

    ``allowed`` is the only field gates strictly need; the rest are surfaced
    so the API/UI can show "X left on plan, Y in wallet" without an extra
    snapshot RPC. ``idempotent`` is True when the call hit the action_id
    ledger; the original outcome's source is preserved.
    """
    allowed: bool
    source: GateSource
    reason: str
    remaining_plan: int = 0
    remaining_wallet: int = 0
    idempotent: bool = False
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class QuotaSnapshot:
    """Read-only snapshot for UI display. Never mutates state."""
    feature: str
    caps: dict[str, int | None]
    used: dict[str, int]
    remaining_plan: int
    remaining_wallet: int
    effective_available: int


@dataclass(frozen=True)
class DedupDecision:
    """URL-dedup gate outcome. ``found`` is the existing canonical lookup
    (None on fresh). The gate decides the branch only — entitlement + engine
    are the caller's responsibility per branch (keeps this module FastAPI-free
    and side-effect-free, matching the FunctionalGates principle)."""
    branch: DedupBranch
    found: object | None = None


class GateError(Exception):
    """Raised when a gate denies an action. Carries the 402 detail payload."""

    def __init__(
        self,
        *,
        feature: str,
        decision: GateDecision,
        action_id: str | None = None,
    ) -> None:
        self.feature = feature
        self.decision = decision
        self.action_id = action_id
        self.status_code = 402
        super().__init__(
            f"quota_exhausted for feature={feature!r} action_id={action_id!r}"
        )
