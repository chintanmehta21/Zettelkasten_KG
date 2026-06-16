-- Migration 89 (Community Graph Part B / Phase 0 — P1 prereq): cross-worker
-- cache coherency counter. The community graph is a single aggregate object;
-- "mark one node private => it (and its edges) vanish" can't be expressed
-- per-key, so we use a generation counter (research §2.5). Workers poll this int
-- once per TTL window (PgBouncer-safe; LISTEN/NOTIFY does not scale to the 10k+
-- write target). Bumped on make-private/make-public via set_private. NEW table
-- => explicit grants (08/64 GRANT ALL only cover <= their slot). Idempotent:
-- CREATE TABLE IF NOT EXISTS + seed-once INSERT guard.

BEGIN;
  SET LOCAL lock_timeout = '3s';

  CREATE TABLE IF NOT EXISTS content.community_cache_version (
      id        boolean PRIMARY KEY DEFAULT true CHECK (id),  -- single-row guard
      version   bigint NOT NULL DEFAULT 0,
      bumped_at timestamptz NOT NULL DEFAULT now()
  );

  INSERT INTO content.community_cache_version (id, version)
  VALUES (true, 0)
  ON CONFLICT (id) DO NOTHING;

  ALTER TABLE content.community_cache_version ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS community_cache_version_service_all ON content.community_cache_version;
  CREATE POLICY community_cache_version_service_all ON content.community_cache_version
      FOR ALL TO service_role USING (true) WITH CHECK (true);

  GRANT SELECT, UPDATE ON content.community_cache_version TO service_role;

  CREATE OR REPLACE FUNCTION content.bump_community_cache_version()
  RETURNS bigint
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
  DECLARE
    v bigint;
  BEGIN
    UPDATE content.community_cache_version
       SET version = version + 1, bumped_at = now()
     WHERE id = true
     RETURNING version INTO v;
    RETURN v;
  END
  $$;

  REVOKE ALL ON FUNCTION content.bump_community_cache_version() FROM public;
  GRANT EXECUTE ON FUNCTION content.bump_community_cache_version() TO service_role;
COMMIT;

NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
