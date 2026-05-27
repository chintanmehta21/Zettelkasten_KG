-- 80_chat_messages_user_partial_idx.down.sql
-- Reverse migration 80. ALSO non-transactional for the same reason as the up.
--
-- ─── APPLY PROCEDURE — MANUAL ONLY (NOT via apply_migrations.py) ─────────
-- DROP INDEX CONCURRENTLY cannot run inside a transaction. Standard runner
-- (ops/scripts/apply_migrations.py wraps in autocommit=False) will fail.
-- Operator runs:
--
--   psql "$PROD_DATABASE_URL" \
--        -v ON_ERROR_STOP=1 \
--        -f supabase/website/_v2/80_chat_messages_user_partial_idx.down.sql
--
-- The DROP INDEX CONCURRENTLY itself takes SHARE UPDATE EXCLUSIVE briefly
-- but does NOT block writers (concurrent INSERT/UPDATE/DELETE on
-- rag.chat_messages remain unaffected).

DROP INDEX CONCURRENTLY IF EXISTS rag.idx_chat_messages_workspace_user_created;
