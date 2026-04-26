"""Apply pending Supabase migrations from supabase/website/kg_public/migrations.

D-1 (KAS-11): the iter-01 manual_review.md RCA showed that several committed
migrations (notably ``2026-04-26_fix_rag_bulk_add_to_sandbox.sql``) were never
applied to prod Supabase, leaving the website RAG pipeline broken (Kasten chat
returns "no Zettels in selected scope" even for fully-populated Kastens). This
script makes deploys auto-apply every pending migration in lexical order,
exactly once, atomically per file, with a SHA-256 audit trail.

Usage::

    SUPABASE_DB_URL=postgresql://... python ops/scripts/apply_migrations.py
    # or
    SUPABASE_URL=https://<ref>.supabase.co \\
    SUPABASE_SERVICE_ROLE_KEY=... \\
        python ops/scripts/apply_migrations.py [--dry-run]
        [--migrations-dir DIR] [--rollback NAME]

Behaviour summary
-----------------
* Connects to Postgres via ``SUPABASE_DB_URL`` if set, else assembles the DSN
  from ``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY`` (Supabase pooler /
  ``db.<ref>.supabase.co:5432`` with ``user=postgres``).
* Acquires a session-level Postgres advisory lock so two simultaneous deploys
  cannot race on the same migration.
* Self-bootstraps ``_migrations_applied`` (the table is also committed as a
  regular migration so a fresh DB rebuilt from ``schema.sql`` matches).
* For each ``.sql`` file in lexical order: skip if checksum matches an already-
  applied row; HARD FAIL on checksum mismatch (someone edited an applied
  migration); otherwise run the SQL inside a transaction and INSERT the audit
  row, rolling back on any error.
* ``--dry-run`` parses + lists the plan without writing.
* ``--rollback NAME`` runs ``<name>.down.sql`` (must exist) inside a
  transaction and DELETEs the audit row.

Exit codes
----------
``0`` success, ``1`` migration error / checksum mismatch / SQL failure,
``2`` configuration error (missing env vars, bad args).
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Sequence
from urllib.parse import quote_plus, urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - optional in test env
    from dotenv import load_dotenv

    load_dotenv(ROOT / "supabase" / ".env")
    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass

DEFAULT_MIGRATIONS_DIR = (
    ROOT / "supabase" / "website" / "kg_public" / "migrations"
)

# Stable lock key derived from the literal string 'apply_migrations' so two
# concurrent invocations serialize on Postgres rather than racing.
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"apply_migrations").digest()[:8],
    "big",
    signed=True,
)

logger = logging.getLogger("apply_migrations")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


# ---------------------------------------------------------------------------
# DSN assembly
# ---------------------------------------------------------------------------
def _build_dsn() -> str:
    """Return the Postgres DSN from ``SUPABASE_DB_URL``.

    Auto-deriving from ``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY`` is
    NOT supported: the service-role JWT is not the postgres direct-connect
    password. The DB password is set per project in Supabase Studio and
    must be supplied via ``SUPABASE_DB_URL`` (preferably the IPv4 pooler
    endpoint, since ``db.<ref>.supabase.co`` is IPv6-only and may not
    resolve from IPv4-only droplet networks).

    Format (IPv4 pooler):
        postgresql://postgres.<ref>:<DB_PASSWORD>@aws-0-<region>.pooler.supabase.com:6543/postgres
    """
    direct = os.environ.get("SUPABASE_DB_URL")
    if direct:
        return direct

    raise RuntimeError(
        "SUPABASE_DB_URL must be set. Get the IPv4 pooler connection "
        "string from Supabase Studio > Project Settings > Database > "
        "Connection string (Transaction or Session pooler) and register "
        "it as a GitHub Actions secret named SUPABASE_DB_URL. "
        "Note: SUPABASE_SERVICE_ROLE_KEY is NOT the postgres password."
    )


def _redact_dsn(dsn: str) -> str:
    """Return DSN with password masked, for safe logging."""
    try:
        p = urlparse(dsn)
        if p.password:
            netloc = f"{p.username}:***@{p.hostname}"
            if p.port:
                netloc += f":{p.port}"
            return dsn.replace(p.netloc, netloc, 1)
    except Exception:
        pass
    return "<redacted>"


# ---------------------------------------------------------------------------
# Migration discovery + checksum
# ---------------------------------------------------------------------------
def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _list_migrations(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise RuntimeError(f"Migrations directory not found: {directory}")
    return sorted(p for p in directory.glob("*.sql") if not p.name.endswith(".down.sql"))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _ensure_table(conn) -> None:
    """Self-bootstrap ``_migrations_applied`` so a fresh DB just works."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations_applied (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                checksum TEXT NOT NULL,
                applied_by TEXT
            )
            """
        )
    conn.commit()


def _applied_index(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT name, checksum FROM _migrations_applied")
        return {row[0]: row[1] for row in cur.fetchall()}


def _acquire_lock(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
    conn.commit()


def _release_lock(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        conn.commit()
    except Exception:  # pragma: no cover - best effort
        logger.exception("failed to release advisory lock")


# ---------------------------------------------------------------------------
# Apply / rollback
# ---------------------------------------------------------------------------
def _apply_one(conn, path: Path, sql: str, checksum: str, hostname: str) -> float:
    """Run one migration file inside a single transaction. Returns elapsed ms."""
    t0 = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO _migrations_applied (name, checksum, applied_by) "
                "VALUES (%s, %s, %s)",
                (path.name, checksum, hostname),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return (time.perf_counter() - t0) * 1000.0


def _run_rollback(conn, directory: Path, name: str, hostname: str) -> int:
    down = directory / f"{name}.down.sql"
    if not down.exists():
        logger.error(
            "rollback failed: companion file not found: %s. Manual rollback "
            "required — write a <name>.down.sql alongside the original.",
            down,
        )
        return 1
    sql = down.read_text(encoding="utf-8")
    logger.warning(
        "[migration] ROLLBACK %s — running %s and removing audit row "
        "(operator=%s)",
        name,
        down.name,
        hostname,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("DELETE FROM _migrations_applied WHERE name = %s", (name,))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("rollback failed: %s", exc)
        return 1
    logger.info("[migration] rolled back %s", name)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Plan only; never write.")
    p.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help=f"Directory of *.sql migrations (default: {DEFAULT_MIGRATIONS_DIR}).",
    )
    p.add_argument(
        "--rollback",
        default=None,
        help="Name of an applied migration to roll back (requires <name>.down.sql).",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        dsn = _build_dsn()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 2

    try:
        import psycopg  # type: ignore
    except ImportError:
        logger.error(
            "psycopg (v3) is required: pip install 'psycopg[binary]'"
        )
        return 2

    directory = Path(args.migrations_dir).resolve()
    hostname = socket.gethostname()

    logger.info("[migration] connecting to %s", _redact_dsn(dsn))
    try:
        conn = psycopg.connect(dsn, autocommit=False, connect_timeout=15)
    except Exception as exc:
        logger.error(
            "could not connect to Postgres at %s: %s. "
            "If the host did not resolve, the assembled DSN is IPv6-only — "
            "set SUPABASE_DB_URL to the IPv4 pooler endpoint from "
            "Supabase Studio > Project Settings > Database > Connection string.",
            _redact_dsn(dsn),
            exc,
        )
        return 2

    applied_count = 0
    skipped_count = 0
    total_count = 0
    rc = 0
    try:
        _acquire_lock(conn)
        _ensure_table(conn)

        if args.rollback:
            return _run_rollback(conn, directory, args.rollback, hostname)

        applied = _applied_index(conn)
        migrations = _list_migrations(directory)
        total_count = len(migrations)

        for path in migrations:
            sql = path.read_text(encoding="utf-8")
            checksum = _checksum(sql)
            prior = applied.get(path.name)
            if prior is not None:
                # Allow the bootstrap placeholder so operators can flip to a
                # real checksum on first successful re-application.
                if prior == checksum or prior == "manual-prebackfill":
                    logger.info("[migration] skip %s (already applied)", path.name)
                    skipped_count += 1
                    continue
                logger.error(
                    "[migration] CHECKSUM MISMATCH for %s — applied=%s "
                    "current=%s. Refusing to run. An already-applied migration "
                    "was edited; investigate and reconcile manually.",
                    path.name,
                    prior,
                    checksum,
                )
                rc = 1
                break

            if args.dry_run:
                logger.info("[migration] PLAN apply %s (sha256=%s)", path.name, checksum[:12])
                applied_count += 1
                continue

            try:
                elapsed = _apply_one(conn, path, sql, checksum, hostname)
            except Exception as exc:
                logger.error(
                    "[migration] FAILED %s — rolled back. Error: %s",
                    path.name,
                    exc,
                )
                rc = 1
                break
            logger.info(
                "[migration] applied %s in %.0fms", path.name, elapsed
            )
            applied_count += 1
    finally:
        _release_lock(conn)
        conn.close()

    logger.info(
        "[migration] summary applied=%d skipped=%d total=%d%s",
        applied_count,
        skipped_count,
        total_count,
        " (dry-run)" if args.dry_run else "",
    )
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
