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
  v_main_board jsonb;
  v_general jsonb;
  v_zettel jsonb;
  v_kasten jsonb;
  v_domain jsonb;
  v_activity jsonb;
  v_graph jsonb;
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

  -- ─── Main Board section ─────────────────────────────────────────────
  -- 1) 26-week activity heatmap: daily zettel count for the last 182 days,
  --    zero-filled via generate_series so client renders a complete grid.
  --    Bucketed by UTC date (core.profiles.timezone column does not exist;
  --    timezone-correct streaks are a v1.5 follow-up).
  -- 2) Lifetime + this-month zettel counts (RAW counters; quota composition
  --    lives in the Python route via billing.pricing_get_quota_snapshot).
  -- 3) Lifetime kasten count (RAW; quota composition same as zettels).

  WITH days AS (
    SELECT generate_series(
      (now() - interval '181 days')::date,
      now()::date,
      interval '1 day'
    )::date AS d
  ),
  buckets AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS d,
           count(*)::int AS n
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id
       AND deleted_at IS NULL
       AND created_at >= now() - interval '181 days'
     GROUP BY 1
  ),
  heatmap AS (
    SELECT COALESCE(
      jsonb_agg(
        jsonb_build_object('date', days.d, 'count', COALESCE(buckets.n, 0))
        ORDER BY days.d
      ),
      '[]'::jsonb
    ) AS cells
      FROM days LEFT JOIN buckets USING (d)
  )
  SELECT jsonb_build_object(
    'heatmap', (SELECT cells FROM heatmap),
    'zettels', jsonb_build_object(
      'lifetime_count', (
        SELECT count(*)
          FROM content.workspace_zettels
         WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
      ),
      'this_month_count', (
        SELECT count(*)
          FROM content.workspace_zettels
         WHERE workspace_id = p_workspace_id
           AND deleted_at IS NULL
           AND created_at >= date_trunc('month', now())
      )
    ),
    'kastens', jsonb_build_object(
      'lifetime_count', (
        SELECT count(*)
          FROM rag.kastens
         WHERE workspace_id = p_workspace_id
      )
    )
  ) INTO v_main_board;

  -- ─── General Overview section ─────────────────────────────────────────
  -- 1) Member since: joined_at + days_in_vault from core.profiles.created_at
  --    of the workspace owner.
  -- 2) Zettels last 30d: count + prev-30d count + delta_pct + 8-week sparkline
  --    (daily buckets aggregated to weeks for compact serialization).
  -- 3) KG size: nodes + edges count (workspace-scoped).
  -- 4) Source diversity: distinct source_type used vs total enum cardinality.
  --    NOTE: source_type is a CHECK constraint (text IN-list) in
  --    45_document_source_type.sql, NOT a pg_enum — so max_sources is hard-
  --    pinned to 13 (the IN-list cardinality at that migration). If the
  --    IN-list ever grows, update both here and 45_document_source_type.sql.
  --    The Python route does NOT need to compose plan here — plan tier comes
  --    from the separate pricing_get_quota_snapshot call.

  WITH owner_join AS (
    SELECT p.created_at AS joined_at
      FROM core.workspaces w
      JOIN core.profiles  p ON p.id = w.owner_profile_id
     WHERE w.id = p_workspace_id
     LIMIT 1
  ),
  zettel_30d AS (
    SELECT
      count(*) FILTER (WHERE created_at >= now() - interval '30 days') AS last30,
      count(*) FILTER (WHERE created_at >= now() - interval '60 days'
                         AND created_at <  now() - interval '30 days') AS prev30
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
  ),
  sparkline_days AS (
    SELECT generate_series(
      (now() - interval '55 days')::date,
      now()::date,
      interval '1 day'
    )::date AS d
  ),
  sparkline_buckets AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS dd,
           count(*)::int AS n
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id
       AND deleted_at IS NULL
       AND created_at >= now() - interval '55 days'
     GROUP BY 1
  ),
  sparkline_weekly AS (
    SELECT date_trunc('week', sparkline_days.d)::date AS week_start,
           SUM(COALESCE(sparkline_buckets.n, 0))::int AS week_count
      FROM sparkline_days
      LEFT JOIN sparkline_buckets ON sparkline_buckets.dd = sparkline_days.d
     GROUP BY 1
  )
  SELECT jsonb_build_object(
    'member_since', jsonb_build_object(
      'joined_at', (SELECT joined_at FROM owner_join),
      'days_in_vault',
        COALESCE((SELECT (now()::date - joined_at::date)::int FROM owner_join), 0)
    ),
    'zettels_30d', jsonb_build_object(
      'count', (SELECT last30 FROM zettel_30d),
      'prev_30d_count', (SELECT prev30 FROM zettel_30d),
      'delta_pct', CASE
        WHEN (SELECT prev30 FROM zettel_30d) = 0 THEN NULL
        ELSE round(
          100.0 *
          ((SELECT last30 FROM zettel_30d) - (SELECT prev30 FROM zettel_30d))
          / (SELECT prev30 FROM zettel_30d)::numeric,
          1
        )
      END,
      'sparkline_weekly', COALESCE(
        (SELECT jsonb_agg(
                  jsonb_build_object('week', week_start, 'count', week_count)
                  ORDER BY week_start
                ) FROM sparkline_weekly),
        '[]'::jsonb
      )
    ),
    'kg_size', jsonb_build_object(
      'nodes', (SELECT count(*) FROM kg.kg_nodes WHERE workspace_id = p_workspace_id),
      'edges', (SELECT count(*) FROM kg.kg_edges WHERE workspace_id = p_workspace_id)
    ),
    'source_diversity', jsonb_build_object(
      'distinct_sources', (
        SELECT count(DISTINCT cz.source_type)
          FROM content.workspace_zettels wz
          JOIN content.canonical_zettels  cz ON cz.id = wz.canonical_zettel_id
         WHERE wz.workspace_id = p_workspace_id AND wz.deleted_at IS NULL
      ),
      -- Hard-pinned to the CHECK-constraint IN-list cardinality (13) in
      -- 45_document_source_type.sql. Phase 0 discovery confirmed source_type
      -- is text + CHECK, not a pg_enum, so we cannot introspect it via pg_enum.
      'max_sources', 13
    )
  ) INTO v_general;

  -- ─── Zettel-level section ─────────────────────────────────────────────
  -- 1) top_source: most-used source_type (count + pct of total).
  -- 2) latest: most recently captured zettel (title + source_type + created_at).
  -- 3) avg_summary_chars: mean / min / max length of ai_summary.
  -- 4) avg_user_tags: mean count of entries in workspace_zettels.user_tags
  --    array (per-zettel mean). user_tags ONLY — never derived_tags.
  -- 5) tagged_coverage_pct: fraction (0.0-1.0) of zettels with >=1 user tag.

  WITH zw AS (
    SELECT wz.user_tags, wz.ai_summary, wz.created_at,
           cz.source_type, cz.title
      FROM content.workspace_zettels wz
      JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id
     WHERE wz.workspace_id = p_workspace_id AND wz.deleted_at IS NULL
  ),
  top_src AS (
    SELECT source_type, count(*)::int AS n
      FROM zw GROUP BY source_type ORDER BY n DESC NULLS LAST LIMIT 1
  ),
  latest_z AS (
    SELECT title, source_type, created_at
      FROM zw ORDER BY created_at DESC NULLS LAST LIMIT 1
  ),
  totals AS (
    SELECT count(*)::int AS n FROM zw
  )
  SELECT jsonb_build_object(
    'top_source', jsonb_build_object(
      'source_type', (SELECT source_type FROM top_src),
      'count', COALESCE((SELECT n FROM top_src), 0),
      'pct', CASE
        WHEN (SELECT n FROM totals) = 0 THEN NULL
        ELSE round(100.0 * (SELECT n FROM top_src) / (SELECT n FROM totals)::numeric, 1)
      END
    ),
    'latest', jsonb_build_object(
      'title', (SELECT title FROM latest_z),
      'source_type', (SELECT source_type FROM latest_z),
      'created_at', (SELECT created_at FROM latest_z)
    ),
    'avg_summary_chars', jsonb_build_object(
      'mean', COALESCE((SELECT round(avg(length(ai_summary)))::int FROM zw WHERE ai_summary IS NOT NULL), 0),
      'min', COALESCE((SELECT min(length(ai_summary)) FROM zw WHERE ai_summary IS NOT NULL), 0),
      'max', COALESCE((SELECT max(length(ai_summary)) FROM zw WHERE ai_summary IS NOT NULL), 0)
    ),
    'avg_user_tags',
      COALESCE((SELECT round(avg(COALESCE(array_length(user_tags, 1), 0))::numeric, 1) FROM zw), 0)::numeric(4,1),
    'tagged_coverage_pct',
      COALESCE((SELECT round(avg((COALESCE(array_length(user_tags, 1), 0) > 0)::int)::numeric, 3) FROM zw), 0)::numeric(4,3)
  ) INTO v_zettel;

  -- ─── Kasten-level section ────────────────────────────────────────────
  -- Product decision (2026-05-27): the "Kasten" UI tab shows BOTH
  -- Kasten-table stats AND chat retrieval stats. Stats 2-4 below technically
  -- come from rag.chat_messages, but the operator chose to label them under
  -- "Kasten" for the UI because users mentally associate chat sessions with
  -- the Kastens they're scoped to. This is a UI label, not a schema claim.
  --
  -- 1) largest: top-1 Kasten by non-deleted zettel count, with icon/color/last-add.
  -- 2) avg_conversation_depth: mean user-turn count per chat session (workspace-wide).
  -- 3) most_cited_source_type: source_type of canonical zettel most-cited in
  --    assistant messages (via chat_messages.citations jsonb array).
  -- 4) question_streak: gaps-and-islands on distinct days with >=1 user message.

  WITH kasten_sizes AS (
    SELECT k.id, k.name, k.icon, k.color, k.created_at,
           count(*) FILTER (WHERE wz.deleted_at IS NULL) AS n,
           max(kz.added_at) AS last_add
      FROM rag.kastens k
      LEFT JOIN rag.kasten_zettels kz ON kz.kasten_id = k.id
      LEFT JOIN content.workspace_zettels wz ON wz.id = kz.workspace_zettel_id
     WHERE k.workspace_id = p_workspace_id
     GROUP BY k.id
  ),
  largest_k AS (
    SELECT * FROM kasten_sizes ORDER BY n DESC NULLS LAST, created_at ASC LIMIT 1
  ),
  conv_depth AS (
    SELECT COALESCE(round(avg(turn_count)::numeric, 2), 0) AS d
      FROM (
        SELECT session_id, count(*) FILTER (WHERE role = 'user') AS turn_count
          FROM rag.chat_messages
         WHERE workspace_id = p_workspace_id
         GROUP BY session_id
         HAVING count(*) FILTER (WHERE role = 'user') > 0
      ) sessions
  ),
  citation_src AS (
    SELECT cz.source_type, count(*)::int AS n
      FROM rag.chat_messages m,
           LATERAL jsonb_array_elements(COALESCE(m.citations, '[]'::jsonb)) AS cit
      JOIN content.canonical_zettels cz ON cz.id = (cit->>'canonical_zettel_id')::uuid
     WHERE m.workspace_id = p_workspace_id AND m.role = 'assistant'
     GROUP BY cz.source_type
     ORDER BY n DESC NULLS LAST
     LIMIT 1
  ),
  q_days AS (
    SELECT DISTINCT (created_at AT TIME ZONE 'UTC')::date AS d
      FROM rag.chat_messages
     WHERE workspace_id = p_workspace_id AND role = 'user'
  ),
  q_runs AS (
    SELECT d, (d - (row_number() OVER (ORDER BY d))::int) AS g FROM q_days
  ),
  q_groups AS (
    SELECT g, count(*)::int AS c, min(d) AS s, max(d) AS e FROM q_runs GROUP BY g
  ),
  q_current AS (
    SELECT COALESCE((
      SELECT c FROM q_groups
       WHERE e = (now() AT TIME ZONE 'UTC')::date
          OR e = ((now() AT TIME ZONE 'UTC')::date - 1)
       ORDER BY e DESC LIMIT 1
    ), 0) AS c
  ),
  q_longest AS (
    SELECT COALESCE(max(c), 0) AS c FROM q_groups
  )
  SELECT jsonb_build_object(
    'largest', jsonb_build_object(
      'name', (SELECT name FROM largest_k),
      'icon', (SELECT icon FROM largest_k),
      'color', (SELECT color FROM largest_k),
      'zettel_count', COALESCE((SELECT n FROM largest_k), 0),
      'last_added_at', (SELECT last_add FROM largest_k),
      'age_days', COALESCE(
        (SELECT (now()::date - created_at::date)::int FROM largest_k),
        0
      )
    ),
    'avg_conversation_depth', (SELECT d FROM conv_depth),
    'most_cited_source_type', jsonb_build_object(
      'source_type', (SELECT source_type FROM citation_src),
      'count', COALESCE((SELECT n FROM citation_src), 0)
    ),
    'question_streak', jsonb_build_object(
      'current', (SELECT c FROM q_current),
      'longest', (SELECT c FROM q_longest)
    )
  ) INTO v_kasten;

  -- ─── Domain / Topic-level section ────────────────────────────────────
  -- Tag stats use user_tags ONLY (never derived_tags per CLAUDE.md rule).
  --
  -- Consultant adoption #1 (locked 2026-05-27): the LIFETIME baseline CTE
  -- is capped to the last 365 days, NOT all-time. Rationale: gives bounded
  -- compute (consultant report) AND makes emerging/declining semantically
  -- meaningful — comparing "last 30d share" vs "5-year-old baseline share"
  -- is noise. "Recent ramp vs trailing-year baseline" is what the user
  -- actually wants to see.
  --
  -- HHI is computed over the full 365d baseline (no LIMIT on the source
  -- rows; only the time window bounds the cost).

  WITH tag_rows AS (
    SELECT unnest(wz.user_tags) AS tag, wz.created_at
      FROM content.workspace_zettels wz
     WHERE wz.workspace_id = p_workspace_id
       AND wz.deleted_at IS NULL
       AND wz.created_at >= now() - interval '365 days'
  ),
  totals AS (
    SELECT tag, count(*)::numeric AS c FROM tag_rows GROUP BY tag
  ),
  totals_with_share AS (
    SELECT tag, c, (c / NULLIF(SUM(c) OVER (), 0)) AS share FROM totals
  ),
  hhi AS (
    SELECT COALESCE(round(SUM(share * share)::numeric, 4), 0) AS h
      FROM totals_with_share
  ),
  recent AS (
    SELECT tag, count(*)::numeric AS c,
           (count(*) / NULLIF(SUM(count(*)) OVER (), 0)) AS share
      FROM tag_rows
     WHERE created_at >= now() - interval '30 days'
     GROUP BY tag
  ),
  emerging AS (
    SELECT recent.tag, (recent.share - COALESCE(totals_with_share.share, 0)) AS delta
      FROM recent
      LEFT JOIN totals_with_share USING (tag)
     WHERE recent.c >= 2
     ORDER BY delta DESC LIMIT 5
  ),
  declining AS (
    SELECT totals_with_share.tag,
           (COALESCE(recent.share, 0) - totals_with_share.share) AS delta
      FROM totals_with_share
      LEFT JOIN recent USING (tag)
     WHERE totals_with_share.c >= 5
     ORDER BY delta ASC LIMIT 5
  )
  SELECT jsonb_build_object(
    'concentration_hhi', (SELECT h FROM hhi LIMIT 1),
    'emerging_top5', COALESCE(
      (SELECT jsonb_agg(
                jsonb_build_object('tag', tag, 'delta_share', round(delta::numeric, 4))
                ORDER BY delta DESC
              ) FROM emerging),
      '[]'::jsonb
    ),
    'declining_top5', COALESCE(
      (SELECT jsonb_agg(
                jsonb_build_object('tag', tag, 'delta_share', round(delta::numeric, 4))
                ORDER BY delta ASC
              ) FROM declining),
      '[]'::jsonb
    )
  ) INTO v_domain;

  -- ─── Activity / Engagement section ────────────────────────────────────
  -- Unified action stream = zettel-added UNION chat-sent (user) UNION kasten-created.
  -- Streaks bucketed by UTC date (core.profiles.timezone column does NOT exist
  -- per Phase 0 discovery — timezone-correct streaks are a v1.5 follow-up).
  --
  -- current_streak: most recent run ending today OR yesterday (UX choice:
  -- yesterday still counts since today may not be over yet).
  -- longest_streak: max(run_length) across all gaps-and-islands groups.
  -- week_over_week: zettel counts for this calendar week vs prior.
  -- chat_vs_capture: 30-day comparison of capture (zettels) vs chat (user
  -- messages) volume.

  WITH actions AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS d
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
    UNION
    SELECT (created_at AT TIME ZONE 'UTC')::date
      FROM rag.chat_messages
     WHERE workspace_id = p_workspace_id AND role = 'user'
    UNION
    SELECT (created_at AT TIME ZONE 'UTC')::date
      FROM rag.kastens
     WHERE workspace_id = p_workspace_id
  ),
  action_runs AS (
    SELECT d, (d - (row_number() OVER (ORDER BY d))::int) AS g FROM actions
  ),
  action_groups AS (
    SELECT g, count(*)::int AS c, min(d) AS s, max(d) AS e
      FROM action_runs GROUP BY g
  ),
  cur_streak AS (
    SELECT COALESCE((
      SELECT c FROM action_groups
       WHERE e = (now() AT TIME ZONE 'UTC')::date
          OR e = ((now() AT TIME ZONE 'UTC')::date - 1)
       ORDER BY e DESC LIMIT 1
    ), 0) AS c
  ),
  long_streak AS (
    SELECT COALESCE(max(c), 0)::int AS c FROM action_groups
  ),
  wow AS (
    SELECT
      count(*) FILTER (WHERE created_at >= date_trunc('week', now() AT TIME ZONE 'UTC'))::int AS this_w,
      count(*) FILTER (WHERE created_at >= date_trunc('week', now() AT TIME ZONE 'UTC') - interval '7 days'
                         AND created_at <  date_trunc('week', now() AT TIME ZONE 'UTC'))::int AS last_w
      FROM content.workspace_zettels
     WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
  ),
  cap_vs_chat AS (
    SELECT
      (SELECT count(*)::int FROM content.workspace_zettels
        WHERE workspace_id = p_workspace_id AND deleted_at IS NULL
          AND created_at >= now() - interval '30 days') AS caps,
      (SELECT count(*)::int FROM rag.chat_messages
        WHERE workspace_id = p_workspace_id AND role = 'user'
          AND created_at >= now() - interval '30 days') AS chats
  )
  SELECT jsonb_build_object(
    'current_streak', (SELECT c FROM cur_streak),
    'longest_streak', (SELECT c FROM long_streak),
    'week_over_week', jsonb_build_object(
      'this_week', (SELECT this_w FROM wow),
      'last_week', (SELECT last_w FROM wow),
      'delta_pct', CASE
        WHEN (SELECT last_w FROM wow) = 0 THEN NULL
        ELSE round(
          100.0 * ((SELECT this_w FROM wow) - (SELECT last_w FROM wow))
          / (SELECT last_w FROM wow)::numeric,
          1
        )
      END
    ),
    'chat_vs_capture', jsonb_build_object(
      'captures_30d', (SELECT caps FROM cap_vs_chat),
      'chats_30d', (SELECT chats FROM cap_vs_chat),
      'capture_pct', CASE
        WHEN (SELECT caps + chats FROM cap_vs_chat) = 0 THEN NULL
        ELSE round(
          100.0 * (SELECT caps FROM cap_vs_chat)
          / NULLIF((SELECT caps + chats FROM cap_vs_chat), 0)::numeric,
          1
        )
      END
    )
  ) INTO v_activity;

  -- ─── Knowledge Graph section ─────────────────────────────────────────
  -- 1) mean_degree: 2*|E|/|V| (undirected graph). Zero when |V|=0.
  -- 2) top_hubs_10: 10 most-connected nodes (degree desc). Edges are
  --    undirected — count appearances as src OR dst.
  -- 3) personal_vs_global_tags: count(DISTINCT user_tags) vs count(kg_nodes).
  -- 4) relation_type_mix: edge counts by relation_type.

  WITH counts AS (
    SELECT
      (SELECT count(*)::int FROM kg.kg_nodes WHERE workspace_id = p_workspace_id) AS nodes,
      (SELECT count(*)::int FROM kg.kg_edges WHERE workspace_id = p_workspace_id) AS edges
  ),
  deg AS (
    SELECT node_id, count(*)::int AS d FROM (
      SELECT src_node_id AS node_id FROM kg.kg_edges WHERE workspace_id = p_workspace_id
      UNION ALL
      SELECT dst_node_id FROM kg.kg_edges WHERE workspace_id = p_workspace_id
    ) e GROUP BY node_id
  ),
  top_hubs AS (
    SELECT n.canonical_name, n.type::text AS node_type, deg.d AS degree
      FROM deg
      JOIN kg.kg_nodes n ON n.id = deg.node_id
     WHERE n.workspace_id = p_workspace_id
     ORDER BY deg.d DESC NULLS LAST LIMIT 10
  ),
  rel_mix AS (
    SELECT relation_type::text AS relation, count(*)::int AS n
      FROM kg.kg_edges
     WHERE workspace_id = p_workspace_id
     GROUP BY relation_type
  )
  SELECT jsonb_build_object(
    'mean_degree', CASE
      WHEN (SELECT nodes FROM counts) = 0 THEN 0
      ELSE round(
        2.0 * (SELECT edges FROM counts) / (SELECT nodes FROM counts)::numeric,
        2
      )
    END,
    'top_hubs_10', COALESCE(
      (SELECT jsonb_agg(
                jsonb_build_object('name', canonical_name, 'type', node_type, 'degree', degree)
                ORDER BY degree DESC
              ) FROM top_hubs),
      '[]'::jsonb
    ),
    'personal_vs_global_tags', jsonb_build_object(
      'user_tag_count', (
        SELECT count(DISTINCT t)::int
          FROM content.workspace_zettels wz, unnest(wz.user_tags) AS t
         WHERE wz.workspace_id = p_workspace_id AND wz.deleted_at IS NULL
      ),
      'kg_node_count', (SELECT nodes FROM counts)
    ),
    'relation_type_mix', COALESCE(
      (SELECT jsonb_agg(
                jsonb_build_object('relation', relation, 'count', n)
                ORDER BY n DESC
              ) FROM rel_mix),
      '[]'::jsonb
    )
  ) INTO v_graph;

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
    'main_board', v_main_board,
    'general',    v_general,
    'zettel',     v_zettel,
    'kasten',     v_kasten,
    'domain',     v_domain,
    'activity',   v_activity,
    'graph',      v_graph
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
NOTIFY pgrst, 'reload schema';
