"""Latency SLO tracker. iter-03 §B (2026-04-29).

Per-request budget for RAG answers:
  * SOFT budget (5s): emit a structured warning so we can track P95 over time
    and identify slow stages. NO behavior change. Internal-only.
  * HARD budget (20s): wrap the orchestrator with `asyncio.wait_for`; on
    timeout, log a budget breach and return a degraded answer (no citations,
    polite "couldn't find a confident answer" body). Internal-only — the
    user-facing UX is a normal-looking response, not an error toast or
    explicit "we timed out" message.

Both knobs are env-overridable for tuning during the SLO ramp:
  RAG_LATENCY_SOFT_S (default 5.0)
  RAG_LATENCY_HARD_S (default 20.0)

Set RAG_LATENCY_HARD_S=0 to disable the hard cap entirely (useful for the
eval harness where multi-hop synth queries may exceed 20s legitimately
during quality scoring runs).
"""
from __future__ import annotations

import logging
import os
import time

_logger = logging.getLogger("website.latency_budget")


def soft_budget_s() -> float:
    try:
        return float(os.environ.get("RAG_LATENCY_SOFT_S", "5.0"))
    except ValueError:
        return 5.0


def hard_budget_s() -> float:
    try:
        return float(os.environ.get("RAG_LATENCY_HARD_S", "20.0"))
    except ValueError:
        return 20.0


def hard_budget_enabled() -> bool:
    """Tests / eval may set RAG_LATENCY_HARD_S=0 to disable the hard cap."""
    return hard_budget_s() > 0


class LatencyBudget:
    """Tracks elapsed time and signals soft / hard budget crossings.

    Lifecycle:
      bgt = LatencyBudget()
      bgt.checkpoint("retriever_done")  # logs warning if soft crossed
      ...
      if bgt.hard_exceeded():
          # caller decides whether to abort and return degraded
    """

    def __init__(self, soft_s: float | None = None, hard_s: float | None = None) -> None:
        self._start = time.monotonic()
        self._soft_s = soft_s if soft_s is not None else soft_budget_s()
        self._hard_s = hard_s if hard_s is not None else hard_budget_s()
        self._soft_logged = False

    def elapsed_s(self) -> float:
        return time.monotonic() - self._start

    def soft_exceeded(self) -> bool:
        return self.elapsed_s() >= self._soft_s

    def hard_exceeded(self) -> bool:
        return hard_budget_enabled() and self.elapsed_s() >= self._hard_s

    def checkpoint(self, label: str) -> None:
        """Log a soft warning the first time soft is crossed; metric-only."""
        if self._soft_logged:
            return
        if self.soft_exceeded():
            self._soft_logged = True
            _logger.warning(
                "[latency-budget] soft (%.1fs) crossed at stage=%s elapsed=%.2fs",
                self._soft_s, label, self.elapsed_s(),
            )

    def remaining_s(self) -> float:
        if not hard_budget_enabled():
            return float("inf")
        return max(0.0, self._hard_s - self.elapsed_s())
