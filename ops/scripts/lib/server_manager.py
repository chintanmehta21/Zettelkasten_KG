"""Manage the FastAPI server process for the iteration loop."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


def start_server(
    port: int = 10000,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.Popen:
    env = {**os.environ, **(env_overrides or {})}
    repo_root = Path(__file__).resolve().parents[3]
    proc = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _wait_for_health(port)
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _wait_for_health(port: int, timeout_sec: int = 30) -> None:
    deadline = time.monotonic() + timeout_sec
    url = f"http://127.0.0.1:{port}/api/health"
    last_exc = None

    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return
        except Exception as exc:
            last_exc = exc
        time.sleep(1.0)

    raise RuntimeError(
        f"Server did not become healthy within {timeout_sec}s: {last_exc}"
    )


def restart_if_code_changed(
    proc: subprocess.Popen | None,
    last_hash: str,
    new_hash: str,
    port: int = 10000,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.Popen, str]:
    if proc is None or last_hash != new_hash:
        if proc is not None:
            stop_server(proc)
        proc = start_server(port=port, env_overrides=env_overrides)
    return proc, new_hash
