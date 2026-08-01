# Community Graph — Edge Construction Research & Holistic Solution

**Date:** 2026-06-20
**Author:** assistant (deep-research workflow `wf_530a189a-705` — 108 agents, 26 sources fetched, 123 claims extracted, 25 adversarially verified → 19 confirmed / 6 killed)
**Companion docs:** `community_graph_design_2026-06-15.md` (Rev 3, opt-out), `community_graph_partb_research_2026-06-16.md` (privacy/role research), `docs/superpowers/plans/2026-06-16-community-graph-partb.md` (Phase 0+1 plan)
**Scope:** answers *why the community graph has no edges* and *how to add them properly* — the edge half deferred out of Part B Phase 1.

---

## TL;DR — the holistic answer

The industry-standard, low-infra way to connect a cross-user "community" knowledge graph is **a sparse top-K "related items" graph**, *not* "connect every pair above a threshold." For each note keep only its **top-K most-related neighbours**, above a **similarity floor**, with a **global edge cap** — the exact mechanism Neo4j GDS and Pinterest PinSage run at web scale. Both signals we already have are valid and complementary: **shared-tag (folksonomy) overlap** and **BGE embedding (cosine) similarity** — hybrid is the mature pattern. The one non-negotiable is **hub control**: a popular tag (`commentary`=18, `python`=15) must not be allowed to connect everything — solved with **IDF down-weighting + per-node top-K + a min-shared-signal floor** on the tag side, and **mutual-KNN / Mutual Proximity** on the embedding side.

At our current size (125 published canonicals) **exact computation in Postgres is trivially cheap** and is the correct fix now; the approximate-KNN machinery is a documented escalation at ~5–10k notes, not a blocker today.

---

## Part 1 — Root-caused issues (recap)

| # | Issue | Evidence |
|---|---|---|
| 1 | Live Global = 29-node file-store demo, not real data | live Global `29·52`; DB has 136 workspace_zettels |
| 2 | `community_graph_v1` RPC is node-only (zero edges) | `88_*.sql` RETURNS TABLE has no edge cols; wrapper hardcodes `links: []` |
| 3 | Connectivity data exists but is discarded | 114 user_tags shared across ≥2 canonicals; BGE vectors exist |
| 4 | Per-workspace `kg_edges` cannot cross users | edges keyed to per-workspace node ids (Naruto 340, workspace-scoped) |
| 5 | No cross-workspace shared-tag/semantic edge computation exists | absent in RPC, wrapper, `_enrich_graph_with_analytics` |

Issues 2–5 are one design gap: **there is no cross-user relatedness-edge builder anywhere.** This research specifies that builder.

---

## Part 2 — Verified findings (industry standard, <5yr-prioritised)

### A. Edge construction method — what major products do
- **Sparse top-K "related items" graph is the standard.** Neo4j KNN "creates new relationships between each node and its k nearest neighbours" (per-node K, not all-pairs-over-cutoff); Node Similarity exposes the three canonical knobs **`topK` (per-node), `topN` (global cap), `similarityCutoff` (floor)**. Pinterest PinSage "define[s] importance-based neighborhoods … selecting the neighbors with the highest visit counts" — fixed-size top-T "to control the memory footprint." **Verdict: build sparse top-K, not threshold-only.** [3-0] (neo4j.com/.../knn, /node-similarity, pinterest PinSage)
- **Tag co-occurrence AND embeddings are both valid; hybrid is mature.** Pinterest models a bipartite save-graph (co-occurrence backbone) with visual+text **embeddings as node features**. Folksonomy literature analyses tag co-occurrence, cosine-of-co-occurrence, and FolkRank over a *multi-user* system — exactly our setting. **Verdict: either signal alone is defensible; combining them is the production norm.** [3-0] (arxiv 0805.2045, PinSage)

### B. Hub / popular-tag explosion control (the core risk for us)
- **Raw tag co-occurrence is biased toward popular/hub tags** ("most related tags are among the high-frequency tags, independently of the original tag"); **cosine on tag co-occurrence distributions is NOT rank-dominated** and yields the most semantically precise links (synonyms/siblings, WordNet-validated: cosine 18% same-synset). **Verdict: never use raw shared-count; normalise (IDF / set-similarity / distributional cosine).** [2-1 / 3-0] (arxiv 0805.2045)
- **Hubness is real in embedding space too** — a few notes dominate neighbour lists, degrade KNN quality, and starve "anti-hubs" (≈65% reachability in one study). **Mutual-KNN / Mutual Proximity fixes it**: −99% hub vertices, reachability 65%→92% *at the same edge count* as plain top-K. **Verdict: on the embedding side prefer mutual-KNN/MP over plain top-K.** [3-0] (PMC5750815, arxiv 2112.02234)
- **Dense projections get a "backbone" (disparity filter)** — but this *complements*, not replaces, upstream top-K/IDF (the projection itself is the O(n²) step). [3-0] (CRAN backbone vignette, Serrano 2009)

