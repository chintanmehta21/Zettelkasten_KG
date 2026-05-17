-- Phase B — Two-level KG connection strength (schema + repository layer).
--
-- Locked spec: docs/research/phase_b_kg_quality_design.md.
--
-- Builds on 42_kg_connection_strength.sql, which added the single composite
-- `kg.kg_edges.connection_strength NUMERIC(4,3)`. Phase B splits the score into
-- two independently-stored levels plus a provenance map:
--
--   * workspace_strength  — the per-workspace score that DRIVES RENDERING
--     (edge thickness / strong-medium-weak buckets in the per-user
--     /api/graph surface). Scoped to one workspace's evidence only.
--   * global_strength     — the same edge's strength computed across ALL
--     users/workspaces. STORED FOR FUTURE CROSS-USER ANALYTICS ONLY; it is
--     never surfaced to any user-facing API and never feeds rendering.
--   * matched_via         — jsonb provenance: which signals fired and their
--     sub-scores, keys {embedding, tag, structural, temporal}. Lets the
--     scorer pass be audited / re-explained without recomputation.
--
-- All columns NULLABLE-or-defaulted → fully backward-compatible. Existing
-- rows are untouched (no backfill UPDATE: Phase B's scorer unit owns
-- population; legacy rows keep connection_strength from 42 and read NULL
-- two-level until the scorer runs).
--
-- Also adds the natural-key UNIQUE constraint the repository layer needs for
-- idempotent edge upsert ON CONFLICT (none existed on kg.kg_edges before).
--
-- Anti-pattern guards:
--   * Forward-only ADD COLUMN / ADD CONSTRAINT IF-NOT-EXISTS-guarded; safe to
--     re-apply.
--   * No DROP, no destructive op, no CREATE OR REPLACE on existing functions.
--   * Constraint adds use the 42_kg_connection_strength.sql pg_constraint
--     existence-probe pattern (ADD CONSTRAINT has no IF NOT EXISTS in PG).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Two-level strength + provenance columns
-- ---------------------------------------------------------------------------
ALTER TABLE kg.kg_edges
    ADD COLUMN IF NOT EXISTS workspace_strength NUMERIC(4, 3),
    ADD COLUMN IF NOT EXISTS global_strength    NUMERIC(4, 3),
    ADD COLUMN IF NOT EXISTS matched_via        jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Range guards: NULL allowed (legacy / awaiting scorer); when present, [0,1].
-- Pattern mirrors 42_kg_connection_strength.sql:35-49 (PG ADD CONSTRAINT has
-- no IF NOT EXISTS — probe pg_constraint first so re-apply is a no-op).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'kg_edges_workspace_strength_range'
           AND conrelid = 'kg.kg_edges'::regclass
    ) THEN
        ALTER TABLE kg.kg_edges
            ADD CONSTRAINT kg_edges_workspace_strength_range
            CHECK (workspace_strength IS NULL
                   OR (workspace_strength >= 0 AND workspace_strength <= 1));
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'kg_edges_global_strength_range'
           AND conrelid = 'kg.kg_edges'::regclass
    ) THEN
        ALTER TABLE kg.kg_edges
            ADD CONSTRAINT kg_edges_global_strength_range
            CHECK (global_strength IS NULL
                   OR (global_strength >= 0 AND global_strength <= 1));
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2) Natural-key UNIQUE constraint for idempotent edge upsert
-- ---------------------------------------------------------------------------
-- The repository's upsert_edge is idempotent on the logical edge identity
-- (workspace_id, src_node_id, dst_node_id, relation_type). 03_kg_schema.sql
-- defined NO unique key on kg.kg_edges (only the bigserial PK), so a re-run of
-- the scorer would have inserted duplicate rows. We add the natural key here.
--
-- workspace_id (not the GENERATED workspace_key) is used so ON CONFLICT can
-- target a real, user-writable column tuple. upsert_edge always supplies a
-- non-NULL workspace_id (service-role bypasses RLS; NULL would be a
-- cross-tenant write hole), so SQL NULL-distinctness on workspace_id is not a
-- correctness concern for this write path.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'kg_edges_natural_key'
           AND conrelid = 'kg.kg_edges'::regclass
    ) THEN
        ALTER TABLE kg.kg_edges
            ADD CONSTRAINT kg_edges_natural_key
            UNIQUE (workspace_id, src_node_id, dst_node_id, relation_type);
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3) Workspace-scoped strength read / percentile-bucket index
-- ---------------------------------------------------------------------------
-- Mirrors the 42_kg_connection_strength.sql idx_kg_edges_workspace_strength
-- convention (workspace_key + strength DESC NULLS LAST) but on the two-level
-- workspace_strength column the per-user /api/graph render path now reads.
-- Supports min_strength bucket filters and per-workspace percentile scans.
CREATE INDEX IF NOT EXISTS idx_kg_edges_workspace_two_level_strength
    ON kg.kg_edges (workspace_key, workspace_strength DESC NULLS LAST);

-- ---------------------------------------------------------------------------
-- 4) Column documentation
-- ---------------------------------------------------------------------------
COMMENT ON COLUMN kg.kg_edges.workspace_strength IS
    'Phase B: per-workspace connection strength in [0,1]. DRIVES RENDERING — '
    'edge thickness and strong/medium/weak buckets in the per-user /api/graph '
    'surface. NULL until the Phase B scorer pass runs (legacy rows keep the '
    '42_kg_connection_strength composite until then).';
COMMENT ON COLUMN kg.kg_edges.global_strength IS
    'Phase B: cross-user/cross-workspace strength in [0,1]. STORED FOR FUTURE '
    'CROSS-USER ANALYTICS ONLY — never returned by any user-facing API and '
    'never feeds rendering. Isolation: surfacing this would leak other '
    'workspaces'' co-occurrence signal.';
COMMENT ON COLUMN kg.kg_edges.matched_via IS
    'Phase B: provenance map of which signals fired for this edge and their '
    'sub-scores. Keys: embedding, tag, structural, temporal. Audit/explain '
    'surface for the scorer; never RLS-keyed.';

NOTIFY pgrst, 'reload schema';

COMMIT;
