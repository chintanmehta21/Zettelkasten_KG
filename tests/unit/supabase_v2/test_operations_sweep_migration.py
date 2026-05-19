from pathlib import Path

MIG = Path("supabase/website/_v2/49_operations_sweep.sql")


def test_operations_sweep_migration_exists_and_well_formed():
    sql = MIG.read_text(encoding="utf-8").lower()
    # Transaction wrapper (matches 48_operations.sql house style)
    assert "begin" in sql
    assert "commit" in sql
    # pg_cron schedule call present
    assert "cron.schedule" in sql
    # Correct jobname for this sweep job
    assert "jobname" in sql
    assert "'sweep_stale_operations'" in sql
    # Idempotent guard — mirrors 37's DO $$ IF NOT EXISTS pattern.
    # Assert both halves separately; multiline formatting splits them across lines.
    assert "if not exists" in sql
    assert "select 1 from cron.job where jobname" in sql
    # TTL-GC intent: removes rows past expires_at (covers stuck-accepted rows
    # as a subset; simplest correct form avoids redundant status predicate —
    # a SQL comment in the migration explains this explicitly)
    assert "delete from core.operations where expires_at < now()" in sql
    # Hourly cadence
    assert "'0 * * * *'" in sql
    # NOTIFY matches 48 house convention
    assert "notify pgrst, 'reload schema'" in sql
