-- Migration 86 (Community Graph Part B / Phase 0 — P0-b): privacy audit log.
--
-- Append-only record of every make_private / make_public action (privacy
-- demonstrability; withdrawal of public visibility never erases the proof the
-- action happened). Replaces the opt-in design's publish_consent_events: under
-- opt-out the consent basis is the signup NOTICE, and what we audit is the
-- privacy TOGGLE, not a publish event.
--
-- NEW table => explicit grants are REQUIRED. 08_rls_policies.sql's GRANT ALL and
-- 64_grant_all_v2_tables_to_service_role.sql only cover tables that existed when
-- they ran (<= slot 64/84). Append-only => service_role gets SELECT + INSERT
-- only (NO UPDATE/DELETE). community_reader does NOT read this table -> no grant.
-- Idempotent: CREATE TABLE IF NOT EXISTS + DROP/CREATE POLICY.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  CREATE TABLE IF NOT EXISTS content.zettel_privacy_events (
      id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      actor_user_id        uuid,
      workspace_zettel_id  uuid REFERENCES content.workspace_zettels(id) ON DELETE CASCADE,
      action               text NOT NULL CHECK (action IN ('make_private', 'make_public')),
      created_at           timestamptz NOT NULL DEFAULT now()
  );

  CREATE INDEX IF NOT EXISTS idx_zettel_privacy_events_wz
      ON content.zettel_privacy_events (workspace_zettel_id, created_at DESC);

  ALTER TABLE content.zettel_privacy_events ENABLE ROW LEVEL SECURITY;

  -- service_role: append-only (no UPDATE/DELETE policy, no UPDATE/DELETE grant).
  DROP POLICY IF EXISTS zettel_privacy_events_service_select ON content.zettel_privacy_events;
  CREATE POLICY zettel_privacy_events_service_select ON content.zettel_privacy_events
      FOR SELECT TO service_role USING (true);
  DROP POLICY IF EXISTS zettel_privacy_events_service_insert ON content.zettel_privacy_events;
  CREATE POLICY zettel_privacy_events_service_insert ON content.zettel_privacy_events
      FOR INSERT TO service_role WITH CHECK (true);

  GRANT SELECT, INSERT ON content.zettel_privacy_events TO service_role;
COMMIT;

COMMENT ON TABLE content.zettel_privacy_events IS
  'Append-only privacy audit. One row per make_private/make_public. service_role has SELECT+INSERT only; never UPDATE/DELETE.';

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
