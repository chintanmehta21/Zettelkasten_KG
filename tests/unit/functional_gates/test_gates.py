"""Unit tests for functional_gates.gates — mocks the Supabase client."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from website.features.functional_gates import (
    FunctionalGates,
    GateDecision,
    QuotaSnapshot,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_for_tests()
    yield
    reset_for_tests()


def _client_returning(rpc_returns: dict | str):
    """Build a mock supabase client whose .schema(...).rpc(...).execute() returns rpc_returns."""
    client = MagicMock()
    resp = MagicMock()
    resp.data = rpc_returns
    (
        client.schema.return_value
        .rpc.return_value
        .execute.return_value
    ) = resp
    return client


async def test_reserve_and_consume_parses_allowed_plan():
    profile_id = str(uuid.uuid4())
    client = _client_returning({
        "allowed": True,
        "idempotent": False,
        "source": "plan",
        "reason": "ok",
        "remaining_plan": 1,
        "remaining_wallet": 0,
    })
    gate = FunctionalGates(client=client)
    # Skip plan lookup by passing explicit plan.
    decision = await gate.reserve_and_consume(
        profile_id=profile_id,
        feature="zettel",
        action_id="probe-1",
        plan="free",
    )

    assert isinstance(decision, GateDecision)
    assert decision.allowed is True
    assert decision.source == "plan"
    assert decision.remaining_plan == 1

    # Verify the RPC payload contained caps from config and the right wallet meter.
    call = client.schema.return_value.rpc.call_args
    assert call.args[0] == "pricing_reserve_and_consume"
    payload = call.args[1]
    assert payload["p_feature"] == "zettel"
    assert payload["p_action_id"] == "probe-1"
    assert payload["p_caps"]["day"] == 2  # Free zettel day cap
    assert payload["p_wallet_meter"] == "zettel"


async def test_reserve_and_consume_parses_denied():
    profile_id = str(uuid.uuid4())
    client = _client_returning({
        "allowed": False,
        "source": "none",
        "reason": "quota_exhausted",
        "remaining_plan": 0,
        "remaining_wallet": 0,
    })
    gate = FunctionalGates(client=client)
    decision = await gate.reserve_and_consume(
        profile_id=profile_id, feature="zettel", action_id="probe-2", plan="free",
    )
    assert decision.allowed is False
    assert decision.source == "none"
    assert decision.reason == "quota_exhausted"


async def test_reserve_and_consume_rejects_empty_action_id():
    gate = FunctionalGates(client=_client_returning({"allowed": True}))
    with pytest.raises(ValueError, match="action_id"):
        await gate.reserve_and_consume(
            profile_id=str(uuid.uuid4()), feature="zettel", action_id="", plan="free",
        )


async def test_reserve_and_consume_rejects_empty_feature():
    gate = FunctionalGates(client=_client_returning({"allowed": True}))
    with pytest.raises(ValueError, match="feature"):
        await gate.reserve_and_consume(
            profile_id=str(uuid.uuid4()), feature="", action_id="x", plan="free",
        )


async def test_reserve_and_consume_rejects_non_uuid_profile():
    gate = FunctionalGates(client=_client_returning({"allowed": True}))
    with pytest.raises(ValueError, match="UUID"):
        await gate.reserve_and_consume(
            profile_id="not-a-uuid", feature="zettel", action_id="x", plan="free",
        )


async def test_quota_snapshot_parses_response():
    profile_id = str(uuid.uuid4())
    client = _client_returning({
        "feature": "zettel",
        "caps": {"day": 2, "week": 10, "month": 30, "lifetime": None},
        "used": {"day": 1, "week": 1, "month": 1, "lifetime": 0},
        "remaining_plan": 1,
        "remaining_wallet": 4,
        "effective_available": 5,
    })
    gate = FunctionalGates(client=client)
    snap = await gate.quota_snapshot(
        profile_id=profile_id, feature="zettel", plan="free",
    )
    assert isinstance(snap, QuotaSnapshot)
    assert snap.feature == "zettel"
    assert snap.caps["day"] == 2
    assert snap.remaining_plan == 1
    assert snap.remaining_wallet == 4
    assert snap.effective_available == 5


async def test_plan_for_profile_caches_within_ttl():
    profile_id = str(uuid.uuid4())
    client = _client_returning("basic")
    gate = FunctionalGates(client=client)

    p1 = await gate.plan_for_profile(profile_id)
    p2 = await gate.plan_for_profile(profile_id)
    assert p1 == p2 == "basic"
    # Only one RPC call for the two reads — cache hit on second.
    assert client.schema.return_value.rpc.call_count == 1


async def test_plan_for_profile_unknown_falls_back_to_free():
    profile_id = str(uuid.uuid4())
    client = _client_returning("not-a-real-plan")
    gate = FunctionalGates(client=client)
    assert await gate.plan_for_profile(profile_id) == "free"


async def test_plan_for_profile_returns_free_on_rpc_failure():
    profile_id = str(uuid.uuid4())
    client = MagicMock()
    client.schema.return_value.rpc.return_value.execute.side_effect = RuntimeError("boom")
    gate = FunctionalGates(client=client)
    assert await gate.plan_for_profile(profile_id) == "free"


async def test_reserve_and_consume_passes_caps_for_resolved_plan():
    """When plan is None, gate resolves it and passes the matching caps."""
    profile_id = str(uuid.uuid4())

    # Sequence: first call resolves the plan -> 'max', second call is the
    # reserve_and_consume; verify the caps payload matches Max zettel caps.
    client = MagicMock()
    plan_resp = MagicMock()
    plan_resp.data = "max"
    consume_resp = MagicMock()
    consume_resp.data = {
        "allowed": True, "source": "plan", "reason": "ok",
        "remaining_plan": 29, "remaining_wallet": 0,
    }
    client.schema.return_value.rpc.return_value.execute.side_effect = [plan_resp, consume_resp]

    gate = FunctionalGates(client=client)
    decision = await gate.reserve_and_consume(
        profile_id=profile_id, feature="zettel", action_id="probe-max",
    )
    assert decision.allowed is True

    consume_payload = client.schema.return_value.rpc.call_args_list[-1].args[1]
    assert consume_payload["p_caps"]["day"] == 30   # Max zettel day cap
    assert consume_payload["p_caps"]["week"] == 100
    assert consume_payload["p_caps"]["month"] == 200
