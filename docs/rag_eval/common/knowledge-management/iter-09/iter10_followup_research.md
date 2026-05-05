# Iter-10 follow-up research (post-user-feedback)

> **Scope:** deep research pass for the seven items the user flagged as "needs more rigor" after approving the obvious harness-fix + auto-title-outside-slot + q10 un-gate set. Each item gets a verdict, two+ sources, general approach, specific approach, cross-class regression risk, trade-off matrix, cost, and a falsifiable test.
>
> **Inputs verified before recommendations:**
>
> - `docs/rag_eval/common/knowledge-management/iter-09/PLAN.md` (full)
> - `docs/rag_eval/common/knowledge-management/iter-09/RESEARCH.md` (RES-1..RES-7)
> - `docs/rag_eval/common/knowledge-management/iter-09/iter09_failure_deepdive.md` (Agent B forensic per-query)
> - `docs/rag_eval/common/knowledge-management/iter-09/prior_attempts_knowledge_base.md` (Agent A iter-04..iter-08 changelog + rejected approaches)
> - `docs/rag_eval/common/knowledge-management/iter-09/iter10_solutions_research.md` (Agent C P1..P14)
> - `docs/rag_eval/common/knowledge-management/iter-09/queries.json` (KM Kasten 14 queries)
> - `docs/rag_eval/common/knowledge-management/iter-09/verification_results.json` (per-query primary, expected, verdict, latency)
> - `CLAUDE.md` (Critical Infra Decision Guardrails, Research Discipline)
> - `website/features/rag_pipeline/retrieval/hybrid.py:165-293, 318-551, 588-627` (retrieve, dedup_and_fuse, xQuAD)
> - `website/features/rag_pipeline/retrieval/chunk_share.py:29-57` (`should_apply_chunk_share`)
> - `website/features/rag_pipeline/retrieval/anchor_seed.py:8-32` (RPC client)
> - `website/api/chat_routes.py:143-198` (`_post_answer_side_effects`, `_run_answer`)
> - `website/api/_concurrency.py:31-74` (`acquire_rerank_slot`, `QueueFull`)
> - External: BGE reranker docs, FastAPI background-tasks docs, Starlette ASGI middleware docs, Python 3 asyncio.TaskGroup docs, xQuAD original paper (Santos 2010), Hamel Husain Starlette concurrency note.

---

## Summary table

