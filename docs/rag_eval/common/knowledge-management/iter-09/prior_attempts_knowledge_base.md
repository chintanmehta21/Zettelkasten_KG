# KM Kasten RAG Eval — Prior-Art Knowledge Base (iter-04 → iter-09)

> Compact reference of every change attempted, what shipped, what worked, what regressed, and what to never propose again. Built for iter-10 planning.

**Source files consulted:**
- `docs/rag_eval/common/knowledge-management/iter-{04..09}/{PLAN,RESEARCH,scores,verification_results,timing_report,README}.{md,json}`
- `git log --oneline --since=2026-04-25 -- website/features/rag_pipeline/ ops/scripts/score_rag_eval.py docs/rag_eval/`
- Cross-domain: youtube/urban-climate channels (only `urban-climate-resilience/iter-05/queries.json` exists; no shipped iters elsewhere).

---

## Section 1 — Iter-by-iter changelog

### iter-04 (KM) — composite n/a (pre-scorer) | gold@1 0.6429
- **Hypotheses tested:** burst-pressure 502 storm fix; retrieval quality lift; class-aware retry/refusal handling.
- **Changes shipped (commits):**
  - `8f4eada` feat: iter-04 retrieval quality + burst hardening (introduced `kasten_freq` anti-magnet penalty, `_MIN_TOTAL_HITS_FOR_PENALTY=50` floor)
  - `a28dc12` fix: iter-04 retry guards + thematic diversity floor
  - `1e51731` feat: class aware context floor + partial refusal prompt
  - `234abdf` fix: critic regex + class aware retry
  - `9904b49` perf: parallel metadata + transform reenable extractor
  - `17a549c` feat: RAGAS scoring + iter-aware eval harness (sidecar)
  - `f2c6d7f` feat: add PageIndex RAG eval
- **Outcome:** end_to_end_gold@1 = 0.6429; p95 latency 58s; **infra_failures=4** (burst-pressure phase still failing 0/1); 14 queries.
- **Why:** anti-magnet `kasten_freq` shipped but inert (floor=50 never reached on 7-zettel KM Kasten). RAGAS sidecar wired in this iter became the standard scorer downstream.

### iter-05 (KM) — composite **77.95** | gold@1 0.6429 | rerank **77.86** ← peak rerank
- **Hypotheses:** validate iter-04 retrieval quality; baseline composite scoring with new RAGAS-aware scorer.
- **Changes shipped:** purely measurement/ops — no major retrieval code change vs iter-04.
- **Outcome:** composite 77.95; chunking 31.94 (frozen); retrieval 97.70 (peak); rerank 77.86 (peak); synth 77.25; faithfulness 100; answer_relevancy 96.43. Burst: `{524: 11, 200: 1}` — **0× 503** (admission gate broken, all timeouts).
- **Why it worked:** healthy retrieval recall + content not yet over-fitted by later "fixes". `kasten_freq` still inert but didn't matter.
- **Why it regressed later:** the burst-mute (no 503) was already present here but masked because content scores were good.

### iter-06 (KM) — content-fixed-but-deferred | composite n/a | gold@1 **0.7857** ← peak gold@1
- **Hypotheses:** validate `RAG_QUEUE_MAX 8 → 3` admission lower; eval-log cleanup. Identical queries to iter-05.
- **Changes shipped:**
  - `RAG_QUEUE_MAX: 8 → 3` (`ops/docker-compose.{blue,green}.yml:15`)
  - Eval scoring log dedupe (`ops/scripts/score_rag_eval.py`)
  - `ee1fd32` test: add iter-06 eval scaffold
- **Outcome:** **gold@1=0.7857** (peak across all iters); p95 49.8s; infra_failures=0. Burst-pressure target STILL not met (no 503 with Retry-After).
- **Why:** unchanged content + lower per-worker queue prevented OOM cascades, but admission wire-mismatch (`_run_answer` not in `acquire_rerank_slot`) means `state.depth` never increments — the 503 path remains dead. Identified later in iter-09 RES-4.

