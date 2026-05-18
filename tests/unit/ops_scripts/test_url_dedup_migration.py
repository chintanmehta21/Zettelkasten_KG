"""Static checks for the 45_url_dedup.sql migration.

These are text-level assertions only. Behavioral and transactional
correctness (loser collapse, child re-point, membership preservation,
single BEGIN/COMMIT, idempotent re-apply) is verified by the
migration-CI dry-run and the operator dry-run against a snapshot, not
by this unit test.
"""

from pathlib import Path

MIG = Path("supabase/website/_v2/46_url_dedup.sql")


def test_migration_exists_and_is_well_formed():
    sql = MIG.read_text(encoding="utf-8")
    assert "ORDER BY created_at DESC" in sql
    assert "UPDATE content.workspace_zettels" in sql
    assert "UPDATE content.canonical_chunks" in sql
    assert "DELETE FROM content.canonical_zettels" in sql
    assert "content_hash" in sql
    assert "ADD CONSTRAINT canonical_zettels_normalized_url_key UNIQUE (normalized_url)" in sql
    assert "IF EXISTS" in sql and "IF NOT EXISTS" in sql
    # FIX 1: membership re-point/delete must be present (RAG data-loss guard).
    assert "workspace_chunk_membership" in sql
    # FIX 3: single shared keeper_map drives every re-point/delete.
    assert "keeper_map" in sql
    # FIX 2: deterministic secondary sort on every keeper ranking.
    assert "id DESC" in sql


def test_rpc_conflict_target_is_url_only():
    rpc = Path("supabase/website/_v2/17_content_rpcs.sql").read_text(encoding="utf-8").lower()
    assert "on conflict (normalized_url)" in rpc
    # The composite (normalized_url, content_hash) must not survive as a
    # conflict target. Scope the negative check to the ON CONFLICT clause:
    # the bare substring also appears in the INSERT column list, so a raw
    # `not in` would false-fail.
    assert "on conflict (normalized_url, content_hash)" not in rpc
