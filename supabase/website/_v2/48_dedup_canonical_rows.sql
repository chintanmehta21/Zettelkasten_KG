-- 48 — One-off dedup of duplicate content.canonical_zettels rows (D6)
--
-- DEFECT (audit R2 / D6):
--   The pre-P1-7 content_hash was sha256(body_md) where body_md fell through
--   to the NON-DETERMINISTIC LLM summary. Re-ingesting the same URL produced
--   a different hash every time, the (normalized_url, content_hash) ON CONFLICT
--   key in content.upsert_canonical_zettel missed, and a NEW canonical row was
--   inserted on every re-ingest. Result: many duplicate canonical rows for the
--   same normalized_url with divergent content_hash, splitting chunks / KG
--   evidence / workspace overlays across phantom twins.
--
--   P1-7 already FIXED the recurrence at the write path (content_hash now
--   derives only from normalized_url + extracted source text, deterministic
--   across re-ingests). This migration is the one-off backlog cleanup of the
--   rows the old bug already created. It is NOT applied automatically — the
--   operator runs it gated (see docs plan sequencing: D6 BEFORE D5).
--
-- KEEP / SURVIVOR RULE (per normalized_url group with >1 row):
--   The P1-7-correct row is the one a deterministic re-ingest produced and
--   successfully chunked. SQL cannot recompute the Python sha256(source text),
--   so we use the observable proxy that tracks it exactly:
--     1. most canonical_chunks  (a P1-7 re-ingest segments + embeds; stale
--        pre-fix twins are typically 0/1-chunk),
--     2. tie-break: newest created_at (latest deterministic write wins),
--     3. final tie-break: greatest id (total order, fully deterministic).
--   Losers are merged INTO the survivor, then deleted.
--
-- FK CHILDREN repointed to the survivor before deleting losers:
--   * content.canonical_chunks.canonical_zettel_id      (ON DELETE CASCADE)
--   * content.workspace_zettels.canonical_zettel_id     (ON DELETE RESTRICT)
--   * kg.kg_edges.evidence_canonical_zettel_id          (ON DELETE SET NULL)
--   canonical_chunks has UNIQUE(canonical_zettel_id, chunk_idx) and
--   workspace_zettels has UNIQUE(workspace_id, canonical_zettel_id): a naive
--   repoint can collide with the survivor's own rows. We therefore DROP the
--   loser's colliding children (the survivor already holds the correct,
--   freshly-chunked set + its own workspace overlay) and only repoint the
--   non-colliding remainder.
--
-- SAFETY:
--   * Single transaction (BEGIN/COMMIT) — all-or-nothing.
--   * Idempotent: re-running after a successful run is a no-op (no group has
--     >1 row once deduped; the recurrence guard index makes a second dup
--     physically impossible at the url level going forward).
--   * Does NOT modify any function body (golden-md5 RPCs untouched).
--   * NOTIFY pgrst at the end so PostgREST reloads the schema cache.
--
-- RECURRENCE GUARD (operator note — read before applying):
--   The base table keeps its UNIQUE(normalized_url, content_hash). The added
--   partial unique index ``uq_canonical_zettels_url_singleton`` enforces
--   one canonical row PER normalized_url. This is intentionally stricter than
--   the base composite key: post-P1-7 a stable URL re-ingest yields the SAME
--   hash so the composite key already dedups; a genuine SOURCE-CONTENT change
--   would (by the P1-7 design) want a new (url, new_hash) row, and this guard
--   would instead force an in-place update of the single row for that URL.
--   That is the desired behavior for this corpus (one canonical artifact per
--   URL; the latest extraction supersedes the prior) and it makes the D6
--   duplicate class structurally impossible to recur. If a future iteration
--   deliberately wants URL-versioned canonical history, drop this index in a
--   later migration with explicit operator approval.

BEGIN;

-- ── 1. Resolve survivor per duplicate normalized_url group ────────────────
CREATE TEMP TABLE _dedup_map ON COMMIT DROP AS
WITH chunk_counts AS (
    SELECT cz.id AS zettel_id,
           cz.normalized_url,
           cz.created_at,
           COALESCE(cc.n, 0) AS chunk_n
      FROM content.canonical_zettels cz
      LEFT JOIN (
            SELECT canonical_zettel_id, count(*) AS n
              FROM content.canonical_chunks
             GROUP BY canonical_zettel_id
      ) cc ON cc.canonical_zettel_id = cz.id
),
ranked AS (
    SELECT zettel_id,
           normalized_url,
           first_value(zettel_id) OVER (
               PARTITION BY normalized_url
               ORDER BY chunk_n DESC, created_at DESC, zettel_id DESC
           ) AS survivor_id
      FROM chunk_counts
)
SELECT zettel_id AS loser_id, survivor_id, normalized_url
  FROM ranked
 WHERE zettel_id <> survivor_id;

-- ── 2. canonical_chunks: drop loser chunks that would collide on
--       (survivor_id, chunk_idx); repoint the remainder ────────────────────
DELETE FROM content.canonical_chunks cc
 USING _dedup_map m
 WHERE cc.canonical_zettel_id = m.loser_id
   AND EXISTS (
        SELECT 1 FROM content.canonical_chunks s
         WHERE s.canonical_zettel_id = m.survivor_id
           AND s.chunk_idx = cc.chunk_idx
   );

UPDATE content.canonical_chunks cc
   SET canonical_zettel_id = m.survivor_id
  FROM _dedup_map m
 WHERE cc.canonical_zettel_id = m.loser_id;

-- ── 3. workspace_zettels: drop loser overlay where the survivor already has
--       one for the same workspace; repoint the remainder ──────────────────
DELETE FROM content.workspace_zettels wz
 USING _dedup_map m
 WHERE wz.canonical_zettel_id = m.loser_id
   AND EXISTS (
        SELECT 1 FROM content.workspace_zettels s
         WHERE s.canonical_zettel_id = m.survivor_id
           AND s.workspace_id = wz.workspace_id
   );

UPDATE content.workspace_zettels wz
   SET canonical_zettel_id = m.survivor_id
  FROM _dedup_map m
 WHERE wz.canonical_zettel_id = m.loser_id;

-- ── 4. kg.kg_edges evidence pointer: repoint (no uniqueness constraint) ───
UPDATE kg.kg_edges ke
   SET evidence_canonical_zettel_id = m.survivor_id
  FROM _dedup_map m
 WHERE ke.evidence_canonical_zettel_id = m.loser_id;

-- ── 5. Delete the now-orphaned loser canonical rows ───────────────────────
DELETE FROM content.canonical_zettels cz
 USING _dedup_map m
 WHERE cz.id = m.loser_id;

-- ── 6. Recurrence guard: one canonical row per normalized_url ─────────────
--       (idempotent; CONCURRENTLY is not allowed inside a txn so plain
--        CREATE UNIQUE INDEX IF NOT EXISTS — table is low-traffic, this is an
--        operator-gated maintenance window).
CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_zettels_url_singleton
    ON content.canonical_zettels (normalized_url);

NOTIFY pgrst, 'reload schema';

COMMIT;