### iter-07 (KM) — composite **62.88** | gold@1 0.4286 | rerank 62.48
- **Hypotheses:** patch q3/q5/q7/q10 content failures; thematic n=3→5 for q5 recall.
- **Changes shipped:**
  - `60cf902` feat: iter-07 RAG content fixes (q3, q5, q7, q10) — set THEMATIC `_multi_query` n=5; lowered `_DIVERSITY_FLOOR_SCORE_MIN`; raised anti-magnet floor; tightened critic semantic-coverage gate
- **Outcome:** **regression**: composite 77.95 → 62.88 (-15.07); gold@1 0.6429 → 0.4286 (-0.21); rerank 77.86 → 62.48 (-5.38); burst `{402: 12}` (Gemini quota exhaustion).
- **Why it regressed:** RES-3 proved n=5 added ZERO retrieval delta on q5 (identical retrieved_node_ids vs n=3) but burned Gemini quota → q13/q14 = HTTP 402. Iter-07 pulled multiple knobs simultaneously, masking which one(s) regressed.

### iter-08 (KM) — composite **63.53** | gold@1 **0.7143** | chunking **40.43** ← chunker unlock
- **Hypotheses:** revert n=5; unlock frozen chunking score; structurally attack magnet bias; cite hygiene; KG entity-anchor.
- **Changes shipped (in order):**
  - Phase 1: `1d631ae` revert thematic n 5→3
  - Phase 2.1-2.4: chunker score unlock — `c80ac8b` boundary regex relax, `d17d2b9` adaptive `target_tokens`, `95422d7` pass embeddings to coherence, `79669d0` snap chunks to sentence boundaries
  - Phase 3.1-3.3: magnet bundle — `9d20946` class-aware `_cap_per_node`, `052682f` THEMATIC xQuAD λ 0.7→0.5, `eeb36dc` text-only compare-intent regex
  - Phase 4: `0c8d60c` per-Kasten chunk-count store + `045056d` chunk-share normalization (`rrf_score *= 1/sqrt(chunk_count)`); `a7515b1` deprecate `kasten_freq`
  - Phase 5: `cd5df7d` cite-hygiene filter (dark canary, default OFF)
  - Phase 6: `1721696` KG entity-anchor resolver + `14f5480` KG entity-anchor boost (+0.05 × is_1hop_neighbour)
  - Phase 7.A-7.H scorer fixes: refusal regex, RAGAS retry, answer_relevancy aggregation, NDCG normaliser per-query achievable max, empty-list sentinel, NaN guard, dropped-qid surfacing, p50/p95 trimmed mean
  - `5f92cee` anchor boost runs after chunk share (g3 ordering fix)
  - `84771ad` TTL cache for chunk-share store (g4)
  - `f739ce3` kg_link.relation enum migration (Phase 8 schema groundwork)
- **Outcome:** composite +0.65 (63.53); chunking **+8.49** (40.43); gold@1 **+0.2857** (0.7143); **rerank -13.17** (49.31, REGRESSION); within_budget -0.07 (0.2143); burst `{524: 7, 502: 3, 200: 2}` — **502 rate 0.25** (new failure mode); RAGAS faithfulness 91.67 / answer_relevancy 90.83.
- **Why partial:** chunking unlock + gold@1 worked. Rerank regressed because uniform `1/sqrt(chunk_count)` damp slashed legitimately chunky LOOKUP gold (Walker, Steve Jobs zettels). 502 burst storm means Gunicorn workers OOMing — wired but un-bounded.

