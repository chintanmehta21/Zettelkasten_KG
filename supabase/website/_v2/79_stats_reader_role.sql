-- 79_stats_reader_role.sql
-- Read-only role for the user statistics module. Hard timeouts to prevent
-- runaway aggregations from starving OLTP / OOM-killing the 2GB droplet.
-- Architecture audit reference: docs/claude_audits/user_stats_architecture_research_2026-05-26.md

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stats_reader') THEN
    CREATE ROLE stats_reader NOLOGIN;
  END IF;
END $$;

-- Hard guardrails (per architecture audit §4):
ALTER ROLE stats_reader SET statement_timeout = '45s';
ALTER ROLE stats_reader SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE stats_reader SET lock_timeout = '5s';
ALTER ROLE stats_reader SET work_mem = '32MB';

-- Read-only grants (least privilege). Tables verified to exist via Phase 0
-- discovery (supabase/website/_v2/01-04, 06 schemas + migration 44 changes).
GRANT USAGE ON SCHEMA core, content, kg, rag, billing TO stats_reader;

GRANT SELECT ON
  core.profiles,
  core.workspaces,
  core.workspace_members,
  core.usage_events,
  content.canonical_zettels,
  content.workspace_zettels,
  content.canonical_chunks,
  content.workspace_chunk_membership,
  rag.kastens,
  rag.kasten_zettels,
  rag.kasten_members,
  rag.chat_sessions,
  rag.chat_messages,
  rag.retrieval_feedback_events,
  kg.kg_nodes,
  kg.kg_edges,
  kg.chunk_node_mentions,
  billing.pricing_subscriptions,
  billing.pricing_usage_counters
TO stats_reader;

-- Allow execution of the stats RPC (defined in migration 81)
-- GRANT EXECUTE is deferred to migration 81 where the functions are created.
