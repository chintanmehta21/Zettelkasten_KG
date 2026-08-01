-- Migration 90 (Community Graph Part B / Phase 1.5 — TAG BACKBONE): the
-- cross-user relatedness EDGE builder for the community graph.
--
-- WHY THIS EXISTS: migration 88 (community_graph_v1) is NODE-ONLY, and the
-- per-workspace kg.kg_edges are keyed to per-workspace kg_node ids, so they can
-- never connect one user's zettel to another's. The result was a community
-- surface with 125 nodes and ZERO edges. This RPC is the missing cross-user
-- edge computation. It operates on the DEDUPED CANONICAL layer (the same unit
-- 88 emits), which is what makes it cross-user by construction.
--
-- METHOD (researched 2026-06-20, see docs/claude_audits/
-- community_graph_edges_research_2026-06-20.md; industry-standard sparse top-K
-- "related items" graph per Neo4j GDS topK/topN/similarityCutoff + Pinterest
-- PinSage fixed-size neighbourhoods):
--   score = IDF-weighted COSINE over each canonical's public tag vector
--   idf(t) = ln(N / df(t))   -- N = public canonicals, df = canonicals carrying t
-- Hub control is the load-bearing part (raw co-occurrence is provably biased
-- toward globally popular tags — Cattuto et al. 2008, arXiv 0805.2045). FOUR
-- independent brakes, so one popular tag can never connect everything:
--   1. IDF down-weighting  — a tag on many canonicals is worth ~0 (ln(N/N)=0).
--                            This is the PRIMARY brake: because the score is a
--                            cosine over IDF weights, two zettels sharing only
--                            `commentary`(df=18) score far below the floor,
--                            while two sharing only `psychedelics`(df=7) clear
--                            it. Cosine is not rank-dominated (ibid.).
--   2. p_max_df_ratio      — belt-and-braces ceiling: a tag on >50% of the corpus
--                            is not allowed to pair at all.
--   3. p_top_k             — each node keeps only its K strongest neighbours.
--   4. p_min_shared        — require N shared tags. Retained as a tunable but
--                            DEFAULTS TO 1; see calibration note below.
-- Plus p_min_strength (the similarity floor) and p_limit (global edge cap).
--
-- CALIBRATION (2026-06-22, measured read-only against the live corpus — the
-- research explicitly refused to supply a borrowed constant, so these defaults
-- are empirical, not guessed). Corpus: 190 canonicals, 174 tagged, 163 with at
-- least one shared tag (the connectivity CEILING), 129 shared vs 715 SINGLETON
-- tags. Measured (top_k=10, max_df_ratio=0.50):
--     min_shared=2, floor=0.15 ->  46 edges, 53 nodes connected  (33% of ceiling)
--     min_shared=1, floor=0.10 -> 290 edges, 132 nodes connected (81%)
--     min_shared=1, floor=0.05 -> 451 edges, 154 nodes connected (94%)  <-- chosen
-- Max degree stayed at 14 in ALL min_shared=1 runs — i.e. NO hub explosion, the
-- IDF cosine alone contains it. Requiring 2 shared tags was the a-priori design
-- but costs ~54% of connectable nodes for no hub-safety gain, because this
-- corpus's tags are overwhelmingly idiosyncratic (715 singletons). Hence
-- min_shared defaults to 1 and the IDF floor does the filtering.
--
-- The floor is deliberately PERMISSIVE (0.05 = a noise floor, not a taste
-- filter). Presentation-level culling belongs to the caller's `min_strength`
-- request param, which _apply_min_strength_filter applies against each link's
-- connection_strength — layering the user's slider on top of the DB noise floor.
--
-- user_tags ONLY — NOT derived_tags. Migration 72 split system-derived tags
-- (source_domain:youtube.com, modality:video, speaker:*) out of user_tags
-- precisely because they are not user semantics; they are also pure hubs (every
-- YouTube zettel shares one), so pairing on them would manufacture noise.
--
-- PRIVACY: identical fail-closed posture to 88 — SECURITY DEFINER + OWNER
-- community_reader (non-BYPASSRLS), so the body runs under the migration-87 RLS
-- policy `is_private = false AND deleted_at IS NULL`. Private rows therefore
-- cannot enter the tag vocabulary, the IDF statistics, or any edge. No new
-- grants are needed: community_reader already holds SELECT on
-- content.workspace_zettels (87), the only table this reads.
--
-- COST: exact computation, no materialized view and no pg_cron. At N=125 public
-- canonicals the self-join is sub-second and the existing SWR cache + version
-- counter (89) absorbs it. Documented escalation at ~5-10k canonicals: promote
-- to a MATERIALIZED VIEW refreshed CONCURRENTLY by pg_cron, or move the
-- semantic tier to pgvector ANN. Deliberately NOT built now (minimal infra).
--
-- Node ids are byte-identical to 88's ('web-' || left(canonical::text, 12)) so
-- the frontend joins links to nodes without a translation layer.

