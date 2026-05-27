-- 80_chat_messages_user_partial_idx.sql
-- Partial index on rag.chat_messages for User Stats endpoint.
--
-- Rationale (architecture audit §retrieval):
-- Existing idx_chat_messages_session is session-keyed. Stats 4.2/4.3/4.4
-- (avg conversation depth, most-cited source type, question streak) all
-- filter on (workspace_id, role='user', created_at). At 10k+ messages
-- per workspace this index keeps stats endpoint latency under 50ms.
--
-- IMPORTANT: CREATE INDEX CONCURRENTLY cannot run inside a transaction.
-- Apply this migration with psql --single-transaction=off or via a
-- migration runner that does NOT wrap each .sql in BEGIN/COMMIT. Unlike
-- migration 79 (which IS transactional), this file has no BEGIN/COMMIT.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_messages_workspace_user_created
  ON rag.chat_messages (workspace_id, created_at DESC)
  WHERE role = 'user';

ANALYZE rag.chat_messages;
