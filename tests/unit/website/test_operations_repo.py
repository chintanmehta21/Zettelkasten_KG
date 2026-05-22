from __future__ import annotations

from unittest.mock import MagicMock, call, patch
from uuid import uuid4

from website.core import operations_repo as orepo


class _Resp:
    def __init__(self, data):
        self.data = data


def _client(rows=None):
    c = MagicMock()
    tbl = MagicMock()
    c.schema.return_value.table.return_value = tbl
    tbl.upsert.return_value.execute.return_value = _Resp(rows or [])
    tbl.update.return_value.eq.return_value.eq.return_value.execute.return_value = _Resp(rows or [])
    sel = tbl.select.return_value.eq.return_value.eq.return_value
    sel.limit.return_value.execute.return_value = _Resp(rows or [])
    # expose tbl for call_args inspection
    c._tbl = tbl
    return c


def test_get_operation_returns_row_scoped_to_user():
    uid = uuid4()
    row = {"operation_id": "a-1", "user_id": str(uid), "status": "succeeded",
           "response": {"status": "succeeded", "operation_id": "a-1"}, "error": None}
    mock_client = _client([row])
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        got = orepo.get_operation(user_id=uid, operation_id="a-1")
    assert got is not None and got["status"] == "succeeded"
    tbl = mock_client._tbl
    # BOLA shape: both columns asserted (chained .eq().eq())
    first_eq = tbl.select.return_value.eq
    assert first_eq.call_args == call("user_id", str(uid))
    second_eq = first_eq.return_value.eq
    assert second_eq.call_args == call("operation_id", "a-1")
    # limit(1) must be applied
    second_eq.return_value.limit.assert_called_once_with(1)


def test_get_operation_missing_returns_none():
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", return_value=_client([])):
        assert orepo.get_operation(user_id=uid, operation_id="missing") is None


def test_repo_never_raises_on_client_error():
    """get_operation must swallow client errors and return None so the request
    path never 5xxs from a transient operations-store hiccup."""
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", side_effect=RuntimeError("supabase down")):
        assert orepo.get_operation(user_id=uid, operation_id="x") is None


# ---------------------------------------------------------------------------
# Phase 2 (async-ops redesign): RPC-backed state-machine wrappers.
# Tests exercise the accept/start/finalize/cancel/count_in_flight wrappers
# that call migration 51's core.ops_accept / ops_start / ops_finalize.
# (Phase 5 deleted the prior legacy create_accepted / mark_succeeded /
# mark_failed / _mark upsert helpers; tests for them were removed with the
# functions — the state-guarded RPCs cover the same correctness properties at
# the DB layer where they actually hold.)
# ---------------------------------------------------------------------------


def _rpc_client(rpc_data=None, table_count=0):
    """Build a mock supabase client whose .schema('core').rpc(...).execute()
    returns ``rpc_data`` and whose .schema('core').table('operations').select(...)
    .eq().in_().execute() returns ``count=table_count``."""
    c = MagicMock()
    schema = c.schema.return_value
    schema.rpc.return_value.execute.return_value = _Resp(rpc_data)
    # Backpressure count chain
    sel = schema.table.return_value.select.return_value
    chain = sel.eq.return_value.in_.return_value
    resp = _Resp([])
    resp.count = table_count
    chain.execute.return_value = resp
    # expose handles for assertions
    c._schema = schema
    c._rpc = schema.rpc
    return c


def test_accept_passes_correct_rpc_args():
    """ops_accept arg names must match migration 51 SQL signature exactly:
    p_user_id, p_operation_id, p_request_hash, p_accepted, p_ttl_seconds."""
    uid = uuid4()
    body = {"status": "accepted", "operation_id": "a-1"}
    client = _rpc_client(rpc_data=[
        {"operation_id": "a-1", "status": "queued", "is_new": True}
    ])
    with patch.object(orepo, "get_v2_client", return_value=client):
        op_id, is_new = orepo.accept(
            user_id=uid, operation_id="a-1", request_hash="h1",
            accepted_body=body, ttl_seconds=900,
        )
    assert op_id == "a-1" and is_new is True
    # schema('core').rpc('ops_accept', {...}).execute() — single call
    client._schema.rpc.assert_called_once()
    args, kwargs = client._schema.rpc.call_args
    assert args[0] == "ops_accept"
    params = args[1] if len(args) > 1 else kwargs.get("params") or kwargs
    assert params["p_user_id"] == str(uid)
    assert params["p_operation_id"] == "a-1"
    assert params["p_request_hash"] == "h1"
    assert params["p_accepted"] == body
    assert params["p_ttl_seconds"] == 900