BEGIN;

CREATE OR REPLACE FUNCTION content.community_graph_edges_v1(
    p_limit        int  DEFAULT 4000,   -- global edge cap (topN)
    p_top_k        int  DEFAULT 10,     -- per-node neighbour cap (topK)
    p_min_shared   int  DEFAULT 1,      -- min shared tags (calibrated: 1; see header)
    p_min_strength real DEFAULT 0.05,   -- IDF-cosine noise floor (similarityCutoff)
    p_max_df_ratio real DEFAULT 0.50    -- tags on >this share of corpus cannot pair
)
RETURNS TABLE (
    source_node_id text,
    target_node_id text,
    strength       real,
    shared_tags    int
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
-- Per-call safety net (independent of role-level settings on community_reader).
-- These MUST be function-level SET clauses, NOT `SET LOCAL` in the body: Postgres
-- rejects SET inside a non-VOLATILE function ("SET is not allowed in a
-- non-volatile function"), so a STABLE function with SET LOCAL fails on EVERY
-- call. Function-level SET has the same semantics (applied on entry, restored on
-- exit) and is legal here. Verified against postgres:15.
SET search_path = public
SET statement_timeout = '30s'
SET work_mem = '32MB'
AS $$
BEGIN
  RETURN QUERY
  WITH canon_tags AS (
      -- One row per (canonical, tag): the UNION of tags across every PUBLIC
      -- workspace copy of that canonical. GROUP BY is the dedup (two users
      -- tagging the same canonical `python` must not double-count).
      -- Tags are already NFKC+lower+trim normalized at rest (migration 73);
      -- btrim/lower here is idempotent belt-and-braces for pre-73 rows.
      SELECT wz.canonical_zettel_id AS cid,
             lower(btrim(t))        AS tag
        FROM content.workspace_zettels wz
        CROSS JOIN LATERAL unnest(wz.user_tags) AS t
       WHERE wz.is_private = false        -- forced opt-out predicate (mirrors 88)
         AND wz.deleted_at IS NULL
         AND t IS NOT NULL
         AND length(btrim(t)) > 0
       GROUP BY wz.canonical_zettel_id, lower(btrim(t))
  ),
  totals AS (
      SELECT GREATEST(COUNT(DISTINCT cid), 1)::float AS n FROM canon_tags
  ),
  tag_df AS (
      -- df = number of DISTINCT public canonicals carrying the tag. canon_tags
      -- is already unique on (cid, tag), so COUNT(*) is that count.
      SELECT tag, COUNT(*)::float AS df FROM canon_tags GROUP BY tag
  ),
  tag_idf AS (
      SELECT d.tag,
             d.df,
             ln(t.n / d.df) AS idf,   -- df = N  ->  idf = 0 (carries no signal)
             t.n            AS n
        FROM tag_df d CROSS JOIN totals t
  ),
  weights AS (
      -- FULL tag vector per canonical (including tags unique to one canonical).
      -- Used for the cosine NORM so a note with many unshared tags is correctly
      -- penalised — this is what stops "we share 2 tags and nothing else" from
      -- scoring 1.0.
      SELECT c.cid, c.tag, i.idf, i.df, i.n
        FROM canon_tags c
        JOIN tag_idf i ON i.tag = c.tag
       WHERE i.idf > 0
  ),
  norms AS (
      SELECT cid, sqrt(SUM(idf * idf)) AS nrm
        FROM weights
       GROUP BY cid
      HAVING SUM(idf * idf) > 0
  ),
  pairable AS (
      -- Only tags that CAN link two canonicals, and are not corpus-wide hubs.
      SELECT w.* FROM weights w
       WHERE w.df >= 2
         AND w.df <= GREATEST(2.0, (p_max_df_ratio)::float * w.n)
  ),
  raw_pairs AS (
      SELECT a.cid AS a_cid,
             b.cid AS b_cid,
             SUM(a.idf * b.idf) AS dot,
             COUNT(*)::int      AS n_shared
        FROM pairable a
        JOIN pairable b ON b.tag = a.tag AND b.cid > a.cid   -- unordered pairs
       GROUP BY a.cid, b.cid
      HAVING COUNT(*) >= GREATEST(1, p_min_shared)
  ),
  -- NOTE: internal columns are named sim / n_shared, NOT strength / shared_tags.
  -- RETURNS TABLE declares those as OUT parameters, and plpgsql substitutes
  -- variables into the query — a bare `strength` column reference would raise
  -- `column reference "strength" is ambiguous` at runtime. They are aliased to
  -- the OUT names only in the final SELECT, where aliasing is unambiguous.
  scored AS (
      SELECT r.a_cid,
             r.b_cid,
             (r.dot / (na.nrm * nb.nrm))::real AS sim,
             r.n_shared
        FROM raw_pairs r
        JOIN norms na ON na.cid = r.a_cid
        JOIN norms nb ON nb.cid = r.b_cid
       WHERE (r.dot / (na.nrm * nb.nrm)) >= p_min_strength
  ),
  directed AS (
      -- Expand to both directions so top-K is evaluated from EACH endpoint.
      SELECT a_cid AS src, b_cid AS dst, sim, n_shared FROM scored
      UNION ALL
      SELECT b_cid AS src, a_cid AS dst, sim, n_shared FROM scored
  ),
  ranked AS (
      SELECT src, dst, sim, n_shared,
             ROW_NUMBER() OVER (PARTITION BY src ORDER BY sim DESC, dst) AS rn
        FROM directed
  ),
  kept AS (
      -- UNION symmetrisation: keep the edge if it is in EITHER endpoint's
      -- top-K. (Mutual-KNN — the stricter variant — is the documented upgrade
      -- for the future embedding tier, where hubness is severe; for the tag
      -- tier the IDF-cosine floor already contains hubs — measured max degree
      -- 14 — and mutual-KNN would over-sparsify a 190-node corpus.)
      SELECT DISTINCT
             LEAST(src, dst)    AS a_cid,
             GREATEST(src, dst) AS b_cid,
             sim,
             n_shared
        FROM ranked
       WHERE rn <= GREATEST(1, p_top_k)
  )
  SELECT 'web-' || left(k.a_cid::text, 12) AS source_node_id,
         'web-' || left(k.b_cid::text, 12) AS target_node_id,
         k.sim      AS strength,
         k.n_shared AS shared_tags
    FROM kept k
   ORDER BY k.sim DESC, k.a_cid, k.b_cid
   LIMIT GREATEST(1, LEAST(p_limit, 20000));
END
$$;

-- Must run AS community_reader (non-BYPASSRLS) so the migration-87 RLS policy
-- bites if the is_private predicate is ever dropped. Load-bearing DDL.
ALTER FUNCTION content.community_graph_edges_v1(int, int, int, real, real)
  OWNER TO community_reader;

-- Called via the app's service_role connection only; no PostgREST anon exposure.
REVOKE ALL ON FUNCTION content.community_graph_edges_v1(int, int, int, real, real) FROM public;
GRANT EXECUTE ON FUNCTION content.community_graph_edges_v1(int, int, int, real, real) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
