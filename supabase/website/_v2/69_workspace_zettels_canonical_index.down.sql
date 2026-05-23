-- Down migration for 69_workspace_zettels_canonical_index.sql.
DROP INDEX IF EXISTS content.idx_workspace_zettels_workspace_canonical;
