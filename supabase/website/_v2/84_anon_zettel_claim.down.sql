-- 84_anon_zettel_claim.down.sql — reverse of 84_anon_zettel_claim.sql

DROP FUNCTION IF EXISTS content.commit_anon_claim(uuid, uuid, uuid[]);
DROP FUNCTION IF EXISTS content.peek_claimable_anon_zettels(uuid, uuid);
DROP FUNCTION IF EXISTS content.tag_anon_zettel(uuid, uuid, text, text);

DROP TABLE IF EXISTS content.anon_sessions;

-- Restore the original added_via CHECK. Convert any 'claim' rows to 'share'
-- first so the stricter constraint can be re-applied without violation.
UPDATE content.workspace_zettels SET added_via = 'share' WHERE added_via = 'claim';
ALTER TABLE content.workspace_zettels
    DROP CONSTRAINT IF EXISTS workspace_zettels_added_via_check;
ALTER TABLE content.workspace_zettels
    ADD CONSTRAINT workspace_zettels_added_via_check
    CHECK (added_via IN ('telegram', 'website', 'share', 'migration'));

DROP INDEX IF EXISTS content.idx_workspace_zettels_anon_sid;
ALTER TABLE content.workspace_zettels DROP COLUMN IF EXISTS anon_sid;

NOTIFY pgrst, 'reload schema';
