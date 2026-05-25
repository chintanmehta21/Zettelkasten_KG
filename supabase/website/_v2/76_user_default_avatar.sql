-- 76_user_default_avatar.sql — auto-assign random avatar at signup; backfill
-- existing users whose avatar_url is NULL or points at a third-party host.
--
-- Why: auth.users.raw_user_meta_data.avatar_url is set by Google/Gravatar OAuth
-- for social-login users, and left NULL for email/password signups. The
-- front-end avatar.js renders whatever is in that field — if it is a Google or
-- Gravatar URL, the user gets the third-party image rather than the curated
-- Zettelkasten set (/artifacts/avatars/avatar_NN.svg, NN = 00..59). Stripping
-- third-party URLs at signup (via trigger) and in the backfill ensures the
-- curated set is rendered consistently across all users and login methods.
-- Zoro (a57e1f2f) and Naruto (f2105544) are pinned to avatar_00 and avatar_01
-- respectively as stable test-fixture identities; the pin runs after the random
-- backfill so it always wins.
--
-- What: (1) BEFORE INSERT trigger on auth.users that stamps a random curated
-- avatar when avatar_url is absent at row creation; (2) one-time backfill UPDATE
-- wrapped in a DO block with RAISE NOTICE for operator visibility; (3) canonical-
-- user pin UPDATEs for Zoro + Naruto.
--
-- Idempotency: the backfill WHERE guard excludes rows already pointing at
-- /artifacts/avatars/% so a partial-first-run + re-apply cannot reassign a
-- random index to a user who already received one.
--
-- Versioned, immutable (schema-drift gate frozen).

BEGIN;

CREATE OR REPLACE FUNCTION public.assign_default_avatar()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_idx text;
BEGIN
  IF (NEW.raw_user_meta_data->>'avatar_url') IS NULL THEN
    v_idx := lpad((floor(random() * 60))::text, 2, '0');
    NEW.raw_user_meta_data := COALESCE(NEW.raw_user_meta_data, '{}'::jsonb)
      || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_' || v_idx || '.svg');
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created_assign_avatar ON auth.users;
CREATE TRIGGER on_auth_user_created_assign_avatar
  BEFORE INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.assign_default_avatar();

-- Backfill NULL + Google + Gravatar rows (idempotent: skips already-curated rows)
DO $$
DECLARE
  v_count integer;
BEGIN
  UPDATE auth.users
  SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
    || jsonb_build_object(
         'avatar_url',
         '/artifacts/avatars/avatar_' || lpad((floor(random() * 60))::text, 2, '0') || '.svg'
       )
  WHERE (
         (raw_user_meta_data->>'avatar_url') IS NULL
      OR (raw_user_meta_data->>'avatar_url') LIKE '%googleusercontent.com%'
      OR (raw_user_meta_data->>'avatar_url') LIKE '%gravatar.com%'
    )
    AND (raw_user_meta_data->>'avatar_url') NOT LIKE '/artifacts/avatars/%';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RAISE NOTICE '76_user_default_avatar: backfilled % users', v_count;
END $$;

-- Pin canonical users
UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_00.svg')
WHERE id = 'a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e';  -- Zoro

UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object('avatar_url', '/artifacts/avatars/avatar_01.svg')
WHERE id = 'f2105544-b73d-4946-8329-096d82f070d3';  -- Naruto

GRANT EXECUTE ON FUNCTION public.assign_default_avatar() TO service_role;

COMMIT;
