"""DSN-assembly hard-fail tests for apply_migrations (iter-03 §1C.1).

The IPv6-only ``db.<ref>.supabase.co`` fallback caused 4 prior deploy
incidents. ``_build_dsn`` must require ``SUPABASE_DB_URL`` explicitly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.scripts.apply_migrations import _build_dsn  # noqa: E402


def test_build_dsn_requires_explicit_db_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
    with pytest.raises(RuntimeError, match="SUPABASE_DB_URL"):
        _build_dsn()


def test_build_dsn_returns_explicit_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@host:6543/db")
    assert _build_dsn() == "postgresql://u:p@host:6543/db"
