from __future__ import annotations

from unittest.mock import MagicMock, patch
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
    return c


def test_create_accepted_upserts_accepted_row():
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", return_value=_client()):
        ok = orepo.create_accepted(
            user_id=uid, operation_id="a-1", request_hash="h1",
            accepted_body={"status": "accepted", "operation_id": "a-1"},
        )
    assert ok is True


def test_mark_succeeded_writes_response():
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", return_value=_client()):
        ok = orepo.mark_succeeded(
            user_id=uid, operation_id="a-1",
            response={"status": "succeeded", "operation_id": "a-1"},
        )
    assert ok is True


def test_mark_failed_writes_error():
    uid = uuid4()
    with patch.object(orepo, "get_v2_client", return_value=_client()):
        ok = orepo.mark_failed(
            user_id=uid, operation_id="a-1",
            response={"status": "failed", "operation_id": "a-1"},
        )
    assert ok is True


def test_get_operation_returns_row_scoped_to_user():
    uid = uuid4()
    row = {"operation_id": "a-1", "user_id": str(uid), "status": "succeeded",
           "response": {"status": "succeeded", "operation_id": "a-1"}, "error": None}
    with patch.object(orepo, "get_v2_client", return_value=_client([row])):
        got = orepo.get_operation(user_id=uid, operation_id="a-1")
    assert got is not None and got["status"] == "succeeded"


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
