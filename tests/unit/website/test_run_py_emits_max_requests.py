"""Iter-05: gunicorn must run with --max-requests 100 and --max-requests-jitter 25
by default. Workflow override at .github/workflows/deploy-droplet.yml MUST match
these values; the prior 5/2 hard-pin was a debug leftover and let drift events
propagate to gunicorn-recycle storms (1 of 2 workers down every 3-7 reqs).
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

import run as run_module


def test_run_py_emits_max_requests_in_argv(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("GUNICORN_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("GUNICORN_MAX_REQUESTS_JITTER", raising=False)
    captured: list[list[str]] = []

    def _fake_call(cmd):
        captured.append(cmd)
        return 0

    with patch.object(run_module.subprocess, "call", _fake_call):
        rc = run_module.main()
    assert rc == 0
    assert len(captured) == 1
    cmd = captured[0]
    assert "--max-requests" in cmd
    idx = cmd.index("--max-requests")
    assert cmd[idx + 1] == "100"
    assert "--max-requests-jitter" in cmd
    jdx = cmd.index("--max-requests-jitter")
    assert cmd[jdx + 1] == "25"


def test_run_py_honors_env_override(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("GUNICORN_MAX_REQUESTS", "250")
    monkeypatch.setenv("GUNICORN_MAX_REQUESTS_JITTER", "50")
    captured: list[list[str]] = []
    with patch.object(run_module.subprocess, "call", lambda c: captured.append(c) or 0):
        run_module.main()
    cmd = captured[0]
    assert cmd[cmd.index("--max-requests") + 1] == "250"
    assert cmd[cmd.index("--max-requests-jitter") + 1] == "50"
