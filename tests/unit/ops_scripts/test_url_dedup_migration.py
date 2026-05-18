from pathlib import Path

MIG = Path("supabase/website/_v2/45_url_dedup.sql")


def test_migration_exists_and_is_well_formed():
    sql = MIG.read_text(encoding="utf-8")
    assert "ORDER BY created_at DESC" in sql
    assert "UPDATE content.workspace_zettels" in sql
    assert "UPDATE content.canonical_chunks" in sql
    assert "DELETE FROM content.canonical_zettels" in sql
    assert "content_hash" in sql
    assert "ADD CONSTRAINT canonical_zettels_normalized_url_key UNIQUE (normalized_url)" in sql
    assert "IF EXISTS" in sql and "IF NOT EXISTS" in sql


def test_rpc_conflict_target_is_url_only():
    rpc = Path("supabase/website/_v2/17_content_rpcs.sql").read_text(encoding="utf-8")
    assert "ON CONFLICT (normalized_url)\n" in rpc
    assert "ON CONFLICT (normalized_url, content_hash)" not in rpc
