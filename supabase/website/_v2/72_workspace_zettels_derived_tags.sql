-- Migration 72 (Phase 4 / B7): separate derived/system tags from user tags.
--
-- (Plan-numbered "Migration 50" in 2026-05-23-kg-render-correctness-overhaul.md;
-- bumped to 72 because slots 50-71 are taken in this repo.)
--
-- Today: derive_pseudo_tags() appends `source_domain:youtube.com`,
-- `modality:video`, `speaker:<slug>` to `augmented_tags`, which is then
-- persisted as `user_tags`. Those appear in the user's side-panel tag chips
-- and the tag-filter dropdown as if they were typed by the user.
--
-- Fix: add a sibling column `derived_tags text[]`. The scorer still unions
-- both sets internally (the union is computed in kg_population), but the
-- wire/UI separation is clean — only `user_tags` reach the frontend's
-- panel + filter UI.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + the WHERE-fenced backfill skips
-- rows that have already been migrated.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  ALTER TABLE content.workspace_zettels
    ADD COLUMN IF NOT EXISTS derived_tags text[] NOT NULL DEFAULT '{}'::text[];

  -- One-shot backfill: identify rows where user_tags contains derived-style
  -- prefixes (`source_domain:`, `modality:`, `speaker:`) and migrate them.
  UPDATE content.workspace_zettels
     SET derived_tags = ARRAY(
           SELECT t FROM unnest(user_tags) AS t
            WHERE t LIKE 'source_domain:%' OR t LIKE 'modality:%' OR t LIKE 'speaker:%'
         ),
         user_tags = ARRAY(
           SELECT t FROM unnest(user_tags) AS t
            WHERE t NOT LIKE 'source_domain:%' AND t NOT LIKE 'modality:%' AND t NOT LIKE 'speaker:%'
         )
   WHERE EXISTS (
         SELECT 1 FROM unnest(user_tags) AS t
          WHERE t LIKE 'source_domain:%' OR t LIKE 'modality:%' OR t LIKE 'speaker:%'
       );
COMMIT;

COMMENT ON COLUMN content.workspace_zettels.derived_tags IS
  'System-derived tags from pseudo_tags.derive_pseudo_tags (e.g. source_domain:, modality:, speaker:). Never shown in user-facing UI; scorer still unions with user_tags internally.';
