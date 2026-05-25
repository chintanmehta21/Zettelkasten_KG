-- 78_user_default_avatar.sql — assign random curated avatar to every user;
-- backfill existing rows whose avatar is missing or non-curated.
--
-- Why: the canonical mobile + desktop UI renders avatars exclusively from the
-- curated set under /artifacts/avatars/avatar_NN.svg (NN = 00..59). The
-- existing v2 surfaces read avatar from ``core.profiles.avatar_url`` (e.g.
-- /api/me, /api/me/avatar). Pre-2026-05-25 that column was left NULL by the
-- ``core.handle_new_auth_user`` trigger; /api/me then fell back to the JWT
-- claim ``user_metadata.avatar_url``, which Google/Gravatar/etc. set during
-- OAuth signup. To enforce the curated set across all login methods we (a)
-- populate ``core.profiles.avatar_url`` with a random curated URL whenever a
-- profile is created and (b) clear any non-curated string left in
-- ``auth.users.raw_user_meta_data.avatar_url`` so the /api/me fallback can
-- never resurface a third-party image. Zoro (a57e1f2f) and Naruto (f2105544)
-- are pinned to avatar_00 / avatar_01 as stable test-fixture identities; the
-- pin runs after the random backfill so it always wins.
--
-- What: (1) trigger ``core.assign_default_profile_avatar`` runs BEFORE INSERT
-- on core.profiles and stamps a random curated URL when avatar_url is missing
-- or non-curated. Because BEFORE INSERT runs strictly before the row lands,
-- NEW.avatar_url is mutated directly. (2) one-time backfill UPDATE on
-- core.profiles for rows already in the table whose avatar_url is missing or
-- non-curated, wrapped in DO + RAISE NOTICE for operator visibility. (3) pin
-- updates for Zoro + Naruto. (4) defensive clear of
-- auth.users.raw_user_meta_data.avatar_url where it points anywhere except
-- /artifacts/avatars/, so the /api/me JWT-claim fallback path stays curated.
--
-- Idempotency: the trigger's "missing or non-curated" guard means a re-apply
-- never re-rolls a user already pointing at a curated URL. The backfill
-- WHERE predicate uses ``IS DISTINCT FROM`` semantics via explicit ``IS NULL
-- OR NOT LIKE`` — NULL safely matches the IS NULL branch (Codex P1 fix:
-- predicate previously used ``AND NOT LIKE`` which NULL-eats the IS NULL
-- branch under three-valued logic).
--
-- Versioned, immutable (schema-drift gate frozen).

BEGIN;

-- Step 1: trigger function on core.profiles
CREATE OR REPLACE FUNCTION core.assign_default_profile_avatar()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  v_idx text;
BEGIN
  IF NEW.avatar_url IS NULL
     OR NEW.avatar_url !~ '^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$' THEN
    v_idx := lpad((floor(random() * 60))::text, 2, '0');
    NEW.avatar_url := '/artifacts/avatars/avatar_' || v_idx || '.svg';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_assign_default_profile_avatar ON core.profiles;
CREATE TRIGGER trg_assign_default_profile_avatar
  BEFORE INSERT ON core.profiles
  FOR EACH ROW EXECUTE FUNCTION core.assign_default_profile_avatar();

GRANT EXECUTE ON FUNCTION core.assign_default_profile_avatar() TO service_role;

-- Step 2: backfill core.profiles rows whose avatar_url is missing or non-curated.
DO $$
DECLARE
  v_count integer;
BEGIN
  UPDATE core.profiles
  SET avatar_url = '/artifacts/avatars/avatar_'
                   || lpad((floor(random() * 60))::text, 2, '0')
                   || '.svg'
  WHERE avatar_url IS NULL
     OR avatar_url !~ '^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RAISE NOTICE '78_user_default_avatar: backfilled % core.profiles rows', v_count;
END $$;

-- Step 3: pin canonical users (Zoro + Naruto). Runs AFTER the random backfill
-- so the deterministic pin always wins.
UPDATE core.profiles
SET avatar_url = '/artifacts/avatars/avatar_00.svg'
WHERE id = 'a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e';  -- Zoro

UPDATE core.profiles
SET avatar_url = '/artifacts/avatars/avatar_01.svg'
WHERE id = 'f2105544-b73d-4946-8329-096d82f070d3';  -- Naruto

-- Step 4: clear non-curated auth.users.raw_user_meta_data.avatar_url so the
-- /api/me fallback path can never resurface a Google/Gravatar/etc. URL when
-- core.profiles.avatar_url somehow becomes NULL. Strip-only — does not write
-- a replacement (the canonical store is core.profiles).
DO $$
DECLARE
  v_count integer;
BEGIN
  UPDATE auth.users
  SET raw_user_meta_data = raw_user_meta_data - 'avatar_url'
  WHERE raw_user_meta_data ? 'avatar_url'
    AND (raw_user_meta_data->>'avatar_url') !~ '^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RAISE NOTICE '78_user_default_avatar: stripped non-curated avatar_url from % auth.users metadata rows', v_count;
END $$;

COMMIT;
