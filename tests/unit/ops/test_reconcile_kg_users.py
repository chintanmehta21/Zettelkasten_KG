"""Tests for reconcile_kg_users (Task 2D.1).

The script talks to Postgres; tests use a fake conn/cursor recording every
SQL statement and returning canned rows. We verify the SQL contract, dry-run
vs apply behavior, and that the allowlist is respected.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.scripts import reconcile_kg_users as r

NARUTO = "f2105544-b73d-4946-8329-096d82f070d3"
ZORO = "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
DUPE_NARUTO = "11111111-1111-1111-1111-111111111111"
ORPHAN = "99999999-9999-9999-9999-999999999999"

ALLOWLIST = {
    "allowed_auth_ids": [NARUTO, ZORO],
    "_canonical_naruto": NARUTO,
    "_canonical_zoro": ZORO,
}


class FakeCursor:
    def __init__(self, rows_by_query):
        self._rows_by_query = rows_by_query
        self._rows = []
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        for prefix, rows in self._rows_by_query.items():
            if prefix in sql:
                self._rows = list(rows)
                return
        self._rows = []

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, rows_by_query):
        self._rows = rows_by_query
        self._cursor = FakeCursor(rows_by_query)
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_load_allowlist(tmp_path: Path):
    p = tmp_path / "allow.json"
    p.write_text(json.dumps(ALLOWLIST), encoding="utf-8")
    assert r.load_allowlist(p) == ALLOWLIST


def test_audit_returns_users_and_orphans():
    conn = FakeConn({
        "FROM kg_users": [(NARUTO, "naruto@example.com"), (ZORO, "zoro@example.com")],
        "FROM kg_nodes": [(NARUTO,), (ZORO,), (ORPHAN,)],
    })
    report = r.audit(conn, allowlist=ALLOWLIST)
    assert ORPHAN in report["orphan_owners"]
    assert NARUTO not in report["orphan_owners"]
    assert report["duplicate_naruto"] == []


def test_audit_flags_duplicate_naruto():
    conn = FakeConn({
        "FROM kg_users": [
            (NARUTO, "naruto@konoha.test"),
            (DUPE_NARUTO, "naruto-old@konoha.test"),
            (ZORO, "zoro@example.com"),
        ],
        "FROM kg_nodes": [(NARUTO,)],
    })
    report = r.audit(conn, allowlist=ALLOWLIST)
    assert any(row[0] == DUPE_NARUTO for row in report["duplicate_naruto"])


def test_dedupe_naruto_dry_run_does_not_commit():
    conn = FakeConn({
        "FROM kg_users WHERE LOWER(email) LIKE 'naruto%%'": [(DUPE_NARUTO,)],
    })
    n = r.dedupe_naruto(conn, dry_run=True, allowlist=ALLOWLIST)
    assert n == 1
    assert conn.commits == 0
    update_calls = [c for c in conn._cursor.executed if "UPDATE" in c[0] or "DELETE" in c[0]]
    assert update_calls == []


def test_dedupe_naruto_apply_reassigns_and_deletes():
    conn = FakeConn({
        "FROM kg_users WHERE LOWER(email) LIKE 'naruto%%'": [(DUPE_NARUTO,)],
    })
    n = r.dedupe_naruto(conn, dry_run=False, allowlist=ALLOWLIST)
    assert n == 1
    assert conn.commits == 1
    sqls = [c[0] for c in conn._cursor.executed]
    assert any("UPDATE kg_nodes" in s for s in sqls)
    assert any("UPDATE kg_links" in s for s in sqls)
    assert any("UPDATE kg_node_chunks" in s for s in sqls)
    assert any("DELETE FROM kg_users" in s for s in sqls)


def test_dedupe_handles_no_duplicates():
    conn = FakeConn({"FROM kg_users WHERE LOWER(email) LIKE 'naruto%%'": []})
    assert r.dedupe_naruto(conn, dry_run=False, allowlist=ALLOWLIST) == 0
    assert conn.commits == 0


def test_purge_orphans_dry_run_only_counts():
    conn = FakeConn({
        "COUNT(*) FROM kg_nodes WHERE user_id::text NOT IN": [(7,)],
        "COUNT(*) FROM kg_links WHERE user_id::text NOT IN": [(3,)],
    })
    counts = r.purge_orphans(conn, dry_run=True, allowlist=ALLOWLIST)
    assert counts == {"nodes": 7, "links": 3}
    assert conn.commits == 0


def test_purge_orphans_apply_deletes():
    conn = FakeConn({
        "COUNT(*) FROM kg_nodes WHERE user_id::text NOT IN": [(2,)],
        "COUNT(*) FROM kg_links WHERE user_id::text NOT IN": [(1,)],
    })
    r.purge_orphans(conn, dry_run=False, allowlist=ALLOWLIST)
    assert conn.commits == 1
    sqls = [c[0] for c in conn._cursor.executed]
    assert any("DELETE FROM kg_nodes" in s for s in sqls)
    assert any("DELETE FROM kg_links" in s for s in sqls)


def test_main_requires_at_least_one_action(monkeypatch):
    with pytest.raises(SystemExit):
        r.main([])
