from __future__ import annotations

import datetime as _dt
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


def test_create_accepted_insert_only_cannot_downgrade_terminal_row():
    """P1 race fix: the accepted write is insert-only (ON CONFLICT DO NOTHING
    via ignore_duplicates=True), so a delayed create_accepted landing AFTER a
    terminal mark_succeeded/mark_failed can NEVER revert the row to
    status='accepted'. A plain conflict-overwriting upsert (no
    ignore_duplicates) would clobber the terminal row -> false 202-forever."""
    uid = uuid4()
    accepted_body = {"status": "accepted", "operation_id": "a-1"}
    mock_client = _client()
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        ok = orepo.create_accepted(
            user_id=uid, operation_id="a-1", request_hash="h1",
            accepted_body=accepted_body,
        )
    assert ok is True
    tbl = mock_client._tbl
    tbl.upsert.assert_called_once()
    payload, kwargs = tbl.upsert.call_args
    upsert_dict = payload[0] if payload else kwargs.get("json", {})
    # all NOT NULL columns satisfied on the insert path
    assert upsert_dict["status"] == "accepted"
    assert upsert_dict["response"] == accepted_body
    assert upsert_dict["error"] is None
    assert upsert_dict["user_id"] == str(uid)
    assert upsert_dict["operation_id"] == "a-1"
    assert upsert_dict["request_hash"] == "h1"
    assert kwargs.get("on_conflict") == "user_id,operation_id"
    # the race-safety guarantee: insert-only, never an overwriting upsert
    assert kwargs.get("ignore_duplicates") is True


def test_mark_succeeded_writes_response():
    uid = uuid4()
    response_payload = {"status": "succeeded", "operation_id": "a-1"}
    mock_client = _client()
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        ok = orepo.mark_succeeded(
            user_id=uid, operation_id="a-1", request_hash="rh1",
            response=response_payload,
        )
    assert ok is True
    tbl = mock_client._tbl
    # R1: terminal write is an UPSERT (self-sufficient even if the best-effort
    # accepted row was never created), NOT a blind .update().
    tbl.upsert.assert_called_once()
    payload, kwargs = tbl.upsert.call_args
    upsert_dict = payload[0] if payload else kwargs.get("json", {})
    assert upsert_dict["status"] == "succeeded"
    assert upsert_dict["response"] == response_payload
    # symmetry/cleanliness: succeeded clears the error column too
    assert upsert_dict["error"] is None
    # all NOT NULL columns satisfied for the insert-on-conflict branch
    assert upsert_dict["user_id"] == str(uid)
    assert upsert_dict["operation_id"] == "a-1"
    assert upsert_dict["request_hash"] == "rh1"
    assert kwargs.get("on_conflict") == "user_id,operation_id"
    # updated_at must be a real ISO-8601 datetime, not the literal "now()"
    assert "updated_at" in upsert_dict
    assert upsert_dict["updated_at"] != "now()"
    _dt.datetime.fromisoformat(upsert_dict["updated_at"])  # raises if not valid ISO


def test_mark_failed_writes_error():
    uid = uuid4()
    failed_payload = {"status": "failed", "operation_id": "a-1"}
    mock_client = _client()
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        ok = orepo.mark_failed(
            user_id=uid, operation_id="a-1", request_hash="rh2",
            response=failed_payload,
        )
    assert ok is True
    tbl = mock_client._tbl
    tbl.upsert.assert_called_once()
    payload, kwargs = tbl.upsert.call_args
    upsert_dict = payload[0] if payload else kwargs.get("json", {})
    assert upsert_dict["status"] == "failed"
    # failed path writes the failure body to `error` AND clears the stale
    # accepted body still sitting in `response` (P1 self-consistency fix)
    assert upsert_dict.get("error") == failed_payload
    assert upsert_dict["response"] is None
    assert upsert_dict["request_hash"] == "rh2"
    assert kwargs.get("on_conflict") == "user_id,operation_id"
    assert "updated_at" in upsert_dict
    assert upsert_dict["updated_at"] != "now()"
    _dt.datetime.fromisoformat(upsert_dict["updated_at"])  # raises if not valid ISO


def test_terminal_upsert_persists_without_prior_accepted_row():
    """R1 core: best-effort create_accepted may have been skipped/failed. The
    terminal mark must still write a row readable by get_operation from another
    worker — i.e. it is an insert-or-update, not a zero-row no-op .update()."""
    uid = uuid4()
    resp_payload = {"status": "succeeded", "operation_id": "op-r1"}
    store: dict[tuple[str, str], dict] = {}
    mock_client = _client()
    tbl = mock_client._tbl

    def _do_upsert(row, **kw):
        store[(row["user_id"], row["operation_id"])] = row
        m = MagicMock()
        m.execute.return_value = _Resp([row])
        return m

    tbl.upsert.side_effect = _do_upsert
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        ok = orepo.mark_succeeded(
            user_id=uid, operation_id="op-r1", request_hash="rh",
            response=resp_payload,
        )
    assert ok is True
    # the terminal row exists keyed by (user_id, operation_id) despite NO
    # create_accepted having run first
    assert (str(uid), "op-r1") in store
    assert store[(str(uid), "op-r1")]["status"] == "succeeded"


def test_terminal_upsert_idempotent_on_duplicate_mark():
    """A second mark_* overwrites with the same terminal state (idempotent)."""
    uid = uuid4()
    mock_client = _client()
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        assert orepo.mark_succeeded(
            user_id=uid, operation_id="dup", request_hash="rh",
            response={"status": "succeeded"},
        ) is True
        assert orepo.mark_succeeded(
            user_id=uid, operation_id="dup", request_hash="rh",
            response={"status": "succeeded"},
        ) is True
    tbl = mock_client._tbl
    assert tbl.upsert.call_count == 2
    for c in tbl.upsert.call_args_list:
        assert c.kwargs.get("on_conflict") == "user_id,operation_id"
        assert c.args[0]["status"] == "succeeded"


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
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", side_effect=RuntimeError("supabase down")):
        assert orepo.create_accepted(user_id=uid, operation_id="x", request_hash="h",
                                     accepted_body={}) is False
        assert orepo.mark_succeeded(user_id=uid, operation_id="x",
                                    request_hash="h", response={}) is False
        assert orepo.get_operation(user_id=uid, operation_id="x") is None


# ---------------------------------------------------------------------------
# Phase 2 (async-ops redesign): RPC-backed state-machine wrappers.
# Tests exercise the new accept/start/finalize/cancel/count_in_flight wrappers
# that call migration 51's core.ops_accept / ops_start / ops_finalize.
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


def test_accept_defensive_on_rpc_error_returns_op_id_true():
    """Any client error -> (operation_id, True) so request path never 5xxs."""
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", side_effect=RuntimeError("pg down")):
        op_id, is_new = orepo.accept(
            user_id=uid, operation_id="op-x", request_hash="rh",
            accepted_body={},
        )
    assert op_id == "op-x"
    assert is_new is True


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
