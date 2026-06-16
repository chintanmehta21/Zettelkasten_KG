"""POSIX RLIMIT_AS jail for the CPU/RAM-bound sync PDF parse.

Bounds a single parse's address space so a malicious/pathological PDF self-OOMs
(raising MemoryError, caught by the caller) instead of OOM-killing the worker on
the 2 GB droplet. Independent of — and never touches — gunicorn workers/timeout.
No-op on non-POSIX so Windows dev + CI behave normally.
"""
from __future__ import annotations

import contextlib
import os

# 384 MB: comfortably above a legitimate 10 MB PDF's parse working set, well
# below the per-worker headroom that keeps 2 gunicorn workers alive on 2 GB.
_DEFAULT_MAX_BYTES = 384 * 1024 * 1024


@contextlib.contextmanager
def parse_resource_limit(*, max_bytes: int = _DEFAULT_MAX_BYTES):
    if os.name != "posix":
        yield
        return
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    cap = max_bytes if hard == resource.RLIM_INFINITY else min(max_bytes, hard)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
