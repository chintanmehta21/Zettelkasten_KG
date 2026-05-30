-- 84_anon_zettel_claim.sql
-- Item 6 — anon → user zettel claim (dual-ownership).
--
-- When an anonymous visitor (zettels stored under the canonical "Zoro" user)
-- signs in during the same browser session, their session zettels are ALSO
-- inserted into the new user's workspace (dual-row). Zoro keeps its rows.
--
-- Design: docs/claude_audits/anon_zettel_claim_design_2026-05-30.md
--
-- Safety: ADDITIVE + reversible. The universal content.upsert_workspace_zettel
-- RPC (every ingestion path) is intentionally NOT modified — anon provenance is
-- written by a dedicated content.tag_anon_zettel call that only fires for anon
-- (Zoro) captures, so the authed write path has ZERO new behaviour.
--
-- Operator note: after applying, regenerate the schema-drift snapshot
-- (supabase/website/_v2/expected_schema.json) via the apply_migrations runner,
-- or the schema-drift gate will fail the next deploy.

-- ── 1. Provenance column: which anon browser-session created a Zoro row ──────
ALTER TABLE content.workspace_zettels
    ADD COLUMN IF NOT EXISTS anon_sid uuid;

-- Partial index: claim lookups only scan the (small) set of anon-tagged rows.
CREATE INDEX IF NOT EXISTS idx_workspace_zettels_anon_sid
    ON content.workspace_zettels (anon_sid)
    WHERE anon_sid IS NOT NULL AND deleted_at IS NULL;

-- Allow 'claim' as a provenance value for the sibling rows minted on claim.
ALTER TABLE content.workspace_zettels
    DROP CONSTRAINT IF EXISTS workspace_zettels_added_via_check;
ALTER TABLE content.workspace_zettels
    ADD CONSTRAINT workspace_zettels_added_via_check
    CHECK (added_via IN ('telegram', 'website', 'share', 'migration', 'claim'));

-- ── 2. Anon browser-session ledger (first-claim-wins + 24h window) ───────────
CREATE TABLE IF NOT EXISTS content.anon_sessions (
    id               uuid PRIMARY KEY,            -- == opaque zk_anon_sid cookie value
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at     timestamptz NOT NULL DEFAULT now(),
    claimed_by_user  uuid REFERENCES core.profiles(id) ON DELETE SET NULL,
    claimed_at       timestamptz,
    ip_hash          text,                        -- sha256(ip+salt) — abuse forensics, not PII
    ua_hash          text
);

GRANT SELECT, INSERT, UPDATE ON content.anon_sessions TO service_role;

-- ── 3. tag_anon_zettel — additive provenance tag for anon captures ───────────
-- Kept OUT of upsert_workspace_zettel so the universal ingestion RPC is never
-- touched. Upserts the session row + stamps anon_sid on the just-persisted row.
CREATE OR REPLACE FUNCTION content.tag_anon_zettel(
    p_workspace_zettel_id uuid,
    p_anon_sid            uuid,
    p_ip_hash            text DEFAULT NULL,
    p_ua_hash            text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = content, core, public AS $$
BEGIN
    INSERT INTO content.anon_sessions (id, ip_hash, ua_hash)
        VALUES (p_anon_sid, p_ip_hash, p_ua_hash)
        ON CONFLICT (id) DO UPDATE SET last_seen_at = now();
    -- Caller contract: the add-zettel handler calls this with the server-
    -- generated id of a JUST-persisted anon (Zoro) row. The anon_sid IS NULL
    -- guard makes tagging stamp-once and defends a future SECURITY DEFINER
    -- caller from re-stamping an authed user's row (which would expose it to a
    -- claim).
    UPDATE content.workspace_zettels
        SET anon_sid = p_anon_sid
        WHERE id = p_workspace_zettel_id
          AND anon_sid IS NULL;
END $$;

GRANT EXECUTE ON FUNCTION content.tag_anon_zettel(uuid, uuid, text, text) TO service_role;

