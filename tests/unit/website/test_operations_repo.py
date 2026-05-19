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


def test_create_accepted_upserts_accepted_row():
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
    assert upsert_dict["status"] == "accepted"
    assert upsert_dict["response"] == accepted_body
    assert upsert_dict["error"] is None
    assert upsert_dict["user_id"] == str(uid)
    assert upsert_dict["operation_id"] == "a-1"
    assert upsert_dict["request_hash"] == "h1"
    assert kwargs.get("on_conflict") == "user_id,operation_id"


def test_mark_succeeded_writes_response():
    uid = uuid4()
    response_payload = {"status": "succeeded", "operation_id": "a-1"}
    mock_client = _client()
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        ok = orepo.mark_succeeded(
            user_id=uid, operation_id="a-1",
            response=response_payload,
        )
    assert ok is True
    tbl = mock_client._tbl
    tbl.update.assert_called_once()
    update_dict = tbl.update.call_args[0][0]
    assert update_dict["status"] == "succeeded"
    assert update_dict["response"] == response_payload
    # updated_at must be a real ISO-8601 datetime, not the literal "now()"
    assert "updated_at" in update_dict
    assert update_dict["updated_at"] != "now()"
    _dt.datetime.fromisoformat(update_dict["updated_at"])  # raises if not valid ISO
    # BOLA: both user_id and operation_id scoped (chained .eq().eq())
    first_eq = tbl.update.return_value.eq
    assert first_eq.call_args == call("user_id", str(uid))
    second_eq = first_eq.return_value.eq
    assert second_eq.call_args == call("operation_id", "a-1")


def test_mark_failed_writes_error():
    uid = uuid4()
    failed_payload = {"status": "failed", "operation_id": "a-1"}
    mock_client = _client()
    with patch.object(orepo, "get_v2_client", return_value=mock_client):
        ok = orepo.mark_failed(
            user_id=uid, operation_id="a-1",
            response=failed_payload,
        )
    assert ok is True
    tbl = mock_client._tbl
    tbl.update.assert_called_once()
    update_dict = tbl.update.call_args[0][0]
    assert update_dict["status"] == "failed"
    # failed path writes to `error` column, NOT `response`
    assert update_dict.get("error") == failed_payload
    assert "response" not in update_dict
    assert "updated_at" in update_dict
    assert update_dict["updated_at"] != "now()"
    _dt.datetime.fromisoformat(update_dict["updated_at"])  # raises if not valid ISO


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
        assert orepo.mark_succeeded(user_id=uid, operation_id="x", response={}) is False
        assert orepo.get_operation(user_id=uid, operation_id="x") is None
