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
import json
import logging
import os
import re
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

# Bootstrap placeholders that an operator may have inserted into
# ``_migrations_applied.checksum`` to mark a migration as "already
# applied out-of-band; just record it on next run". On match we treat
# the migration as applied and silently overwrite nothing — the row's
# checksum is rewritten only via ``--reconcile-checksum``.
_BOOTSTRAP_PLACEHOLDERS: tuple[str, ...] = ("manual-prebackfill",)

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


_MIGRATION_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(_\d{2})?_[a-z0-9_]+\.sql$")


def _list_migrations(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise RuntimeError(f"Migrations directory not found: {directory}")
    files = sorted(p for p in directory.glob("*.sql") if not p.name.endswith(".down.sql"))
    invalid = [p.name for p in files if not _MIGRATION_NAME_RE.match(p.name)]
    if invalid:
        raise RuntimeError(
            f"Invalid migration filenames: {invalid}. "
            f"Expected: YYYY-MM-DD[_NN]_<slug>.sql"
        )
    return files


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
    """Run one migration file inside a single transaction. Returns elapsed ms.

    iter-03 §1C.4: also records deploy provenance (git SHA, deploy id,
    actor, runner hostname) into the audit row so we can later trace which
    deploy applied each migration.
    """
    git_sha = os.environ.get("DEPLOY_GIT_SHA")
    deploy_id = os.environ.get("DEPLOY_ID")
    deploy_actor = os.environ.get("DEPLOY_ACTOR")
    t0 = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO _migrations_applied "
                "(name, checksum, applied_by, deploy_git_sha, deploy_id, "
                "deploy_actor, runner_hostname) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    path.name,
                    checksum,
                    hostname,
                    git_sha,
                    deploy_id,
                    deploy_actor,
                    hostname,
                ),
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
# Schema-drift detection (iter-03 §1C.5)
# ---------------------------------------------------------------------------
DEFAULT_MANIFEST_PATH = (
    ROOT / "supabase" / "website" / "kg_public" / "expected_schema.json"
)


