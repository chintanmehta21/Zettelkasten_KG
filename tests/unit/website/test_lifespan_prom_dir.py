"""Tests for `_ensure_prometheus_multiproc_dir` (PR #89, commit B).

Contract:
  * Creates ``PROMETHEUS_MULTIPROC_DIR`` if missing (the 2026-05-25 Naruto
    failure cause — dir wiped post-container-start).
  * Wipes stale ``*.db`` files left by prior process generations (upstream
    ``prometheus_client`` guidance + Nautobot #4234 inode-exhaustion lesson).
  * NEVER raises — exceptions are swallowed + logged so a broken filesystem
    cannot block FastAPI startup. The per-emit ``safe_metrics`` harness is
    the final fallback.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from website.main import _ensure_prometheus_multiproc_dir


def test_creates_dir_if_missing(tmp_path, monkeypatch):
    target = tmp_path / "prom"
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))
    assert not target.exists()

    _ensure_prometheus_multiproc_dir()

    assert target.is_dir()


def test_idempotent_on_existing_dir(tmp_path, monkeypatch):
    target = tmp_path / "prom"
    target.mkdir()
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))

    # Should not raise on a dir that already exists.
    _ensure_prometheus_multiproc_dir()

    assert target.is_dir()


def test_wipes_stale_db_files(tmp_path, monkeypatch):
    """Per upstream prometheus_client guidance, the multiproc dir MUST be
    wiped between Gunicorn runs — otherwise per-PID files accumulate
    (Nautobot #4234 → inode exhaustion after months)."""
    target = tmp_path / "prom"
    target.mkdir()
    stale1 = target / "counter_15.db"
    stale2 = target / "histogram_42.db"
    keeper = target / "not-a-db.txt"  # must not be wiped
    stale1.write_bytes(b"stale")
    stale2.write_bytes(b"stale")
    keeper.write_bytes(b"keep")

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))
    _ensure_prometheus_multiproc_dir()

    assert not stale1.exists()
    assert not stale2.exists()
    # Non-.db files left alone — only the per-PID metric shards are stale.
    assert keeper.exists()


def test_unset_env_var_is_noop(monkeypatch):
    """If multiprocess mode is disabled, the helper is a no-op."""
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    # Must not raise.
    _ensure_prometheus_multiproc_dir()


def test_swallows_makedirs_failure(monkeypatch, caplog):
    """Lifespan startup must NEVER block on a broken filesystem — the swallow
    is the final guarantee. The per-emit ``safe_metrics`` harness will then
    absorb the resulting `.inc()` failures."""
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", "/some/path")

    def _boom(*_, **__):
        raise PermissionError(13, "no perms")

    monkeypatch.setattr(os, "makedirs", _boom)

    with caplog.at_level(logging.ERROR, logger="website.main"):
        _ensure_prometheus_multiproc_dir()  # must not raise

    assert any("PROMETHEUS_MULTIPROC_DIR setup failed" in r.message
               for r in caplog.records)


def test_unlink_failure_does_not_break_setup(tmp_path, monkeypatch):
    """If one stale file can't be unlinked, the helper still creates the dir
    and continues — the missing wipe is a soft failure."""
    target = tmp_path / "prom"
    target.mkdir()
    stuck = target / "stuck.db"
    stuck.write_bytes(b"stuck")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))

    real_unlink = os.unlink

    def _flaky_unlink(p):
        if str(p).endswith("stuck.db"):
            raise PermissionError(13, "no perms")
        real_unlink(p)

    monkeypatch.setattr(os, "unlink", _flaky_unlink)
    # Must not raise.
    _ensure_prometheus_multiproc_dir()
    assert target.is_dir()


def test_dockerfile_pins_app_var_prom():
    """Pin the new canonical path. If anyone moves it back to /tmp/prom_multiproc
    without also updating the lifespan + safe_metrics rationale comments, this
    test fails and forces a deliberate decision."""
    dockerfile = (
        Path(__file__).resolve().parents[3] / "ops" / "Dockerfile"
    ).read_text(encoding="utf-8")
    assert "PROMETHEUS_MULTIPROC_DIR=/app/var/prom" in dockerfile
    assert "mkdir -p /app/var/prom" in dockerfile
    # The OLD /tmp placement must not creep back without removing the rationale.
    assert "PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc" not in dockerfile