-- ── 4. peek_claimable_anon_zettels — candidate list for the quota loop ───────
-- Read-only. Up to 20 Zoro rows tagged with this session that the new user does
-- NOT already own, only when the session is unclaimed AND < 24h old.
CREATE OR REPLACE FUNCTION content.peek_claimable_anon_zettels(
    p_new_user uuid,
    p_anon_sid uuid
) RETURNS TABLE (
    workspace_zettel_id uuid,
    canonical_zettel_id uuid
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = content, core, public AS $$
DECLARE
    v_new_ws uuid;
BEGIN
    PERFORM 1 FROM content.anon_sessions s
        WHERE s.id = p_anon_sid
          AND s.claimed_at IS NULL                       -- immutable sentinel; see commit_anon_claim
          AND s.created_at > now() - interval '24 hours';
    IF NOT FOUND THEN RETURN; END IF;

    SELECT cm.workspace_id INTO v_new_ws
        FROM core.workspace_members cm
        WHERE cm.profile_id = p_new_user
        ORDER BY cm.added_at
        LIMIT 1;
    IF v_new_ws IS NULL THEN RETURN; END IF;

    RETURN QUERY
        SELECT wz.id, wz.canonical_zettel_id
        FROM content.workspace_zettels wz
        WHERE wz.anon_sid = p_anon_sid
          AND wz.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM content.workspace_zettels o
              WHERE o.workspace_id = v_new_ws
                AND o.canonical_zettel_id = wz.canonical_zettel_id
                AND o.deleted_at IS NULL)
        ORDER BY wz.created_at
        LIMIT 20;
END $$;

GRANT EXECUTE ON FUNCTION content.peek_claimable_anon_zettels(uuid, uuid) TO service_role;

-- ── 5. commit_anon_claim — atomic dual-row insert + first-claim-wins mark ────
-- Endpoint passes ONLY the canonical_ids the user can afford (the per-zettel
-- quota loop ran first). Locks the session row so concurrent claims serialise;
-- the second claimant sees claimed_by_user set and gets 0 (first-claim-wins).
CREATE OR REPLACE FUNCTION content.commit_anon_claim(
    p_new_user      uuid,
    p_anon_sid      uuid,
    p_canonical_ids uuid[]
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = content, core, public AS $$
DECLARE
    v_new_ws     uuid;
    v_count      integer := 0;
    v_claimed_at timestamptz;
    v_created    timestamptz;
BEGIN
    -- claimed_at is the first-claim-wins sentinel (set once, never nulled). We
    -- key off it rather than claimed_by_user because that FK is ON DELETE SET
    -- NULL — deleting the claiming profile would otherwise reset the guard and
    -- make an already-claimed session re-claimable within the 24h window.
    SELECT claimed_at, created_at INTO v_claimed_at, v_created
        FROM content.anon_sessions
        WHERE id = p_anon_sid
        FOR UPDATE;
    IF NOT FOUND THEN RETURN 0; END IF;
    IF v_claimed_at IS NOT NULL THEN RETURN 0; END IF;                    -- first-claim-wins
    IF v_created <= now() - interval '24 hours' THEN RETURN 0; END IF;    -- window
    IF p_canonical_ids IS NULL OR array_length(p_canonical_ids, 1) IS NULL THEN
        -- nothing affordable, but the session is now spoken for
        UPDATE content.anon_sessions
            SET claimed_by_user = p_new_user, claimed_at = now()
            WHERE id = p_anon_sid;
        RETURN 0;
    END IF;

    SELECT cm.workspace_id INTO v_new_ws
        FROM core.workspace_members cm
        WHERE cm.profile_id = p_new_user
        ORDER BY cm.added_at
        LIMIT 1;
    IF v_new_ws IS NULL THEN RETURN 0; END IF;

    INSERT INTO content.workspace_zettels (
        workspace_id, canonical_zettel_id, ai_summary, ai_summary_engine_version,
        user_tags, user_note, pinned, added_via
    )
    SELECT DISTINCT ON (wz.canonical_zettel_id)
        v_new_ws, wz.canonical_zettel_id, wz.ai_summary, wz.ai_summary_engine_version,
        wz.user_tags, wz.user_note, false, 'claim'
    FROM content.workspace_zettels wz
    WHERE wz.anon_sid = p_anon_sid
      AND wz.canonical_zettel_id = ANY (p_canonical_ids)
      AND wz.deleted_at IS NULL
    ORDER BY wz.canonical_zettel_id, wz.created_at
    ON CONFLICT (workspace_id, canonical_zettel_id) WHERE deleted_at IS NULL DO NOTHING;
    GET DIAGNOSTICS v_count = ROW_COUNT;

    UPDATE content.anon_sessions
        SET claimed_by_user = p_new_user, claimed_at = now()
        WHERE id = p_anon_sid;

    RETURN v_count;
END $$;

GRANT EXECUTE ON FUNCTION content.commit_anon_claim(uuid, uuid, uuid[]) TO service_role;

NOTIFY pgrst, 'reload schema';
