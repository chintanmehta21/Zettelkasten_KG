# ruff: noqa: E402  (sys.path bootstrap must precede website.* imports)
"""DESTRUCTIVE: hard-DELETE every ``content.workspace_zettels`` row owned by an
automated end-to-end test profile (``core.profiles.email LIKE 'e2e-%@test.com'``).

These are throwaway fixtures minted per e2e run; they inflate the dataset and
are not real user data. Real users (Naruto, Zoro, anyone without an
``e2e-…@test.com`` email) are never touched. Rows are matched by owner email
only — narrow and explicit.

Same safety model as purge_dirty_zettels: dry-run default; ``--apply`` +
mandatory ``--expect N`` (abort on drift); full fsynced JSON backup before any
DELETE; single transaction; rowcount verified == expected or rollback. FK
children (workspace_chunk_membership, rag.kasten_zettels) cascade; pipeline
items SET NULL — verified, no RESTRICT blocker. Profiles / auth.users are NOT
deleted (only the zettel rows, per the operator's "delete all rows" scope).

Usage:
    python ops/scripts/purge_e2e_test_zettels.py                  # dry-run
    python ops/scripts/purge_e2e_test_zettels.py --apply --expect 281

Requires ``SUPABASE_V2_DATABASE_URL``. DSN never logged.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "supabase" / ".env")
load_dotenv(ROOT / ".env", override=False)

from website.core.supabase_v2.client import get_v2_database_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("purge_e2e_test_zettels")

_EMAIL_PATTERN = "e2e-%@test.com"

_SELECT = """
SELECT wz.id, wz.workspace_id, wz.canonical_zettel_id, p.email, wz.deleted_at, wz.created_at
FROM content.workspace_zettels wz
JOIN core.workspaces w ON w.id = wz.workspace_id
JOIN core.profiles p ON p.id = w.owner_profile_id
WHERE p.email LIKE %s
ORDER BY wz.created_at ASC
"""


def _connect(dsn: str, *, autocommit: bool):
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit("psycopg (v3) is required: pip install 'psycopg[binary]'") from exc
    return psycopg.connect(dsn, autocommit=autocommit, connect_timeout=15)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually DELETE (default: dry-run).")
    parser.add_argument("--expect", type=int, help="Required with --apply: exact row count.")
    parser.add_argument("--backup-dir", default="purge_backups", help="Backup JSON directory.")
    args = parser.parse_args()

    dsn = get_v2_database_url()
    if not dsn:
        logger.error("SUPABASE_V2_DATABASE_URL is unset; aborting.")
        return 2

    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"purged_e2e_zettels_{ts}.json"

    conn = _connect(dsn, autocommit=not args.apply)
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT, (_EMAIL_PATTERN,))
            rows = [
                {
                    "id": str(r[0]),
                    "workspace_id": str(r[1]),
                    "canonical_zettel_id": str(r[2]),
                    "owner_email": r[3],
                    "deleted_at": r[4].isoformat() if r[4] else None,
                    "created_at": r[5].isoformat() if r[5] else None,
                }
                for r in cur.fetchall()
            ]
            n = len(rows)
            live = sum(1 for r in rows if r["deleted_at"] is None)
            logger.info("e2e rows matched: %d (live=%d, soft-deleted=%d)", n, live, n - live)

            if not args.apply:
                backup_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
                logger.info("DRY-RUN. Preview -> %s. Re-run with --apply --expect %d.", backup_path, n)
                return 0

            if args.expect is None or args.expect != n:
                logger.error("ABORT: --expect %s != matched %d (drift). No deletes.", args.expect, n)
                conn.rollback()
                return 3
            if n == 0:
                logger.info("Nothing to delete.")
                conn.rollback()
                return 0

            with backup_path.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps(rows, indent=2))
                fh.flush()
                os.fsync(fh.fileno())
            logger.info("Backup of %d rows written + fsynced -> %s", n, backup_path)

            ids = [r["id"] for r in rows]
            cur.execute(
                "DELETE FROM content.workspace_zettels WHERE id = ANY(%s::uuid[])", (ids,)
            )
            deleted = cur.rowcount
            if deleted != n:
                logger.error("ABORT: DELETE affected %d != expected %d. Rolling back.", deleted, n)
                conn.rollback()
                return 4
            conn.commit()
            logger.info("Hard-deleted %d e2e workspace_zettels. Backup: %s", deleted, backup_path)
            return 0
    except Exception:
        conn.rollback()
        logger.exception("e2e purge failed; rolled back. No rows deleted.")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
