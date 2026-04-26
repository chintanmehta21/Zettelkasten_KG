"""Nightly recompute of kg_usage_edges from supported QA turns.

Plan: docs/superpowers/plans/2026-04-26-rag-improvements-iter-01-02.md (Task 22).

Source-table choice
-------------------
The plan's pseudocode references a hypothetical ``rag_turns`` table, but the
production schema does not include one. The candidate tables that record the
verdict + retrieved-node-id audit trail required for co-citation edges are:

  1. ``chat_messages`` (supabase/website/rag_chatbot/004_chat_sessions.sql)
     - Columns: ``user_id``, ``role``, ``critic_verdict``, ``query_class``,
       ``retrieved_node_ids[]``, ``created_at``. RLS + service-role policy.
  2. ``rag_messages`` / ``rag_answers`` — no such tables exist (greppable
     proof: only ``chat_messages`` matches both ``verdict`` + ``retrieved_*``).

We therefore read **assistant** rows from ``chat_messages`` whose
``critic_verdict`` is in the supported set. ``critic_verdict`` matches the
exact verdict CHECK constraint on ``kg_usage_edges`` (``supported``,
``retried_supported``).

Co-citation model
-----------------
For every supported assistant turn we materialize one row per ordered pair
``(source_node_id, target_node_id)`` of distinct retrieved nodes (with
``source_node_id < target_node_id`` so the same edge is never double-counted
within one turn). ``delta`` is 1.0 for ``supported`` and 0.5 for
``retried_supported`` per the plan's ``VERDICT_DELTA`` table.

Idempotency
-----------
The window lower-bound is the most recent successful run's ``ran_at`` (per
optional ``--user-id`` scope is ignored for the run-bound — runs are
job-wide). The upper bound is "now". Re-running over the same window
therefore inserts no duplicate rows because no source ``chat_messages`` rows
fall inside the bounded window twice. ``--window-hours`` provides a
fallback floor when no prior successful run exists.

Run:
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
        python ops/scripts/recompute_usage_edges.py [--window-hours 24] \
        [--dry-run] [--user-id <uuid>]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Iterable, Sequence

# Project root for dotenv
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - optional in test env
    from dotenv import load_dotenv

    load_dotenv(ROOT / "supabase" / ".env")
except Exception:  # pragma: no cover
    pass

from supabase import create_client  # noqa: E402

JOB_NAME = "recompute_usage_edges"
DEFAULT_WINDOW_HOURS = 24
SUPPORTED_VERDICTS = ("supported", "retried_supported")
VERDICT_DELTA = {"supported": 1.0, "retried_supported": 0.5}

logger = logging.getLogger("recompute_usage_edges")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help=(
            "Fallback lookback window when no prior successful run exists "
            f"(default: {DEFAULT_WINDOW_HOURS})."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute edges + log counts but skip inserts and MV refresh.",
    )
    p.add_argument(
        "--user-id",
        default=None,
        help="If set, scope the source-message scan to a single kg_users.id.",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def _last_run_cutoff(sb, fallback: datetime) -> datetime:
    """Return the lower-bound timestamp for the source-message window.

    Uses the most-recent ``recompute_runs`` row with ``status='ok'`` and
    ``job_name=JOB_NAME``. Falls back to ``fallback`` when no such row
    exists. Any error reading the table is non-fatal — we degrade to
    ``fallback`` so the producer still makes forward progress.
    """
    try:
        resp = (
            sb.table("recompute_runs")
            .select("ran_at, status, job_name")
            .eq("job_name", JOB_NAME)
            .eq("status", "ok")
            .execute()
        )
        rows = resp.data or []
    except Exception:
        rows = []
    if not rows:
        return fallback
    # Sort client-side; the fake supabase used in tests doesn't honour order().
    latest = max((r.get("ran_at") or "" for r in rows), default="")
    if not latest:
        return fallback
    try:
        if latest.endswith("Z"):
            latest = latest[:-1] + "+00:00"
        return datetime.fromisoformat(latest)
    except ValueError:
        return fallback


def _co_citation_rows(messages: Iterable[dict]) -> list[dict]:
    """Materialize one ``kg_usage_edges`` row per ordered co-cited pair."""
    out: list[dict] = []
    for msg in messages:
        verdict = msg.get("critic_verdict")
        if verdict not in VERDICT_DELTA:
            continue
        node_ids = list(dict.fromkeys(msg.get("retrieved_node_ids") or []))
        if len(node_ids) < 2:
            continue
        delta = VERDICT_DELTA[verdict]
        for src, tgt in combinations(sorted(node_ids), 2):
            out.append(
                {
                    "user_id": msg["user_id"],
                    "source_node_id": src,
                    "target_node_id": tgt,
                    "query_class": msg.get("query_class") or "lookup",
                    "verdict": verdict,
                    "delta": delta,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        return 2

    sb = create_client(url, key)

    fallback_cutoff = datetime.now(timezone.utc) - timedelta(
        hours=max(1, args.window_hours)
    )
    lower = _last_run_cutoff(sb, fallback_cutoff)
    upper = datetime.now(timezone.utc)

    rows_inserted = 0
    rows_aggregated = 0
    status = "ok"
    error_msg: str | None = None

    try:
        q = (
            sb.table("chat_messages")
            .select(
                "user_id, role, critic_verdict, query_class, "
                "retrieved_node_ids, created_at"
            )
            .gte("created_at", lower.isoformat())
            .lt("created_at", upper.isoformat())
            .in_("critic_verdict", list(SUPPORTED_VERDICTS))
            .eq("role", "assistant")
        )
        if args.user_id:
            q = q.eq("user_id", args.user_id)
        messages = q.execute().data or []
        logger.info(
            "fetched %d supported assistant messages (window %s -> %s)",
            len(messages),
            lower.isoformat(),
            upper.isoformat(),
        )

        rows = _co_citation_rows(messages)
        logger.info("computed %d co-citation edge rows", len(rows))

        if rows and not args.dry_run:
            # Bulk insert. supabase-py chunks internally for very large
            # payloads but we keep the call simple — typical nightly loads
            # are well under 10k rows.
            sb.table("kg_usage_edges").insert(rows).execute()
            rows_inserted = len(rows)

            sb.rpc("kg_refresh_usage_edges_agg").execute()
            rows_aggregated = len(rows)
        elif args.dry_run:
            logger.info("dry-run: skipping insert + MV refresh")
    except Exception as exc:
        status = "error"
        error_msg = f"{exc}\n{traceback.format_exc()}"
        logger.error("recompute failed: %s", exc)

    # Always record the run, even on dry-run, so operators can see history.
    try:
        sb.table("recompute_runs").insert(
            {
                "job_name": JOB_NAME,
                "rows_inserted": rows_inserted,
                "rows_aggregated": rows_aggregated,
                "status": status,
                "error_message": error_msg,
            }
        ).execute()
    except Exception:
        # If we can't even record the run, surface the failure but don't
        # mask the original status.
        logger.exception("failed to write recompute_runs row")
        if status == "ok":
            status = "error"

    return 0 if status == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
