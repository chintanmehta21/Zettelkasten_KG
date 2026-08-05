"""Phase 7.3c: nightly cleanup of leftover ``e2e-*@test.com`` test fixtures.

The pytest_sessionfinish hook in ``tests/integration/v2/conftest.py`` is the
first line of defence; this script is the safety net for crashes that skip
teardown entirely (KeyboardInterrupt, OOM, runner SIGKILL) and for fixture
leaks from one-off operator runs.

Idempotent: matches the canonical mint pattern ``e2e-{8 hex}@test.com``
(allow 6-12 hex for forward-compat). Only deletes users older than
``--age-hours`` (default 24h) so an in-flight test run is never disrupted.

Requires the service-role key (``SUPABASE_V2_SERVICE_ROLE_KEY`` or
``SUPABASE_SERVICE_ROLE_KEY``) — admin.list_users / admin.delete_user are
service-role-only RPCs.

Usage::

    python ops/scripts/purge_test_fixtures.py --age-hours 24
    python ops/scripts/purge_test_fixtures.py --age-hours 0 --dry-run

Exit codes: 0 success, 1 runtime error, 2 config error.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv(ROOT / "supabase" / ".env")
    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)-22s %(message)s",
)
log = logging.getLogger("purge_test_fixtures")

# Mint pattern: ``e2e-{uuid.uuid4().hex[:8]}@test.com``. Allow 6-12 hex for
# forward-compat if the prefix length is ever tuned.
E2E_EMAIL_PATTERN = re.compile(r"^e2e-[0-9a-f]{6,12}@test\.com$")


def _parse_supabase_timestamp(value: str) -> datetime | None:
    """Parse a Supabase ISO-8601 timestamp into a tz-aware UTC datetime."""
    if not value:
        return None
    try:
        # Supabase emits e.g. "2026-05-10T06:42:01.123456+00:00".
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _user_created_at(user) -> datetime | None:
    raw = getattr(user, "created_at", None)
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    return _parse_supabase_timestamp(str(raw))


def _assert_clean_or_fail(age_hours: float) -> int:
    """DEAD-MAN SWITCH: 0 if no eligible fixtures remain, 1 otherwise.

    "exit 0" is NOT evidence the database is clean. Two real failure modes look
    identical to a clean run from the outside:
      * the job is CANCELLED mid-purge — the 10-minute `timeout-minutes` did
        exactly this on 2026-08-04, stopping with 182 of 436 users still
        present, and a cancelled run fires neither `failure` nor `timed_out`
        so scheduled-failure-alert.yml stayed quiet;
      * the auth listing silently returns nothing, so `candidates` is empty and
        the script "succeeds" having deleted nothing.
    Re-querying the DB closes both: a half-done sweep exits non-zero, which
    becomes a deduped GitHub issue via the alerter.
    """
    try:
        import psycopg

        from website.core.supabase_v2.client import get_v2_database_url

        with psycopg.connect(get_v2_database_url()) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM auth.users
                 WHERE email ~ %s
                   AND created_at < now() - make_interval(hours => %s)
                """,
                (E2E_EMAIL_PATTERN.pattern, float(age_hours)),
            )
            remaining = cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001 — the check itself must be loud
        log.error("--assert-clean check failed: %s: %s", type(exc).__name__, exc)
        return 1
    if remaining:
        log.error(
            "ASSERT-CLEAN FAILED: %d eligible e2e fixture user(s) still present "
            "after the purge (expected 0) — the sweep did not finish.",
            remaining,
        )
        return 1
    log.info("assert-clean OK: 0 eligible fixtures remain")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--age-hours",
        type=float,
        default=24.0,
        help="Only delete users older than this many hours (default: 24).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matches without deleting.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="auth.admin.list_users page size (default: 200).",
    )
    parser.add_argument(
        "--assert-clean",
        action="store_true",
        help=(
            "After purging, re-query the DB and fail if ANY eligible fixture "
            "remains. Without this a half-finished or no-op run is "
            "indistinguishable from a clean one."
        ),
    )
    args = parser.parse_args(argv)

    try:
        from website.core.supabase_v2.client import get_v2_client
    except Exception as exc:  # noqa: BLE001
        log.error("could not import v2 client: %s: %s", type(exc).__name__, exc)
        return 2

    try:
        client = get_v2_client()
    except Exception as exc:  # noqa: BLE001
        log.error("get_v2_client failed: %s: %s", type(exc).__name__, exc)
        return 2

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=args.age_hours)
    log.info("cutoff = %s (age >= %.1fh)", cutoff.isoformat(), args.age_hours)

    candidates = []
    page = 1
    scanned = 0
    while True:
        try:
            resp = client.auth.admin.list_users(page=page, per_page=args.page_size)
        except Exception as exc:  # noqa: BLE001
            log.error("list_users page=%d failed: %s: %s", page, type(exc).__name__, exc)
            return 1
        users = resp if isinstance(resp, list) else getattr(resp, "users", [])
        if not users:
            break
        scanned += len(users)
        for u in users:
            email = getattr(u, "email", None) or ""
            if not email or not E2E_EMAIL_PATTERN.match(email):
                continue
            created = _user_created_at(u)
            if created is None:
                log.warning("skip %s: no parseable created_at", email)
                continue
            if created > cutoff:
                continue
            candidates.append((u, email, created))
        if len(users) < args.page_size:
            break
        page += 1
        if page > 50:
            log.warning("hit page-cap of 50 (10k users); stopping scan")
            break

    log.info(
        "scanned=%d matched=%d (older than cutoff)",
        scanned,
        len(candidates),
    )

    if not candidates:
        # Still run the dead-man check. "No candidates" is ambiguous: either
        # genuinely clean, OR the auth listing returned nothing while fixtures
        # sit in the DB — the second is precisely the silent failure mode.
        if args.assert_clean and not args.dry_run:
            return _assert_clean_or_fail(args.age_hours)
        return 0

    if args.dry_run:
        for _u, email, created in candidates[:50]:
            log.info("would delete %s (created=%s)", email, created.isoformat())
        if len(candidates) > 50:
            log.info("... and %d more (dry-run)", len(candidates) - 50)
        return 0

    # Pre-clean FK-bound rows the GoTrue admin API does NOT cascade through
    # (rag.retrieval_feedback_events, billing.pricing_subscriptions,
    # rag.kasten_members, ...). Without this, admin.delete_user returns
    # HTTP 500 "Database error deleting user" and the fixture user survives —
    # which is why this nightly job failed every run from at least 2026-07-31
    # to 2026-08-04 and let ~1.4k e2e zettels accumulate in content.
    # tests/integration/v2/conftest.py already solved this for the per-test
    # teardown path (Supabase Discussion #28776: admin.delete_user has no
    # cascade flag); this is the same fix for the standalone nightly job.
    # 2026-08-04: removal now goes through the DATABASE, not the GoTrue admin
    # API. The pre-clean above was necessary but NOT sufficient — deletes still
    # returned HTTP 500 "AuthApiError: Database error deleting user" for every
    # candidate. Diagnosis against prod:
    #   * every FK referencing auth.users / core.profiles is CASCADE or
    #     SET NULL — there is NO blocking constraint, in any schema;
    #   * there are NO user-defined DELETE triggers on either table;
    #   * `DELETE FROM auth.users WHERE id = ...` run directly against the DB
    #     SUCCEEDS (probed inside a transaction that was rolled back).
    # So the fault is inside the GoTrue admin endpoint, not our schema. Deleting
    # through SQL lets Postgres' own CASCADE rules do exactly what the admin API
    # would have relied on anyway.
    from website.core.account_purge import purge_user_dependencies

    try:
        import psycopg

        from website.core.supabase_v2.client import get_v2_database_url

        dsn = get_v2_database_url()
    except Exception as exc:  # noqa: BLE001
        log.error("cannot open DB for purge: %s: %s", type(exc).__name__, exc)
        return 2

    deleted, failed, skipped = 0, 0, 0
    with psycopg.connect(dsn, autocommit=False) as conn:
        for u, email, _created in candidates:
            # SAFETY (defence in depth): never trust the listing alone.
            # 1. re-assert the e2e pattern on this row;
            # 2. the DELETE matches on BOTH id AND the exact email, so a
            #    garbled/incorrect listing can only ever affect 0 rows —
            #    a real user cannot be removed by this script.
            if not E2E_EMAIL_PATTERN.match(email):
                log.warning("refusing to delete non-e2e email %r", email)
                skipped += 1
                continue
            try:
                # Best-effort pre-clean of rows the cascade intentionally does
                # not own (anonymised feedback events etc.). Non-fatal.
                try:
                    purge_user_dependencies(uuid.UUID(str(u.id)))
                except Exception as purge_exc:  # noqa: BLE001
                    log.warning(
                        "purge_user_dependencies(%s) failed: %s: %s",
                        email,
                        type(purge_exc).__name__,
                        purge_exc,
                    )
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM auth.users WHERE id = %s AND email = %s",
                        (str(u.id), email),
                    )
                    affected = cur.rowcount
                conn.commit()
                if affected == 1:
                    deleted += 1
                else:
                    # Already gone, or id/email disagreed. Not a hard error, but
                    # surfaced rather than silently counted as a success.
                    skipped += 1
                    log.warning(
                        "delete %s affected %d rows (expected 1)", email, affected
                    )
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                failed += 1
                log.warning("delete %s failed: %s: %s", email, type(exc).__name__, exc)

    if skipped:
        log.info("skipped=%d (pattern mismatch or already absent)", skipped)

    log.info("done: deleted=%d failed=%d", deleted, failed)

    if args.assert_clean:
        rc = _assert_clean_or_fail(args.age_hours)
        if rc:
            return rc

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
