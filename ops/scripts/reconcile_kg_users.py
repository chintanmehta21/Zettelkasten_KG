"""Reconcile kg_users: dedupe duplicates of Naruto, purge orphans (spec §3.9, plan 2D.1).

Single-tenant allowlist enforcement: only the canonical Naruto + Zoro auth IDs
own data in production. Any other kg_users row, kg_nodes row, or kg_links row
is a leftover from prior auth migrations and must be reassigned (Naruto dupes)
or purged (orphans).

Usage:
  python ops/scripts/reconcile_kg_users.py --audit
  python ops/scripts/reconcile_kg_users.py --dedupe-naruto         # dry-run
  python ops/scripts/reconcile_kg_users.py --dedupe-naruto --apply # writes
  python ops/scripts/reconcile_kg_users.py --purge-orphans --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = ROOT / "ops" / "deploy" / "expected_users.json"

logger = logging.getLogger("reconcile_kg_users")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(conn, allowlist: dict | None = None) -> dict:
    aw = allowlist or load_allowlist()
    canonical = {aw["_canonical_naruto"], aw["_canonical_zoro"]}
    with conn.cursor() as cur:
        cur.execute("SELECT id::text, email FROM kg_users")
        users = list(cur.fetchall())
        cur.execute("SELECT DISTINCT user_id::text FROM kg_nodes")
        node_owners = {r[0] for r in cur.fetchall()}
    duplicate_naruto = [
        list(u) for u in users
        if u[1] and "naruto" in u[1].lower() and u[0] != aw["_canonical_naruto"]
    ]
    orphan_owners = sorted(node_owners - canonical)
    report = {
        "users": [list(u) for u in users],
        "duplicate_naruto": duplicate_naruto,
        "orphan_owners": orphan_owners,
    }
    logger.info(
        "audit: %d users, %d duplicate Naruto, %d orphan owners",
        len(users), len(duplicate_naruto), len(orphan_owners),
    )
    return report


def dedupe_naruto(conn, *, dry_run: bool = True, allowlist: dict | None = None) -> int:
    aw = allowlist or load_allowlist()
    canonical = aw["_canonical_naruto"]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM kg_users WHERE LOWER(email) LIKE 'naruto%%' AND id != %s",
            (canonical,),
        )
        dupes = [r[0] for r in cur.fetchall()]
    if not dupes:
        logger.info("no duplicate Naruto users")
        return 0
    logger.warning("found %d duplicate Naruto users: %s", len(dupes), dupes)
    if dry_run:
        return len(dupes)
    with conn.cursor() as cur:
        for dupe_id in dupes:
            cur.execute("UPDATE kg_nodes SET user_id = %s WHERE user_id = %s", (canonical, dupe_id))
            cur.execute("UPDATE kg_links SET user_id = %s WHERE user_id = %s", (canonical, dupe_id))
            cur.execute(
                "UPDATE kg_node_chunks SET user_id = %s WHERE user_id = %s",
                (canonical, dupe_id),
            )
            cur.execute("DELETE FROM kg_users WHERE id = %s", (dupe_id,))
    conn.commit()
    return len(dupes)


def purge_orphans(conn, *, dry_run: bool = True, allowlist: dict | None = None) -> dict[str, int]:
    aw = allowlist or load_allowlist()
    allowed = tuple(aw["allowed_auth_ids"])
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM kg_nodes WHERE user_id::text NOT IN %s", (allowed,))
        n_nodes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM kg_links WHERE user_id::text NOT IN %s", (allowed,))
        n_links = cur.fetchone()[0]
    counts = {"nodes": n_nodes, "links": n_links}
    if dry_run:
        logger.info("would purge: %s", counts)
        return counts
    with conn.cursor() as cur:
        cur.execute("DELETE FROM kg_nodes WHERE user_id::text NOT IN %s", (allowed,))
        cur.execute("DELETE FROM kg_links WHERE user_id::text NOT IN %s", (allowed,))
    conn.commit()
    logger.info("purged: %s", counts)
    return counts


def _connect():
    import psycopg

    dsn = os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL is required")
    return psycopg.connect(dsn, autocommit=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", action="store_true")
    p.add_argument("--dedupe-naruto", action="store_true")
    p.add_argument("--purge-orphans", action="store_true")
    p.add_argument("--apply", action="store_true", help="commit changes (default is dry-run)")
    args = p.parse_args(argv)

    if not (args.audit or args.dedupe_naruto or args.purge_orphans):
        p.error("specify at least one of --audit / --dedupe-naruto / --purge-orphans")

    conn = _connect()
    try:
        dry = not args.apply
        if args.audit:
            print(json.dumps(audit(conn), indent=2, default=str))
        if args.dedupe_naruto:
            dedupe_naruto(conn, dry_run=dry)
        if args.purge_orphans:
            purge_orphans(conn, dry_run=dry)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
