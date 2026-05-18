"""One-shot v2 backfill: normalize leaked inline markdown headings in every
existing ``content.workspace_zettels.ai_summary`` row.

New rows are born clean — ``website/core/summary_rendering.py`` now runs
``normalize_markdown_headings`` as a deterministic backstop and the structural
transform handles unbalanced inline code. This script repairs rows persisted
*before* that fix so the dataset is consistent at-rest and the client
normalizer becomes pure defense-in-depth rather than load-bearing.

``ai_summary`` is JSON ``{"brief_summary": ..., "detailed_summary": ...}``
(see ``website/core/persist.py::_encode_summary_payload``). Some legacy rows
may store a bare string; the envelope shape is preserved either way — only the
inner summary text is normalized.

Usage:
    python ops/scripts/backfill_normalize_summary_headings.py            # dry-run
    python ops/scripts/backfill_normalize_summary_headings.py --apply    # write
    python ops/scripts/backfill_normalize_summary_headings.py --limit 50 # cap rows

Idempotent: running with ``--apply`` twice changes zero additional rows.

Prerequisites:
    ``SUPABASE_V2_DATABASE_URL`` (or fallback ``SUPABASE_DB_URL``) in the
    environment / ``supabase/.env`` / ``.env``. The DSN is treated as a secret
    and never logged in full.
"""
# ruff: noqa: E402  (sys.path bootstrap must precede website.* imports)
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "supabase" / ".env")
load_dotenv(ROOT / ".env", override=False)

from website.core.supabase_v2.client import get_v2_database_url
from website.features.summarization_engine.post_summary_transformation import (
    normalize_markdown_headings,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("backfill_normalize_headings")

_SELECT = (
    "SELECT id, ai_summary FROM content.workspace_zettels "
    "WHERE ai_summary IS NOT NULL AND ai_summary <> '' AND deleted_at IS NULL "
    "ORDER BY created_at ASC"
)


def _normalize_payload(ai_summary: str) -> str:
    """Return a normalized ai_summary, preserving the original envelope shape.

    JSON envelope -> normalize the ``brief_summary``/``detailed_summary``
    string fields in place. Bare string -> normalize the string directly.
    Unparseable / unexpected shape -> returned unchanged (never corrupt data).
    """

    try:
        decoded = json.loads(ai_summary)
    except (ValueError, TypeError):
        return normalize_markdown_headings(ai_summary)

    if isinstance(decoded, dict) and ("detailed_summary" in decoded or "brief_summary" in decoded):
        updated: dict[str, Any] = dict(decoded)
        for field in ("brief_summary", "detailed_summary"):
            value = updated.get(field)
            if isinstance(value, str) and value:
                updated[field] = normalize_markdown_headings(value)
        # Mirror _encode_summary_payload's serialization exactly so an
        # already-clean row re-encodes byte-identically (true idempotency).
        return json.dumps(updated, ensure_ascii=False)

    if isinstance(decoded, str):
        return normalize_markdown_headings(decoded)

    return ai_summary


def _connect(dsn: str):
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit("psycopg (v3) is required: pip install 'psycopg[binary]'") from exc
    return psycopg.connect(dsn, autocommit=False, connect_timeout=15)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    parser.add_argument("--limit", type=int, default=0, help="Cap rows scanned (0 = all).")
    parser.add_argument("--show", type=int, default=5, help="Sample diffs to print.")
    args = parser.parse_args()

    dsn = get_v2_database_url()
    if not dsn:
        logger.error("SUPABASE_V2_DATABASE_URL is unset; cannot connect.")
        return 2
    logger.info("Connecting to v2 DB (DSN hidden as <private>).")

    conn = _connect(dsn)
    changed: list[tuple[str, str]] = []
    scanned = 0
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT)
            for row_id, ai_summary in cur:
                scanned += 1
                normalized = _normalize_payload(ai_summary)
                if normalized != ai_summary:
                    changed.append((str(row_id), normalized))
                if args.limit and scanned >= args.limit:
                    break

        logger.info("Scanned %d rows; %d need normalization.", scanned, len(changed))
        for row_id, normalized in changed[: max(args.show, 0)]:
            logger.info("  would update %s -> %s", row_id, normalized[:160].replace("\n", "\\n"))

        if not args.apply:
            logger.info("Dry-run only. Re-run with --apply to write %d rows.", len(changed))
            return 0

        if not changed:
            logger.info("Nothing to apply; dataset already clean.")
            return 0

        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE content.workspace_zettels SET ai_summary = %s, updated_at = now() WHERE id = %s",
                [(normalized, row_id) for row_id, normalized in changed],
            )
        conn.commit()
        logger.info("Applied %d updates.", len(changed))
        return 0
    except Exception:
        conn.rollback()
        logger.exception("Backfill failed; transaction rolled back. No rows changed.")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