### C. Scoring metric + threshold
- **Canonical metrics: Jaccard `|A∩B|/|A∪B|`, Overlap (Szymkiewicz–Simpson) `|A∩B|/min(|A|,|B|)`, Cosine.** Standard pairing = **Jaccard/Overlap for tag SETS, Cosine for embeddings.** Overlap surfaces subset/containment (a small specific note fully inside a broad note → 1.0) — useful for small/unequal tag-sets. **Verdict: Jaccard-or-Overlap on tags, cosine on vectors.** [3-0 / 2-1] (neo4j node-similarity & knn, nvidia overlap-vs-jaccard)
- **Threshold/K value is NOT given by industry** — must be calibrated on our own corpus (see open questions). [mechanism confirmed; constant not]

### D. Cost / scale → why sparsify
- **Exact all-pairs node similarity = O(n²) space, O(n³) time.** At scale you MUST pre-filter (degree cutoff, component split) + top-K, or move to approximate KNN. **NN-Descent scales quasi-linearly (~n^1.14).** **Verdict: exact is fine for hundreds; approximate/pgvector-ANN at 10k+.** [3-0] (neo4j node-similarity & knn, Dong WWW2011)
- **Critical nuance (refuted over-claim):** in the *exact* algorithm `topK` bounds **memory, not runtime** — only degree/component filtering shrinks the comparison set. Do **not** assume "add topK" makes an exact self-join cheap. [exact-algo caveat]

---

## Part 3 — Each issue → researched solution

| Root-cause issue | Holistic solution (researched) |
|---|---|
| #2 RPC node-only | Add an **edge-returning companion** (or extend the RPC) producing a sparse top-K related-note edge set over public canonicals |
| #3 data discarded | Use **tag-set overlap (IDF-weighted)** now (114 shared tags); layer **BGE cosine** edges when zettel-level vectors are confirmed |
| #4 per-workspace edges can't cross users | Compute over the **deduped canonical layer** (community RPC already dedups by `canonical_zettel_id`), not per-workspace nodes |
| #5 no cross-user builder | New **sparse top-K builder**: per-note top-K, similarity floor, global cap, **IDF hub down-weighting**, min-shared-signal ≥ 2 (or weighted-overlap ≥ cutoff) |
| Hub blow-up (`commentary`=18 → 153 edges) | **IDF weight** (rare shared tag ≫ common) + **top-K cap** + **floor** so a lone hub tag never makes an edge |

---

## Part 4 — Pragmatic design for our scale & data

**Scale math (ours):** n=125 → n²≈15.6k, n³≈2M (sub-second SQL). n=1,000 → n³≈10⁹ (seconds, periodic). n=10,000 → n³≈10¹² (exact too costly → ANN). **So exact, hub-controlled SQL is correct now and comfortable into low thousands.**

**Recommended build (Phase-1.5, additive, all inside Postgres):**
1. **Tag backbone (primary, data-confirmed).** Over the **published-only** canonical set, compute per-pair **IDF-weighted tag overlap** (each shared tag weighted `ln(N/df_tag)`, so `psychedelics`(7) ≫ `commentary`(18)). Keep an edge only if **weighted-overlap ≥ cutoff AND shared-tag-count ≥ 2** (kills lone-hub-tag edges). Then **per-node top-K (start K≈8–10)** and a **global cap**.
2. **Materialise + refresh.** A `MATERIALIZED VIEW` (or plain edge table) refreshed by **pg_cron** (already available) after ingestion / every N min. `REFRESH MATERIALIZED VIEW CONCURRENTLY` (unique-index required) holds **no exclusive lock** → reads never block. Memory is KB→low-MB even at 10k with capping.
3. **Semantic layer (enhancement, gated on a check).** If published canonicals have a usable zettel-level BGE vector, add **pgvector cosine top-K** edges with **mutual-KNN** (cheap mutual filter) to tame hubs, then **union-dedup** with the tag backbone. Fusion weight calibrated empirically.
4. **Serve.** Community RPC returns nodes **+ this capped edge set**; wrapper stops hardcoding `links: []`; `_enrich_graph_with_analytics` runs PageRank/clustering on the real edges.
5. **Escalation path (documented, not built now):** at ~5–10k notes switch the semantic side to **pgvector HNSW ANN** and/or **disparity-filter** the tag projection. No infra change — same Postgres.

