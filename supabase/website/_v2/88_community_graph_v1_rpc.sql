-- Migration 88 (Community Graph Part B / Phase 0 — P0-c cont.): the forced-
-- predicate community read RPC. This is the ONLY read path for the community
-- surface (design D3/D4 — the predicate lives in the DB, not re-implemented in
-- Python). SECURITY DEFINER + OWNED BY community_reader means the body runs as
-- the non-BYPASSRLS role: a forgotten predicate fails closed via the RLS policy
-- from migration 87.
--
-- OPT-OUT predicate: returns PUBLIC nodes only (is_private = false AND
-- deleted_at IS NULL), deduped by canonical_zettel_id (one canonical saved by N
-- users => ONE node). NO user_id, NO owner_profile_id, NO made_private_at.
-- Attribution = the owner's display_name (the chosen public-attribution model;
-- anonymous mode is deferred). Node id is opaque + derived from the canonical id
-- (NOT user_id, so the id itself cannot fingerprint a user), matching the
-- existing assembler node-id convention ({prefix}-{canonical[:N]}).
--
-- Mirrors 81_profile_stats_v1_rpc.sql's SECURITY DEFINER + REVOKE/GRANT idiom.
-- This is a CREATE OR REPLACE code-object, but it is kept VERSIONED (not in
-- repeatable/R__) because it carries one-time ownership DDL (ALTER FUNCTION
-- OWNER) that must run AFTER role 87 exists; see plan DESIGN DECISIONS.

BEGIN;

CREATE OR REPLACE FUNCTION content.community_graph_v1(
    p_limit int DEFAULT 5000,
    p_min_strength float DEFAULT 0.0
)
RETURNS TABLE (
    canonical_zettel_id uuid,
    node_id             text,
    title               text,
    source_type         text,
    url                 text,
    author_display_name text,
    contributor_count   int
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- Per-call safety net (independent of role-level settings on community_reader).
  SET LOCAL statement_timeout = '30s';
  SET LOCAL work_mem = '32MB';

  RETURN QUERY
  WITH public_rows AS (
    SELECT
      cz.id                AS canonical_zettel_id,
      cz.title             AS title,
      cz.source_type       AS source_type,
      cz.normalized_url    AS url,
      -- Attribution: earliest saver's display_name (public-by-default model).
      (ARRAY_AGG(p.display_name ORDER BY wz.created_at ASC NULLS LAST))[1]
                           AS author_display_name,
      COUNT(DISTINCT wz.workspace_id)::int AS contributor_count
    FROM content.workspace_zettels wz
    JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id
    JOIN core.workspaces w           ON w.id  = wz.workspace_id
    JOIN core.profiles   p           ON p.id  = w.owner_profile_id
    WHERE wz.is_private = false      -- the forced opt-out predicate (D3, Rev 3)
      AND wz.deleted_at IS NULL
    GROUP BY cz.id, cz.title, cz.source_type, cz.normalized_url
  )
  SELECT
    public_rows.canonical_zettel_id,
    'web-' || left(public_rows.canonical_zettel_id::text, 12) AS node_id,
    public_rows.title,
    public_rows.source_type,
    public_rows.url,
    public_rows.author_display_name,
    public_rows.contributor_count
  FROM public_rows
  ORDER BY public_rows.canonical_zettel_id
  LIMIT GREATEST(1, LEAST(p_limit, 10000));
END
$$;

-- The function must run AS community_reader (non-BYPASSRLS) so the RLS policy
-- bites if the predicate is ever dropped. OWNER change is the load-bearing DDL.
ALTER FUNCTION content.community_graph_v1(int, float) OWNER TO community_reader;

-- The app calls this via the service_role connection; only service_role needs
-- EXECUTE. Deny PUBLIC/anon/authenticated (no direct PostgREST exposure).
REVOKE ALL ON FUNCTION content.community_graph_v1(int, float) FROM public;
GRANT EXECUTE ON FUNCTION content.community_graph_v1(int, float) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
