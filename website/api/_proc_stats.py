"""Reader for /proc + cgroup memory stats. iter-03 mem-bounded §2.8.

Single-shot helper; no caching. Expected per-call cost ~50-80 µs (six file
reads in /proc and /sys/fs/cgroup, all small). Both the on-demand admin
endpoint and the periodic logger task call ``read_proc_stats``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("website.api._proc_stats")

# Override-able module-level paths so tests can point at a fake /proc layout.
_PROC_STATUS = Path("/proc/self/status")
_PROC_LOADAVG = Path("/proc/loadavg")
_CGROUP_MEM_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_MEM_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_SWAP_MAX = Path("/sys/fs/cgroup/memory.swap.max")
_CGROUP_SWAP_CURRENT = Path("/sys/fs/cgroup/memory.swap.current")

# cgroup v1 fallback paths (used in older kernels / dev environments).
_CGROUP_V1_MEM_MAX = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_CGROUP_V1_MEM_CURRENT = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")


def _read_int(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return None
    if raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_proc_status(path: Path) -> dict[str, int | None]:
    out: dict[str, int | None] = {
        "vm_rss_kb": None, "vm_size_kb": None, "vm_swap_kb": None,
        "num_threads": None,
    }
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return out
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            out["vm_rss_kb"] = int(line.split()[1])
        elif line.startswith("VmSize:"):
            out["vm_size_kb"] = int(line.split()[1])
        elif line.startswith("VmSwap:"):
            out["vm_swap_kb"] = int(line.split()[1])
        elif line.startswith("Threads:"):
            out["num_threads"] = int(line.split()[1])
    return out


def _parse_loadavg(path: Path) -> dict[str, float | None]:
    try:
        parts = path.read_text(encoding="utf-8").split()
    except (OSError, FileNotFoundError):
        return {"load_1m": None, "load_5m": None, "load_15m": None}
    if len(parts) < 3:
        return {"load_1m": None, "load_5m": None, "load_15m": None}
    return {
        "load_1m": float(parts[0]),
        "load_5m": float(parts[1]),
        "load_15m": float(parts[2]),
    }


def _read_cgroup_mem() -> dict[str, int | None]:
    # Prefer cgroup v2; fall through to v1.
    out: dict[str, int | None] = {
        "cgroup_mem_max": _read_int(_CGROUP_MEM_MAX),
        "cgroup_mem_current": _read_int(_CGROUP_MEM_CURRENT),
        "cgroup_swap_max": _read_int(_CGROUP_SWAP_MAX),
        "cgroup_swap_current": _read_int(_CGROUP_SWAP_CURRENT),
    }
    if out["cgroup_mem_max"] is None:
        out["cgroup_mem_max"] = _read_int(_CGROUP_V1_MEM_MAX)
    if out["cgroup_mem_current"] is None:
        out["cgroup_mem_current"] = _read_int(_CGROUP_V1_MEM_CURRENT)
    return out


def read_proc_stats() -> dict[str, Any]:
    """Return a flat dict of all the stats. Missing values are ``None``."""
    out: dict[str, Any] = {}
    out.update(_parse_proc_status(_PROC_STATUS))
    out.update(_parse_loadavg(_PROC_LOADAVG))
    out.update(_read_cgroup_mem())
    return out


def format_log_line(stats: dict[str, Any]) -> str:
    """Render one-line ``[proc_stats] key=val key=val ...`` for the periodic
    logger. Stable field order so log greppers can rely on it."""
    fields = [
        "vm_rss_kb", "vm_swap_kb", "vm_size_kb", "num_threads",
        "load_1m", "load_5m", "load_15m",
        "cgroup_mem_current", "cgroup_mem_max",
        "cgroup_swap_current", "cgroup_swap_max",
    ]
    parts = [f"{k}={stats.get(k)}" for k in fields]
    return "[proc_stats] " + " ".join(parts)
