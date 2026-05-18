# ruff: noqa: E402  (sys.path bootstrap must precede website.* imports)
"""DESTRUCTIVE: hard-DELETE unrecoverable ``content.workspace_zettels`` rows
(buckets malformed / degenerate / legacy_version) that the latest engine never
properly ingested. Reserved concurrent-PR Zettels (kasten skeleton URLs) and
repairable ``markdown_leak`` rows are NEVER deleted.

Safety model (all enforced, no exceptions):
  * Dry-run by default. ``--apply`` required to delete.
  * Candidate set is RE-DERIVED LIVE here using the audit module's classifier
    + keep-list — never trusts a stale id file. The keep-list is re-checked at
    delete time so a Zettel the other PR added since the audit is still spared.
  * ``--expect N`` is mandatory with ``--apply``: if the live candidate count
    != N the script ABORTS without deleting (guards against drift).
  * A full JSON backup of every row to be deleted (id, workspace_id,
    canonical_zettel_id, ai_summary, engine_version, normalized_url,
    created_at) is written and flushed BEFORE any DELETE. Hard-delete is
    irreversible at the DB; the backup is the only recovery path.
  * Single transaction: backup -> DELETE -> verify rowcount == expected ->
    COMMIT. Any error rolls back; zero rows changed.
  * FK children (workspace_chunk_membership, rag.kasten_zettels) are ON DELETE
    CASCADE; pipeline_run_items is SET NULL. Verified — no RESTRICT blocker.

Usage:
    # dry-run (read-only; writes a preview backup, no deletes)
    python ops/scripts/purge_dirty_zettels.py \
        --keep-md ../../docs/kasten_skeletons/kasten1.md ../../docs/kasten_skeletons/kasten2.md

    # destructive (requires exact expected count)
    python ops/scripts/purge_dirty_zettels.py --keep-md ... --apply --expect 326

Requires ``SUPABASE_V2_DATABASE_URL``. DSN never logged.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "supabase" / ".env")
load_dotenv(ROOT / ".env", override=False)

import importlib.util

from website.core.supabase_v2.client import get_v2_database_url

_audit_spec = importlib.util.spec_from_file_location(
    "audit_zettel_ingest_quality", Path(__file__).with_name("audit_zettel_ingest_quality.py")
)
assert _audit_spec and _audit_spec.loader
_audit = importlib.util.module_from_spec(_audit_spec)
_audit_spec.loader.exec_module(_audit)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("purge_dirty_zettels")


def _connect(dsn: str, *, autocommit: bool):
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit("psycopg (v3) is required: pip install 'psycopg[binary]'") from exc
    return psycopg.connect(dsn, autocommit=autocommit, connect_timeout=15)


def _derive_candidates(cur, keep: set[str]) -> list[dict]:
    cur.execute(_audit._SELECT)
    out: list[dict] = []
    for (
        row_id,
        ws_id,
        canon_id,
        ai_summary,
        engine_version,
        added_via,
        created_at,
        normalized_url,
    ) in cur.fetchall():
        bucket = _audit.classify(ai_summary, engine_version)
        if bucket not in _audit.PURGEABLE_BUCKETS:
            continue  # clean / markdown_leak(repairable) are never purged
        if _audit._is_reserved(normalized_url, keep):
            continue  # concurrent-PR Zettel — always kept
        out.append(
            {
                "id": str(row_id),
                "workspace_id": str(ws_id),
                "canonical_zettel_id": str(canon_id),
                "bucket": bucket,
                "ai_summary": ai_summary,
                "ai_summary_engine_version": engine_version,
                "normalized_url": normalized_url,
                "created_at": created_at.isoformat() if created_at else None,
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-md", nargs="+", required=True, help="Concurrent-PR skeleton .md files.")
    parser.add_argument("--apply", action="store_true", help="Actually DELETE (default: dry-run).")
    parser.add_argument("--expect", type=int, help="Required with --apply: exact candidate count.")
    parser.add_argument("--backup-dir", default="purge_backups", help="Where to write the backup JSON.")
    args = parser.parse_args()

    dsn = get_v2_database_url()
    if not dsn:
        logger.error("SUPABASE_V2_DATABASE_URL is unset; aborting.")
        return 2

    keep = _audit.build_keep_set([Path(p) for p in args.keep_md])
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"purged_zettels_{ts}.json"

    conn = _connect(dsn, autocommit=not args.apply)
    try:
        with conn.cursor() as cur:
            candidates = _derive_candidates(cur, keep)
            n = len(candidates)
            from collections import Counter

            by_bucket = Counter(c["bucket"] for c in candidates)
            logger.info("Live purge candidates: %d  %s", n, dict(by_bucket))

            if not args.apply:
                backup_path.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
                logger.info("DRY-RUN. Preview backup -> %s. Re-run with --apply --expect %d.",
                            backup_path, n)
                return 0

            if args.expect is None or args.expect != n:
                logger.error(
                    "ABORT: --expect %s != live candidate count %d (drift). No rows deleted.",
                    args.expect, n,
                )
                conn.rollback()
                return 3
            if n == 0:
                logger.info("Nothing to purge.")
                conn.rollback()
                return 0

            # Backup BEFORE delete — the only recovery path for a hard delete.
            backup_path.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
            with backup_path.open("rb") as fh:
                import os

                os.fsync(fh.fileno()) if hasattr(os, "fsync") else None
            logger.info("Backup of %d rows written -> %s", n, backup_path)

            ids = [c["id"] for c in candidates]
            cur.execute(
                "DELETE FROM content.workspace_zettels WHERE id = ANY(%s::uuid[])", (ids,)
            )
            deleted = cur.rowcount
            if deleted != n:
                logger.error("ABORT: DELETE affected %d != expected %d. Rolling back.", deleted, n)
                conn.rollback()
                return 4
            conn.commit()
            logger.info("Hard-deleted %d workspace_zettels. Backup: %s", deleted, backup_path)
            return 0
    except Exception:
        conn.rollback()
        logger.exception("Purge failed; rolled back. No rows deleted.")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
