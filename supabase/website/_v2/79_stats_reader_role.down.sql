-- 79_stats_reader_role.down.sql
REVOKE SELECT ON
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
FROM stats_reader;

REVOKE USAGE ON SCHEMA core, content, kg, rag, billing FROM stats_reader;

DROP ROLE IF EXISTS stats_reader;
