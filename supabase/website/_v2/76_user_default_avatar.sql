-- ── 76_user_default_avatar.sql ────────────────────────────────────────────
-- Auto-assign random Zettelkasten avatar at signup; backfill existing users.
-- Avatars served from /artifacts/avatars/avatar_NN.svg (NN = 00..59).
-- Removes any third-party (Google/Gravatar) avatar URL so the front-end
-- avatar.js renders the curated set instead.
-- ──────────────────────────────────────────────────────────────────────────

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

-- Backfill NULL + Google + Gravatar rows
UPDATE auth.users
SET raw_user_meta_data = COALESCE(raw_user_meta_data, '{}'::jsonb)
  || jsonb_build_object(
       'avatar_url',
       '/artifacts/avatars/avatar_' || lpad((floor(random() * 60))::text, 2, '0') || '.svg'
     )
WHERE (raw_user_meta_data->>'avatar_url') IS NULL
   OR (raw_user_meta_data->>'avatar_url') LIKE '%googleusercontent.com%'
   OR (raw_user_meta_data->>'avatar_url') LIKE '%gravatar.com%';

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
GRANT EXECUTE ON FUNCTION public.assign_default_avatar() TO authenticated;

COMMIT;
