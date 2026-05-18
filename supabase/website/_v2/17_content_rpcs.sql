-- supabase/website/_v2/17_content_rpcs.sql
-- Phase 1.C: SECURITY DEFINER RPCs for the content schema.
-- Used by ContentRepository.upsert_canonical_zettel (Phase-2.0 prereq for Phase 4).

CREATE OR REPLACE FUNCTION content.upsert_canonical_zettel(
    p_normalized_url   text,
    p_content_hash     bytea,
    p_source_type      text,
    p_title            text,
    p_body_md          text,
    p_publication_date date,
    p_source_metadata  jsonb
) RETURNS TABLE (id uuid, was_new boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    -- 2026-05-19 (D6 reversal → Option B singleton + content-hash change
    -- detection, operator-approved via Research methodology): under master's
    -- singleton UNIQUE(normalized_url) (46_url_dedup), a re-ingest of the same
    -- URL with CHANGED source content MUST replace the canonical row's content
    -- (industry-standard upsert/replace-on-change — LangChain/LlamaIndex).
    -- The prior `DO UPDATE SET normalized_url = EXCLUDED.normalized_url`
    -- self-assign returned the row but SILENTLY DROPPED changed content (only
    -- the URL was self-assigned). We now DO UPDATE every content column:
    -- identical re-ingest writes a value-equal tuple (idempotent — the
    -- deterministic content_hash makes it stable); changed content is
    -- persisted in place; the caller re-derives child chunks/KG. Still
    -- returns the row from RETURNING and (xmax = 0) still correctly
    -- identifies inserter vs updater under concurrent contention (NOT
    -- DO NOTHING, which returns zero rows + breaks was-new detection).
    -- A pure zero-write no-op on byte-identical re-ingest is a separate
    -- follow-up micro-optimization; intentionally NOT bundled into this merge.
    RETURN QUERY
        INSERT INTO content.canonical_zettels (
            normalized_url, content_hash, source_type, title,
            body_md, publication_date, source_metadata
        )
        VALUES (
            p_normalized_url, p_content_hash, p_source_type, p_title,
            p_body_md, p_publication_date, p_source_metadata
        )
        ON CONFLICT (normalized_url)
        DO UPDATE SET
            content_hash     = EXCLUDED.content_hash,
            source_type      = EXCLUDED.source_type,
            title            = EXCLUDED.title,
            body_md          = EXCLUDED.body_md,
            publication_date = EXCLUDED.publication_date,
            source_metadata  = EXCLUDED.source_metadata
        RETURNING canonical_zettels.id, (xmax = 0) AS was_new;
END $$;

GRANT EXECUTE ON FUNCTION content.upsert_canonical_zettel(text, bytea, text, text, text, date, jsonb)
    TO authenticated, service_role;

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
