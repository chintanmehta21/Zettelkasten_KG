-- 81_profile_stats_v1_rpc.sql
-- User Statistics SECURITY DEFINER aggregation RPC (scaffold + meta only).
--
-- Returns a JSONB with: meta + 7 empty section placeholders that Tasks 3.1-3.7
-- will populate. Cross-tenant access is denied with ERRCODE 42501 (route maps
-- to 403). Hard timeouts (45s/32MB) are also set role-side on stats_reader
-- (migration 79); the SET LOCAL here is the per-call safety net independent
-- of role-level settings (the RPC runs SECURITY DEFINER as its owner, which
-- in Supabase is the migration-applying role — not stats_reader directly).
--
-- DESIGN DECISION (research-locked 2026-05-27): this RPC stays PURE-OLTP and
-- does NOT touch billing.*. Pricing composition (quota "used vs available")
-- is done in the FastAPI route by calling billing.pricing_get_quota_snapshot
-- separately and merging in Python. Rationale: keeps SECURITY DEFINER scope
-- narrow (audit surface = content/kg/rag/core only), allows cap changes in
-- Python config without DB migration, ETag composition is cleaner. See
-- docs/claude_audits/user_stats_architecture_research_2026-05-26.md and the
-- 3 research subagent reports cited in PR #118.
--
-- Scope check uses the canonical core.jwt_workspace_ids() + core.is_service_role()
-- helpers from 01_core_schema.sql (lines 95 + 120). Mirrors the kasten-RPC
-- pattern in 13_v2_kasten_rpcs.sql (which predates is_service_role() and uses
-- the inline current_setting()::jsonb form); new code prefers the helper.
--
-- Applied via the standard runner (BEGIN/COMMIT wrap is safe for plain
-- CREATE OR REPLACE FUNCTION — no DDL conflicts with autocommit).

BEGIN;

CREATE OR REPLACE FUNCTION core.profile_stats_v1(p_workspace_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_payload jsonb;
BEGIN
  -- Per-call safety net (independent of role-level settings on stats_reader).
  SET LOCAL statement_timeout = '45s';
  SET LOCAL work_mem = '32MB';

  -- Scope check: caller's auth context must include this workspace.
  -- Mirrors the kasten-RPC pattern in 13_v2_kasten_rpcs.sql §workspace-scope.
  IF NOT (p_workspace_id = ANY (core.jwt_workspace_ids())
          OR core.is_service_role()) THEN
    RAISE EXCEPTION 'workspace not accessible' USING ERRCODE = '42501';
  END IF;

  -- Scaffold payload: meta + 7 empty section placeholders.
  -- Sections to be populated by Tasks 3.1-3.7:
  --   main_board   — heatmap + zettel quota + kasten quota (Task 3.1)
  --   general      — member since + 30d delta + KG size + source diversity + plan (Task 3.2)
  --   zettel       — top source + latest + avg summary chars + tag stats (Task 3.3)
  --   kasten       — largest + conv depth + cited source + question streak (Task 3.4)
  --   domain       — HHI + emerging + declining (Task 3.5)
  --   activity     — streaks + week-over-week + chat-vs-capture (Task 3.6)
  --   graph        — mean degree + hubs + tag coverage + relation mix (Task 3.7)
  v_payload := jsonb_build_object(
    'meta', jsonb_build_object(
      'workspace_id', p_workspace_id::text,
      'computed_at', now(),
      'schema_version', 1
    ),
    'main_board', '{}'::jsonb,
    'general',    '{}'::jsonb,
    'zettel',     '{}'::jsonb,
    'kasten',     '{}'::jsonb,
    'domain',     '{}'::jsonb,
    'activity',   '{}'::jsonb,
    'graph',      '{}'::jsonb
  );

  RETURN v_payload;
END;
$$;

-- Tighten access: deny PUBLIC, grant only authenticated + stats_reader +
-- service_role. authenticated triggers the SECURITY DEFINER + scope check;
-- stats_reader is NOLOGIN (migration 79) and exists as the documented OWNER
-- role for the SELECT grant surface; service_role bypasses scope.
REVOKE ALL ON FUNCTION core.profile_stats_v1(uuid) FROM public;
GRANT EXECUTE ON FUNCTION core.profile_stats_v1(uuid)
  TO authenticated, stats_reader, service_role;

COMMIT;

-- PostgREST schema-cache reload so the RPC is callable via .rpc(...) without
-- the post-migration 2s sleep being load-bearing.
NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
