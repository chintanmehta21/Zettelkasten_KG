"""Tests for the iter-03 §1C.5 hardened manifest gate (controller fill-in).

Verifies the three branches of the new env-driven logic:
  * MIGRATION_MANIFEST_REQUIRED=1 (default) + manifest absent → exit 1.
  * MIGRATION_MANIFEST_AUTOBOOTSTRAP=1 + manifest absent → write + return 0.
  * MIGRATION_MANIFEST_REQUIRED=0 → warn-only emergency fallback.

Reuses the fake_psycopg + mig_dir fixtures from test_apply_migrations.py via
explicit re-import so the gate sees a successful migration apply.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest_plugins = ("tests.unit.ops.test_apply_migrations",)

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.unit.ops.test_apply_migrations import (  # noqa: E402
    _load,
    fake_psycopg as _fake_psycopg,
    mig_dir as _mig_dir,
)


@pytest.fixture(name="fake_psycopg")
def fake_psycopg_fixture(monkeypatch):
    return _fake_psycopg.__wrapped__(monkeypatch)


@pytest.fixture(name="mig_dir")
def mig_dir_fixture(tmp_path):
    return _mig_dir.__wrapped__(tmp_path)


@pytest.fixture
def env_no_manifest_gate(monkeypatch, tmp_path):
    """Same as the standard ``env`` fixture but does NOT pre-disable the gate."""
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://u:p@h:5432/db")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("MIGRATION_MANIFEST_REQUIRED", raising=False)
    monkeypatch.delenv("MIGRATION_MANIFEST_AUTOBOOTSTRAP", raising=False)
    am = _load()
    monkeypatch.setattr(am, "DEFAULT_MANIFEST_PATH", tmp_path / "no-manifest.json")


def test_required_default_is_one_hard_fails_when_missing(
    fake_psycopg, env_no_manifest_gate, mig_dir, tmp_path
):
    am = _load()
    rc = am.main(["--migrations-dir", str(mig_dir)])
    assert rc == 1, "missing manifest with required=1 (default) must hard-fail"


def test_autobootstrap_writes_manifest_and_returns_zero(
    fake_psycopg, env_no_manifest_gate, mig_dir, tmp_path, monkeypatch
):
    monkeypatch.setenv("MIGRATION_MANIFEST_AUTOBOOTSTRAP", "1")
    am = _load()
    manifest = tmp_path / "bootstrap.json"
    rc = am.main([
        "--migrations-dir", str(mig_dir),
        "--manifest-path", str(manifest),
    ])
    assert rc == 0
    assert manifest.exists(), "autobootstrap must write the manifest"


def test_required_zero_warns_only(
    fake_psycopg, env_no_manifest_gate, mig_dir, tmp_path, monkeypatch
):
    monkeypatch.setenv("MIGRATION_MANIFEST_REQUIRED", "0")
    am = _load()
    rc = am.main(["--migrations-dir", str(mig_dir)])
    assert rc == 0, "MIGRATION_MANIFEST_REQUIRED=0 (legacy) must not fail"
