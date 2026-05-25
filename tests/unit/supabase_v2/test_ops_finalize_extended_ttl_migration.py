"""SQL-shape tests for migration 75 (ops_finalize extended TTL).

Lightweight assertion style matching test_operations_migration.py: we read
the migration SQL and assert the exact tokens that define the new behavior.
"""

from pathlib import Path

MIG = Path("supabase/website/_v2/75_ops_finalize_extended_ttl.sql")
DOWN = Path("supabase/website/_v2/75_ops_finalize_extended_ttl.down.sql")


def test_forward_migration_exists_and_well_formed():
    sql = MIG.read_text(encoding="utf-8").lower()
    # CREATE OR REPLACE makes the migration safely re-runnable
    assert "create or replace function core.ops_finalize" in sql
    # The state-guarded transition (kept from migration 51)
    assert "where user_id = p_user_id" in sql
    assert "and operation_id = p_operation_id" in sql
    assert "and status in ('queued', 'running')" in sql
    # The TTL extension itself: 7 days on failed/cancelled, else preserve
    assert "expires_at = case" in sql
    assert "p_target in ('failed', 'cancelled')" in sql
    assert "now() + interval '7 days'" in sql
    assert "else expires_at" in sql
    # Security posture unchanged from migration 51
    assert "security definer" in sql
    assert "set search_path = 'core', 'public'" in sql
    # GRANT survives the CREATE OR REPLACE
    assert "grant execute on function core.ops_finalize" in sql
    assert "to service_role" in sql
    # Tail
    assert "begin;" in sql
    assert "commit;" in sql
    assert "notify pgrst, 'reload schema'" in sql


def test_down_migration_restores_old_body():
    sql = DOWN.read_text(encoding="utf-8").lower()
    assert "create or replace function core.ops_finalize" in sql
    # Critical: the down version must NOT assign expires_at (mention in the
    # header comment is fine; an `expires_at =` in the UPDATE body is not).
    assert "expires_at =" not in sql
    assert "interval '7 days'" not in sql
    assert "case" not in sql or "case" in sql.split("$$")[0]  # no CASE in body
    assert "updated_at = now()" in sql
    assert "grant execute on function core.ops_finalize" in sql
    assert "begin;" in sql
    assert "commit;" in sql
