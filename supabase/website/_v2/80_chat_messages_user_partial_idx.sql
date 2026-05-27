-- 80_chat_messages_user_partial_idx.sql
-- Partial index on rag.chat_messages for User Stats endpoint.
--
-- ─── Rationale (architecture audit §retrieval) ───────────────────────────
-- Existing idx_chat_messages_session is session-keyed. Stats 4.2/4.3/4.4
-- (avg conversation depth, most-cited source type, question streak) all
-- filter on (workspace_id, role='user', created_at). At 10k+ messages
-- per workspace this index keeps stats endpoint latency under 50ms.
--
-- ─── APPLY PROCEDURE — MANUAL ONLY (NOT via apply_migrations.py) ─────────
-- The standard runner (ops/scripts/apply_migrations.py) wraps every .sql
-- in autocommit=False which is INCOMPATIBLE with CREATE INDEX CONCURRENTLY.
-- Applying this file via the standard runner will fail with
-- ERROR 25001 (cannot run CREATE INDEX CONCURRENTLY in a transaction block).
--
-- Operator MUST apply this file MANUALLY first, then mark it applied in
-- the migration ledger so the standard runner skips it:
--
--   1) Apply outside any transaction:
--      psql "$PROD_DATABASE_URL" --single-transaction=off \
--           -f supabase/website/_v2/80_chat_messages_user_partial_idx.sql
--
--   2) Reconcile the migration ledger so future runs of apply_migrations.py
--      skip this file (record exists with correct checksum):
--      python ops/scripts/apply_migrations.py --v2 \
--             --reconcile-checksum 80_chat_messages_user_partial_idx.sql
--
-- ─── RECOVERY — if a prior CONCURRENTLY attempt failed ──────────────────
-- Postgres may leave an INVALID index that IF NOT EXISTS will then skip.
-- The planner won't use an invalid index. To recover, drop and retry:
--   SELECT indexrelid::regclass, indisvalid FROM pg_index
--    WHERE indexrelid = 'rag.idx_chat_messages_workspace_user_created'::regclass;
--   -- If indisvalid = false:
--   DROP INDEX CONCURRENTLY rag.idx_chat_messages_workspace_user_created;
--   -- Then re-run this migration.
--
-- ─── ANALYZE expectation ─────────────────────────────────────────────────
-- The trailing ANALYZE on a 10k+ row table briefly holds SHARE UPDATE
-- EXCLUSIVE (~50-200ms typical). Schedule the apply during low-traffic.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chat_messages_workspace_user_created
  ON rag.chat_messages (workspace_id, created_at DESC)
  WHERE role = 'user';

ANALYZE rag.chat_messages;
