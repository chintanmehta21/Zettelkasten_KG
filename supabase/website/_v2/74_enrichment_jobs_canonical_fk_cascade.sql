-- 74_enrichment_jobs_canonical_fk_cascade.sql — wire enrichment-job rows to
-- their canonical zettel with ON DELETE CASCADE.
--
-- Why: migration 60 declared core.zettel_enrichment_jobs.canonical_zettel_id
-- as plain `uuid NOT NULL` — there is no foreign-key constraint linking the
-- job row to content.canonical_zettels at all. The forensic sweep on
-- 2026-05-25 found an orphan: a `succeeded` chunk_embed job pointing at a
-- canonical_zettel_id that no longer exists (the canonical was hard-deleted
-- post-success without cascading to the job queue). The fix has two parts,
-- both inside this single transaction:
--
--   (a) Pre-clean any current orphans. They are by definition unreachable
--       (the canonical they describe is gone), so they can be dropped
--       safely; otherwise the ADD CONSTRAINT below would fail. Guarded by
--       a hard-fail if the orphan count exceeds 100 — that volume suggests
--       data corruption beyond this fix's scope and needs operator triage.
--   (b) Add the FK with ON DELETE CASCADE so any future canonical purge
--       (purge_dirty_zettels.py, manual cleanup, partition retention, …)
--       can never again leave a dangling enrichment_job behind. The
--       chunk_embed worker then never hits the
--       canonical_chunks_canonical_zettel_id_fkey FK violation that
--       previously surfaced in dead-letter rows.
--
-- Versioned, immutable (schema-drift gate frozen). Co-applies with deploy.

BEGIN;

DO $$
DECLARE
    v_orphan_count int;
BEGIN
    SELECT COUNT(*) INTO v_orphan_count
      FROM core.zettel_enrichment_jobs j
     WHERE NOT EXISTS (
        SELECT 1 FROM content.canonical_zettels c
         WHERE c.id = j.canonical_zettel_id
     );

    RAISE NOTICE 'enrichment_jobs FK pre-cleanup: % orphan row(s) detected',
        v_orphan_count;

    -- Safety brake: catastrophic orphan volume implies the FK add itself is
    -- masking a deeper data-integrity bug. Surface the count and fail; an
    -- operator-driven sweep should land separately before this migration.
    IF v_orphan_count > 100 THEN
        RAISE EXCEPTION
            'enrichment_jobs orphan count % exceeds safety brake 100 — '
            'investigate before applying this migration',
            v_orphan_count
            USING ERRCODE = '22023';
    END IF;

    IF v_orphan_count > 0 THEN
        DELETE FROM core.zettel_enrichment_jobs j
         WHERE NOT EXISTS (
            SELECT 1 FROM content.canonical_zettels c
             WHERE c.id = j.canonical_zettel_id
         );
        RAISE NOTICE 'enrichment_jobs FK pre-cleanup: deleted % orphan row(s)',
            v_orphan_count;
    END IF;
END;
$$;

-- Defensive: drop the constraint if a prior partial apply left it behind, so
-- this migration is safely re-runnable.
ALTER TABLE core.zettel_enrichment_jobs
    DROP CONSTRAINT IF EXISTS enrichment_jobs_canonical_fk;

ALTER TABLE core.zettel_enrichment_jobs
    ADD CONSTRAINT enrichment_jobs_canonical_fk
    FOREIGN KEY (canonical_zettel_id)
    REFERENCES content.canonical_zettels(id)
    ON DELETE CASCADE;

COMMENT ON CONSTRAINT enrichment_jobs_canonical_fk
    ON core.zettel_enrichment_jobs IS
    'Added 2026-05-25 (migration 74). Cascade-delete prevents orphan jobs '
    'after any future canonical hard-delete.';

COMMIT;

NOTIFY pgrst, 'reload schema';
