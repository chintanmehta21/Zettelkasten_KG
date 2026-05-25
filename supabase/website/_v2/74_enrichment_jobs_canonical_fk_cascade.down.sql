-- 74_enrichment_jobs_canonical_fk_cascade.down.sql — revert migration 74.
--
-- Drops the enrichment_jobs_canonical_fk FK. Note that the DELETE of
-- pre-existing orphans in the forward migration is NOT reversed — those
-- rows were unreachable by definition (their canonical was already gone),
-- so resurrecting them is not possible from the down migration alone.

BEGIN;

ALTER TABLE core.zettel_enrichment_jobs
    DROP CONSTRAINT IF EXISTS enrichment_jobs_canonical_fk;

COMMIT;

NOTIFY pgrst, 'reload schema';
