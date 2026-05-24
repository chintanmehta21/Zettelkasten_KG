-- Migration 73 (Phase 4 / X5): NFKC + lower + strip canonical form for user_tags.
--
-- (Plan-numbered "Migration 50" in 2026-05-23-kg-render-correctness-overhaul.md;
-- bumped to 73 because slots 50-72 are taken in this repo.)
--
-- Today: tags persist as the raw user-typed string. Two visually-identical
-- tags from disparate Unicode forms (`Café` typed as NFD vs NFC, full-width
-- digits, ligatures) hash to different bucket keys and fragment the
-- /knowledge-graph filter chip UI into duplicates.
--
-- Fix: rewrite content.workspace_zettels.user_tags in-place with the same
-- canonical form the new website.core.text_polish.normalize_tag() uses:
--   NFKC normalize  +  trim  +  lower.
--
-- DEVIATION FROM PLAN: the plan's SQL used `unaccent(t)` which would strip
-- accents (café -> cafe). That conflicts with the Python normalize_tag
-- (NFKC-only — does NOT strip accents). Postgres `normalize(t, NFKC)`
-- (PG 13+, Supabase runs PG 15+) matches the Python implementation exactly.
-- Required-extension list is unchanged: vanilla `normalize` lives in core SQL.
--
-- Idempotent: the WHERE clause skips rows already in canonical form.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  UPDATE content.workspace_zettels
     SET user_tags = ARRAY(
           SELECT DISTINCT lower(trim(normalize(t, NFKC)))
             FROM unnest(user_tags) AS t
            WHERE t IS NOT NULL AND length(trim(t)) > 0
         )
   WHERE user_tags <> ARRAY(
           SELECT DISTINCT lower(trim(normalize(t, NFKC)))
             FROM unnest(user_tags) AS t
            WHERE t IS NOT NULL AND length(trim(t)) > 0
         );
COMMIT;
