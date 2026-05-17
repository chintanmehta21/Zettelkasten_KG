"""Per-profile no-seed invariant (Phase-9 update).

Phase-9 functional gates (PR #18) introduce ONE permitted auto-seed:
``billing.pricing_subscriptions`` gets a single ``plan_id='free'`` row on
``core.profiles INSERT`` via the trigger ``seed_free_subscription_on_profile``.
Every other per-profile billing table MUST still start empty for a fresh user.

If any of the always-zero tables drift to non-zero, an unauthorised seeding
path landed and the operator must be surfaced per CLAUDE.md pricing-authority
rule.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


# Tables that MUST have zero rows for a fresh user (per-profile).
_PER_PROFILE_TABLES = [
    ("billing.pricing_balances", "profile_id"),
    ("billing.pricing_billing_profiles", "profile_id"),
    ("billing.pricing_orders", "profile_id"),
    ("billing.pricing_refunds", "profile_id"),
    ("billing.pricing_disputes", "profile_id"),
    ("billing.pricing_usage_counters", "profile_id"),
    ("billing.pricing_action_ledger", "profile_id"),
]


async def test_fresh_user_has_no_per_profile_billing_rows(mint_user, asyncpg_pool):
    """A freshly minted user has zero rows in every always-empty billing table."""
    user = mint_user()

    counts: dict[str, int] = {}
    async with asyncpg_pool.acquire() as conn:
        for table, pid_col in _PER_PROFILE_TABLES:
            row = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE {pid_col} = $1",
                user.profile_id,
            )
            counts[table] = int(row or 0)

    seeded = {t: n for t, n in counts.items() if n != 0}
    assert not seeded, (
        f"Fresh user {user.profile_id} has pre-seeded rows in: {seeded}. "
        "Pricing-authority rule violation — STOP and surface to operator."
    )


async def test_fresh_user_has_exactly_one_free_subscription(mint_user, asyncpg_pool):
    """Fresh user MUST have exactly one Free subscription (operator-approved auto-seed).

    Phase-9 contract: ``seed_free_subscription_on_profile`` trigger inserts
    one ``plan_id='free', status='active'`` row on profile creation. Anything
    else (zero rows, multiple rows, non-Free plan, non-active status) is a
    contract violation.
    """
    user = mint_user()

    async with asyncpg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, plan_id, provider_payload "
            "FROM billing.pricing_subscriptions WHERE profile_id = $1",
            user.profile_id,
        )

    assert len(rows) == 1, (
        f"Fresh user expected exactly 1 subscription; got {len(rows)}: "
        f"{[dict(r) for r in rows]}"
    )
    row = rows[0]
    assert row["plan_id"] == "free", f"expected plan_id='free'; got {row['plan_id']}"
    assert row["status"] == "active", f"expected status='active'; got {row['status']}"
