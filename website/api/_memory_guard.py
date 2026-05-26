"""Soft RSS-guard middleware. iter-03 mem-bounded §2.9.

Reads /proc/self/status before dispatching every request. When VmRSS exceeds
``RAG_MEMORY_GUARD_THRESHOLD_PERCENT`` of the cgroup memory limit, returns
503 with Retry-After=5 instead of letting the kernel cgroup-OOM the worker
mid-request (which would surface as a 502 from Caddy).

Path exemptions: /api/health, /api/admin/*, /favicon.*.
These probes/ops paths must always work, even under pressure.

Set RAG_MEMORY_GUARD_THRESHOLD_PERCENT=0 to disable entirely (tests/dev).

Pure-ASGI MemoryGuardMiddleware replaces the prior BaseHTTPMiddleware
decorator in PR #115 (Scope C) per encode/starlette#1438.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI

logger = logging.getLogger("website.api._memory_guard")

_ASGISend = Callable[[dict], Awaitable[None]]
_ASGIReceive = Callable[[], Awaitable[dict]]
_ASGIApp = Callable[[dict, _ASGIReceive, _ASGISend], Awaitable[None]]

_CGROUP_V2_MEM_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_MEM_MAX = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_STATUS = Path("/proc/self/status")

_EXEMPT_PREFIXES = (
    "/api/health",
    "/api/admin/",
    "/favicon.ico",
    "/favicon.svg",
)

_DEFAULT_THRESHOLD_PERCENT = 90


def _detect_mem_max() -> int:
    """Return the cgroup memory limit in bytes, falling back to MemTotal."""
    for p in (_CGROUP_V2_MEM_MAX, _CGROUP_V1_MEM_MAX):
        try:
            raw = p.read_text(encoding="utf-8").strip()
        except (OSError, FileNotFoundError):
            continue
        if raw == "max":
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    try:
        for line in _PROC_MEMINFO.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, FileNotFoundError):
        pass
    return 0


def _read_vm_rss_bytes() -> int:
    try:
        for line in _PROC_STATUS.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, FileNotFoundError):
        pass
    return 0


def _threshold_percent() -> int:
    raw = os.environ.get("RAG_MEMORY_GUARD_THRESHOLD_PERCENT")
    if raw is None:
        return _DEFAULT_THRESHOLD_PERCENT
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD_PERCENT


class MemoryGuardMiddleware:
    """Pure-ASGI RSS-guard. Pre-dispatch RSS check; short-circuits with a
    synthetic 503 + Retry-After: 5 if VmRSS / cgroup-mem-max exceeds the
    configured percentage. Exempt prefixes pass through unconditionally.
    """

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: _ASGIReceive, send: _ASGISend
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        threshold = _threshold_percent()
        if threshold <= 0:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        mem_max = _detect_mem_max()
        if mem_max <= 0:
            await self.app(scope, receive, send)
            return
        rss = _read_vm_rss_bytes()
        if rss <= 0:
            await self.app(scope, receive, send)
            return
        if rss * 100 >= mem_max * threshold:
            logger.warning(
                "memory pressure shedding: rss=%d mem_max=%d threshold_pct=%d path=%s",
                rss, mem_max, threshold, path,
            )
            body = json.dumps(
                {"error": "server_under_memory_pressure", "retry_after_seconds": 5}
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("latin-1")),
                        (b"retry-after", b"5"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def install(app: FastAPI) -> None:
    """Register MemoryGuardMiddleware on ``app``. Kept as a thin wrapper so
    callers don't have to know the middleware class — but new code should
    prefer ``app.add_middleware(MemoryGuardMiddleware)`` directly.
    """
    app.add_middleware(MemoryGuardMiddleware)
