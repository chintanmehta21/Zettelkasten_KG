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
