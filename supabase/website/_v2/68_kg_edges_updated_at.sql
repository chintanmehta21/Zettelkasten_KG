-- Migration 68 (Phase 2 / B7-b): kg_edges.updated_at column + trigger.
--
-- (Plan-numbered "Migration 47" in 2026-05-23-kg-render-correctness-overhaul.md.
-- Renumbered at execution because slot 47 was already taken by
-- 47_migrate_17_to_repeatable.sql.)
--
-- 2026-05-23 REWRITE (industry-standard pattern):
-- Originally written as `ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()`,
-- which would force a FULL TABLE REWRITE under AccessExclusive lock. The fast-
-- default optimisation in Postgres 11+ only applies to IMMUTABLE defaults;
-- `now()` is STABLE and triggers the rewrite path. On the 2 GB / 1 vCPU
-- droplet this is 1-5 seconds of fully-blocked writes on the kg_edges table.
--
-- Three-step safe pattern instead (Brandur Leach / Squawk / Supabase Timeouts):
--   1. ADD COLUMN nullable (instant via attmissingval — no rewrite).
--   2. UPDATE backfill (NULL -> created_at if exists, else now()).
--   3. SET DEFAULT now() + SET NOT NULL (after backfill, sub-second locks).
--
-- The lock_timeout + statement_timeout wraps surface a stuck-lock as an error
-- instead of queueing behind every reader. Safe to apply during business hours.
--
-- Reuses the existing `core.fn_set_updated_at` trigger function from
-- _v2/16_nexus_tokens.sql:59.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  -- Step 1: instant via attmissingval (no rewrite); column initially NULL.
  ALTER TABLE kg.kg_edges
    ADD COLUMN IF NOT EXISTS updated_at timestamptz;

  -- Step 2: backfill. Prefer `created_at` so existing-row updated_at >=
  -- created_at after this migration; fall back to now() for any rows
  -- missing both. WHERE clause makes the migration safe to re-run.
  UPDATE kg.kg_edges
     SET updated_at = COALESCE(created_at, now())
   WHERE updated_at IS NULL;

  -- Step 3: lock down the invariant.
  ALTER TABLE kg.kg_edges
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;
COMMIT;

-- Trigger sits outside the transaction so a failed body doesn't half-apply
-- (DDL is transactional but the lock-timeout could roll back; the trigger
-- step is independent and idempotent).
DROP TRIGGER IF EXISTS trg_kg_edges_set_updated_at ON kg.kg_edges;
CREATE TRIGGER trg_kg_edges_set_updated_at
  BEFORE UPDATE ON kg.kg_edges
  FOR EACH ROW
  EXECUTE FUNCTION core.fn_set_updated_at();

COMMENT ON COLUMN kg.kg_edges.updated_at IS
  'Maintained by trg_kg_edges_set_updated_at on every UPDATE. Use for "edges re-scored since T" queries.';
