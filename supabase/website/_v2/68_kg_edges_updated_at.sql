-- Migration 68 (Phase 2 / B7-b): kg_edges.updated_at column + trigger.
--
-- (Plan-numbered "Migration 47" in 2026-05-23-kg-render-correctness-overhaul.md.
-- Renumbered at execution because slot 47 was already taken by
-- 47_migrate_17_to_repeatable.sql. Design content unchanged.)
--
-- The Phase B scorer's re-upsert path updates strength columns in place;
-- without an updated_at, callers cannot implement "edges re-scored since T"
-- diff queries or efficient incremental cache invalidation.
--
-- Reuses the existing `core.fn_set_updated_at` trigger function from
-- _v2/16_nexus_tokens.sql:59. Additive (DEFAULT now()) so existing rows
-- get a sensible value on column creation.

ALTER TABLE kg.kg_edges
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_kg_edges_set_updated_at ON kg.kg_edges;
CREATE TRIGGER trg_kg_edges_set_updated_at
  BEFORE UPDATE ON kg.kg_edges
  FOR EACH ROW
  EXECUTE FUNCTION core.fn_set_updated_at();

COMMENT ON COLUMN kg.kg_edges.updated_at IS
  'Maintained by trg_kg_edges_set_updated_at on every UPDATE. Use for "edges re-scored since T" queries.';
