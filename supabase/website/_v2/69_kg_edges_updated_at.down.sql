-- Down migration for 69_kg_edges_updated_at.sql.
DROP TRIGGER IF EXISTS trg_kg_edges_set_updated_at ON kg.kg_edges;
DROP FUNCTION IF EXISTS kg.fn_set_updated_at();
ALTER TABLE kg.kg_edges DROP COLUMN IF EXISTS updated_at;
