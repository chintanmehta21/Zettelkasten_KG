"""2026-05-24 (PR #72): gunicorn defaults raised from iter-05's 100/25 to
1000/200 after live SSE recycle bug (worker recycled mid-/api/rag/sessions/.../messages
stream → "Lost connection mid-answer"). Per Gunicorn maintainer (discussion
#3042) + Modexa prod guide: recycle every 15-60 min, not every few requests.
graceful_timeout also bumped 60→200 so in-flight SSE drains before SIGKILL
(must exceed --timeout=180).
"""
from __future__ import annotations

from unittest.mock import patch


import run as run_module


def test_run_py_emits_max_requests_in_argv(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("GUNICORN_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("GUNICORN_MAX_REQUESTS_JITTER", raising=False)
    monkeypatch.delenv("GUNICORN_GRACEFUL_TIMEOUT", raising=False)
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
    assert cmd[idx + 1] == "1000"
    assert "--max-requests-jitter" in cmd
    jdx = cmd.index("--max-requests-jitter")
    assert cmd[jdx + 1] == "200"
    # graceful_timeout must exceed --timeout=180 so in-flight SSE drains
    # before SIGKILL during a max_requests-triggered worker recycle.
    assert "--graceful-timeout" in cmd
    gdx = cmd.index("--graceful-timeout")
    assert cmd[gdx + 1] == "200"


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
