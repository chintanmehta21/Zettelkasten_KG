-- Migration 85 (Community Graph Part B / Phase 0 — P0-a): per-zettel PRIVACY flag.
--
-- OPT-OUT model (design Rev 3, operator decision 2026-06-16): every zettel is
-- PUBLIC in the community graph by default; a user marks a zettel private to
-- hide it. The flag lives on the per-(user,canonical) overlay row
-- content.workspace_zettels, NEVER on the deduped content.canonical_zettels
-- (UNIQUE(normalized_url), PR #25): a flag on the shared canonical row would let
-- User A's choice silently control User B the moment a second user saves the
-- same URL. Per-overlay is the granular, per-data-subject unit.
--
-- is_private DEFAULT false => existing ~80 zettels become PUBLIC via the column
-- default; NO BACKFILL is run. made_private_at is set when a zettel flips
-- private (internal audit; never returned by any public API).
--
-- Column adds on an already-granted table need no new GRANT (08_rls_policies.sql
-- granted ALL on content.* to service_role + SELECT/INSERT/UPDATE/DELETE to
-- authenticated). The partial index + the PostgREST reload DO need the NOTIFY.
-- Idempotent: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.

BEGIN;
  SET LOCAL lock_timeout = '3s';
  SET LOCAL statement_timeout = '60s';

  ALTER TABLE content.workspace_zettels
    ADD COLUMN IF NOT EXISTS is_private boolean NOT NULL DEFAULT false;

  ALTER TABLE content.workspace_zettels
    ADD COLUMN IF NOT EXISTS made_private_at timestamptz;
COMMIT;

COMMENT ON COLUMN content.workspace_zettels.is_private IS
  'Per-zettel OPT-OUT flag. Default FALSE = PUBLIC (shown in the community graph with the owner display_name). TRUE hides it. NEVER on canonical_zettels (would over-hide/over-share via URL dedup).';
COMMENT ON COLUMN content.workspace_zettels.made_private_at IS
  'Internal audit timestamp set when is_private flips TRUE. NEVER returned by any public API.';

-- Community-read partial index: the community RPC scans the PUBLIC, non-deleted
-- hot set. A partial index materializes just that set ordered by recency so the
-- cross-workspace read (and any "recently added" surface) stays cheap at scale.
-- At ~80 rows this is moot, but it is designed for the 10k+ scale target.
CREATE INDEX IF NOT EXISTS idx_workspace_zettels_community
    ON content.workspace_zettels (created_at DESC)
    WHERE is_private = false AND deleted_at IS NULL;

NOTIFY pgrst, 'reload schema';
