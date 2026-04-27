"""Schema-drift comparator tests for apply_migrations (iter-03 §1C.5).

The comparator (``_diff_schemas``) is pure — no DB needed. We exercise the
five drift kinds called out in the spec:

* added column   (column in live but not manifest)  -> "unexpected column"
* removed column (column in manifest but not live)  -> "missing column"
* type change                                       -> "data_type mismatch"
* nullability change                                -> "is_nullable mismatch"
* default change                                    -> "default mismatch"

Plus: missing table, missing function, identical schema (no drift).

We also test ``_verify_schema`` against an in-memory fake conn so the
manifest-on-disk path is covered end-to-end.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.scripts.apply_migrations import (  # noqa: E402
    _diff_schemas,
    _verify_schema,
)


def _table(**cols) -> dict:
    """Build a {'columns': {col: {data_type, is_nullable, default}}} block."""
    return {"columns": cols}


def _col(data_type: str, is_nullable: str = "NO", default=None) -> dict:
    return {"data_type": data_type, "is_nullable": is_nullable, "default": default}


# ---------------------------------------------------------------------------
# _diff_schemas: pure comparator
# ---------------------------------------------------------------------------
def test_identical_schemas_no_drift():
    snap = {
        "tables": {"kg_nodes": _table(id=_col("uuid"), title=_col("text"))},
        "functions": {"hybrid_search(text)": {"return_type": "TABLE(...)"}},
    }
    assert _diff_schemas(snap, snap) == []


def test_missing_table_detected():
    expected = {"tables": {"kg_nodes": _table(id=_col("uuid"))}, "functions": {}}
    live = {"tables": {}, "functions": {}}
    drift = _diff_schemas(expected, live)
    assert any("missing table: kg_nodes" in d for d in drift)


def test_missing_column_detected():
    expected = {"tables": {"t": _table(a=_col("text"), b=_col("int"))}, "functions": {}}
    live = {"tables": {"t": _table(a=_col("text"))}, "functions": {}}
    drift = _diff_schemas(expected, live)
    assert any("missing column: t.b" in d for d in drift)


def test_added_column_in_live_flagged_as_unexpected():
    """If live has a column the manifest doesn't, flag — manifest is stale."""
    expected = {"tables": {"t": _table(a=_col("text"))}, "functions": {}}
    live = {"tables": {"t": _table(a=_col("text"), c=_col("text"))}, "functions": {}}
    drift = _diff_schemas(expected, live)
    assert any("unexpected column" in d and "t.c" in d for d in drift)


def test_data_type_change_detected():
    expected = {"tables": {"t": _table(a=_col("text"))}, "functions": {}}
    live = {"tables": {"t": _table(a=_col("integer"))}, "functions": {}}
    drift = _diff_schemas(expected, live)
    assert any("data_type mismatch" in d and "t.a" in d for d in drift)


def test_nullability_change_detected():
    expected = {"tables": {"t": _table(a=_col("text", is_nullable="NO"))}, "functions": {}}
    live = {"tables": {"t": _table(a=_col("text", is_nullable="YES"))}, "functions": {}}
    drift = _diff_schemas(expected, live)
    assert any("is_nullable mismatch" in d and "t.a" in d for d in drift)


def test_default_change_detected():
    expected = {
        "tables": {"t": _table(a=_col("text", default="'x'::text"))},
        "functions": {},
    }
    live = {
        "tables": {"t": _table(a=_col("text", default="'y'::text"))},
        "functions": {},
    }
    drift = _diff_schemas(expected, live)
    assert any("default mismatch" in d and "t.a" in d for d in drift)


def test_missing_function_detected():
    expected = {
        "tables": {},
        "functions": {"hybrid_search(text)": {"return_type": "TABLE(...)"}},
    }
    live = {"tables": {}, "functions": {}}
    drift = _diff_schemas(expected, live)
    assert any("missing function: hybrid_search(text)" in d for d in drift)


def test_legacy_bare_string_type_supported():
    """Manifest authored before §1C.5 may store columns as bare type strings."""
    expected = {"tables": {"t": {"columns": {"a": "text"}}}, "functions": {}}
    live = {"tables": {"t": _table(a=_col("text"))}, "functions": {}}
    # Bare strings only pin data_type; nullability/default are not asserted.
    assert _diff_schemas(expected, live) == []

    live_wrong = {"tables": {"t": _table(a=_col("integer"))}, "functions": {}}
    drift = _diff_schemas(expected, live_wrong)
    assert any("data_type mismatch" in d for d in drift)


# ---------------------------------------------------------------------------
# _verify_schema: end-to-end with a fake conn + on-disk manifest
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "from information_schema.columns" in s:
            self._rows = self.conn.column_rows
        elif "from pg_indexes" in s:
            self._rows = self.conn.index_rows
        elif "from pg_proc" in s:
            self._rows = self.conn.function_rows
        else:
            self._rows = []

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self):
        self.column_rows: list[tuple] = []
        self.index_rows: list[tuple] = []
        self.function_rows: list[tuple] = []

    def cursor(self):
        return _FakeCursor(self)


def test_verify_schema_returns_one_when_manifest_missing(tmp_path):
    conn = _FakeConn()
    rc = _verify_schema(conn, tmp_path / "missing.json")
    assert rc == 1


def test_verify_schema_zero_when_match(tmp_path):
    manifest = {
        "tables": {"t": _table(a=_col("text", "NO", None))},
        "functions": {},
        "indexes": {},
    }
    p = tmp_path / "expected.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    conn = _FakeConn()
    conn.column_rows = [("t", "a", "text", "NO", None)]
    rc = _verify_schema(conn, p)
    assert rc == 0


def test_verify_schema_one_when_column_missing(tmp_path):
    manifest = {
        "tables": {"t": _table(a=_col("text"), b=_col("int"))},
        "functions": {},
        "indexes": {},
    }
    p = tmp_path / "expected.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    conn = _FakeConn()
    conn.column_rows = [("t", "a", "text", "NO", None)]
    rc = _verify_schema(conn, p)
    assert rc == 1
