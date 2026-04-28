"""One-shot: mark Zoro's auth.users row as email_confirmed (idempotent).

Spec §3.9 / Plan 2D.2. Run after deploy from the droplet shell:

    python ops/scripts/confirm_zoro_email.py

Idempotent: subsequent runs report ``0 rows updated`` because the WHERE clause
filters on ``email_confirmed_at IS NULL``.
"""
from __future__ import annotations

import logging
import os
import sys

ZORO_AUTH_ID = "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"

logger = logging.getLogger("confirm_zoro_email")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def confirm(conn, *, zoro_id: str = ZORO_AUTH_ID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE auth.users SET email_confirmed_at = NOW() "
            "WHERE id = %s AND email_confirmed_at IS NULL",
            (zoro_id,),
        )
        affected = cur.rowcount
    conn.commit()
    return affected


def main() -> int:
    import psycopg

    dsn = os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is required")
    with psycopg.connect(dsn, autocommit=False) as conn:
        affected = confirm(conn)
    logger.info("Zoro email confirmation: %d row updated", affected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
