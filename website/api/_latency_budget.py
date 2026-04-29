"""Latency SLO tracker. iter-03 §B (2026-04-29).

Per-request budget for RAG answers — internal/log-only signals, NO behavior
change to the user-facing answer:

  * SOFT (default 5s): WARNING log when crossed mid-pipeline. Tag: `[latency-
    budget] soft crossed at stage=...`. Used to track P95 in monitoring.
  * CRITICAL / HARD (default 20s): CRITICAL log when crossed. Tag: `[latency-
    budget] critical crossed at stage=...`. Used to alert on degraded SLO.

We deliberately do NOT cancel the pipeline on hard crossing — better to ship
a slow correct answer than a polite refusal during the quality-ramp phase.
This decision can be revisited (re-add asyncio.wait_for) once P50 lands
under 10s and we have headroom to enforce.

Knobs:
  RAG_LATENCY_SOFT_S (default 5.0)
  RAG_LATENCY_HARD_S (default 20.0; 0 disables critical signal)
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
    """Set RAG_LATENCY_HARD_S=0 to silence the critical signal."""
    return hard_budget_s() > 0


class LatencyBudget:
    """Logs soft (warning) and critical (hard) budget crossings.

    Lifecycle:
      bgt = LatencyBudget()
      bgt.checkpoint("retriever_done")  # logs once on each threshold cross
      ...
      bgt.finalize("answer_done")        # logs final tier with total elapsed
    """

    def __init__(self, soft_s: float | None = None, hard_s: float | None = None) -> None:
        self._start = time.monotonic()
        self._soft_s = soft_s if soft_s is not None else soft_budget_s()
        self._hard_s = hard_s if hard_s is not None else hard_budget_s()
        self._soft_logged = False
        self._critical_logged = False

    def elapsed_s(self) -> float:
        return time.monotonic() - self._start

    def soft_exceeded(self) -> bool:
        return self.elapsed_s() >= self._soft_s

    def hard_exceeded(self) -> bool:
        return hard_budget_enabled() and self.elapsed_s() >= self._hard_s

    def checkpoint(self, label: str) -> None:
        """Emit warning/critical log on first crossing. Idempotent per tier."""
        elapsed = self.elapsed_s()
        if not self._soft_logged and elapsed >= self._soft_s:
            self._soft_logged = True
            _logger.warning(
                "[latency-budget] soft (%.1fs) crossed at stage=%s elapsed=%.2fs",
                self._soft_s, label, elapsed,
            )
        if (
            hard_budget_enabled()
            and not self._critical_logged
            and elapsed >= self._hard_s
        ):
            self._critical_logged = True
            _logger.critical(
                "[latency-budget] critical (%.1fs) crossed at stage=%s elapsed=%.2fs",
                self._hard_s, label, elapsed,
            )

    def finalize(self, label: str = "request_complete") -> None:
        """Final-tier log. Always emits an info line with total elapsed for
        P50/P95 tracking; escalates to critical if hard never logged but the
        final elapsed crossed (catches stages between checkpoints)."""
        elapsed = self.elapsed_s()
        # Escalate any tiers that the in-flight checkpoints missed.
        self.checkpoint(label)
        _logger.info(
            "[latency-budget] %s total_elapsed=%.2fs soft_crossed=%s critical_crossed=%s",
            label, elapsed, self._soft_logged, self._critical_logged,
        )
