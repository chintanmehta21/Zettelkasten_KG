from __future__ import annotations

from pathlib import Path


MIGRATIONS_DIR = Path("supabase/website/rag_chatbot")


def _read(name: str) -> str:
    path = MIGRATIONS_DIR / name
    assert path.exists(), f"Missing migration file: {path}"
    return path.read_text(encoding="utf-8")


def test_phase1_migration_files_exist() -> None:
    expected = [
        "001_hnsw_migration.sql",
        "002_chunks_table.sql",
        "003_sandboxes.sql",
        "004_chat_sessions.sql",
        "005_rag_rpcs.sql",
    ]
    for name in expected:
        assert (MIGRATIONS_DIR / name).exists()


def test_hnsw_migration_contains_expected_index_changes() -> None:
    sql = _read("001_hnsw_migration.sql")
    assert "DROP INDEX CONCURRENTLY IF EXISTS public.idx_kg_nodes_embedding;" in sql
    assert "idx_kg_nodes_embedding_hnsw" in sql
    assert "ALTER DATABASE postgres SET hnsw.iterative_scan = 'strict_order';" in sql


def test_chunks_migration_contains_table_and_indexes() -> None:
    sql = _read("002_chunks_table.sql")
    assert "CREATE TABLE IF NOT EXISTS kg_node_chunks" in sql
    assert "idx_kg_node_chunks_embedding_hnsw" in sql
    assert "CREATE TRIGGER trg_kg_node_chunks_fts" in sql
    assert "CREATE POLICY kg_node_chunks_service_all" in sql


def test_sandboxes_migration_contains_tables_view_and_policies() -> None:
    sql = _read("003_sandboxes.sql")
    assert "CREATE TABLE IF NOT EXISTS rag_sandboxes" in sql
    assert "CREATE TABLE IF NOT EXISTS rag_sandbox_members" in sql
    assert "CREATE OR REPLACE VIEW rag_sandbox_stats AS" in sql
    assert "CREATE POLICY rag_sandboxes_service_all" in sql
    assert "CREATE POLICY rag_sandbox_members_service_all" in sql


def test_chat_sessions_migration_contains_trigger_and_rls() -> None:
    sql = _read("004_chat_sessions.sql")
    assert "CREATE TABLE IF NOT EXISTS chat_sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS chat_messages" in sql
    assert "CREATE OR REPLACE FUNCTION chat_session_stats_update()" in sql
    assert "CREATE TRIGGER trg_chat_session_stats" in sql
    assert "CREATE POLICY chat_sessions_service_all" in sql
    assert "CREATE POLICY chat_messages_service_all" in sql


def test_rag_rpcs_migration_contains_all_required_functions() -> None:
    sql = _read("005_rag_rpcs.sql")
    for fn_name in [
        "rag_resolve_effective_nodes",
        "rag_hybrid_search",
        "rag_subgraph_for_pagerank",
        "rag_bulk_add_to_sandbox",
        "rag_replace_node_chunks",
    ]:
        assert f"FUNCTION {fn_name}" in sql or f"FUNCTION {fn_name}(" in sql
