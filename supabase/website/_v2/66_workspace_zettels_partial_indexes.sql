-- 66_workspace_zettels_partial_indexes.sql — partial indexes for soft-delete hot paths.
--
-- Industry-standard pattern (Brandur 2023, Cultured Systems 2024, PHP Architect
-- 2026): when every read query filters `WHERE deleted_at IS NULL`, a partial
-- index that materializes only the live set is dramatically smaller and faster
-- than a full index over a table where a growing fraction of rows are
-- tombstones. Without it the planner falls back to seq scan as the table grows
-- — the recurring soft-delete-at-scale anti-pattern called out in 2024-2026
-- production-postmortem writeups.
--
-- Two indexes are added here. A third "list-zettels hot path" partial index
-- already exists in 02_content_schema.sql (idx_workspace_zettels_workspace_created
-- WHERE deleted_at IS NULL), so we don't redundantly recreate it.
--
-- Idempotent: every DDL is guarded by IF EXISTS / IF NOT EXISTS.

BEGIN;

-- ── 1. UNIQUE-while-alive on (workspace_id, canonical_zettel_id) ──────────
--
-- The table-level UNIQUE constraint at 02_content_schema.sql declares
--   UNIQUE (workspace_id, canonical_zettel_id)
-- which blocks re-insertion of a workspace_zettel after the prior one was
-- soft-deleted — the tombstone occupies the unique slot. With the new
-- visible-Trash + Restore UX (PR exec/DB_delete_zettel_refine--1a) a user
-- can restore from trash AND a user re-adding the same URL after a delete
-- both legitimately need a NEW row to land. Partial UNIQUE on the live
-- set fixes this without losing the dedup invariant for active rows.
--
-- Drop the absolute UNIQUE first. The auto-generated constraint name
-- follows the Postgres convention `<table>_<columns>_key`.
ALTER TABLE content.workspace_zettels
    DROP CONSTRAINT IF EXISTS workspace_zettels_workspace_id_canonical_zettel_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_zettel_active
    ON content.workspace_zettels (workspace_id, canonical_zettel_id)
    WHERE deleted_at IS NULL;

-- ── 2. Trash hot path: (workspace_id, deleted_at DESC) for soft-deleted rows ─
--
-- Powers the new GET /api/zettels/trash endpoint (visible Trash UI).
-- Without this partial index, listing soft-deleted rows would fall back to
-- a seq scan AND/OR force the planner to use the live-row index and post-
-- filter on deleted_at IS NOT NULL — both wasteful. The partial index is
-- small (only soft-deleted rows) and the ORDER BY deleted_at DESC is
-- index-supported.
CREATE INDEX IF NOT EXISTS idx_workspace_zettels_trash
    ON content.workspace_zettels (workspace_id, deleted_at DESC)
    WHERE deleted_at IS NOT NULL;

COMMIT;

NOTIFY pgrst, 'reload schema';