| # | Item | Verdict | Recommended approach |
|---|---|---|---|
| 1 | P3 q5 magnet (gh-zk-org-zk wins THEMATIC top-1) | ⚠ ship-with-mitigation | Score-rank-correlation demote (option e) at xQuAD slot 1 ONLY for THEMATIC/STEP_BACK; gated on a percentile-rank-vs-rerank-rank gap. Do NOT implement a generic cross-encoder gate (option a) — too coarse. Title-overlap demote (option b) and λ tweak (option c) ship as cheap secondary signals. Anchor-seed cosmetic floor 0.30 → 0.20 (option d) NO — lower floor weakens the only thing keeping seeded nodes in the candidate set. |
| 2 | P4 q10 anchor-seed `(n_persons + n_entities) >= 1` re-gate | ✓ ship | Drop the re-gate; trust `anchor_nodes` non-empty as sufficient evidence. The gate is double-filtering: `resolve_anchor_nodes` already requires entity match. Add a defence: only inject seeds whose `node_id` was in `anchor_nodes` (already true via the RPC), AND skip seeded injection if `query_class is THEMATIC` (avoid q5-shape collateral). |
| 3 | Subtle gates differentiating zettel types so fixes don't break other zettel types | ⚠ ship-with-mitigation | Add 2 cheap discriminator signals: `chunk_count_quartile` (already implicit in chunk-share gate; surface explicitly) and `source_type × query_class` weight from `_source_type_boost` (already exists at `hybrid.py:801-847`; document and unit-test the matrix). Defer learned routers, cluster-conditioned reranker fine-tuning. |
| 4 | P9 pre-rerank candidate-quality gate (drop rrf<0.10 before BGE int8) | ⚠ ship-with-mitigation | Ship adaptive percentile-based floor (drop bottom 30% of rerank input set), NOT hard 0.10. Dispatch a scout first to count what fraction of recent eval rows have rrf<0.10; if >40% of pool is below this floor on cold-start queries, hard floor will collapse recall. Adaptive percentile floors with a `min_keep=8` safety lower bound. |
| 5 | P11 pin auto-title to flash-lite | ✓ ship | Auto-title is 5-10 word title generation — flash-lite is the canonically correct tier. Falls back to flash via key-pool when flash-lite quota exhausted (existing GeminiKeyPool model-tier walk). Sources confirm flash-lite "designed for low-latency, cost-sensitive use cases, tasks that don't require sophisticated reasoning". |
| 6 | P14 per-route slot-acquire pattern fragility | ✗ defer to iter-11 | RES-4 already concluded this. ASGI middleware refactor risks mis-ordering with `Depends(get_current_user)` auth (auth must run BEFORE admission so unauthenticated bursts don't consume slots). Industry consensus: Hamel Husain note + Starlette docs confirm middleware-based concurrency is right pattern, but defer to dedicated iter spec. |
| 7 | Per-query latency budget aborter (mid-flight) | ✗ defer to iter-11 | TaskGroup/`asyncio.timeout` cancellation has a documented edge (CPython issues #94398, #116720) where late-created tasks aren't cancelled cleanly. Mid-flight abort can leave Supabase RPC connections, BGE encoder forwards in indeterminate state. Add wall-clock budget logging in iter-10, ship abort in iter-11 with a dedicated test plan. |

---

## Item 1 — P3 q5 magnet (gh-zk-org-zk wins THEMATIC top-1)

### Verdict: ⚠ ship-with-mitigation

The "magnet" definition needs to broaden from chunk-share-based to a score-vs-percentile correlation rule, but only for THEMATIC and STEP_BACK classes. None of the five proposed sub-options should ship in isolation; the safe combination is **(e)** primary + **(b)** secondary, with **(c)** as a cheap λ tweak. Cross-encoder gate **(a)** and floor change **(d)** carry too much cross-class regression risk to ship.

### General approach for similar zettels (THEMATIC + STEP_BACK)

The principle: **a top-1 candidate that is anomalously high vs its retrieval-stage percentile is a magnet, not a winner.** Conventional MMR/xQuAD guards against intra-list redundancy. They do NOT guard against "low-rrf candidate gets a disproportionate cross-encoder boost from lexical magnet effects". For THEMATIC queries the user is asking for cross-zettel synthesis; an outlier rank-jump from rrf-pos-7 to rerank-pos-1 is suspicious unless the candidate has supporting evidence (sibling-kind agreement, anchor-neighbour membership, author-match). For STEP_BACK same shape. For LOOKUP this exact rank-jump is *expected* (gold zettel may be lexically odd; cross-encoder is doing its job) — so the gate must NOT fire on LOOKUP.

### Specific approach for THIS use case

q5 case as confirmed in deep-dive: gh-zk-org-zk has 2 chunks (smallest in the kasten of {16, 13, 10, 6, 6, 3, 2}). It does NOT win via chunk-share inflation — the chunk-share gate is correctly NOT damping it (`max/median = 16/6 = 2.67`, threshold met, but the high-chunk magnets are damped instead, making the SMALL magnet relatively stronger). It wins via dense+title overlap on "knowledge worker / day / thinking" semantic neighborhood + the consensus bump (`+0.05 × (hits-1)` at `hybrid.py:391-392`).

**Implementation (option e — score-rank-correlation demote):**

1. After `_xquad_select` returns `ordered`, compute for each candidate the *retrieval-percentile* (its rank in the pre-rerank rrf-sorted list) vs its *rerank-percentile* (its rank in the post-cross-encoder list).
2. If `query_class in {THEMATIC, STEP_BACK}` AND top-1 candidate's retrieval-percentile is below the 50th percentile (i.e. rrf-rank 5+ in a 10-pool) AND its rerank-rank is 1, demote it ONE slot (multiplicative `× 0.95`, never subtractive).
3. Whitelist: skip the demote if the candidate is in `anchor_neighbours` OR has `_author_match_boost > 0` OR is in `effective_nodes` member set with `_ensure_member_coverage` already promoting it. These are evidence-of-relevance signals that justify the rank jump.

**Secondary (option b — title-overlap demote):**

Add a query-aware demote: if a candidate's `_title_match_boost` against the *primary question* (not all variants) is zero AND the candidate is rerank-#1 AND `query_class in {THEMATIC, STEP_BACK}`, demote `× 0.97`. Cheap; uses existing helper at `hybrid.py:730-751`. Helps q5 because gh-zk-org-zk title is "zk-org/zk" — zero overlap with "knowledge worker", "structure a day", "thinking".

**λ tweak (option c — increase novelty term for THEMATIC):**

Current `_xquad_lambda_for_class`:THEMATIC is 0.5 (per RES-2 / iter-08 Phase 3.2). Drop to 0.45 ONLY when `chunk_counts is non-empty AND magnet_detected` (re-use `should_apply_chunk_share` gate result). Tightens novelty when an outlier is in the pool. 5 LOC.

### Risk of breaking other zettel types

- **(a) Cross-encoder semantic-relevance gate at xQuAD slot 1** — DANGEROUS for LOOKUP. q3 Patrick Winston "verbal punctuation" question: BGE will give the exact gold chunk a high score (0.85+) but if the cross-encoder threshold is set at 0.3 as Agent C suggested, that threshold catches q5 but a slightly higher threshold would catch q3-style sparse-retrieval LOOKUPs. **Verdict:** do NOT ship (a).
- **(d) Floor 0.30 → 0.20 anchor-seed** — Q10 case (the only anchor-seed gold-recovery proven case): the seed rrf is 0.20-0.25 from `1 - cosine_distance` on a query embedding distant from a 2-chunk node. Lowering the floor weakens the seed below baseline rrf scores from the rest of the pool, defeating the seeding's purpose. **Verdict:** do NOT ship (d) — keep floor at 0.30.
- **(e) Score-rank-correlation demote** — class-gated to THEMATIC/STEP_BACK only; LOOKUP and MULTI_HOP unaffected. Multiplicative damp `× 0.95` preserves rank ties cleanly (per RES-3 reasoning). Whitelist on `anchor_neighbours` / `_author_match_boost` covers the "legitimate rank jump" case.
- **(b) Title-overlap demote** — same class gate, multiplicative. Could falsely fire on lexically-mismatched-but-correct LOOKUP gold (e.g. q7 "commencement" → yt-steve-jobs-2005-stanford has zero title overlap with "commencement" but is correct gold). **Mitigation:** only fire on THEMATIC/STEP_BACK, where multi-citation is expected.

### Trade-off matrix

| Option | Mechanism | Helps | Hurts | LOC | Risk |
|---|---|---|---|---|---|
| (a) cross-encoder gate at xQuAD slot 1 | hard score floor on top-1 | q5 (drops 2-chunk magnet) | q3 / q11 / q12 LOOKUP if threshold tuned wrong; high false-positive on lexically-sparse gold | 25 | HIGH — breaks ColBERT-style late-interaction principle ("trust cross-encoder") |
| (b) title-overlap demote | multiplicative damp on no-overlap top-1 | q5, q12-shape thematic | q7 vague single-token (mitigated by class gate) | 15 | LOW |
| (c) λ for THEMATIC | greedier xQuAD novelty | q5, q12 | reduces relevance weighting on legit single-source thematic | 5 | LOW |
| (d) anchor-seed floor 0.30→0.20 | weaker injection floor | (none verified) | q10 — defeats RES-7 design | 1 | MEDIUM — silently undoes RES-7 |
| (e) score-rank-correlation demote | demote rank-jumpers in THEMATIC/STEP_BACK | q5 (rrf-pos-3 → rerank-pos-1 disproportion) | none if whitelist covers anchor_neighbours / author / effective_nodes | 30 | LOW with whitelist |

**Recommended ship set:** (e) + (b) + (c). All three multiplicative. Class-gated. Whitelist-protected.

### Cost

- (e) primary: ~30 LOC in `hybrid.py:_dedup_and_fuse` post-`_xquad_select`. ~40 LOC tests (4 cases: thematic-magnet-demoted, lookup-untouched, anchor-neighbour-whitelisted, evidence-protected).
- (b) secondary: ~15 LOC + 2 tests.
- (c) λ tweak: 5 LOC + 1 test.
- Production blast radius: low. All multiplicative damps; no candidate ever DROPPED from pool; cross-encoder still decides final rank.
- Extra LLM calls: 0.

### Falsifiable test

1. **Regression:** rerun iter-04..iter-08 KM fixture. Assert zero THEMATIC-class primary citation flips on q4, q5 (iter-04..iter-07 baseline), q11, q12, q13, q14 vs prior iter scores.
2. **q5 fix:** primary citation changes from `gh-zk-org-zk` to one of the 5 expected thematic nodes (`yt-programming-workflow-is`, `yt-steve-jobs-2005-stanford`, `web-transformative-tools-for`, `yt-matt-walker-sleep-depriv`, `nl-the-pragmatic-engineer-t`).
3. **LOOKUP unbreakage:** q1 (gh-zk-org-zk gold) MUST still pick gh-zk-org-zk as primary. q3, q11, q12 LOOKUP scores stay flat or improve.
4. **Whitelist-correctness:** synthetic test — anchor_neighbours candidate with low-rrf rank should NOT be demoted.

### Sources

- [xQuAD: Explicit Search Result Diversification through Sub-queries (Santos et al. 2010)](https://link.springer.com/chapter/10.1007/978-3-642-12275-0_11) — original framework; novelty term + λ trade-off explicit per-query.
- [Reranking using Cross Encoder — Boost Your RAG Pipeline Accuracy](https://medium.com/@aishikbhattacharjee98/reranking-using-cross-encoder-boost-your-rag-pipeline-accuracy-d2da22006dad) — confirms the standard pattern is "trust the cross-encoder", argues against post-hoc gates.
- `website/features/rag_pipeline/retrieval/hybrid.py:391-403` (consensus bump + title-match boost — the input signal that magnifies the magnet).
- `website/features/rag_pipeline/retrieval/hybrid.py:588-627` (`_xquad_select` — where the demote hook lands).
- `website/features/rag_pipeline/retrieval/chunk_share.py:29-57` (existing magnet-ratio gate; reuse the gate-result for option c λ tweak).
- iter-09 RESEARCH.md RES-3 (multi-gate magnet penalty deferred — option e is a SUBSET of that, score-rank-only, no chunk-count or title-overlap; safer and more orthogonal).

---

## Item 2 — P4 q10 anchor-seed `(n_persons + n_entities) >= 1` re-gate

### Verdict: ✓ ship

Drop the re-gate at `hybrid.py:276`. Add a defence: skip the seeded injection when `query_class is THEMATIC` (avoid q5-shape collateral if anchor resolution accidentally fires for thematic queries via the `compare` clause).

### General approach for similar zettels (LOOKUP + person/entity)

**Principle:** if upstream entity resolution already returned `anchor_nodes` (proof of an entity match in this kasten), do NOT re-gate downstream on a metadata field that may have missed the same surname (NER recall != FTS author/entity recall). Single source of truth for "should we inject anchor seeds?" is the upstream resolution result.

### Specific approach for THIS use case

**Trace the gate's history (from PLAN.md / RESEARCH.md / git):**

- Origin: iter-09 PLAN.md Phase 2 / Task 8 `Step 6: Wire into hybrid.py:retrieve() post-RPC fan-out` — original gate read `compare or (is_lookup and (n_persons + n_entities) >= 1)`.
- Stated intent: "gate the RPC to LOOKUP queries with at least one detected entity OR explicit compare-intent" (RES-7).
- The redundancy: `anchor_nodes` itself is the output of `resolve_anchor_nodes(entities, sandbox_id, ...)` at `hybrid.py:251-253`. If entity resolution returned anchors, by definition there was at least one entity match. The downstream `(n_persons + n_entities) >= 1` re-gate adds NO new information — it just runs the same check on `query_metadata` (which can be more conservative due to NER recall on single-name surnames like "Matuschak", q14, or "Naval", q10).

**What the gate was protecting against (worst-case):**

The only scenario the gate rules out that `anchor_nodes non-empty` doesn't: a query with NO `query_metadata.authors / entities` populated where someone manually pre-set `anchor_nodes` upstream (no current code path does this). That's hypothetical, not real.

**What we lose if we drop the gate:**

LOOKUP queries with anchor entities resolved but `query_metadata.entities = []` due to NER miss now fire anchor-seed. That's exactly q10. Recall improvement, no regression risk because anchor_seed itself only injects seeds for nodes that appeared in entity resolution.

**What we gain noise-wise (concern):**

THEMATIC queries with `compare_intent=true` and any anchor node match would still fire anchor-seed under the original gate (`compare or ...`) — and that path is unaffected by the change. But what if a future THEMATIC query has `compare_intent=false` AND non-empty `anchor_nodes`? Currently that path is blocked. After the change, THEMATIC + anchor_nodes would fire seed injection. Not desired for q5-shape thematic.

**Defensive mitigation:** add `query_class is not QueryClass.THEMATIC` to the gate (THEMATIC bias toward magnet drag is iter-09's primary regression). Final gate:

```python
if compare or (
    query_class in {QueryClass.LOOKUP, QueryClass.MULTI_HOP, QueryClass.STEP_BACK}
    and anchor_nodes
):
    seeds = await fetch_anchor_seeds(...)
```

VAGUE class also benefits from anchor seeding (q7 "commencement" + entity "Stanford" if NER catches it). LOOKUP, MULTI_HOP, STEP_BACK, VAGUE all OK to seed when anchor_nodes is non-empty. THEMATIC explicitly excluded.

### Risk of breaking other zettel types

- **LOOKUP recall improvement** (q10-shape): yes — exactly the design intent. Non-blocking.
- **MULTI_HOP** (q4 walker+programming-workflow): MULTI_HOP queries also benefit from anchor seeding when they name entities. Should help, not hurt.
- **THEMATIC** (q5 / cross-zettel synthesis): explicitly excluded by the new gate. No regression possible from this lever.
- **VAGUE** (q7 "commencement"): if NER does extract "Stanford" or "Jobs", VAGUE fires seed; correct. If not, no seed; same as today.
- **Cross-tenant safety**: the underlying RPC (`rag_fetch_anchor_seeds`) still has `INNER JOIN rag_sandbox_members` (RES-7 Task 8). No tenant leak.

### Trade-off matrix

| Predicate | Helps | Hurts | LOC |
|---|---|---|---|
| iter-09 current: `compare OR (LOOKUP AND n_persons+n_entities>=1)` | most cases | q10 (NER missed Jobs as entity, even though anchor resolved) | 0 |
| Drop re-gate entirely: `compare OR anchor_nodes` | q10 | THEMATIC magnet drag (q5-shape collateral if anchor resolved on thematic) | -3 |
| Drop re-gate, exclude THEMATIC: `compare OR (class != THEMATIC AND anchor_nodes)` ★ | q10, future MULTI_HOP entity queries | none | -3 + 1 conditional |
| Trust upstream confidence: `compare OR (anchor_nodes AND resolution_confidence > 0.7)` | most rigorous | requires `resolve_anchor_nodes` to expose confidence (does not currently) | +20 |

**Recommended:** option 3 (drop + exclude THEMATIC). 4 LOC change.

### Cost

- 4 LOC `hybrid.py:262-282`.
- 1 new unit test: q10-shape (LOOKUP with Jobs surname missed by NER, anchor_nodes non-empty) → seed injection fires.
- 1 regression test: q5-shape (THEMATIC, anchor_nodes hypothetically resolved) → seed injection NOT fired.
- Production blast radius: low. RPC failure already handled silently (`anchor_seed.py:31-32` returns `[]`).
- Extra LLM calls: 0.

### Falsifiable test

1. **q10:** primary becomes `yt-steve-jobs-2005-stanford` (currently None). Verdict shifts from `unsupported_no_retry` to `partial`.
2. **q5 regression check:** primary stays away from `gh-zk-org-zk` and from anchor_seed-only nodes. Specifically, force a THEMATIC query with hypothetical `anchor_nodes=["gh-zk-org-zk"]` injected via test stub; confirm seed injection NOT fired.
3. **q14:** Matuschak query — if anchor_nodes non-empty (Matuschak resolved as author), seeded injection fires. Even if NER missed surname.

### Sources

- iter-09 PLAN.md Phase 2 / Task 8 step 6 (gate origin).
- iter-09 RESEARCH.md RES-7 "Q10 anchor-seed" (stated rationale).
- iter-09 iter09_failure_deepdive.md q10 row, lines 132-143 (forensic confirms anchor resolution likely fired but seed gate or RPC return blocked).
- iter-09 iter10_solutions_research.md row P4.
- `website/features/rag_pipeline/retrieval/hybrid.py:251-282` (resolution + re-gate).
- `website/features/rag_pipeline/retrieval/anchor_seed.py:8-32` (RPC client).

---

## Item 3 — Subtle gates differentiating zettel types so fixes don't break other zettel types

### Verdict: ⚠ ship-with-mitigation

The META question. Ship 2 cheap discriminator signals; defer learned routers. Fixes for q10 (LOOKUP + person + single-name surname) and q5 (THEMATIC + magnet) WILL collide unless the existing class-aware gates are made explicit and audited.

### General approach for HETEROGENEOUS RAG corpora

The corpus is heterogeneous along ≥3 axes:
- `source_type ∈ {youtube, github, newsletter, web}`
- `chunk_count` (2..16 in KM kasten)
- `content_kind` (transcript / article / code / discussion)

Industry consensus from the 2024-2025 RAG survey literature is that **source-type-aware fusion weights** + **per-class retrieval depth** are the highest-ROI signals; learned cluster routers and per-class reranker fine-tuning are higher cost and only justified at >100k corpus scale. The HetaRAG paper explicitly endorses heterogeneous-store integration via simple typed weights, not learned routing for small corpora.

**The trade-off statement:** more gates = more knobs = more places to mis-tune. The win condition is gates with a SHARED predicate vocabulary (shared source-type matrix, shared class taxonomy) so they are visible as a unit instead of scattered constants. A single audit pass across `_source_type_boost`, `_xquad_lambda_for_class`, `_GATED_CLASSES` (chunk_share), `_should_skip_retry` class checks, anchor-seed gate, and the new score-rank-correlation gate (Item 1) lets us see the full matrix.

### Specific approach for THIS use case

Two cheap discriminator signals to add explicitly:

**(1) `chunk_count_quartile` exposed at `hybrid._dedup_and_fuse` level.**
Compute per-candidate `quartile = bisect(sorted(chunk_counts.values()), candidate.chunk_count)` ∈ {0,1,2,3}. Use as a boost gate input — cheaper than the current scalar `chunk_count` because it's robust to absolute scale. Expose to `_xquad_select` so diversity-by-quartile becomes a tie-breaker (when two candidates have similar rrf, prefer different quartiles — promotes mid-chunk-count zettels in a kasten where 16-chunk and 2-chunk magnets coexist).

**(2) `source_type × query_class` matrix audit.**
`_source_type_boost` at `hybrid.py:801-847` already encodes a matrix (e.g. `LOOKUP_RECENCY × newsletter` boost). Add a unit test asserting the matrix per cell — currently NO test enforces e.g. that `LOOKUP × github` doesn't accidentally damp gh-zk-org-zk on q1. With the test, future tweaks can't silently regress a cell.

**Reject (for iter-10, defer to iter-11+):**
- Learned passage-class router (Voyage / Cohere style) — requires labeled training data; build cost > marginal recall.
- Cluster-conditioned reranker fine-tuning — same.
- DPR/multi-vector — architectural rewrite.

### Risk of breaking other zettel types

- **(1) chunk_count_quartile signal**: low risk; adds a tie-breaker that helps when two candidates have near-identical rrf. Could in pathological case flip rank between two equally-good candidates of different quartiles — acceptable.
- **(2) source_type × class matrix audit**: zero risk by itself (test is read-only). Catches future regressions.

### Trade-off matrix

| Signal | Cost | Win | Lose |
|---|---|---|---|
| `chunk_count_quartile` tie-breaker | 15 LOC | nudges mid-chunk zettels up when surrounded by 16-chunk magnet + 2-chunk lexical magnet (q5 helper) | might flip rank between two equally-rrf candidates of different quartiles (acceptable) |
| `source_type × query_class` matrix unit test | 30 LOC test | catches future regression in a 4×6 matrix that's currently un-tested | none |
| Learned class-aware retrieval router (DEFER) | 500+ LOC + train data | cleaner long-term | not justified at 7-zettel scale |
| Cluster-conditioned reranker fine-tuning (DEFER) | 1000+ LOC + train data | best precision | not justified at 7-zettel scale |
| DPR / multi-vector (DEFER) | ~architectural rewrite | best recall on heterogeneous corpora | iter-12+ work; full re-deploy |

### Cost

- 15 LOC `hybrid.py` (chunk_count_quartile in `_xquad_select` tie-break).
- 30 LOC test (matrix audit).
- 0 production blast.
- 0 extra LLM calls.

### Falsifiable test

1. Replay iter-04..iter-09 KM fixture with quartile signal enabled. Assert composite delta within ±2 points (no major regression).
2. Matrix test: synthetic LOOKUP_RECENCY query with newsletter source — assert boost applies. LOOKUP query with github source — assert no spurious damp.
3. q5 + Item 1 + this combined: chunk_count_quartile diversifies the top-3, helps demote both 16-chunk and 2-chunk magnets when mid-quartile candidates exist.

### Sources

- [HetaRAG: Hybrid Deep Retrieval-Augmented Generation across Heterogeneous Data Stores (2024)](https://arxiv.org/html/2509.21336v1) — endorses simple typed-store weights for heterogeneous corpora.
- [A Systematic Review of Key Retrieval-Augmented Generation (RAG) Systems (2025)](https://arxiv.org/html/2507.18910v1) — reviews source-type-aware fusion approaches.
- [Hybrid Retrieval-Augmented Generation Systems for Knowledge-Intensive Tasks](https://medium.com/@adnanmasood/hybrid-retrieval-augmented-generation-systems-for-knowledge-intensive-tasks-10347cbe83ab) — practical guidance on per-class retrieval depth and source-type fusion.
- `website/features/rag_pipeline/retrieval/hybrid.py:801-847` (`_source_type_boost` — existing source-type × class matrix; needs explicit unit test coverage).
- iter-08 RESEARCH.md ACT-1 (rejected: cluster-conditioned reranker fine-tuning — too invasive). Re-confirms defer decision.

---

## Item 4 — P9 pre-rerank candidate-quality gate (drop rrf<0.10 before BGE int8)

### Verdict: ⚠ ship-with-mitigation

Ship adaptive percentile-based floor (drop bottom 30% of rerank input set, with `min_keep=8` lower bound), NOT hard rrf<0.10. Hard 0.10 risks recall collapse on cold-start kastens.

### General approach (heterogeneous corpus, varying recall regimes)

**Principle from cross-encoder reranking literature:** the standard pattern keeps top-K = 50-200 dense candidates, reranks down to 3-10. Pre-filter aggressiveness must be tuned to the bi-encoder/RRF recall floor, not absolute thresholds, because absolute scores are corpus-dependent. The OpenAI Cookbook on cross-encoder reranking explicitly warns: "overly aggressive filtering at an early stage can eliminate relevant documents that later stages can never recover."

**Adaptive percentile** is the standard answer. Keep top-X percentile of rrf scores OR top-K candidates, whichever is larger.

### Specific approach for THIS use case

**Question 1: what fraction of candidates currently have rrf<0.10?**

Need to dispatch a scout. Without that data, I cannot recommend the hard 0.10 floor. Dispatch instrumentation (~10 LOC at `cascade.py` rerank loop) that logs `pre_rerank_rrf_distribution=[p10, p30, p50, p75, p95]` per query. Run iter-09 fixture; collect the distribution. Then choose threshold.

**Question 2: alternatives ranked.**

| Option | Mechanism | Risk |
|---|---|---|
| (a) Hard rrf<0.10 floor | `if c.rrf_score < 0.10: skip` before cross-encoder pair | HIGH — drops legit gold on cold-start when most candidates have low RRF (e.g. 7-zettel kasten where median RRF could be 0.05) |
| (b) Adaptive percentile floor (drop bottom 30%) ★ | `cutoff = percentile(scores, 30)` + `min_keep=8` | LOW — guaranteed minimum 8 candidates always reach reranker |
| (c) Cross-encoder batch-size cap (rerank top-N=20 instead of all 50) | `for c in candidates[:20]: rerank(c)` | MEDIUM — recall drops if ranking is well-calibrated up to position 50 |
| (d) Two-stage rerank: BGE-small first, BGE-int8 on top-K | adds another model load | HIGHEST — multi-iter project; requires re-quantization, threshold re-tuning. Out of scope |

**Recommended:** option (b). 12 LOC + 3 unit tests.

```python
# cascade.py — before the rerank pair loop
_RERANK_PRE_FILTER_PERCENTILE = float(os.environ.get("RAG_RERANK_PRE_FILTER_PERCENTILE", "30"))
_RERANK_PRE_FILTER_MIN_KEEP = int(os.environ.get("RAG_RERANK_PRE_FILTER_MIN_KEEP", "8"))

if len(candidates) > _RERANK_PRE_FILTER_MIN_KEEP:
    scores = [c.rrf_score for c in candidates]
    cutoff = statistics.quantiles(scores, n=100)[int(_RERANK_PRE_FILTER_PERCENTILE) - 1]
    kept = [c for c in candidates if c.rrf_score >= cutoff][:max(_RERANK_PRE_FILTER_MIN_KEEP, len(candidates))]
else:
    kept = candidates
```

### Risk of breaking other zettel types

- **THEMATIC (q5-shape)** — q5 input set has 5+ candidates with rrf in 0.4-0.8 range; bottom-30% percentile cuts the lowest 1-2; gold seeds (walker, jobs) which weren't even in the pool can't be cut by this gate, so q5 is unaffected.
- **LOOKUP (q1, q3, q11, q12, q13, q14)** — gold zettel typically dominates top-3 with rrf>0.5; bottom-30% cut leaves it untouched.
- **VAGUE (q7)** — vague "commencement" expansion produces low rrf scores across pool. Hard 0.10 floor would empty the pool. Adaptive percentile + min_keep=8 protects.
- **Cold-start kasten** — 7-zettel KM kasten + 8 candidates min_keep guarantees reranker always sees full kasten. Hard 0.10 would risk on smaller kastens.

### Trade-off matrix

(See above options table)

### Cost

- 12 LOC + 3 unit tests (full pool, sparse pool, single-candidate edge case).
- Production blast: low; gate is opt-in via env (`RAG_RERANK_PRE_FILTER_PERCENTILE` defaulting to 30; setting it to 0 disables).
- Latency win: 30% fewer cross-encoder pairs ≈ 30% rerank-stage latency reduction. On droplet with ~250-400 ms/pair BGE int8, this is a measurable win.
- Extra LLM calls: 0.

### Falsifiable test

1. **Distribution scout:** before shipping, dispatch `cascade.py` instrumentation; pull droplet logs; confirm `p30(rrf) > 0` for KM kasten (otherwise hard floor risk acknowledged).
2. **Recall regression:** rerun iter-04..iter-09 fixture with gate enabled. Assert composite delta ≥ -1.0 (small expected loss from dropping the absolute lowest candidates, but reranker quality stays).
3. **Latency win:** measure p50 / p95 server-side rerank-stage latency. Expect 20-30% reduction.
4. **Cold-start protection:** synthetic test — pool of 8 candidates all with rrf<0.05; assert all 8 still reach reranker (min_keep guard works).

### Sources

- [Search reranking with cross-encoders (OpenAI Cookbook)](https://cookbook.openai.com/examples/search_reranking_with_cross-encoders) — explicit guidance on pre-rerank candidate window sizing.
- [Reranking using Cross Encoder (Aishik Bhattacharjee, 2024)](https://medium.com/@aishikbhattacharjee98/reranking-using-cross-encoder-boost-your-rag-pipeline-accuracy-d2da22006dad) — practical range 10-30 candidates for reranker.
- [BAAI/bge-reranker-base · Hugging Face](https://huggingface.co/BAAI/bge-reranker-base) — BGE input sizing recommendations.
- iter-09 iter10_solutions_research.md row P9 (original proposal).
- `website/features/rag_pipeline/retrieval/cascade.py:583` (rerank-pair loop call site, per RES-3 reference).

---

## Item 5 — P11 pin auto-title to flash-lite

### Verdict: ✓ ship

Auto-title is the canonical flash-lite use case. No A/B test required for first deploy — the task is a 5-10 word summary, not a sophisticated reasoning task. If user-visible title quality drops noticeably, roll back via env override (`AUTO_TITLE_MODEL=gemini-2.5-flash`).

### General approach (background tasks, cheapest tier)

**Principle:** every background task with a non-user-blocking output should default to the cheapest model tier. The expensive tier should be reserved for user-visible answer generation. Specifically for the GeminiKeyPool (`website/features/api_key_switching/`), the existing key-first traversal already provides fallback: `key1/lite → key2/lite → ... → key1/flash → ...`. So when flash-lite hits a quota during burst, the pool walks to flash anyway — pinning `lite` as the *primary* tier is strictly an improvement.

**Background tasks that should be lite-first:**
- Auto-title (1-2 sentence summary)
- Tag extraction
- Session-level metadata writes
- Query rewriter (already on flash; could downgrade in future iter)
- Critic verdict (NO — needs reasoning; stays flash/pro)

### Specific approach for THIS use case

**Implementation:** 1-3 LOC in `website/features/sessions/auto_title.py` (or wherever `auto_title_session` is defined) — pin `model="gemini-2.5-flash-lite"` in the GeminiKeyPool call.

**Quality test (manual smoke, no code):** generate 5 sample titles for 5 sessions:
- "What is the zk command-line tool written in?"
- "Compare Steve Jobs and Naval on meaningful work"
- "How does Matuschak define augmented book"
- "Anything about commencement?"
- "What does Walker say about sleep and emotion regulation"

Check titles render coherently. If yes, ship. If a title is gibberish, fall back to flash.

### Cross-effect: key-pool fallback behaviour

GeminiKeyPool key-first traversal: when flash-lite hits 429, the pool walks `key1/lite → key2/lite → ... → key1/flash`. So flash-lite quota exhaustion does not break auto-title — it adds 5-15s cascade latency. Acceptable for non-blocking auto-title when it's outside the rerank slot (post Phase 3 / Task 3.1 of iter-10). Before that fix, the 5-15s cascade still blocks the slot. So auto-title-tier-pin and auto-title-outside-slot must ship together (already in Agent C's approved set).

### Risk

- Title quality regression: low — Gemini blog post, llm-stats benchmark, and Vertex AI docs all confirm flash-lite handles 1-2 sentence summarization well. "Designed for low-latency, cost-sensitive use cases, tasks that don't require sophisticated reasoning."
- Quota exhaustion: handled by pool fallback.
- User-visible: titles are visible in the sessions list. Mitigation: env-flag-revertible.

### Cost

- 1-3 LOC.
- 1 manual smoke (5 titles).
- Production blast: low. Failure mode = title quality drop, recoverable.
- Extra LLM calls: 0 (replacement, not addition).

### Falsifiable test

1. Generate 5 sample titles via flash-lite vs flash; check coherence.
2. Measure auto-title latency: expect 1-3s vs current 15-40s.
3. After Phase 3 (auto-title outside slot) ships: server `latency_ms_server` for first-message-of-session unaffected by auto-title; can verify by hitting `/api/rag/adhoc` twice in same session and comparing `latency_ms_server`.

### Sources

- [Gemini 2.5 Flash-Lite | Vertex AI docs](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-lite) — official "low-latency, cost-sensitive" positioning.
- [Improved Gemini 2.5 Flash and Flash-Lite (Sep 2025, Simon Willison)](https://simonwillison.net/2025/Sep/25/improved-gemini-25-flash-and-flash-lite/) — confirms flash-lite quality has improved across the 2.5 series.
- [Comparing Gemini 2.5 Flash-Lite, Flash, and Pro](https://medium.com/@asmita.vishwakerma/comparing-gemini-2-5-flash-lite-flash-and-pro-34f8fafde4c5) — practical guidance on tier selection.
- [Gemini 2.5 Flash vs Gemini 2.5 Flash-Lite Comparison (llm-stats)](https://llm-stats.com/models/compare/gemini-2.5-flash-vs-gemini-2.5-flash-lite) — flash wins on 10 reasoning benchmarks; flash-lite is 4.9x cheaper.
- iter-09 iter10_solutions_research.md row P11 (original proposal).
- CLAUDE.md "API Key Pool & Model Fallback" section (key-first traversal documented).

---

## Item 6 — P14 per-route slot-acquire pattern fragility

### Verdict: ✗ defer to iter-11

Per-route guard is fragile (drift risk every new endpoint), but ASGI middleware refactor in iter-10 risks mis-ordering with auth dependency. RES-4 already concluded this. Industry research confirms middleware is the right durable pattern; iter-10 should not re-litigate without a dedicated spec.

### General approach (Starlette/FastAPI bounded concurrency)

**Industry consensus from sources:**
- **Hamel Husain** (Answer.AI Starlette concurrency note, 2024): bounded concurrency for Starlette apps is best implemented via `asyncio.Semaphore` held at app scope with middleware enforcement OR via a thread-pool size constraint. Per-route guards are explicitly "drift-prone" because new routes silently bypass.
- **Starlette docs:** "All middleware in Starlette must be a class with `async def __call__(self, scope, receive, send)`." Pure ASGI middleware composes cleanly with FastAPI's dependency-injection auth.
- **FastAPI advanced middleware docs:** order matters — auth middleware MUST run before admission, otherwise unauthenticated bursts consume slots.

**Two valid patterns:**
1. Pure ASGI middleware (`__call__(scope, receive, send)`) — finest control, hardest to write.
2. `BaseHTTPMiddleware` (Starlette-provided) — simpler, but introduces an extra anyio task per request that can subtly affect timeouts (well-documented Starlette issue).

### Specific approach for THIS use case (if we WERE to do it in iter-10)

Hypothetical refactor:

```python
# website/api/_admission_middleware.py (new)
from starlette.middleware.base import BaseHTTPMiddleware
from website.api._concurrency import acquire_rerank_slot, QueueFull

_RAG_PATHS = {"/api/rag/adhoc", "/api/chat/sessions"}

class RagAdmissionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path not in _RAG_PATHS or request.method != "POST":
            return await call_next(request)
        try:
            async with acquire_rerank_slot():
                return await call_next(request)
        except QueueFull:
            return JSONResponse(
                {"code": "queue_full", "message": "Rerank capacity full; retry shortly."},
                status_code=503,
                headers={"Retry-After": "5"},
            )
```

**Why this is iter-11 not iter-10:**

1. **Auth ordering risk:** `Depends(get_current_user)` runs in route handlers, AFTER middleware. So unauthenticated bursts WOULD consume slots if middleware admission runs first. Fix requires either (a) auth-as-middleware refactor, or (b) explicit path skip for unauthenticated probes — both nontrivial scope.
2. **Stream-path interaction:** `_stream_answer` already wraps `acquire_rerank_slot()` at `chat_routes.py:240`. Middleware wrap would double-acquire — need to remove the inner one. State migration risk during deploy.
3. **CLAUDE.md guarded subsystem:** the rerank semaphore is on the protected list. Refactor without dedicated iter spec violates Research Discipline.
4. **Iter-09 RES-4 already concluded:** "the per-route fix is the minimal symmetry restoration; middleware refactor is iter-10+ scope".

### Risk of mid-iter-10 attempt

HIGH. Mis-ordering auth + admission could allow unauthenticated probe floods to consume slots → DOS vector. Fixing this requires a dedicated test plan covering: auth-failed admission, stream/non-stream parity, env-flag rollback, double-acquire detection.

### Trade-off matrix

| Option | LOC | Risk | Iter |
|---|---|---|---|
| Per-route guard (current) | 0 | Drift if new endpoints added without wrap | shipped iter-09 |
| Decorator-based `@admit` | 30 | Forgot decorator = drift | iter-10 (alt) |
| Single ASGI middleware (BaseHTTPMiddleware) | 60 | Auth ordering, double-acquire | iter-11 |
| Pure ASGI middleware | 80 | Same + `__call__` complexity | iter-11 |

### Cost (if shipped iter-10)

- 60 LOC middleware + 30 LOC migration (remove inner wraps) + 50 LOC test (auth-failed, stream, non-stream, double-acquire).
- Production blast radius: HIGH — admission is on the CLAUDE.md protected list.
- Extra LLM calls: 0.

### Falsifiable test (when shipped)

1. Burst 12-concurrent → ≥1 503 with `Retry-After: 5`. Same as today.
2. Burst 12-concurrent unauthenticated → 401s without consuming slots (auth-before-admission test).
3. Stream + non-stream parity: same admission behaviour on both paths.
4. Replay iter-04..iter-09 fixtures — zero regression.

### Sources

- [Concurrency For Starlette Apps (Hamel Husain, Answer.AI 2024)](https://www.answer.ai/posts/2024-10-10-concurrency.html) — endorses semaphore-as-middleware over per-route guards.
- [Middleware - Starlette docs](https://starlette.dev/middleware/) — pure ASGI vs `BaseHTTPMiddleware` trade-offs.
- [FastAPI Background Tasks and Middleware (Sentry)](https://sentry.io/answers/fastapi-background-tasks-and-middleware/) — middleware ordering with auth.
- [The Core of FastAPI: Deep Dive into Starlette](https://dev.to/leapcell/the-core-of-fastapi-a-deep-dive-into-starlette-59hc) — middleware ordering rules.
- iter-09 RESEARCH.md RES-4 (refactor explicitly deferred).
- iter-09 iter10_solutions_research.md row P14 (confirms defer).
- `website/api/_concurrency.py:31-74` (current `acquire_rerank_slot`).
- `website/api/chat_routes.py:156-198, 240` (current per-route wrap pattern).

---

## Item 7 — Per-query latency budget aborter (mid-flight)

### Verdict: ✗ defer to iter-11

Mid-flight cancellation is the right long-term fix for tail-latency tail control, but Python's `asyncio.TaskGroup` has documented nested-cancellation edges (CPython issues #94398, #116720) that introduce silent state-corruption risk — especially for our Supabase RPC connections and BGE encoder forward passes where partial state is unrecoverable. Iter-10 should ship wall-clock budget LOGGING only.

### General approach (production RAG mid-flight aborts)

**Industry patterns from research:**

1. **`asyncio.wait_for` at retrieval boundaries** — straightforward; cancels the awaited coroutine via `CancelledError`. Caveat: if the awaited code does I/O (Supabase RPC), the cancellation propagates only if the I/O lib respects it. `httpx` does. Some `psycopg`/`asyncpg` connections may leave the pool in a partial state.
2. **Structured concurrency via `asyncio.TaskGroup` (Python 3.11+)** — preferred for nested aborts. But [CPython issue #94398](https://github.com/python/cpython/issues/94398) confirms TaskGroup may not cancel late-created tasks if `_aborted` is already set; [issue #116720](https://github.com/python/cpython/issues/116720) confirms nested TaskGroup can swallow parent cancellation.
3. **`asyncio.timeout` context manager** — Python 3.11+; cleanest. Same caveats as TaskGroup re: late-created tasks and nested swallows.
4. **OpenAI Cookbook on streaming aborts** (referenced via search): primary recommendation is to abort the synthesis stream at user-perceived budget, NOT the retrieval stage (synthesis is the visible 80% of latency).

**Risks for OUR architecture:**

- **Retrieval mid-abort:** Supabase RPC mid-flight cancellation may leave a pgvector index scan partially consumed. Acceptable; postgres handles client disconnect.
- **Rerank mid-abort:** BGE int8 ONNX inference is in a thread (via `loop.run_in_executor`). `CancelledError` at the await DOES NOT cancel the inflight ONNX forward pass. The thread continues, the result is discarded. Wasted compute but safe.
- **Synthesis mid-abort:** Gemini streaming abort is supported via `httpx` cancellation. Clean.
- **Critic mid-abort:** ditto.

### Specific approach for THIS use case

**Phase iter-10 (this iteration):** wall-clock budget LOGGING only, no abort.

```python
# website/features/rag_pipeline/orchestrator.py: answer
budget_ms = budget_for_class(query_class)
t0 = time.monotonic()
# ... existing retrieval, rerank, synth, critic ...
t_total = (time.monotonic() - t0) * 1000
if t_total > budget_ms * 0.8:
    _log.warning("[budget] over_80pct query_class=%s elapsed_ms=%.0f budget_ms=%.0f", query_class, t_total, budget_ms)
```

This gives data for iter-11 abort policy without behaviour change.

**Phase iter-11 (next iteration):** ship abort with `asyncio.timeout` at synthesis boundary only (NOT retrieval/rerank — too risky):

```python
# website/features/rag_pipeline/orchestrator.py: answer
synth_budget_ms = budget_ms - (time.monotonic() - t0) * 1000
try:
    async with asyncio.timeout(synth_budget_ms / 1000):
        answer = await synthesize(...)
except asyncio.TimeoutError:
    answer = await synthesize_short_form(...)  # fallback to one-paragraph mode
```

Class-gated (e.g. STRONG/PRO multi-hop synth might legitimately want full 180s; LOOKUP/VAGUE caps at 30s).

### Risk of breaking other zettel types

- **MULTI_HOP synth** — hardest case. Cutting synth at 80% budget may produce a plausible-but-incomplete N-hop answer. Mitigation: synth-only abort (NOT retrieval), with fallback to "short-form" prompt.
- **THEMATIC** — same as MULTI_HOP.
- **LOOKUP / VAGUE** — short answers; abort rarely fires.

### Trade-off matrix

| Option | LOC | Risk | Iter |
|---|---|---|---|
| (a) `asyncio.wait_for` at every stage boundary | 60 | Supabase RPC partial-state, BGE thread leak | iter-11 |
| (b) `asyncio.timeout` at synthesis boundary only | 30 | partial-pool synth quality | iter-11 |
| (c) TaskGroup with structured cancellation | 80 | CPython issues #94398, #116720 | iter-12+ |
| (d) Wall-clock budget LOGGING only ★ | 15 | none | iter-10 |

**Recommended for iter-10:** (d). Logging only. Data-collection for iter-11 abort policy.

### Cost (iter-10 logging)

- 15 LOC.
- 0 production blast.
- 0 extra LLM calls.
- 1 unit test (budget exceedance triggers warning log).

### Falsifiable test

1. **iter-10:** synthetic slow-synth query (mock Gemini to sleep 25s); assert log contains `[budget] over_80pct`.
2. **iter-11 (when shipped):** synthetic slow-synth → fallback to short-form; assert response within budget.
3. **Replay iter-04..iter-09 KM fixture:** zero composite regression from logging-only change.

### Sources

- [Coroutines and tasks (Python 3 docs)](https://docs.python.org/3/library/asyncio-task.html) — `asyncio.TaskGroup`, `asyncio.timeout`, `CancelledError` semantics.
- [`asyncio.TaskGroup` may not cancel all tasks on failure (CPython #94398)](https://github.com/python/cpython/issues/94398) — late-created tasks not cancelled.
- [Nested TaskGroup can silently swallow cancellation (CPython #116720)](https://github.com/python/cpython/issues/116720) — nested swallow risk.
- [Asyncio Cancel All Tasks If One Task Fails (SuperFastPython)](https://superfastpython.com/asyncio-cancel-all-tasks-if-task-fails/) — practical patterns.
- [Cancellation in Concurrency (Bruce Eckel)](https://bruceeckel.substack.com/p/cancellation-in-concurrency) — semantic gotchas.
- iter-09 iter10_solutions_research.md Section 2 / Refactor C (original proposal).
- `website/features/rag_pipeline/orchestrator.py:91-240` (current orchestrator.answer; abort hook point).

---

## Cross-cutting integration: what ships together vs separately

**Iter-10 ship set (post user feedback):**

| Set | Items | Why ship together |
|---|---|---|
| Already-approved (per user) | Harness `t0` arithmetic fix, `_post_answer_side_effects` outside slot, q10 anchor-seed un-gate | obvious, foundational |
| New ✓ ship (this research) | Item 2 (q10 un-gate variant: drop re-gate + exclude THEMATIC); Item 5 (auto-title flash-lite) | both single-line, both validate already-approved fixes |
| New ⚠ ship-with-mitigation | Item 1 (q5 magnet — option e + b + c); Item 3 (chunk_count_quartile + matrix unit test); Item 4 (adaptive percentile rerank pre-filter, after scout) | each requires a regression-suite replay before merge |
| New ✗ defer to iter-11 | Item 6 (admission middleware); Item 7 (mid-flight abort) | structural risk; requires dedicated iter spec |

**Iter-10 phase ordering (recommended):**

1. **Phase 0:** scout (rrf distribution for Item 4, manual title smoke for Item 5).
2. **Phase 1:** harness `t0` fix (already-approved). Re-run to validate p_user metrics.
3. **Phase 2:** Items 2 + 5 (single-line drops). Re-run.
4. **Phase 3:** `_post_answer_side_effects` outside slot (already-approved).
5. **Phase 4:** Item 4 (adaptive percentile rerank gate). Re-run; require composite delta ≥ -1.
6. **Phase 5:** Items 1 + 3 (q5 magnet + zettel-type discriminators). Re-run; require q5 primary in expected set AND zero LOOKUP regressions.
7. **Phase 6:** final eval; require composite ≥ 80, gold@1 ≥ 0.78. (composite ≥ 85 may slip to iter-11 if Phase 5 tuning needs another pass.)

---

## Open questions for the user (recommended ASK before shipping)

1. **Item 1 (q5 magnet, option e):** is the score-rank-correlation demote acceptable as a NEW THEMATIC-class signal, or do you want a 90-second scout first to verify gh-zk-org-zk's actual rrf-rank in the iter-09 q5 retrieval pool? (I have only the deep-dive's claim that gh-zk-org-zk was "in pos 3" of 5 retrieved nodes; verifying the rrf percentile rank requires reading verification_results.json or a fresh eval log.)
2. **Item 4 (adaptive percentile rerank pre-filter):** ship after scout, or defer to iter-11? My recommendation is "ship after scout"; if you want to keep iter-10 to recall fixes only, defer.
3. **Item 5 (flash-lite auto-title):** quality-smoke-then-ship, or A/B with prod traffic for 3 days first? My recommendation is "smoke-then-ship"; the rollback path is 1 LOC.

---

## Notes for the executor

- All seven items honour the CLAUDE.md guarded knob list. None touches `GUNICORN_WORKERS`, `--preload`, `FP32_VERIFY_ENABLED`, `GUNICORN_TIMEOUT`, semaphore concurrency, SSE heartbeat, Caddy timeouts.
- The "magnet" definition broadening (Item 1) is the most contentious change; ship behind `RAG_THEMATIC_RANK_DEMOTE_ENABLED` env flag for safe rollback.
- Item 4 must dispatch the rrf-distribution scout BEFORE writing code. Hard-coded threshold without distribution data is exactly the "research-before-recommend" anti-pattern CLAUDE.md flags.
- Auto-title flash-lite pin (Item 5) is the cleanest single-line win — ship first to validate the iter-10 deploy pipeline.
