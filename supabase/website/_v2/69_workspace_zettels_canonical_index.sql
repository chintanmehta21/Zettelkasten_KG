-- Migration 69 (Phase 2 / C4): partial index for edge-driven overlay assembly.
--
-- (Plan-numbered "Migration 48" in 2026-05-23-kg-render-correctness-overhaul.md.
-- Renumbered at execution because slots 47/48/49 were already taken by
-- earlier migrations in the repeatable-conversion + operations work. Design
-- content unchanged.)
--
-- _v2_assemble_graph currently builds `canonical_to_overlay` from the first
-- page of `content.list_workspace_zettels`, dropping any edge whose endpoint
-- zettel falls outside that page. The C4 fix inverts the assembly: fetch
-- edges first (keyset-paginated), collect endpoint canonical ids, then
-- batch-fetch overlays by canonical id. That batch fetch needs an index on
-- (workspace_id, canonical_zettel_id) with a tenant predicate.
--
-- Partial index excludes soft-deleted rows so the lookup matches the
-- repository query exactly. Tested locally to be sub-millisecond on a
-- 100k-row table on the 1 vCPU droplet (B-tree on (uuid, uuid) is cheap).
--
-- Idempotent: CREATE INDEX IF NOT EXISTS + named index.

CREATE INDEX IF NOT EXISTS idx_workspace_zettels_workspace_canonical
  ON content.workspace_zettels (workspace_id, canonical_zettel_id)
  WHERE deleted_at IS NULL;

COMMENT ON INDEX content.idx_workspace_zettels_workspace_canonical IS
  'Supports edge-driven overlay assembly in routes._v2_assemble_graph (Phase 2 C4 fix).';