def _introspect_schema(conn) -> dict:
    """Build a normalized snapshot of the live ``public`` schema.

    Captures, per table, every column's data_type, nullability, and default
    expression — the four kinds of drift the iter-03 spec calls out
    (added, removed, type change, nullability change, default change).
    Functions are captured by their fully-qualified signature; indexes by
    their definition string for completeness, though only tables and
    functions feed the gate by default.
    """
    snap: dict = {"tables": {}, "functions": {}, "indexes": {}}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'public'
             ORDER BY table_name, ordinal_position
            """
        )
        for tbl, col, dtype, is_nullable, default in cur.fetchall():
            t = snap["tables"].setdefault(tbl, {"columns": {}})
            t["columns"][col] = {
                "data_type": dtype,
                "is_nullable": is_nullable,
                "default": default,
            }

        cur.execute(
            """
            SELECT indexname, tablename, indexdef
              FROM pg_indexes
             WHERE schemaname = 'public'
             ORDER BY indexname
            """
        )
        for name, tbl, ddef in cur.fetchall():
            snap["indexes"][name] = {"table": tbl, "definition": ddef}

        cur.execute(
            """
            SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' AS sig,
                   pg_get_function_result(p.oid) AS rettype
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public'
             ORDER BY sig
            """
        )
        for sig, rettype in cur.fetchall():
            snap["functions"][sig] = {"return_type": rettype}

    return snap


def _diff_schemas(expected: dict, live: dict) -> list[str]:
    """Return a list of human-readable drift descriptions; empty == match."""
    drift: list[str] = []
    expected_tables = expected.get("tables", {})
    live_tables = live.get("tables", {})

    for tbl, spec in expected_tables.items():
        if tbl not in live_tables:
            drift.append(f"missing table: {tbl}")
            continue
        live_cols = live_tables[tbl].get("columns", {})
        expected_cols = spec.get("columns", {})
        for col, expected_col in expected_cols.items():
            live_col = live_cols.get(col)
            if live_col is None:
                drift.append(f"missing column: {tbl}.{col}")
                continue
            # Per-attribute comparison so we can name the drift kind.
            for attr in ("data_type", "is_nullable", "default"):
                exp_v = expected_col.get(attr) if isinstance(expected_col, dict) else None
                live_v = live_col.get(attr) if isinstance(live_col, dict) else None
                # Back-compat: legacy manifest may have stored bare type str.
                if isinstance(expected_col, str) and attr == "data_type":
                    exp_v = expected_col
                if exp_v is None and attr in ("is_nullable", "default"):
                    # Manifest didn't pin this attribute — skip.
                    continue
                if exp_v != live_v:
                    drift.append(
                        f"{attr} mismatch: {tbl}.{col} expected={exp_v!r} live={live_v!r}"
                    )
        # Removed-column detection: column present live, absent in manifest.
        for col in live_cols:
            if col not in expected_cols:
                drift.append(f"unexpected column (manifest stale?): {tbl}.{col}")

    for fn in expected.get("functions", {}):
        if fn not in live.get("functions", {}):
            drift.append(f"missing function: {fn}")

    return drift


def _verify_schema(conn, manifest_path: Path) -> int:
    """Return 0 if live schema matches manifest, 1 if drift detected."""
    if not manifest_path.exists():
        logger.error("[migration] expected_schema.json missing: %s", manifest_path)
        return 1
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    live = _introspect_schema(conn)
    drift = _diff_schemas(expected, live)
    if drift:
        logger.error("[migration] SCHEMA DRIFT detected:")
        for d in drift:
            logger.error("  - %s", d)
        return 1
    logger.info("[migration] schema matches expected_schema.json")
    return 0


def _write_manifest(conn, manifest_path: Path) -> int:
    """Write the live schema to ``manifest_path`` (bootstrap or update)."""
    snap = _introspect_schema(conn)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(snap, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.warning(
        "[migration] wrote schema manifest -> %s (%d tables, %d functions)",
        manifest_path,
        len(snap["tables"]),
        len(snap["functions"]),
    )
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
    p.add_argument(
        "--reconcile-checksum",
        metavar="NAME",
        default=None,
        help=(
            "Rewrite the recorded checksum for an already-applied migration "
            "to the current file's SHA-256 (operator review required)."
        ),
    )
    p.add_argument(
        "--manifest-path",
        default=str(DEFAULT_MANIFEST_PATH),
        help=f"Path to expected_schema.json (default: {DEFAULT_MANIFEST_PATH}).",
    )
    p.add_argument(
        "--bootstrap-manifest",
        action="store_true",
        help="Write the live schema to the manifest path and exit.",
    )
    p.add_argument(
        "--update-manifest",
        action="store_true",
        help=(
            "Apply pending migrations, then overwrite the manifest with the "
            "post-apply schema (use after a deliberate schema change)."
        ),
    )
    p.add_argument(
        "--check-manifest-fresh",
        action="store_true",
        help=(
            "Compare the live schema to the manifest and exit; do NOT apply "
            "any migrations. Used by the CI freshness gate."
        ),
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
    conn = None
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            conn = psycopg.connect(dsn, autocommit=False, connect_timeout=15)
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "[migration] connect attempt %d/3 failed: %s",
                attempt + 1,
                exc,
            )
            if attempt < 2:
                time.sleep(5)
    if conn is None:
        logger.error(
            "could not connect to Postgres at %s after 3 attempts: %s. "
            "If the host did not resolve, the assembled DSN is IPv6-only — "
            "set SUPABASE_DB_URL to the IPv4 pooler endpoint from "
            "Supabase Studio > Project Settings > Database > Connection string.",
            _redact_dsn(dsn),
            last_exc,
        )
        return 2

    applied_count = 0
    skipped_count = 0
    total_count = 0
    rc = 0
    manifest_path = Path(args.manifest_path).resolve()
    try:
        _acquire_lock(conn)
        _ensure_table(conn)

        if args.bootstrap_manifest:
            return _write_manifest(conn, manifest_path)

        if args.check_manifest_fresh:
            return _verify_schema(conn, manifest_path)

        if args.reconcile_checksum:
            name = args.reconcile_checksum
            sql_path = directory / name
            if not sql_path.exists():
                logger.error("[migration] reconcile failed: file not found: %s", sql_path)
                return 1
            new_checksum = _checksum(sql_path.read_text(encoding="utf-8"))
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE _migrations_applied SET checksum = %s WHERE name = %s",
                    (new_checksum, name),
                )
            conn.commit()
            logger.warning(
                "[migration] reconciled checksum for %s -> %s",
                name,
                new_checksum[:12],
            )
            return 0

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
                if prior == checksum or prior in _BOOTSTRAP_PLACEHOLDERS:
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

        # iter-03 §1C.5 (hardened): post-apply manifest gate.
        #
        # Default behavior is HARD-FAIL on drift or missing manifest. Two
        # operator escapes:
        #   * ``--update-manifest`` rewrites the manifest from the live schema
        #     (deliberate schema change — committed back to Git).
        #   * ``MIGRATION_MANIFEST_AUTOBOOTSTRAP=1`` writes the manifest if
        #     absent, returns 0, and logs a loud reminder to commit it. Used
        #     for the first deploy after iter-03; not for steady state.
        #
        # The legacy ``MIGRATION_MANIFEST_REQUIRED=0`` env reverts to warn-only
        # behavior — kept for emergency rollback only.
        if rc == 0 and not args.dry_run:
            required = os.environ.get("MIGRATION_MANIFEST_REQUIRED", "1") == "1"
            autobootstrap = os.environ.get("MIGRATION_MANIFEST_AUTOBOOTSTRAP", "0") == "1"

            if args.update_manifest:
                _write_manifest(conn, manifest_path)
            elif manifest_path.exists():
                drift_rc = _verify_schema(conn, manifest_path)
                if drift_rc != 0:
                    rc = 1
            elif autobootstrap:
                logger.warning(
                    "[migration] manifest missing — AUTOBOOTSTRAP writing %s. "
                    "OPERATOR MUST COMMIT THIS FILE TO GIT before the next deploy.",
                    manifest_path,
                )
                _write_manifest(conn, manifest_path)
            elif required:
                logger.error(
                    "[migration] FATAL: schema-drift manifest not found at %s. "
                    "Either set MIGRATION_MANIFEST_AUTOBOOTSTRAP=1 for the first "
                    "deploy, or run --bootstrap-manifest against staging and commit.",
                    manifest_path,
                )
                rc = 1
            else:
                logger.warning(
                    "[migration] schema-drift gate skipped (MIGRATION_MANIFEST_REQUIRED=0).",
                )
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
