"""POSIX RLIMIT_AS jail for the CPU/RAM-bound sync PDF parse.

Bounds a single parse's INCREMENTAL address-space growth so a malicious/
pathological PDF self-OOMs (raising MemoryError, caught by the caller) instead
of OOM-killing the worker on the 2 GB droplet. Independent of — and never
touches — gunicorn workers/timeout. No-op on non-POSIX so Windows dev + CI
behave normally.

WHY RELATIVE, NOT ABSOLUTE: RLIMIT_AS caps the WHOLE process. The worker
baseline (interpreter + libs + lazily-loaded model) already consumes a large
address space, so an *absolute* cap (e.g. 384 MB) sits BELOW baseline + a
legitimate complex parse and falsely OOMs real files. We read the current
VmSize and allow `max_bytes` of headroom above it, bounding only what the parse
itself adds.
"""
from __future__ import annotations

import contextlib
import os

# Headroom above the worker's CURRENT address space the parse may consume.
# 512 MB is far above any legitimate 10 MB-PDF parse working set, yet bounds a
# decompression/vector bomb to a single survivable transient on the 2 GB box.
_PARSE_HEADROOM_BYTES = 512 * 1024 * 1024


def _current_address_space() -> int:
    """Process virtual-memory size in bytes from /proc; 0 when unavailable."""
    try:
        with open("/proc/self/statm") as fh:
            pages = int(fh.read().split()[0])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        return 0


@contextlib.contextmanager
def parse_resource_limit(*, max_bytes: int = _PARSE_HEADROOM_BYTES):
    if os.name != "posix":
        yield
        return
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    base = _current_address_space()
    # base + headroom — never below current usage (that would insta-OOM every
    # allocation). Fall back to absolute headroom only if /proc is unreadable.
    target = (base + max_bytes) if base else max_bytes
    cap = target if hard == resource.RLIM_INFINITY else min(target, hard)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
