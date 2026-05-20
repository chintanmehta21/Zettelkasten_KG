"""iter-12 R4: per-Kasten Thompson-sampling bandit for anchor-seed floor.

Status (2026-05-20): retired in Phase 8.5 D. The underlying v1 table
`public.kg_bandit_posteriors` was dropped 2026-05-11 and the v1 RPCs
(`public.rag_bandit_read_arms`, `public.rag_bandit_record_outcome`) were
dropped by `_v2/56_drop_legacy_public_functions.sql` along with their
manifest entries. Until a v2 bandit replacement ships
(docs/db-v2/bandit-v2-roadmap.md), `sample_floor` returns the static fallback
and `record_outcome` is a no-op. The fail-open contract is preserved — callers
in retrieval/hybrid.py see identical behaviour to the pre-deployment
"db_unreachable" path that has been the only live path since 2026-05-11.

Resurrection: rebuild against the v2 bandit RPC surface (rag.bandit_*) and
restore the per-request Thompson sampling logic preserved in git history at
commit 358824b1 and prior.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger("rag.anchor_seed_bandit")

# Static fallback mirrors the existing env var so behaviour matches the pre-
# bandit baseline. This is the value sample_floor returns unconditionally
# while the v2 bandit replacement is unbuilt.
_STATIC_FALLBACK: float = float(os.environ.get("RAG_ANCHOR_SEED_FLOOR_RRF", "0.30"))

# Kept for module-level API compatibility (tests + callers reference these).
_BANDIT_ENABLED: bool = False
_ARMS: list[float] = [
    float(a)
    for a in os.environ.get("RAG_ANCHOR_BANDIT_ARMS", "0.25,0.30,0.35,0.40").split(",")
]


def bucket_pool_size(n: int) -> str:
    """Map candidate pool size to stratification bucket: S, M, or L.

    Helper retained because it has no dependency on the dropped RPCs and is
    still useful downstream telemetry once the v2 bandit lands.
    """
    if n < 30:
        return "S"
    if n < 80:
        return "M"
    return "L"


async def sample_floor(
    *,
    p_user_id: str,
    kasten_id: str,
    pool_size: int,
    supabase: Any,
) -> tuple[float, dict]:
    """Return (_STATIC_FALLBACK, telemetry) — RPC path retired Phase 8.5 D.

    Preserves the signature and the fail-open semantics callers in
    retrieval/hybrid.py depend on. No DB round-trip, no log spam.
    """
    bucket = bucket_pool_size(pool_size)
    telemetry: dict = {
        "p_user_id": p_user_id,
        "kasten_id": kasten_id,
        "pool_bucket": bucket,
        "pool_size": pool_size,
        "fallback_reason": "bandit_retired_phase8d",
        "arm_sampled": None,
        "alpha_at_sample": None,
        "beta_at_sample": None,
        "theta_drawn": None,
        "posterior_entropy_nats": None,
    }
    return _STATIC_FALLBACK, telemetry


async def record_outcome(
    *,
    p_user_id: str,
    kasten_id: str,
    arm: float,
    pool_bucket: str,
    seed_survived: bool,
    supabase: Any,
) -> None:
    """No-op — RPC path retired Phase 8.5 D.

    Preserves the signature so retrieval/hybrid.py can keep calling it without
    branches. When the v2 bandit RPC surface lands, restore the UPSERT body.
    """
    return None
