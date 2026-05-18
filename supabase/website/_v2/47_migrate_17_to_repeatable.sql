-- Phase 8.0 Rev+: migrate stale 17_content_rpcs manifest row to repeatable form.
--
-- Context: 17_content_rpcs.sql's body was changed (RPC
-- content.upsert_canonical_zettel ON CONFLICT target → (normalized_url) for
-- URL-identity dedup, PR #25), so its committed checksum no longer matches the
-- core._migrations_applied row recorded 2026-05-09. The object is a
-- CREATE OR REPLACE FUNCTION code-object, so it is re-classified as a
-- Repeatable (repeatable/R__content_rpcs.sql); apply_migrations.py's
-- repeatable-loop re-records it under its new name on next deploy. This
-- versioned migration deletes the now-orphan versioned row so the
-- versioned-loop stops failing with CHECKSUM MISMATCH.
--
-- Ordering invariant (verified in apply_migrations.py main()):
--   versioned-loop (this file runs)  →  repeatable-loop (R__ file runs)
-- so the DELETE here lands before R__'s INSERT.

DELETE FROM core._migrations_applied
 WHERE name = '17_content_rpcs.sql';

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