---

## Part 5 — Side-effects & infra-overhead check (req #4)

- **No new service / infra.** Everything stays in Supabase Postgres (matview + pg_cron + optional pgvector, all already present).
- **Memory:** tag self-join over public canonicals is KB-scale at 125; bounded by top-K cap at 10k. Safe under the 2GB ceiling.
- **CPU:** a periodic refresh blip, not steady-state. `CONCURRENTLY` avoids read-blocking.
- **Protected knobs:** untouched (no gunicorn workers/timeout/semaphore/heartbeat/Caddy changes).
- **Privacy:** edge builder runs **inside the same published-only predicate** as the community_reader RPC → no private row enters the projection → no leakage (see open Q1 + regression-gate requirement).
- **Backward-compat:** purely additive; Personal graph (`_v2_assemble_graph`, per-workspace `kg_edges`) is untouched.

---

## Part 6 — What research did NOT settle (our determinations needed)

1. **Privacy/leakage** — no source addressed whether public-only edge computation can leak private content. **Determination:** build the projection/ANN index strictly from the `is_private=false` view; extend the existing "private-never-appears" `@live` gate to also assert **no edge references a private/absent node**. (Co-occurrence counts are aggregates over public notes only → safe by construction.)
2. **Hybrid fusion** — sources confirm tags+embeddings are complementary but give **no fusion weight**. **Determination:** start with **union-of-top-K-per-signal** (simplest, defensible); tune weight on our data.
3. **Threshold/K calibration** — no defensible constant. **Determination:** sweep K∈{5,8,10,15} and cutoff on our 125 canonicals; eyeball edge precision (don't borrow the music-domain k=5).
4. **Matview-refresh vs incremental-on-insert** — not compared at 2GB. **Determination:** start with full `CONCURRENTLY` refresh (cheap at our size); revisit incremental only if refresh cost grows.
5. **Mutual Proximity on text embeddings** — proven on audio, not BGE text. **Determination:** A/B mutual-KNN vs plain top-K before committing extra compute.

---

## Part 7 — Refuted claims (do NOT rely on)

- ✗ pgvector **HNSW is the "recommended default"** KNN initializer over partition/LSH — the cited benchmark did not support it (0-3).
- ✗ **Obsidian Smart Connections** establishes embeddings as the "dominant" related-note approach (0-3).
- ✗ **`topK` alone caps edge count / reduces exact runtime** — bounds memory only (1-2); and the bare "Jaccard = neighbour-set overlap" graph framing (0-3).

---

## Appendix — primary sources
- Neo4j GDS — KNN: https://neo4j.com/docs/graph-data-science/current/algorithms/knn/
- Neo4j GDS — Node Similarity (topK/topN/cutoff, Jaccard/Overlap/Cosine, O(n²)/O(n³)): https://neo4j.com/docs/graph-data-science/current/algorithms/node-similarity/
- Pinterest PinSage (KDD 2018): https://medium.com/pinterest-engineering/pinsage-a-new-graph-convolutional-neural-network-for-web-scale-recommender-systems-88795a107f48
- Cattuto et al., tag relatedness measures (ISWC/ECAI 2008): https://arxiv.org/pdf/0805.2045
- Mutual Proximity / hubness in KNN graphs (PMC5750815): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5750815/
- Hubness effect on NN-graph construction: https://arxiv.org/pdf/2112.02234
- Overlap vs Jaccard coefficient (NVIDIA): https://developer.nvidia.com/blog/similarity-in-graphs-jaccard-versus-the-overlap-coefficient-2/
- backbone / disparity filter (CRAN): https://cran.r-project.org/web/packages/backbone/vignettes/backbone.html
- pgvector HNSW (Supabase): https://supabase.com/blog/increase-performance-pgvector-hnsw
- pg_cron (Supabase): https://supabase.com/docs/guides/database/extensions/pg_cron
- REFRESH MATERIALIZED VIEW (PostgreSQL): https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html
