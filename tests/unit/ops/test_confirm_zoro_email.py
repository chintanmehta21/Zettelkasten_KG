"""Tests for confirm_zoro_email (Task 2D.2)."""
from __future__ import annotations

from ops.scripts import confirm_zoro_email as c


class FakeCursor:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, rowcount: int):
        self._cursor = FakeCursor(rowcount)
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


def test_confirm_returns_rowcount_and_commits():
    conn = FakeConn(rowcount=1)
    n = c.confirm(conn)
    assert n == 1
    assert conn.commits == 1
    sql, params = conn._cursor.executed[0]
    assert "UPDATE auth.users" in sql
    assert "email_confirmed_at IS NULL" in sql
    assert params == (c.ZORO_AUTH_ID,)


def test_confirm_idempotent_when_already_confirmed():
    conn = FakeConn(rowcount=0)
    n = c.confirm(conn)
    assert n == 0
    assert conn.commits == 1
