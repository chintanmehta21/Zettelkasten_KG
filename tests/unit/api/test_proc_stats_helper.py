"""Iter-03 mem-bounded §2.8: _proc_stats helper reads /proc/self/status,
/proc/loadavg, and /sys/fs/cgroup/memory.{max,current,swap.current,swap.max}
and returns a flat JSON-able dict.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from website.api import _proc_stats


def _write(p: Path, body: str) -> None:
    p.write_text(body, encoding="utf-8")


def test_read_proc_stats_shape(tmp_path: Path):
    # Build a fake /proc + /sys layout
    proc = tmp_path / "proc"
    sys_cg = tmp_path / "cgroup"
    proc.mkdir()
    sys_cg.mkdir()
    _write(proc / "status", "VmRSS:\t  524288 kB\nVmSize:\t1048576 kB\nVmSwap:\t   2048 kB\nThreads:\t   16\n")
    _write(proc / "loadavg", "0.18 0.22 0.30 1/123 4567")
    _write(sys_cg / "memory.max", "1363148800\n")
    _write(sys_cg / "memory.current", "523648000\n")
    _write(sys_cg / "memory.swap.max", "1048576000\n")
    _write(sys_cg / "memory.swap.current", "18432000\n")

    with patch.object(_proc_stats, "_PROC_STATUS", proc / "status"), \
         patch.object(_proc_stats, "_PROC_LOADAVG", proc / "loadavg"), \
         patch.object(_proc_stats, "_CGROUP_MEM_MAX", sys_cg / "memory.max"), \
         patch.object(_proc_stats, "_CGROUP_MEM_CURRENT", sys_cg / "memory.current"), \
         patch.object(_proc_stats, "_CGROUP_SWAP_MAX", sys_cg / "memory.swap.max"), \
         patch.object(_proc_stats, "_CGROUP_SWAP_CURRENT", sys_cg / "memory.swap.current"):
        out = _proc_stats.read_proc_stats()

    assert out["vm_rss_kb"] == 524288
    assert out["vm_size_kb"] == 1048576
    assert out["vm_swap_kb"] == 2048
    assert out["num_threads"] == 16
    assert out["load_1m"] == pytest.approx(0.18)
    assert out["load_5m"] == pytest.approx(0.22)
    assert out["load_15m"] == pytest.approx(0.30)
    assert out["cgroup_mem_max"] == 1363148800
    assert out["cgroup_mem_current"] == 523648000
    assert out["cgroup_swap_max"] == 1048576000
    assert out["cgroup_swap_current"] == 18432000


def test_read_proc_stats_missing_files_yields_none(tmp_path: Path):
    nope = tmp_path / "nope"  # doesn't exist
    with patch.object(_proc_stats, "_PROC_STATUS", nope), \
         patch.object(_proc_stats, "_PROC_LOADAVG", nope), \
         patch.object(_proc_stats, "_CGROUP_MEM_MAX", nope), \
         patch.object(_proc_stats, "_CGROUP_MEM_CURRENT", nope), \
         patch.object(_proc_stats, "_CGROUP_SWAP_MAX", nope), \
         patch.object(_proc_stats, "_CGROUP_SWAP_CURRENT", nope), \
         patch.object(_proc_stats, "_CGROUP_V1_MEM_MAX", nope), \
         patch.object(_proc_stats, "_CGROUP_V1_MEM_CURRENT", nope):
        out = _proc_stats.read_proc_stats()
    assert out["vm_rss_kb"] is None
    assert out["cgroup_mem_max"] is None


def test_log_line_format():
    sample = {
        "vm_rss_kb": 524288, "vm_swap_kb": 18240, "vm_size_kb": 1048576,
        "num_threads": 16,
        "load_1m": 0.18, "load_5m": 0.22, "load_15m": 0.30,
        "cgroup_mem_current": 523648000, "cgroup_mem_max": 1363148800,
        "cgroup_swap_current": 18432000, "cgroup_swap_max": 1048576000,
    }
    line = _proc_stats.format_log_line(sample)
    # Single line, key=value pairs, fields the spec calls out are present
    for key in ("vm_rss_kb", "vm_swap_kb", "load_1m", "cgroup_mem_current",
                "cgroup_mem_max", "cgroup_swap_current", "cgroup_swap_max"):
        assert f"{key}=" in line
    assert "\n" not in line
