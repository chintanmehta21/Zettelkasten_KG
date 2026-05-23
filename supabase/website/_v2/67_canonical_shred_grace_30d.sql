-- 67_canonical_shred_grace_30d.sql — bump canonical-shred grace from 7 → 30 days.
--
-- Aligns the user-recovery window with the 2024-2026 B2C SaaS median:
-- Notion (since 17 Jun 2024), Apple Notes / iCloud, Drafts, Craft, Google
-- Drive, Google Photos, Google Messages — all 30 days. The previous 7-day
-- window sits at the aggressive end of the distribution and below user
-- mental model from those neighbouring apps.
--
-- Legal: 30 days is comfortably within GDPR Art. 17's 1-month "without
-- undue delay" wording, India DPDPA Rule 23's 1-year audit-log floor (the
-- audit log is unaffected), CCPA's 45-day response window, and LGPD's
-- 15-day rule (LGPD applies on formal erasure request which is a SEPARATE
-- path, not this casual-delete grace window).
--
-- This pairs with the new visible Trash UI (/home/zettels?view=trash) so
-- the 30 days isn't just an invisible backend window — users can browse
-- and restore from it.
--
-- Schema-neutral: only replaces a function body, no DDL on tables. The
-- function's SET search_path = pg_catalog, public clause is preserved
-- (originally set by 53_set_search_path_v2_functions.sql; CREATE OR
-- REPLACE without it would clear the setting, so we restate it).

CREATE OR REPLACE FUNCTION content.enqueue_canonical_shred_if_orphan(p_canonical_zettel_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    -- Guard 1: still actively referenced by another active workspace.
    IF EXISTS (
        SELECT 1
          FROM content.workspace_zettels wz
         WHERE wz.canonical_zettel_id = p_canonical_zettel_id
           AND wz.deleted_at IS NULL
    ) THEN
        RETURN;
    END IF;

    -- Guard 2: still cited by chat history (citation-aware orphan protection).
    -- Citations are jsonb arrays of {canonical_chunk_id: uuid, ...}; the
    -- UUID-regex pre-filter avoids casting malformed citations.
    IF EXISTS (
        SELECT 1
          FROM rag.chat_messages cm,
               jsonb_array_elements(cm.citations) c
         WHERE c ? 'canonical_chunk_id'
           AND (c ->> 'canonical_chunk_id') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
           AND (c ->> 'canonical_chunk_id')::uuid IN (
             SELECT id
               FROM content.canonical_chunks
              WHERE canonical_zettel_id = p_canonical_zettel_id
         )
    ) THEN
        RETURN;
    END IF;

    -- Enqueue physical purge 30 days out. The reaper job drains this queue
    -- when `shred_after <= now()` and writes `shredded_at` on completion.
    -- Bump-from-7d: applies to NEW enqueues only; rows already enqueued at
    -- 7-day grace keep their original shred_after — that's deliberate, we
    -- don't reach backwards into the queue.
    INSERT INTO core.soft_delete_queue (table_name, row_id, shred_after)
    VALUES (
        'content.canonical_zettels',
        p_canonical_zettel_id,
        now() + interval '30 days'
    )
    ON CONFLICT DO NOTHING;
END
$$;

NOTIFY pgrst, 'reload schema';
