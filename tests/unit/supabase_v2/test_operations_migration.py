from pathlib import Path

MIG = Path("supabase/website/_v2/48_operations.sql")


def test_operations_migration_exists_and_well_formed():
    sql = MIG.read_text(encoding="utf-8").lower()
    assert "create table if not exists core.operations" in sql
    # composite PK keeps it idempotent + BOLA-safe (user can't read another's op)
    assert "primary key (user_id, operation_id)" in sql
    assert "status text not null" in sql
    assert "check (status in ('accepted', 'succeeded', 'failed'))" in sql
    assert "response jsonb" in sql
    assert "error jsonb" in sql
    assert "request_hash text" in sql
    assert "expires_at timestamptz" in sql
    assert "create index if not exists" in sql and "expires_at" in sql
    # RLS: service-role only (route scopes by user_id), mirrors canonical_chunks
    assert "enable row level security" in sql
    assert "operations_service_all" in sql
    assert "core.is_service_role()" in sql
    assert "if exists" in sql and "if not exists" in sql
    assert "notify pgrst, 'reload schema'" in sql
    assert "comment on column core.operations.updated_at" in sql
