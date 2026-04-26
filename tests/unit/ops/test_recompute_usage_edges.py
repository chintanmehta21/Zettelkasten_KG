"""Unit tests for ops/scripts/recompute_usage_edges.py.

Mocks the Supabase client end-to-end; no network calls are made.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.scripts import recompute_usage_edges as rue  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Supabase client
# ---------------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, table: "_FakeTable", op: str, payload=None):
        self._table = table
        self._op = op
        self._payload = payload
        self._filters: list[tuple] = []

    def select(self, *_a, **_k):
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def lt(self, col, val):
        self._filters.append(("lt", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def execute(self):
        if self._op == "select":
            data = self._table.select_rows
            # Apply filters – minimal subset used by the script
            for kind, col, val in self._filters:
                if kind == "gte":
                    data = [r for r in data if r.get(col, "") >= val]
                elif kind == "lt":
                    data = [r for r in data if r.get(col, "") < val]
                elif kind == "in":
                    data = [r for r in data if r.get(col) in val]
                elif kind == "eq":
                    data = [r for r in data if r.get(col) == val]
            return SimpleNamespace(data=list(data))
        if self._op == "insert":
            payload = (
                self._payload if isinstance(self._payload, list) else [self._payload]
            )
            self._table.inserted.extend(payload)
            return SimpleNamespace(data=list(payload))
        return SimpleNamespace(data=[])


class _FakeTable:
    def __init__(self, name: str, select_rows=None):
        self.name = name
        self.select_rows = select_rows or []
        self.inserted: list[dict] = []

    def select(self, *_a, **_k):
        return _FakeQuery(self, "select")

    def insert(self, payload):
        return _FakeQuery(self, "insert", payload=payload)


class _FakeRPC:
    def __init__(self, raises=None):
        self.calls: list[tuple[str, dict]] = []
        self._raises = raises

    def __call__(self, name, params=None):
        self.calls.append((name, params or {}))
        if self._raises:
            raise self._raises
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=None))


class _FakeSupabase:
    def __init__(self, tables: dict[str, _FakeTable], rpc_raises=None):
        self.tables = tables
        self.rpc = _FakeRPC(raises=rpc_raises)

    def table(self, name):
        if name not in self.tables:
            self.tables[name] = _FakeTable(name)
        return self.tables[name]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
USER_A = "11111111-1111-1111-1111-111111111111"


def _supported_message(node_ids, verdict="supported", query_class="lookup", user=USER_A):
    return {
        "user_id": user,
        "query_class": query_class,
        "critic_verdict": verdict,
        "retrieved_node_ids": list(node_ids),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "assistant",
    }


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_co_citation_edges_are_inserted(fake_env):
    """Two assistant turns each cite a set of nodes -> co-citation pairs are inserted."""
    rows = [
        _supported_message(["n1", "n2", "n3"]),  # 3 ordered pairs
        _supported_message(["n4", "n5"], verdict="retried_supported"),  # 1 pair, delta=0.5
        _supported_message(["n9"]),  # singleton -> no edge
        _supported_message(["nx", "ny"], verdict="unsupported"),  # filtered out
    ]
    fake = _FakeSupabase(
        tables={
            "chat_messages": _FakeTable("chat_messages", select_rows=rows),
            "kg_usage_edges": _FakeTable("kg_usage_edges"),
            "recompute_runs": _FakeTable("recompute_runs"),
        }
    )
    with patch.object(rue, "create_client", return_value=fake):
        rc = rue.main(["--window-hours", "24"])

    assert rc == 0
    inserted = fake.tables["kg_usage_edges"].inserted
    # 3 + 1 = 4 ordered pairs (source < target ordering)
    assert len(inserted) == 4
    # All have user_id, source/target, query_class, verdict, delta
    for row in inserted:
        assert row["user_id"] == USER_A
        assert row["source_node_id"] != row["target_node_id"]
        assert row["source_node_id"] < row["target_node_id"]
        assert row["query_class"] == "lookup"
        assert row["verdict"] in {"supported", "retried_supported"}
    # Half-credit verdict carries delta=0.5
    retried = [r for r in inserted if r["verdict"] == "retried_supported"]
    assert retried and all(r["delta"] == 0.5 for r in retried)
    supported = [r for r in inserted if r["verdict"] == "supported"]
    assert all(r["delta"] == 1.0 for r in supported)
    # Recompute_runs row written with status=ok and rows_inserted matches
    runs = fake.tables["recompute_runs"].inserted
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert runs[0]["rows_inserted"] == 4
    assert runs[0]["job_name"] == "recompute_usage_edges"
    # MV refresh RPC fired
    assert any(c[0] == "kg_refresh_usage_edges_agg" for c in fake.rpc.calls)


def test_dry_run_skips_inserts_and_refresh(fake_env):
    rows = [_supported_message(["a", "b"])]
    fake = _FakeSupabase(
        tables={
            "chat_messages": _FakeTable("chat_messages", select_rows=rows),
            "kg_usage_edges": _FakeTable("kg_usage_edges"),
            "recompute_runs": _FakeTable("recompute_runs"),
        }
    )
    with patch.object(rue, "create_client", return_value=fake):
        rc = rue.main(["--dry-run"])
    assert rc == 0
    assert fake.tables["kg_usage_edges"].inserted == []
    assert fake.rpc.calls == []
    # Dry-run still records the run (status=ok, rows_inserted=0)
    runs = fake.tables["recompute_runs"].inserted
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert runs[0]["rows_inserted"] == 0


def test_error_records_run_with_stack_trace(fake_env):
    rows = [_supported_message(["a", "b"])]
    fake = _FakeSupabase(
        tables={
            "chat_messages": _FakeTable("chat_messages", select_rows=rows),
            "kg_usage_edges": _FakeTable("kg_usage_edges"),
            "recompute_runs": _FakeTable("recompute_runs"),
        },
        rpc_raises=RuntimeError("boom-refresh-failed"),
    )
    with patch.object(rue, "create_client", return_value=fake):
        rc = rue.main([])
    assert rc == 1
    runs = fake.tables["recompute_runs"].inserted
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert "boom-refresh-failed" in runs[0]["error_message"]
    assert "Traceback" in runs[0]["error_message"]


def test_idempotent_window_filtered_select(fake_env):
    """Running twice over the same window produces inserts only for new rows.

    Idempotency is enforced by a window lower-bound = max(ran_at) for prior
    successful runs. Pre-seeding `recompute_runs` with a recent ok-row should
    cause the second invocation to find zero new messages and insert zero
    edges (no duplicates).
    """
    msg = _supported_message(["a", "b"])
    msg["created_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()

    # Pre-seed a successful prior run that finished AFTER the message — so the
    # second pass should find zero rows in its bounded window.
    prior_run = {
        "job_name": "recompute_usage_edges",
        "status": "ok",
        "rows_inserted": 1,
        "ran_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    fake = _FakeSupabase(
        tables={
            "chat_messages": _FakeTable("chat_messages", select_rows=[msg]),
            "kg_usage_edges": _FakeTable("kg_usage_edges"),
            "recompute_runs": _FakeTable(
                "recompute_runs", select_rows=[prior_run]
            ),
        }
    )
    with patch.object(rue, "create_client", return_value=fake):
        rc = rue.main([])
    assert rc == 0
    # The message is older than the prior run → bounded select returns 0 rows
    assert fake.tables["kg_usage_edges"].inserted == []
    # Newly-recorded run row appended
    runs = fake.tables["recompute_runs"].inserted
    assert len(runs) == 1
    assert runs[0]["rows_inserted"] == 0


def test_user_id_filter_scopes_query(fake_env):
    other = "22222222-2222-2222-2222-222222222222"
    rows = [
        _supported_message(["a", "b"], user=USER_A),
        _supported_message(["c", "d"], user=other),
    ]
    fake = _FakeSupabase(
        tables={
            "chat_messages": _FakeTable("chat_messages", select_rows=rows),
            "kg_usage_edges": _FakeTable("kg_usage_edges"),
            "recompute_runs": _FakeTable("recompute_runs"),
        }
    )
    with patch.object(rue, "create_client", return_value=fake):
        rc = rue.main(["--user-id", USER_A])
    assert rc == 0
    inserted = fake.tables["kg_usage_edges"].inserted
    assert len(inserted) == 1
    assert inserted[0]["user_id"] == USER_A
