"""Unit tests for ops/scripts/apply_migrations.py.

The Postgres driver (psycopg v3) is fully mocked — no DB connection is made.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Fake psycopg
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.conn.executed.append((sql.strip(), params))
        sql_low = sql.strip().lower()
        if self.conn.fail_on and self.conn.fail_on in sql_low:
            raise RuntimeError(f"forced failure on: {self.conn.fail_on}")
        if sql_low.startswith("select name, checksum from _migrations_applied"):
            self._rows = list(self.conn.applied_rows)
        elif sql_low.startswith("insert into _migrations_applied"):
            assert params is not None
            name, checksum, applied_by = params
            self.conn.applied_rows.append((name, checksum))
        elif sql_low.startswith("delete from _migrations_applied"):
            assert params is not None
            (name,) = params
            self.conn.applied_rows = [
                r for r in self.conn.applied_rows if r[0] != name
            ]
        elif sql_low.startswith("select pg_advisory_lock"):
            self.conn.lock_acquired = True
        elif sql_low.startswith("select pg_advisory_unlock"):
            self.conn.lock_released = True

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self.applied_rows: list[tuple[str, str]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.lock_acquired = False
        self.lock_released = False
        self.fail_on: str | None = None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_psycopg(monkeypatch):
    fake_conn = FakeConn()
    fake_module = ModuleType("psycopg")

    def _connect(dsn: str, autocommit: bool = False) -> FakeConn:
        fake_conn.dsn = dsn  # type: ignore[attr-defined]
        return fake_conn

    fake_module.connect = _connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", fake_module)
    return fake_conn


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@h:5432/db")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)


@pytest.fixture
def mig_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "001_first.sql").write_text("CREATE TABLE t1 ();\n", encoding="utf-8")
    (d / "002_second.sql").write_text("CREATE TABLE t2 ();\n", encoding="utf-8")
    return d


# Lazily import the script so the test-time monkeypatching of psycopg works.
def _load():
    from ops.scripts import apply_migrations as am  # noqa: WPS433

    return am


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_detects_pending_migrations_and_applies_in_order(fake_psycopg, env, mig_dir):
    am = _load()
    rc = am.main(["--migrations-dir", str(mig_dir)])
    assert rc == 0
    names = [r[0] for r in fake_psycopg.applied_rows]
    assert names == ["001_first.sql", "002_second.sql"]
    assert fake_psycopg.lock_acquired and fake_psycopg.lock_released


def test_skip_already_applied_matching_checksum(fake_psycopg, env, mig_dir):
    am = _load()
    sql = (mig_dir / "001_first.sql").read_text(encoding="utf-8")
    fake_psycopg.applied_rows.append(("001_first.sql", am._checksum(sql)))
    rc = am.main(["--migrations-dir", str(mig_dir)])
    assert rc == 0
    # Only the pending one should have been added; first remains untouched.
    names = [r[0] for r in fake_psycopg.applied_rows]
    assert names.count("001_first.sql") == 1
    assert "002_second.sql" in names


def test_checksum_mismatch_is_hard_fail(fake_psycopg, env, mig_dir):
    am = _load()
    fake_psycopg.applied_rows.append(("001_first.sql", "deadbeef-not-matching"))
    rc = am.main(["--migrations-dir", str(mig_dir)])
    assert rc == 1
    # Second migration must NOT have been applied after the failure.
    names = [r[0] for r in fake_psycopg.applied_rows]
    assert "002_second.sql" not in names


def test_writes_audit_row_on_success(fake_psycopg, env, mig_dir):
    am = _load()
    rc = am.main(["--migrations-dir", str(mig_dir)])
    assert rc == 0
    inserts = [
        ex for ex in fake_psycopg.executed
        if ex[0].lower().startswith("insert into _migrations_applied")
    ]
    assert len(inserts) == 2
    # Each insert carries (name, checksum, hostname) tuple.
    for _sql, params in inserts:
        assert params is not None and len(params) == 3


def test_rolls_back_on_sql_error(fake_psycopg, env, mig_dir):
    am = _load()
    fake_psycopg.fail_on = "create table t2"
    rc = am.main(["--migrations-dir", str(mig_dir)])
    assert rc == 1
    # First succeeded; second triggered rollback.
    assert ("001_first.sql", am._checksum("CREATE TABLE t1 ();\n")) in fake_psycopg.applied_rows
    assert all(r[0] != "002_second.sql" for r in fake_psycopg.applied_rows)
    assert fake_psycopg.rollbacks >= 1


def test_dry_run_does_not_write(fake_psycopg, env, mig_dir):
    am = _load()
    rc = am.main(["--dry-run", "--migrations-dir", str(mig_dir)])
    assert rc == 0
    assert fake_psycopg.applied_rows == []
    inserts = [
        ex for ex in fake_psycopg.executed
        if ex[0].lower().startswith("insert into _migrations_applied")
    ]
    assert inserts == []


def test_advisory_lock_acquired_and_released(fake_psycopg, env, mig_dir):
    am = _load()
    am.main(["--migrations-dir", str(mig_dir)])
    assert fake_psycopg.lock_acquired
    assert fake_psycopg.lock_released


def test_rollback_requires_down_companion(fake_psycopg, env, mig_dir):
    am = _load()
    fake_psycopg.applied_rows.append(("001_first.sql", "anything"))
    rc = am.main([
        "--migrations-dir", str(mig_dir),
        "--rollback", "001_first.sql",
    ])
    assert rc == 1  # no .down.sql file -> hard fail


def test_rollback_runs_down_companion(fake_psycopg, env, mig_dir):
    am = _load()
    sql = (mig_dir / "001_first.sql").read_text(encoding="utf-8")
    fake_psycopg.applied_rows.append(("001_first.sql", am._checksum(sql)))
    (mig_dir / "001_first.sql.down.sql").write_text(
        "DROP TABLE t1;\n", encoding="utf-8"
    )
    rc = am.main([
        "--migrations-dir", str(mig_dir),
        "--rollback", "001_first.sql",
    ])
    assert rc == 0
    assert all(r[0] != "001_first.sql" for r in fake_psycopg.applied_rows)


def test_missing_env_returns_config_error(monkeypatch, fake_psycopg):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    am = _load()
    rc = am.main([])
    assert rc == 2


def test_dsn_assembly_from_url_and_key(monkeypatch, fake_psycopg):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://abcxyz.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret/with+chars")
    am = _load()
    dsn = am._build_dsn()
    assert "db.abcxyz.supabase.co:5432" in dsn
    # URL-encoded special chars in password
    assert "secret%2Fwith%2Bchars" in dsn
