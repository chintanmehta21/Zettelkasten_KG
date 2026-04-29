"""Shared RSS / cgroup trace helper. iter-03 §B (2026-04-29).

Used at every pipeline stage boundary to produce a per-module memory
distribution: which stages add what to RSS during a single query.

Output format (single line per call, greppable):
  [mem-trace] <label> rss_kb=<N> [k=v ...]

To compute deltas across a query, grep `[mem-trace]` from container logs
sorted by timestamp; subtract consecutive rss_kb values to attribute the
spike to its origin stage. The previous in-cascade-only tracer was too
narrow — it could only see stage-2 deltas. Pipeline-wide tracing makes
the rewriter / retriever / synth costs visible too.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger("website.mem_trace")


def read_rss_kb() -> int:
    """Return current process RSS in KB. Returns 0 if /proc not readable."""
    try:
        with open("/proc/self/status", "r", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def log_rss(label: str, **fields: object) -> None:
    """Emit one mem-trace line. No-op when /proc not available (Windows)."""
    rss_kb = read_rss_kb()
    if rss_kb == 0:
        return
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    _logger.info("[mem-trace] %s rss_kb=%d %s", label, rss_kb, extra)
