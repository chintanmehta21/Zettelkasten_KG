"""Manage the FastAPI server process for the iteration loop."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


class _ExistingServer:
    """No-op process shim for a server that was already healthy on the port."""

    def terminate(self) -> None:
        return None

    def wait(self, timeout: int | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


def start_server(
    port: int = 10000,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.Popen | _ExistingServer:
    if _is_healthy(port):
        return _ExistingServer()

    env = {**os.environ, **(env_overrides or {})}
    repo_root = Path(__file__).resolve().parents[3]
    proc = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _wait_for_health(port, proc=proc)
    return proc


def stop_server(proc: subprocess.Popen | _ExistingServer) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _is_healthy(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with httpx.Client(timeout=2.0) as client:
            return client.get(url).status_code == 200
    except Exception:
        return False


def _wait_for_health(
    port: int,
    timeout_sec: int = 30,
    proc: subprocess.Popen | None = None,
) -> None:
    deadline = time.monotonic() + timeout_sec
    url = f"http://127.0.0.1:{port}/api/health"
    last_exc = None

    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            output = ""
            if proc.stdout is not None:
                output = proc.stdout.read()[-1000:]
            raise RuntimeError(
                "Server process exited before becoming healthy: "
                f"exit={proc.returncode}, output={output!r}"
            )
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