def test_accept_returns_is_new_true_from_response_data():
    uid = uuid4()
    client = _rpc_client(rpc_data=[
        {"operation_id": "fresh-op", "status": "queued", "is_new": True}
    ])
    with patch.object(orepo, "get_v2_client", return_value=client):
        op_id, is_new = orepo.accept(
            user_id=uid, operation_id="fresh-op", request_hash="rh",
            accepted_body={"x": 1},
        )
    assert op_id == "fresh-op"
    assert is_new is True


def test_accept_returns_is_new_false_from_response_data():
    """Duplicate active request returns the EXISTING canonical op_id + False."""
    uid = uuid4()
    client = _rpc_client(rpc_data=[
        {"operation_id": "canonical-op", "status": "running", "is_new": False}
    ])
    with patch.object(orepo, "get_v2_client", return_value=client):
        op_id, is_new = orepo.accept(
            user_id=uid, operation_id="dup-attempt", request_hash="rh",
            accepted_body={"x": 1},
        )
    assert op_id == "canonical-op"
    assert is_new is False


def test_accept_fails_closed_with_none_on_rpc_error():
    """ADR-2 (2026-05-22): ``accept`` now FAILS CLOSED — any operations-store
    error returns ``None`` instead of the prior ``(operation_id, True)``.

    Returning ``(op_id, True)`` previously let the request never 5xx, but it
    spawned background work the client could never poll (no durable row to
    read) — an infinite-pending UX. The caller now returns a retriable 503
    when accept is ``None``."""
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", side_effect=RuntimeError("pg down")):
        result = orepo.accept(
            user_id=uid, operation_id="op-x", request_hash="rh",
            accepted_body={},
        )
    assert result is None


def test_accept_fails_closed_with_none_on_empty_rpc_data():
    """The ops_accept CTE guarantees exactly one row; empty ``data`` means the
    store did not durably record the op -> fail closed with ``None``."""
    uid = uuid4()
    client = _rpc_client(rpc_data=[])
    with patch.object(orepo, "get_v2_client", return_value=client):
        result = orepo.accept(
            user_id=uid, operation_id="op-empty", request_hash="rh",
            accepted_body={},
        )
    assert result is None


def test_start_returns_true_on_running_response():
    """ops_start RETURNS text — wrapper accepts list[str], list[dict], scalar str."""
    uid = uuid4()
    # PostgREST scalar-RETURN shape: list with a single dict {fn_name: 'running'}
    client = _rpc_client(rpc_data=[{"ops_start": "running"}])
    with patch.object(orepo, "get_v2_client", return_value=client):
        ok = orepo.start(user_id=uid, operation_id="op-1")
    assert ok is True
    args, _ = client._schema.rpc.call_args
    assert args[0] == "ops_start"
    params = args[1] if len(args) > 1 else {}
    assert params["p_user_id"] == str(uid)
    assert params["p_operation_id"] == "op-1"


def test_start_returns_false_on_null_response():
    """No-op transition (row already running, terminal, or absent) -> False."""
    uid = uuid4()
    client = _rpc_client(rpc_data=[{"ops_start": None}])
    with patch.object(orepo, "get_v2_client", return_value=client):
        assert orepo.start(user_id=uid, operation_id="op-1") is False
    # Also: bare None data (some postgrest scalar shape)
    client2 = _rpc_client(rpc_data=None)
    with patch.object(orepo, "get_v2_client", return_value=client2):
        assert orepo.start(user_id=uid, operation_id="op-2") is False
    # Also: empty list
    client3 = _rpc_client(rpc_data=[])
    with patch.object(orepo, "get_v2_client", return_value=client3):
        assert orepo.start(user_id=uid, operation_id="op-3") is False


