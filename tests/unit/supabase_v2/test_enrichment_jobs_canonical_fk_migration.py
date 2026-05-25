"""SQL-shape tests for migration 74 (enrichment_jobs canonical FK cascade).

Mirrors the lightweight assertion style of test_operations_migration.py: the
migration's SQL is read and checked for the exact tokens that make the
constraint behave correctly. The actual ALTER TABLE is only exercised under
the integration-tests path with a live v2 database.
"""

from pathlib import Path

MIG = Path("supabase/website/_v2/74_enrichment_jobs_canonical_fk_cascade.sql")
DOWN = Path("supabase/website/_v2/74_enrichment_jobs_canonical_fk_cascade.down.sql")


def test_forward_migration_exists_and_well_formed():
    sql = MIG.read_text(encoding="utf-8").lower()
    # FK target is the canonical row + cascade delete
    assert "foreign key (canonical_zettel_id)" in sql
    assert "references content.canonical_zettels(id)" in sql
    assert "on delete cascade" in sql
    # Idempotent shape: drops + re-adds the constraint
    assert "drop constraint if exists enrichment_jobs_canonical_fk" in sql
    assert "add constraint enrichment_jobs_canonical_fk" in sql
    # Orphan pre-cleanup block protects the FK ADD from rejecting current rows
    assert "delete from core.zettel_enrichment_jobs" in sql
    assert "not exists" in sql
    # Safety brake on catastrophic orphan volume
    assert "v_orphan_count > 100" in sql
    assert "raise exception" in sql
    # Standard tail tokens
    assert "begin;" in sql
    assert "commit;" in sql
    assert "notify pgrst, 'reload schema'" in sql


def test_down_migration_exists_and_well_formed():
    sql = DOWN.read_text(encoding="utf-8").lower()
    assert "drop constraint if exists enrichment_jobs_canonical_fk" in sql
    assert "begin;" in sql
    assert "commit;" in sql
    # Down migration must NOT attempt to resurrect pre-cleanup orphans —
    # they are unreachable by definition (canonical already gone).
    assert "insert into core.zettel_enrichment_jobs" not in sql


def test_forward_migration_targets_correct_schema():
    # Sanity: the FK lives on core.zettel_enrichment_jobs, not public/billing/etc.
    sql = MIG.read_text(encoding="utf-8")
    assert "ALTER TABLE core.zettel_enrichment_jobs" in sql
    # FK refers across the schema boundary into content.canonical_zettels
    assert "content.canonical_zettels(id)" in sql
