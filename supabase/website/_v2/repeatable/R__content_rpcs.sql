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
    -- Round-2 R2.6: ON CONFLICT DO UPDATE SET normalized_url = EXCLUDED.normalized_url
    -- (literal no-op self-assign) — DO NOTHING would return zero rows on conflict and
    -- break the (xmax = 0) was-new detection. The self-assign returns the row from
    -- RETURNING and xmax correctly identifies the inserter under concurrent contention.
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
        DO UPDATE SET normalized_url = EXCLUDED.normalized_url
        RETURNING canonical_zettels.id, (xmax = 0) AS was_new;
END $$;

GRANT EXECUTE ON FUNCTION content.upsert_canonical_zettel(text, bytea, text, text, text, date, jsonb)
    TO authenticated, service_role;


-- ──────────────────────────────────────────────────────────────────────────
-- content.upsert_workspace_zettel
-- ──────────────────────────────────────────────────────────────────────────
-- Why an RPC is required (was: thin PostgREST `.upsert()` call):
--   Migration 66_workspace_zettels_partial_indexes.sql replaced the table-
--   level UNIQUE (workspace_id, canonical_zettel_id) with a PARTIAL UNIQUE
--   INDEX that filters `WHERE deleted_at IS NULL` (so soft-deleted rows
--   stop occupying the unique slot — see PR exec/DB_delete_zettel_refine--1
--   for the visible-Trash + Restore UX rationale).
--
--   PostgREST's `?on_conflict=col1,col2` URL grammar can ONLY match a FULL
--   unique constraint — it cannot specify the index predicate required for
--   partial-index inference. Postgres tracks this limitation as PostgREST
--   issue #2123 (open since 2022, still unresolved). The maintainer-
--   endorsed workaround is a server-side function (see Supabase discussion
--   #12565). Result without this RPC: every /api/zettels/add raised
--     postgrest.exceptions.APIError 42P10
--     "there is no unique or exclusion constraint matching the ON CONFLICT
--     specification"
--   and the operation surfaced as kg-write-failed 502 to the client.
--
--   Postgres native syntax `ON CONFLICT (col1, col2) WHERE pred DO UPDATE`
--   correctly drives partial-index inference (PG ≥ 15) — the predicate has
--   to be textually-semantically identical to the index's WHERE clause, so
--   this function uses `WHERE deleted_at IS NULL` to match
--   `uq_workspace_zettel_active`.
--
-- Semantics (mirrors the intent of migration 66, NOT the legacy upsert):
--   1. No live row exists for (workspace_id, canonical_zettel_id) — INSERT
--      a fresh row with deleted_at = NULL. Soft-deleted tombstones for the
--      same pair remain in the trash table untouched (the partial index
--      does not see them).
--   2. A live row exists — UPDATE that row in place, refresh ai_summary /
--      engine_version / user_tags / user_note / pinned / added_via and
--      bump updated_at.
--   3. Restoring a soft-deleted row is intentionally NOT this RPC's job;
--      restore_workspace_zettel handles that explicit user action.
--
-- Concurrency:
--   INSERT ... ON CONFLICT DO UPDATE is atomic (PG docs: "atomic INSERT or
--   UPDATE outcome"). Two concurrent inserters race on the partial index;
--   one wins, the other's speculative insert is converted to UPDATE. No
--   SERIALIZABLE / explicit advisory lock needed.
--
-- Security:
--   SECURITY DEFINER + `SET search_path = public` matches the existing
--   upsert_canonical_zettel pattern (the caller is the service_role JWT
--   bearer, not an end-user; RLS is bypassed by design here because the
--   Python repository already enforces the workspace_id boundary upstream).
--
-- Args / return are typed scalars (not jsonb) so supabase-py kwargs match
-- the call site exactly and PostgREST's OpenAPI surfaces them cleanly.
-- 2026-05-24 (Phase 4 / Task 4.3 / B7): added `p_derived_tags` for the new
-- `workspace_zettels.derived_tags` column (Mig 72). DEFAULT NULL keeps the
-- prior 8-arg call shape working during the deploy window, then the Python
-- repository starts passing it explicitly. The OLD 8-arg signature is
-- explicitly dropped because PostgreSQL overloads functions by signature
-- and we don't want a stale GRANTed copy lingering after the redeploy.
DROP FUNCTION IF EXISTS content.upsert_workspace_zettel(
    uuid, uuid, text, text, text[], text, boolean, text
);

CREATE OR REPLACE FUNCTION content.upsert_workspace_zettel(
    p_workspace_id              uuid,
    p_canonical_zettel_id       uuid,
    p_ai_summary                text,
    p_ai_summary_engine_version text,
    p_user_tags                 text[],
    p_user_note                 text,
    p_pinned                    boolean,
    p_added_via                 text,
    p_derived_tags              text[] DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_id uuid;
BEGIN
    INSERT INTO content.workspace_zettels AS wz (
        workspace_id,
        canonical_zettel_id,
        ai_summary,
        ai_summary_engine_version,
        user_tags,
        derived_tags,
        user_note,
        pinned,
        added_via
    )
    VALUES (
        p_workspace_id,
        p_canonical_zettel_id,
        p_ai_summary,
        p_ai_summary_engine_version,
        COALESCE(p_user_tags, '{}'::text[]),
        COALESCE(p_derived_tags, '{}'::text[]),
        p_user_note,
        COALESCE(p_pinned, false),
        COALESCE(p_added_via, 'website')
    )
    ON CONFLICT (workspace_id, canonical_zettel_id) WHERE deleted_at IS NULL
    DO UPDATE SET
        ai_summary                = EXCLUDED.ai_summary,
        ai_summary_engine_version = EXCLUDED.ai_summary_engine_version,
        user_tags                 = EXCLUDED.user_tags,
        derived_tags              = EXCLUDED.derived_tags,
        user_note                 = EXCLUDED.user_note,
        pinned                    = EXCLUDED.pinned,
        added_via                 = EXCLUDED.added_via,
        updated_at                = now()
    RETURNING wz.id INTO v_id;

    RETURN v_id;
END $$;

GRANT EXECUTE ON FUNCTION content.upsert_workspace_zettel(uuid, uuid, text, text, text[], text, boolean, text, text[])
    TO authenticated, service_role;


NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
