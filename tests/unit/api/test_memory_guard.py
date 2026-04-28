"""Iter-03 mem-bounded §2.9: soft RSS-guard middleware returns 503 with
Retry-After when VmRSS exceeds the threshold (default 90% of cgroup mem_max).

Threshold detection: cgroup v2 → v1 → /proc/meminfo fallback.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from website.api import _memory_guard


def _app_with_guard(threshold_percent: int | None = None) -> FastAPI:
    app = FastAPI()
    if threshold_percent is not None:
        with patch.dict(__import__("os").environ,
                        {"RAG_MEMORY_GUARD_THRESHOLD_PERCENT": str(threshold_percent)}):
            _memory_guard.install(app)
    else:
        _memory_guard.install(app)

    @app.get("/echo")
    async def _echo():
        return {"ok": True}

    @app.get("/api/health")
    async def _health():
        return {"status": "ok"}

    return app


def test_below_threshold_passes_through(monkeypatch):
    monkeypatch.setattr(_memory_guard, "_detect_mem_max", lambda: 1_000_000_000)
    monkeypatch.setattr(_memory_guard, "_read_vm_rss_bytes", lambda: 100_000_000)
    app = _app_with_guard(threshold_percent=90)
    client = TestClient(app)
    r = client.get("/echo")
    assert r.status_code == 200


def test_above_threshold_returns_503_with_retry_after(monkeypatch):
    monkeypatch.setattr(_memory_guard, "_detect_mem_max", lambda: 1_000_000_000)
    monkeypatch.setattr(_memory_guard, "_read_vm_rss_bytes", lambda: 950_000_000)
    app = _app_with_guard(threshold_percent=90)
    client = TestClient(app)
    r = client.get("/echo")
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"
    body = r.json()
    assert body["error"] == "server_under_memory_pressure"


def test_threshold_zero_disables_guard(monkeypatch):
    monkeypatch.setattr(_memory_guard, "_detect_mem_max", lambda: 1_000_000_000)
    monkeypatch.setattr(_memory_guard, "_read_vm_rss_bytes", lambda: 999_999_999)
    app = _app_with_guard(threshold_percent=0)
    client = TestClient(app)
    r = client.get("/echo")
    assert r.status_code == 200


def test_detect_mem_max_cgroup_v2(tmp_path: Path, monkeypatch):
    p = tmp_path / "memory.max"
    p.write_text("1363148800\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", p)
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", tmp_path / "missing")
    assert _memory_guard._detect_mem_max() == 1363148800


def test_detect_mem_max_falls_back_to_v1(tmp_path: Path, monkeypatch):
    p = tmp_path / "limit_in_bytes"
    p.write_text("1024000000\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", p)
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", tmp_path / "missing")
    assert _memory_guard._detect_mem_max() == 1024000000


def test_detect_mem_max_falls_back_to_proc_meminfo(tmp_path: Path, monkeypatch):
    mi = tmp_path / "meminfo"
    mi.write_text("MemTotal:    1992928 kB\nMemFree:      324616 kB\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", mi)
    assert _memory_guard._detect_mem_max() == 1992928 * 1024


def test_detect_mem_max_handles_max_string(tmp_path: Path, monkeypatch):
    p = tmp_path / "memory.max"
    p.write_text("max\n", encoding="utf-8")
    monkeypatch.setattr(_memory_guard, "_CGROUP_V2_MEM_MAX", p)
    monkeypatch.setattr(_memory_guard, "_CGROUP_V1_MEM_MAX", tmp_path / "missing")
    monkeypatch.setattr(_memory_guard, "_PROC_MEMINFO", tmp_path / "missing")
    # No bound found anywhere → returns 0 → guard self-disables.
    assert _memory_guard._detect_mem_max() == 0
