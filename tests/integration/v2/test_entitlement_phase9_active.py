"""Phase-9 active — SQL-layer assertions for billing.pricing_reserve_and_consume.

Caps come from `website.features.functional_gates.config` (operator-editable
Python source of truth). The SQL RPC never reads policy from the DB; tests
pass caps as jsonb exactly as the Python gate will at runtime.

Covered:
1. Fresh Free user can consume up to the day cap, then ``quota_exhausted``.
2. Idempotency: same ``action_id`` returns original outcome without
   double-incrementing.
3. Wallet fallback: plan exhausted + wallet credits → source flips to wallet
   and pricing_balances decrements by 1.
4. Multi-period min(): hitting the day cap blocks even with week/month room.
5. Config-driven: passing a custom caps jsonb at call site changes behavior
   without any DB write.
"""

from __future__ import annotations

import json
import uuid

import pytest

from website.features.functional_gates.config import caps_for, wallet_meter_for

pytestmark = pytest.mark.live


def _caps_jsonb(plan: str, feature: str) -> str:
    return json.dumps(caps_for(plan, feature))


def _as_dict(value):
    """asyncpg returns jsonb as a JSON-encoded str when no codec is registered.
    Coerce to dict so .key access works in assertions."""
    if isinstance(value, str):
        return json.loads(value)
    return value


async def _rpc(conn, sql, *args):
    return _as_dict(await conn.fetchval(sql, *args))


_RESERVE = "SELECT billing.pricing_reserve_and_consume($1, 'zettel', $2, $3::jsonb, $4)"
_SNAPSHOT = "SELECT billing.pricing_get_quota_snapshot($1, 'zettel', $2::jsonb, $3)"


async def test_free_zettel_day_cap_then_blocked(mint_user, asyncpg_pool):
    """Free plan zettel day cap from config; cap+1th call returns ``quota_exhausted``."""
    user = mint_user()
    caps = _caps_jsonb("free", "zettel")
    wallet = wallet_meter_for("zettel")
    day_cap = caps_for("free", "zettel")["day"]
    assert day_cap is not None

    async with asyncpg_pool.acquire() as conn:
        results = []
        for _ in range(day_cap + 1):
            r = await _rpc(conn, _RESERVE, user.profile_id, f"act-{uuid.uuid4().hex}", caps, wallet)
            results.append(r)

    for r in results[:-1]:
        assert r["allowed"] is True and r["source"] == "plan", r
    blocked = results[-1]
    assert blocked["allowed"] is False
    assert blocked["reason"] == "quota_exhausted"
    assert blocked["remaining_plan"] == 0


async def test_reserve_and_consume_is_idempotent(mint_user, asyncpg_pool):
    """Same ``action_id`` returns the original outcome and never double-charges."""
    user = mint_user()
    action_id = f"idem-{uuid.uuid4().hex}"
    caps = _caps_jsonb("free", "zettel")
    wallet = wallet_meter_for("zettel")

    async with asyncpg_pool.acquire() as conn:
        first = await _rpc(conn, _RESERVE, user.profile_id, action_id, caps, wallet)
        second = await _rpc(conn, _RESERVE, user.profile_id, action_id, caps, wallet)
        used_today = await conn.fetchval(
            "SELECT count FROM billing.pricing_usage_counters "
            "WHERE profile_id = $1 AND feature='zettel' AND granularity='day'",
            user.profile_id,
        )

    assert first["allowed"] is True and first["idempotent"] is False
    assert second["allowed"] is True and second["idempotent"] is True
    assert second["source"] == first["source"]
    assert used_today == 1, f"counter incremented twice; expected 1, got {used_today}"


async def test_wallet_fallback_after_plan_exhausted(mint_user, asyncpg_pool):
    """Plan exhausted + wallet credits available → source flips to wallet."""
    user = mint_user()
    caps = _caps_jsonb("free", "zettel")
    wallet_meter = wallet_meter_for("zettel")
    day_cap = caps_for("free", "zettel")["day"]
    assert day_cap is not None

    async with asyncpg_pool.acquire() as conn:
        for _ in range(day_cap):
            await _rpc(conn, _RESERVE, user.profile_id, f"pre-{uuid.uuid4().hex}", caps, wallet_meter)
        await conn.fetchval(
            "SELECT billing.pricing_add_pack_credits($1, $2, 1)",
            user.profile_id, wallet_meter,
        )
        wallet_consume = await _rpc(
            conn, _RESERVE, user.profile_id, f"wallet-{uuid.uuid4().hex}", caps, wallet_meter,
        )
        bal_after = await conn.fetchval(
            "SELECT balance FROM billing.pricing_balances "
            "WHERE profile_id = $1 AND meter = $2",
            user.profile_id, wallet_meter,
        )

    assert wallet_consume["allowed"] is True
    assert wallet_consume["source"] == "wallet"
    assert wallet_consume["remaining_wallet"] == 0
    assert bal_after == 0


async def test_day_cap_blocks_even_when_week_month_room_remains(mint_user, asyncpg_pool):
    """min(day, week, month) — exhausting day blocks even if week has room."""
    user = mint_user()
    caps = _caps_jsonb("free", "zettel")
    wallet_meter = wallet_meter_for("zettel")
    cfg = caps_for("free", "zettel")
    assert cfg["day"] < cfg["week"] < cfg["month"]

    async with asyncpg_pool.acquire() as conn:
        for _ in range(cfg["day"]):
            await _rpc(conn, _RESERVE, user.profile_id, f"d-{uuid.uuid4().hex}", caps, wallet_meter)
        snap = await _rpc(conn, _SNAPSHOT, user.profile_id, caps, wallet_meter)

    assert snap["used"]["day"] == cfg["day"]
    assert snap["used"]["week"] == cfg["day"]
    assert snap["used"]["month"] == cfg["day"]
    assert snap["remaining_plan"] == 0


async def test_caps_are_runtime_configurable(mint_user, asyncpg_pool):
    """Overriding caps at call-site changes behavior; nothing in the DB pins policy."""
    user = mint_user()
    wallet_meter = wallet_meter_for("zettel")
    tight = json.dumps({"day": 1, "week": None, "month": None, "lifetime": None})
    loose = json.dumps({"day": 100, "week": None, "month": None, "lifetime": None})

    async with asyncpg_pool.acquire() as conn:
        r1 = await _rpc(conn, _RESERVE, user.profile_id, f"cap-a-{uuid.uuid4().hex}", tight, wallet_meter)
        r2 = await _rpc(conn, _RESERVE, user.profile_id, f"cap-b-{uuid.uuid4().hex}", tight, wallet_meter)
        r3 = await _rpc(conn, _RESERVE, user.profile_id, f"cap-c-{uuid.uuid4().hex}", loose, wallet_meter)

    assert r1["allowed"] is True
    assert r2["allowed"] is False and r2["reason"] == "quota_exhausted"
    assert r3["allowed"] is True
