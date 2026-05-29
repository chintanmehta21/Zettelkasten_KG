"""Single point of truth for "should this row count in corpus-mean aggregates?"

Added 2026-05-30 (Fix #2.1) as part of the Instructor-style validation retry
work. When ``ConsolidatedEvaluator`` synthesizes neutral defaults for required
fields the judge omitted, the row is FLAGGED via
``evaluator_metadata.backfilled_fields`` and a ``backfilled=1`` column lands
in ``manifest_results.csv``. Downstream aggregators (`04_compute_composite`,
`06_run_stats`, `07_diff_runs`, `11_select_best`, ...) MUST exclude these
rows from corpus-mean stats — otherwise the synthesized 0.5 scores silently
bias the judge mean.

To prevent the "developer adds new aggregator and forgets the filter" risk,
every aggregator imports from here:

    from docs.zettel_eval_v1.scripts.lib.aggregable import aggregable_rows

    means = compute_means(aggregable_rows(rows))

Backfilled rows REMAIN in manifest_results.csv (with ``backfilled=1``) so
analysts can still inspect them — they just don't count toward means.
"""
from __future__ import annotations

from typing import Iterable


def is_aggregable_row(row: dict) -> bool:
    """Return True iff the row should count toward corpus-mean aggregates.

    Currently the only exclusion criterion is the ``backfilled`` flag set by
    ``04_compute_composite._row_for_zettel`` when the evaluator synthesized
    defaults for fields the judge omitted. The check tolerates the column
    being absent entirely (legacy CSVs from before Fix #2.1) — treats those
    rows as aggregable, which matches pre-2026-05-30 behavior.

    CRITICAL: this is called from BOTH in-memory pipelines (where ``backfilled``
    arrives as Python ``int``: ``0`` or ``1``) AND from CSV-read pipelines
    (``csv.DictReader`` returns strings: ``"0"`` or ``"1"``). A naive
    ``not row.get("backfilled")`` works for ints but fails for strings because
    ``not "0"`` is ``False`` (non-empty string is truthy). We normalize via
    ``int(...)`` so the check is consistent across both callers.
    """
    val = row.get("backfilled")
    if val is None or val == "":
        return True  # absent column (legacy CSV) or empty → aggregable
    try:
        return int(val) == 0
    except (TypeError, ValueError):
        # Unparseable value (e.g. a future "true"/"false" writer) — be
        # conservative and count the row rather than silently drop it.
        return True


def aggregable_rows(rows: Iterable[dict]) -> list[dict]:
    """Filter an iterable of rows down to those that should count in
    corpus-mean aggregates. Convenience wrapper over ``is_aggregable_row``."""
    return [r for r in rows if is_aggregable_row(r)]


def excluded_count(rows: Iterable[dict]) -> int:
    """How many rows in the input were excluded? Useful for surface-level
    'N=X (Y backfilled-excluded)' annotations in reports."""
    return sum(1 for r in rows if not is_aggregable_row(r))