### iter-09 (KM) — composite **65.32** | gold@1 0.5714 | rerank 57.14 (partial recovery)
- **Hypotheses (per RES-1..7):** RES-1 `unsupported_with_gold_skip` LOOKUP gate; RES-2 class-gated chunk-share with ratio-to-median magnet detect; RES-3 DEFER post-rerank magnet penalty; RES-4 wrap `_run_answer` in `acquire_rerank_slot`; RES-5 SSE-aware `p_user_*_ms` harness; RES-6 narrow router rule-5 (18→25 words) + 3 new rules + LRU cache; RES-7 carry-forward (warm-up ping, log-pull, CHECK migration, Q10 anchor seed, q5 HOLD).
- **Changes shipped (in order):**
  - `ee31c85` ndcg dedupe reranked + clamp instead of assert (carryover safety)
  - `248d85f` anchor seed injection for q10
  - `97b05fc` router rule-5 narrow + new rules + LRU cache
  - `82f202d` `unsupported_with_gold_skip` retry gate
  - `7c5c482` class-gated chunk-share with magnet detection
  - `c246b39` docs: iter-09 queries from iter-08 + q5 holdnote
- **Outcome:** composite 63.53 → 65.32 (+1.79); chunking 40.43 (held); retrieval 76.90 → 97.08 (+20.18); rerank 49.31 → 57.14 (+7.83 recovery, still below iter-05's 77.86); synth 67.55 → 56.85 (**-10.7 regression**); RAGAS faithfulness 91.67 → 87.50 (-4.17); answer_relevancy 90.83 → 74.29 (-16.54). **Burst `{503: 6, 502: 3, 200: 3}` — 503 rate 0.50 (FIXED! ≥0.08 target met)**, 502 still 0.25.
- **Why partial:** admission wire fix (RES-4) WORKED — 503 came back. But synth/answer_relevancy regressed; q1 still 502 (warm-up not enough); q5 still 500 (HOLD); q7 magnet now `gh-zk-org-zk` (different magnet, same problem); within_budget collapsed 0.2143 → 0.0714. New verdict `unsupported_with_gold_skip` appears in distribution.

### Cross-domain
- **YouTube channel:** halt sentinel dropped (`91449a6`), no shipped iters. Cannot reuse.
- **Urban-climate-resilience:** only iter-05 queries.json scaffold, no shipped runs.

---

## Section 2 — Cons-NOT-to-take master list (every rejected approach across iter-04..09)

- [iter-08 RES-1] Direct `rerank_score < 0.5` cite filter — BGE int8 scores uncalibrated against fusion (cascade.py:737 multiplies raw rerank by 0.60); regresses multi-hop legit hops.
- [iter-08 RES-1] Per-class hardcoded cite minimums (LOOKUP=1, MULTI_HOP=2, THEMATIC=3) — `expected_minimum_citations` lives only in `queries.json` fixtures, baking them in production overfits the eval.
- [iter-08 RES-1] Atomic-claim parsing + re-cite — too invasive.
- [iter-08 RES-2] Lower `kasten_freq` floor 50→5 — band-aid; cold-start fragile, persistence-dependent, lagging indicator.
- [iter-08 RES-2] Pre-seed `kasten_freq` from kg_node telemetry — mixes user-engagement signal with retrieval-magnet signal.
- [iter-08 RES-2] Compute `kasten_freq` on-the-fly per-query — magnets are visible across queries, not within one (already MMR's job).
- [iter-08 RES-3] Scale thematic n with Kasten size — RES-3 verified more variants don't generate new node_ids if not in rerank pool.
- [iter-08 RES-3] Keep n=5 + add quota safeguard — pays recurring cost for feature that demonstrably does nothing on q5.
- [iter-08 RES-4 / B1] `1/sqrt(chunk_count)` damp on rrf_score uniformly — punishes legitimately rich content (nl-pragmatic-engineer-t at 10 chunks). Shipped uniformly anyway in iter-08 → caused rerank regression; iter-09 RES-2 then class-gated it.
- [iter-08 RES-4 / B2] Token-overlap floor for magnet detection — slugified titles + thematic tags overlap too often.
- [iter-08 RES-4] Edge-type weighted PageRank — only "shared-tag" edges exist; needs schema migration first.
- [iter-08 RES-4] Modify PageRank graph build directly — too invasive.
- [iter-08 RES-5] Default-to-0.5 RAGAS parse-fail — fabricates synthetic prior; hides bugs.
- [iter-08 RES-5] Move cite filter to `_finalize_answer` — forks streaming/non-streaming paths.
- [iter-08 RES-5] Reuse critic's `_find_bad_citations` regex — legacy `[id,id]` form.
- [iter-08 RES-6] RAGAS retry-only without `eval_failed` mark — still ends in 0.0 on retry-fail.
- [iter-08 RES-7] NDCG@1 normaliser — throws away ranking signal between positions 2-5; degenerates to `hit_at_k`.
- [iter-08 RES-7] Average Precision normaliser — double-counts the precision axis already in `0.3·P@3 + 0.2·(1-FP@3)`.
- [iter-08 ACT-1] Replace boundary regex with token-aware boundary detection — Chonkie semantic split is sufficient.
- [iter-08 ACT-1] Drop coherence weight to 0 — would lose only semantic signal in chunking.
- [iter-08 ACT-1] Add RAGAS `context_recall` to synthesis weight — overfitting risk without correlation check.
- [iter-08 ACT-5] Replace Chonkie wholesale — too invasive.
- [iter-08 ACT-5] Snap-to-sentence on short atomic-chunk sources (reddit/twitter/github) — already one chunk per zettel.
- [iter-09 RES-1] Broaden `unsupported_with_gold_skip` to MULTI_HOP/STEP_BACK — surfaces confidently-wrong synth when one hop missing; `_top_candidate_score` masks missing hops.
- [iter-09 RES-1] `top_score >= 0.5` for skip — too lenient for harsher `unsupported` verdict.
- [iter-09 RES-1] Reuse `_LOW_CONFIDENCE_DETAILS_TAG` — implies failure; semantically wrong for gold-retrieved.
- [iter-09 RES-1] Apply skip gate to refusal-regex path — already short-circuits.
- [iter-09 RES-2] Original brief's `1/√n → 1/n^0.6` exponent change (class-agnostic) — moves wrong direction for LOOKUP.
- [iter-09 RES-2] Adaptive exponent `1/n^f(class)` — adds another knob; harder to test.
- [iter-09 RES-2] Subtractive log damp `score -= α·log(n)` — additive composition mixes poorly with multiplicative rrf.
- [iter-09 RES-2] Softmax temperature on chunk-count — overkill for 7-zettel Kastens.
- [iter-09 RES-2] ColBERT MaxSim — requires late-interaction architecture, out of scope.
- [iter-09 RES-3] Flat `chunk_count >= 8` post-rerank magnet penalty — false-positives steve-jobs (13 chunks).
- [iter-09 RES-3] Hand-tuned per-Kasten penalty constants — non-generalizable.
- [iter-09 RES-4] Refactor admission to single ASGI middleware NOW — iter-10+ scope; iter-09 fix is minimal symmetry restoration only.
- [iter-09 RES-5] Subtract `latency_ms_server` from `elapsed_ms` to approximate `p_user` — gap is post-answer side-effects time, not user-perceived metric.
- [iter-09 RES-5] Switch entire harness to `stream:true` without keeping `stream:false` opt-in — breaks back-compat for one-shot regression checks.
- [iter-09 RES-5] Move `_post_answer_side_effects` to background task in iter-09 — production touch outside scope; deferred.
- [iter-09 RES-6] Router rule-5 option (a) require explicit decomposition wording — picked (b) lift threshold instead.
- [iter-09 RES-6] Router rule-5 option (c) tag-based author detection — most invasive; deferred to iter-10.
- [iter-09 RES-7] Q10 anchor seed: prepend anchors into `p_effective_nodes` — scope whitelist filter, would leak cross-tenant.
- [iter-09 RES-7] Q10 anchor seed at score>0.5 — bypasses rerank.
- [iter-09 (Critical Infra)] Reduce `GUNICORN_WORKERS` below 2; disable `--preload`; lower `GUNICORN_TIMEOUT` below 180s; disable rerank semaphore; remove SSE heartbeat; revert Caddy 240s read_timeout — guarded knobs from iter-03/04.

---

## Section 3 — Pain-point matrix

| Pain point | iter-04 | iter-05 | iter-06 | iter-07 | iter-08 | iter-09 | Still open |
|---|---|---|---|---|---|---|---|
| q1 cold-start 502 | n/a | n/a | n/a | n/a | first noted (502 in burst) | warm-up ping shipped (RES-7 Task 5) | q1 still 502 in iter-09 — warm-up insufficient |
| q5 RPC 500 | not present | not present | not present | not present | (HTTP 500 first appeared) | bug introduced via new RPCs (`rag_resolve_entity_anchors`, `rag_one_hop_neighbours`, `rag_kasten_chunk_counts`); HOLD; logs pulled to `q5_500_traceback.txt` | root cause confirmed via logs — fix not yet shipped |
| q7 magnet (effective-public-speakin) | yes | yes (web-transformative-tools) | n/a content unchanged | yes (web-transformative-tools magnet) | yes — `web-transformative-tools-for` 3/14 top-1 | now `gh-zk-org-zk` 3/14 top-1 (different magnet emerged) | still magnet-dominated — class-gated chunk-share didn't fully solve; deferred post-rerank penalty (RES-3) for iter-10 |
| Auto-title side-effect blocking JSON return | n/a | n/a | n/a | n/a | discovered cause of 20-48s harness gap | RES-5 documented; SSE harness flips `stream:true`; production move-to-background DEFERRED | needs unblock in iter-10 (`_post_answer_side_effects` should be background task) |
| within_budget rate | n/a | 0.1429 | n/a | 0.2857 | 0.2143 | **0.0714** ← regression | regression |
| burst 502/503 ratio | 4 infra failures | 0% 503 / 11×524 / 1×200 | 0% 503 / target failed | 0/0 (all 12 = 402 quota) | 0% 503 / 25% 502 / 7×524 / 2×200 | **50% 503** (FIXED via RES-4 admission wire) / 25% 502 / 3×200 | 502 still present — likely separate OOM during 503 burst |
| answer_relevancy | n/a | 96.43 | n/a | 82.14 | 90.83 | **74.29** ← regression | regression — likely caused by `unsupported_with_gold_skip` paraphrased-tag answers |
| Reranking score (peak 77.86) | n/a | **77.86** | n/a | 62.48 | **49.31** ← collapse | 57.14 (partial recovery) | still -20 below iter-05 peak — class-gated chunk-share helped but didn't restore |
| Synthesis score | n/a | 77.25 | n/a | 61.26 | 67.55 | **56.85** ← regression | regression — needs investigation; possibly tied to over-firing skip gate |
| Router miscall (q13/q14 LOOKUP→MULTI_HOP) | n/a | n/a | n/a | n/a | first observed | RES-6 narrowed rule-5 (18→25 words); 3 new rules + LRU cache + ROUTER_VERSION=v3 | verify q13/q14 stayed LOOKUP (per scores.md, q13 lookup-distribution count is unchanged: 6 in iter-09 vs 5 in iter-08; needs per-query check) |
| Q10 anchor seed (Steve Jobs zettel) | missed (q10) | missed | missed | missed | spec'd RPC | RPC + injection shipped (RES-7 Task 8, INNER JOIN sandbox_members; floor 0.30) | q10 still gold@1 = F per iter-09 scores; partial verdict — anchor seed ran but cross-encoder still didn't pick gold |
| Frozen chunking 31.94 | 31.94 | 31.94 | 31.94 | 31.94 | **40.43** ← unlocked | 40.43 (held) | held; further +5 possible via real coherence embeddings |
| Burst-pressure 524s (worker timeout) | yes | 11×524 | n/a | 0 (quota burned first) | 7×524 | 0×524 (replaced by 503/502) | resolved via admission wire fix |
| `kasten_freq` dead prior | shipped (floor=50) | inert | inert | inert | DEPRECATED, replaced by chunk-share | n/a | resolved |
| HTTP 402 quota burn | n/a | n/a | n/a | 12/12 burst all 402 | resolved (n=5 reverted) | n/a | resolved by RES-3 |
| Postgres CHECK constraint silently rejecting new verdicts | n/a | n/a | n/a | n/a | (suspected; verdict dataset contamination) | migration v2 (`2026-05-04_chat_messages_verdict_constraint_v2.sql`) shipped allowing all new verdict strings | needs application + recheck of `kasten_freq` historical record_hit data |

---

## Section 4 — Architectural decisions baked in (NEVER revert without explicit chat approval)

Pulled from CLAUDE.md "Critical Infra Decision Guardrails" plus iter-N decision points:

| Decision | Set in | Rationale |
|---|---|---|
| BGE int8 cascade with `--preload` | iter-03 Phase 1A (~110 MB COW saving) | keeps 2 workers viable on 2 GB droplet |
| `GUNICORN_WORKERS=2` | iter-03 | concurrency at scale; pairing with `--preload` |
| `RAG_QUEUE_MAX=8` per worker (later 3 in iter-06) | iter-04 / iter-06 admission gate | cluster cap = workers × max; iter-06 dropped to 3 to prevent OOM |
| Rerank semaphore + bounded queue (`acquire_rerank_slot`) | iter-03 Phase 1B.2 | burst-correctness mechanism; the 503 backpressure path |
| SSE heartbeat wrapper | iter-03 Phase 1B.4 | prevents Cloudflare 502 on idle non-streaming responses |
| Caddy `transport http { read_timeout 240s }` | iter-03 Phase 1B | upstream-timeout fix for slow synth |
| `GUNICORN_TIMEOUT >= 180s` | iter-03 Phase 1B | minimum for Strong/Pro multi-hop synth |
| Schema-drift gate | iter-03 Phase 1C.5 | guards prod schema deploys |
| `kg_users` allowlist gate | iter-03 Phase 2D.2 | guards user-tenant safety |
| FP32_VERIFY top-3-only (not all) | iter-03 Phase 1A.5 | int8 cascade memory budget |
| Teal accents site-wide; amber/gold ONLY on `/knowledge-graph`; never purple | UI guardrail | brand consistency |
| `kasten_freq` deprecation (replaced by chunk-share) | iter-08 Phase 4 RES-2 | floor=50 was empirically dead; do NOT revive |
| Chunk-share normalization is **class-gated** (THEMATIC + MULTI_HOP only) with **ratio-to-median ≥ 2.0** magnet gate | iter-09 RES-2 | LOOKUP must NOT be damped; cold-start guard `len(chunk_counts) < 5` |
| Cite-hygiene filter is **dark by default** (`RAG_CITE_HYGIENE_ENABLED=false`) | iter-08 Phase 5 RES-5 | only flip on after canary regression check |
| RAGAS parse-fail → 1 retry then `eval_failed=True` (NOT default-0.5) | iter-08 Phase 7.B RES-6 | mirrors RAGAS upstream NaN exclusion |
| NDCG normaliser = `dcg(gold_ranking[:min(k_ndcg, len(gold_ranking))])` | iter-08 Phase 7.D RES-7 | Järvelin & Kekäläinen 2002 standard fix |
| Q10 anchor-seed RPC must `INNER JOIN rag_sandbox_members` and use floor RRF=0.30 (not >0.5) | iter-09 RES-7 Task 8 | cross-tenant safety + cross-encoder stays decisive |
| `_run_answer` MUST be wrapped in `acquire_rerank_slot()` on BOTH stream and non-stream paths | iter-09 RES-4 (corrected the iter-04 wire-mismatch bug) | restores 503 backpressure |
| Router `ROUTER_VERSION` constant bumps on ANY rule change to invalidate LRU cache | iter-09 RES-6 | cache key sha256 includes version |
| Verdict allowlist must include all new strings (CHECK migration v2) | iter-09 RES-7 Task 7 | silent INSERT-fail contaminates `record_hit` data |
| Magnet-rerank-penalty post-rerank is DEFERRED to iter-10 | iter-09 RES-3 | avoids double-discount with class-gated chunk-share |
| Auto-title side-effect refactor (background task) DEFERRED to iter-10 | iter-09 RES-5 | production touch outside iter-09 scope |

---

## Section 5 — What genuinely WORKED across iters

- **iter-08 chunk-share normalization** (later class-gated in iter-09): chunking 31.94 → 40.43 (+8.49 sustained through iter-09). Confirmed value.
- **iter-08 Phase 2 chunker unlock** (boundary regex relax + adaptive `target_tokens` + sentence-snap): unlocked the 6-iter-frozen 31.94 ceiling. Highest-confidence WIN.
- **iter-09 RES-4 admission wire fix** (`_run_answer` wrapped in `acquire_rerank_slot`): burst-pressure 503 rate 0% → 50% (target ≥0.08 met first time across all iters). Cleanest WIN.
- **iter-08 revert thematic n=5→3** (RES-3): eliminated HTTP 402 quota burn that took out q13/q14 in iter-07. Pure cleanup.
- **iter-08 Phase 3 magnet bundle** (B3 class-aware `_cap_per_node` + B5 xQuAD λ 0.7→0.5 + B4 compare-intent regex): contributed to gold@1 0.4286 → 0.7143 (+0.2857). Strong WIN even though one magnet later re-emerged in iter-09.
- **iter-08 Phase 7.D NDCG asymmetry fix** (`min(k_ndcg, len(gold))`): textbook fix; eliminates artifact where multi-source queries got penalized vs single-source.
- **iter-08 per-query RAGAS** (`adeafe9`, ACT-2): empty answers no longer dilute cohort mean.
- **iter-09 RES-1 `unsupported_with_gold_skip` LOOKUP-only gate**: appeared in verdict distribution; saved retry budget. Quality cost (answer_relevancy regression) needs review.
- **iter-09 RES-6 router rule-5 narrowing** (18→25 words) + LRU cache: cleaner routing, cheaper repeat queries.
- **iter-06 `RAG_QUEUE_MAX 8 → 3`**: prevented the OOM cascade that produced 11×524 in iter-05 burst.

---

## Notable state at end of iter-09

**Composite trajectory:** iter-05 77.95 → iter-07 62.88 → iter-08 63.53 → iter-09 65.32. **Still -12.6 below iter-05 peak.**

**Lever inventory left for iter-10:**
- post-rerank magnet penalty (RES-3 deferred) — iter-09 q7 still magnet-failing on `gh-zk-org-zk`.
- `_post_answer_side_effects` to background task — within_budget regression (0.0714) is largely measurement: harness now uses SSE but the metric still includes server-side blocking auto-title.
- q5 fix (HOLD) — traceback file `iter-09/q5_500_traceback.txt` exists; deterministic fix not yet shipped.
- synthesis 67.55 → 56.85 regression root cause (likely `unsupported_with_gold_skip` over-firing or paraphrase-tag bleed into answer_relevancy judge).
- q1 502 cold-start (warm-up ping was insufficient — investigate first-request BGE int8 ONNX-load timing).
- ASGI middleware refactor for admission (RES-4 deferred from iter-09) — current per-route guard pattern will drift.
- Edge-type weighted PageRank (Phase 8 schema groundwork shipped via `f739ce3 kg_link.relation enum`); consumer code deferred.
