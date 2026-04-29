"""Aggressive memory release helper. iter-03 §B (2026-04-29).

Python's `gc.collect()` only frees Python-managed heap. The bulk of per-query
memory residual on this app lives in C-extension allocations: ONNX runtime
internal buffers, Gemini/Supabase httpx response buffers, NumPy arrays
allocated in C, glibc malloc heap. Even after their Python references drop,
glibc keeps freed pages in its arena freelist and RSS stays high.

`malloc_trim(0)` is a glibc syscall (`man malloc_trim`) that walks the malloc
heap and returns free pages to the kernel via `madvise(MADV_DONTNEED)`.
Cost: 5-15ms on a typical loaded process. Zero behavior impact — only
releases memory that's already free from the application's perspective.

Used at two boundaries:
  1. After stage-2 rerank completes (the largest in-flight allocator)
  2. After every FastAPI request finishes (catches Gemini/Supabase residual)

On non-glibc systems (e.g. Alpine/musl, Windows test runs) the syscall is
absent; we fall back to gc-only and never raise.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import gc
import logging

_logger = logging.getLogger(__name__)

_libc: ctypes.CDLL | None
try:
    _libc_path = ctypes.util.find_library("c")
    if _libc_path is None:
        # find_library returns None on some systems but the SONAME exists.
        _libc = ctypes.CDLL("libc.so.6")
    else:
        _libc = ctypes.CDLL(_libc_path)
    if not hasattr(_libc, "malloc_trim"):
        _libc = None
except OSError:
    _libc = None


def aggressive_release() -> None:
    """Run a full Python gc + glibc heap trim. Safe on every platform."""
    gc.collect()
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except Exception:  # noqa: BLE001 - never let release break a request
            pass


def malloc_trim_available() -> bool:
    """Used in tests / metrics to verify the platform supports the trim path."""
    return _libc is not None
