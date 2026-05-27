-- 82_stats_route_helpers.sql
-- Two SECURITY DEFINER helper RPCs for the User Stats route layer:
--
--   1. core.profile_stats_etag_probe_v1(p_workspace_id uuid) RETURNS jsonb
--      Cheap 3-table mutation timestamp probe. Returns the latest
--      created_at across content.workspace_zettels, rag.chat_messages,
--      kg.kg_edges. Route hashes these + caps_config_version sentinel
--      to derive ETag; matches -> 304 short-circuit on the route.
--
--   2. billing.pricing_get_quota_snapshot_batch(p_profile_id uuid, p_features jsonb)
--      Wraps billing.pricing_get_quota_snapshot for batched (zettel +
--      kasten + rag_question) calls. Avoids 3-roundtrip N+1 from the
--      Python route. Caps come from Python config (PLAN_CAPS), passed
--      in as p_features jsonb shape:
--        [{"feature": "zettel", "caps": {...}, "wallet_meter": "..."}, ...]
--      Returns a jsonb array of snapshots (one per input element).
--
-- Both: STABLE + SECURITY DEFINER. Per-call statement_timeout '5s' since
-- these are intentionally tiny (single SELECT or 3 RPC fan-out). Larger
-- queries would defeat the cache-probe pattern.
--
-- Apply via standard runner (transactional CREATE OR REPLACE FUNCTION).

BEGIN;

-- ─── ETag probe RPC ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION core.profile_stats_etag_probe_v1(p_workspace_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  SET LOCAL statement_timeout = '5s';

  -- Scope check: same predicate as core.profile_stats_v1.
  IF NOT (p_workspace_id = ANY (core.jwt_workspace_ids())
          OR core.is_service_role()) THEN
    RAISE EXCEPTION 'workspace not accessible' USING ERRCODE = '42501';
  END IF;

  RETURN jsonb_build_object(
    'latest_zettel_at', (
      SELECT max(created_at) FROM content.workspace_zettels
       WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
    ),
    'latest_chat_at', (
      SELECT max(created_at) FROM rag.chat_messages
       WHERE workspace_id = p_workspace_id
    ),
    'latest_kg_edge_at', (
      SELECT max(created_at) FROM kg.kg_edges
       WHERE workspace_id = p_workspace_id
    )
  );
END;
$$;

REVOKE ALL ON FUNCTION core.profile_stats_etag_probe_v1(uuid) FROM public;
GRANT EXECUTE ON FUNCTION core.profile_stats_etag_probe_v1(uuid)
  TO authenticated, stats_reader, service_role;


-- ─── Batched quota snapshot RPC ─────────────────────────────────────

CREATE OR REPLACE FUNCTION billing.pricing_get_quota_snapshot_batch(
  p_profile_id uuid,
  p_features   jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_feature_def jsonb;
  v_result jsonb := '[]'::jsonb;
  v_snapshot jsonb;
BEGIN
  SET LOCAL statement_timeout = '5s';

  -- Identity check: caller can only batch-snapshot their own profile.
  -- Service role bypass for backfill / admin tooling.
  IF NOT (p_profile_id = auth.uid() OR core.is_service_role()) THEN
    RAISE EXCEPTION 'profile not accessible' USING ERRCODE = '42501';
  END IF;

  -- Iterate the requested features and aggregate snapshots into an array.
  FOR v_feature_def IN SELECT * FROM jsonb_array_elements(p_features)
  LOOP
    v_snapshot := billing.pricing_get_quota_snapshot(
      p_profile_id,
      v_feature_def->>'feature',
      COALESCE(v_feature_def->'caps', '{}'::jsonb),
      v_feature_def->>'wallet_meter'
    );
    v_result := v_result || jsonb_build_array(
      jsonb_build_object('feature', v_feature_def->>'feature') || v_snapshot
    );
  END LOOP;

  RETURN v_result;
END;
$$;

REVOKE ALL ON FUNCTION billing.pricing_get_quota_snapshot_batch(uuid, jsonb) FROM public;
GRANT EXECUTE ON FUNCTION billing.pricing_get_quota_snapshot_batch(uuid, jsonb)
  TO authenticated, service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
