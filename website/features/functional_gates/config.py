"""Functional gates configuration — single source of truth for quota policy.

Operator-editable. No database migration required to change a cap; edit the
constants below, redeploy, and the gate picks up the new values on the next
request. The SQL RPC ``billing.pricing_reserve_and_consume`` is intentionally
generic: it accepts caps as ``jsonb`` from Python and never reads policy from
the database. This file is the only place plan/cap semantics live.

Source of truth: docs/research/pricing1.md.

Granularities: ``day`` (UTC YYYY-MM-DD), ``week`` (ISO YYYY-Www),
``month`` (YYYY-MM), ``lifetime`` (sentinel ``*``). ``None`` at a granularity
means "no cap at that period" — the gate ignores it when computing
``min(remaining_*)``. If a (plan, feature) has every granularity set to
``None``, the plan grants nothing for that feature (wallet-only).
"""
from __future__ import annotations

from typing import Final, Mapping

PlanCapMap = Mapping[str, Mapping[str, int | None]]

# ─────────────────────────── Plan caps ───────────────────────────
# pricing1.md (verbatim):
#   Free   Z: 2/day, 10/week, 30/month     K: 1 lifetime               Q: 30/month
#   Basic  Z: 5/day, 30/week, 50/month     K: 5 lifetime               Q: 100/month
#   Max    Z: 30/day, 100/week, 200/month  K: 5/week, 50 lifetime      Q: 500/month
PLAN_CAPS: Final[Mapping[str, PlanCapMap]] = {
    "free": {
        "zettel":       {"day": 2,    "week": 10,   "month": 30,  "lifetime": None},
        "kasten":       {"day": None, "week": None, "month": None, "lifetime": 1},
        "rag_question": {"day": None, "week": None, "month": 30,  "lifetime": None},
    },
    "basic": {
        "zettel":       {"day": 5,    "week": 30,   "month": 50,  "lifetime": None},
        "kasten":       {"day": None, "week": None, "month": None, "lifetime": 5},
        "rag_question": {"day": None, "week": None, "month": 100, "lifetime": None},
    },
    "max": {
        "zettel":       {"day": 30,   "week": 100,  "month": 200, "lifetime": None},
        "kasten":       {"day": None, "week": 5,    "month": None, "lifetime": 50},
        "rag_question": {"day": None, "week": None, "month": 500, "lifetime": None},
    },
}

# Pack-credit wallet meter on billing.pricing_balances per feature.
# Aligned with existing webhook fulfillment path in user_pricing/routes.py
# (_apply_fulfillment -> add_pack_credits(meter=product["meter"])) and the
# catalog mapping in user_pricing/catalog.py:105. Editing these strings here
# WITHOUT updating the catalog/webhook would orphan pack purchases — keep in
# sync if the pricing module ever renames its meters.
WALLET_METER: Final[Mapping[str, str]] = {
    "zettel":       "zettel",
    "kasten":       "kasten",
    "rag_question": "rag_question",
}

FEATURES: Final[tuple[str, ...]] = ("zettel", "kasten", "rag_question")
GRANULARITIES: Final[tuple[str, ...]] = ("day", "week", "month", "lifetime")
DEFAULT_PLAN: Final[str] = "free"
KNOWN_PLANS: Final[frozenset[str]] = frozenset(PLAN_CAPS.keys())


def caps_for(plan: str, feature: str) -> dict[str, int | None]:
    """Return {granularity: limit | None} for (plan, feature).

    Unknown plan -> default plan caps. Unknown feature -> empty dict (which
    the gate treats as "no plan quota → wallet-only").
    """
    plan_map = PLAN_CAPS.get(plan) or PLAN_CAPS.get(DEFAULT_PLAN, {})
    return dict(plan_map.get(feature, {}))


def wallet_meter_for(feature: str) -> str:
    """Return the pricing_balances meter name for pack credits of this feature."""
    return WALLET_METER.get(feature, f"{feature}_credits")


def normalize_plan(plan: str | None) -> str:
    """Coerce an arbitrary plan string to a known plan; unknown → DEFAULT_PLAN."""
    if plan and plan in KNOWN_PLANS:
        return plan
    return DEFAULT_PLAN


def validate_config() -> None:
    """Assert config is internally consistent. Call at module load in dev.

    Raises ValueError on the first inconsistency. Safe to call at startup;
    intended to surface operator typos before production traffic.
    """
    for plan, features in PLAN_CAPS.items():
        if plan not in KNOWN_PLANS:
            raise ValueError(f"plan {plan!r} not in KNOWN_PLANS")
        for feature, caps in features.items():
            if feature not in FEATURES:
                raise ValueError(f"{plan!r}.{feature!r}: unknown feature")
            for gran, val in caps.items():
                if gran not in GRANULARITIES:
                    raise ValueError(f"{plan!r}.{feature!r}.{gran!r}: unknown granularity")
                if val is not None and (not isinstance(val, int) or val < 0):
                    raise ValueError(f"{plan!r}.{feature!r}.{gran!r}: limit must be None or non-negative int, got {val!r}")
    for feature in FEATURES:
        if feature not in WALLET_METER:
            raise ValueError(f"feature {feature!r} missing WALLET_METER mapping")


# Self-check at import; cheap and prevents shipping a broken config.
validate_config()
