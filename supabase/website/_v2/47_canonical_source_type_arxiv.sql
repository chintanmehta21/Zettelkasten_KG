-- 47 — Widen content.canonical_zettels.source_type CHECK to every emitted type
--
-- BUG (observed via real Naruto ingestion through the create_kasten runner):
--   arXiv abstract URLs (https://arxiv.org/abs/...) failed with
--   "Knowledge-graph write failed; the zettel was not saved." and the zettel
--   was NOT persisted at all.
--
-- ROOT CAUSE:
--   summarization_engine.core.models.SourceType emits one of:
--     github, newsletter, reddit, youtube, hackernews, linkedin, arxiv,
--     podcast, twitter, web
--   but the original CHECK only allowed:
--     youtube, reddit, github, twitter, substack, newsletter, medium, web,
--     generic
--   So 'arxiv' (and latently 'hackernews', 'linkedin', 'podcast') violated the
--   CHECK inside content.upsert_canonical_zettel's INSERT. That raised, was
--   caught by website.core.persist.persist_summarized_result's generic
--   handler, and re-raised as SupabaseV2PersistError — a non-200 that aborts
--   the WHOLE canonical zettel write. KG enrichment is fire-and-forget and was
--   never on this path; the canonical write itself failed the constraint.
--
-- FIX:
--   Replace the CHECK with the union of every emitted SourceType value PLUS
--   the historical sub-route flavors already persisted (substack, medium,
--   generic). New values are strictly added; nothing is removed, so every
--   existing row still satisfies the constraint (no data migration needed).
--
-- Anti-pattern guards:
--   * Does NOT modify any function body (golden md5 unaffected).
--   * Idempotent: drops the known constraint name if present, re-adds the
--     widened one; safe to apply repeatedly.
--   * Forward-only, additive value set — no existing row can be invalidated.

BEGIN;

-- Postgres auto-names the inline CHECK ``<table>_<column>_check``.
ALTER TABLE content.canonical_zettels
    DROP CONSTRAINT IF EXISTS canonical_zettels_source_type_check;

ALTER TABLE content.canonical_zettels
    ADD CONSTRAINT canonical_zettels_source_type_check
    CHECK (source_type IN (
        'youtube', 'reddit', 'github', 'twitter', 'substack',
        'newsletter', 'medium', 'web', 'generic',
        'hackernews', 'linkedin', 'arxiv', 'podcast'
    ));

NOTIFY pgrst, 'reload schema';

COMMIT;
