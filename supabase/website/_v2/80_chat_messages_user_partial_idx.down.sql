-- 80_chat_messages_user_partial_idx.down.sql
-- Reverse migration 80. Also non-transactional for the same reason.

DROP INDEX CONCURRENTLY IF EXISTS rag.idx_chat_messages_workspace_user_created;
