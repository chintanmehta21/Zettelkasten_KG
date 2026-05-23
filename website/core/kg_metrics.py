"""LD-4 + Phase 4 observability: Prometheus counters/histograms for the KG read+write paths.

Phase 3 introduces the counters; Phase 4 wires the full ``/api/metrics`` endpoint.
This module can be imported safely even when ``prometheus_client`` is missing —
it degrades to a no-op double so unit tests that don't install ops/requirements
still pass.

Counter inventory:
  - ``cosine_negative_total``   — negative-cosine drift detector (LD-4; alert >2%)
  - ``cosine_pair_total``       — denominator for the drift rate
  - ``kg_edge_drops_total``     — labelled by reason (Phase 4 observability)
  - ``kg_populate_runs_total``  — labelled by outcome (LD-8 state machine)
  - ``kg_populate_duration_seconds`` — populate_kg_for_zettel wall time
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram  # type: ignore[import-untyped]
    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - degrade gracefully
    _PROMETHEUS_AVAILABLE = False

    class _NoOp:
        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            pass

        def observe(self, *args, **kwargs):
            pass

    def Counter(*args, **kwargs):  # type: ignore[no-redef]
        return _NoOp()

    def Histogram(*args, **kwargs):  # type: ignore[no-redef]
        return _NoOp()


# LD-4: alert at >2% to detect Gemini embedding-model drift.
cosine_negative_total = Counter(
    "kg_cosine_negative_total",
    "Count of pairs where raw cosine was negative (drift indicator).",
)

cosine_pair_total = Counter(
    "kg_cosine_pair_total",
    "Total pairs scored by cosine (denominator for drift rate).",
)

kg_edge_drops_total = Counter(
    "kg_edge_drops_total",
    "KG edges dropped from /api/graph payload by reason.",
    ["reason"],  # unresolved_endpoint | cross_workspace | tier_filter
)

kg_populate_runs_total = Counter(
    "kg_populate_runs_total",
    "kg_populate terminal outcomes (LD-8 state machine).",
    ["outcome"],  # succeeded | succeeded_empty | failed_retryable | failed_permanent | skipped_idempotent
)

kg_populate_duration_seconds = Histogram(
    "kg_populate_duration_seconds",
    "Wall time of populate_kg_for_zettel.",
)
