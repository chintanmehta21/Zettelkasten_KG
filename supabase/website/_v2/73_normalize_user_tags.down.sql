-- Migration 73 DOWN: there is no reverse for a one-shot canonicalisation
-- (the pre-normalisation Unicode/case/whitespace variants are irrecoverably
-- lost the moment the UPDATE commits). This file exists only so the
-- ops/scripts/apply_migrations.py harness can record the paired filename
-- without erroring. Restoring the pre-X5 form requires a backup restore.
SELECT 1;