def test_finalize_validates_target_client_side():
    """Garbage target raises ValueError BEFORE the RPC call (faster fail)."""
    uid = uuid4()
    import pytest
    with patch.object(orepo, "get_v2_client", return_value=_rpc_client()):
        with pytest.raises(ValueError):
            orepo.finalize(
                user_id=uid, operation_id="x", target="bogus",
                response=None, error=None,
            )


def test_finalize_succeeded_passes_response_nulls_error():
    uid = uuid4()
    resp_body = {"status": "succeeded", "summary": {"title": "T"}}
    client = _rpc_client(rpc_data=[{"ops_finalize": "succeeded"}])
    with patch.object(orepo, "get_v2_client", return_value=client):
        ok = orepo.finalize(
            user_id=uid, operation_id="op-1", target="succeeded",
            response=resp_body, error=None,
        )
    assert ok is True
    args, _ = client._schema.rpc.call_args
    assert args[0] == "ops_finalize"
    params = args[1]
    assert params["p_target"] == "succeeded"
    assert params["p_response"] == resp_body
    assert params["p_error"] is None


def test_finalize_failed_passes_error_nulls_response():
    uid = uuid4()
    err_body = {
        "type": "https://zettelkasten.in/problems/quota-exhausted",
        "code": "quota_exhausted", "status": 402, "title": "Quota exhausted",
    }
    client = _rpc_client(rpc_data=[{"ops_finalize": "failed"}])
    with patch.object(orepo, "get_v2_client", return_value=client):
        ok = orepo.finalize(
            user_id=uid, operation_id="op-1", target="failed",
            response=None, error=err_body,
        )
    assert ok is True
    args, _ = client._schema.rpc.call_args
    params = args[1]
    assert params["p_target"] == "failed"
    assert params["p_response"] is None
    assert params["p_error"] == err_body


def test_finalize_returns_false_on_noop():
    """Already-terminal row: RPC returns NULL -> wrapper returns False."""
    uid = uuid4()
    client = _rpc_client(rpc_data=[{"ops_finalize": None}])
    with patch.object(orepo, "get_v2_client", return_value=client):
        ok = orepo.finalize(
            user_id=uid, operation_id="x", target="succeeded",
            response={}, error=None,
        )
    assert ok is False


def test_count_in_flight_for_user_uses_count_head():
    """Backpressure count must use count='exact', head=True (cheap COUNT, no rows)."""
    uid = uuid4()
    client = _rpc_client(table_count=4)
    with patch.object(orepo, "get_v2_client", return_value=client):
        n = orepo.count_in_flight_for_user(user_id=uid)
    assert n == 4
    schema = client._schema
    schema.table.assert_called_with("operations")
    sel = schema.table.return_value.select
    sel.assert_called_once_with("operation_id", count="exact", head=True)
    eq = sel.return_value.eq
    eq.assert_called_with("user_id", str(uid))
    in_ = eq.return_value.in_
    in_.assert_called_with("status", ["queued", "running"])


def test_count_in_flight_for_user_fail_open_on_error():
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", side_effect=RuntimeError("down")):
        assert orepo.count_in_flight_for_user(user_id=uid) == 0


def test_cancel_calls_finalize_with_cancelled_target():
    uid = uuid4()
    client = _rpc_client(rpc_data=[{"ops_finalize": "cancelled"}])
    with patch.object(orepo, "get_v2_client", return_value=client):
        ok = orepo.cancel(user_id=uid, operation_id="op-c")
    assert ok is True
    args, _ = client._schema.rpc.call_args
    assert args[0] == "ops_finalize"
    params = args[1]
    assert params["p_target"] == "cancelled"
    assert params["p_response"] is None
    # error payload is a populated dict (RFC 9457-ish), not None
    assert isinstance(params["p_error"], dict)
    assert params["p_error"].get("code") == "operation_cancelled"
    assert params["p_error"].get("status") == 499


def test_cancel_idempotent_on_terminal_returns_false():
    """Duplicate cancel of already-terminal row: RPC returns NULL -> False."""
    uid = uuid4()
    client = _rpc_client(rpc_data=[{"ops_finalize": None}])
    with patch.object(orepo, "get_v2_client", return_value=client):
        assert orepo.cancel(user_id=uid, operation_id="terminal") is False
