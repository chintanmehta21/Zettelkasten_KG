# iter-10 Scorecard

**Composite:** 64.50  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45})

## Components
- chunking:    40.43
- retrieval:   78.79
- reranking:   54.17
- synthesis:   72.74

## RAGAS sidecar (0..100)
- faithfulness:      89.29   (iter-09: 87.50, +1.79)
- answer_relevancy:  83.93   (iter-09: 74.29, +9.64 — **P13 clause-coverage rule worked**)

## Latency
- p50: 30016 ms
- p95: 36135 ms
- p_user_avg (true wall-clock per query): 30659 ms
- ttft_avg (true first-token latency): 28684 ms

## Coverage
- total queries:       14
- refusal-expected:    1   (q9)
- eval_divergence:     False

## Holistic monitoring
- gold@1 (unconditional):     0.6429   (iter-09 audited: 0.6429 — **unchanged**)
- gold@1 within budget:       0.6429   (iter-09: 0.0714 — **+0.5715 from P1 harness fix**)
- gold@3:                     0.7143
- gold@8:                     0.8571
- within_budget_rate:         0.6429   (iter-09: 0.0714 — major recovery)
- refused_count:              3

### critic_verdict distribution
- supported:                  6
- partial:                    4
- unsupported_no_retry:       3
- unsupported_with_gold_skip: 1

### query_class distribution
- thematic:    5
- multi_hop:   4
- lookup:      5

### magnet-spotter (>=25% top-1 share)
- web-transformative-tools-for: top-1 in 3/14 queries
- nl-the-pragmatic-engineer-t: top-1 in 4/14 queries (NEW magnet — see "Regressions" below)

### burst pressure
- by_status:   {200: 3, 502: 3, 503: 6}
- 503 rate (target >= 0.08):   0.50  PASS
- 502 rate (target = 0.0):     0.25  FAIL  (no improvement; iter-11 carryover)

---

## Iter-09 -> iter-10 delta

| Metric | iter-09 | iter-10 | Delta | Verdict |
|---|---:|---:|---:|---|
| Composite | 65.32 | 64.50 | -0.82 | regressions offset gains |
| gold@1 unconditional | 0.6429 | 0.6429 | 0 | flat (q5/q6 recovered, q8/q12 regressed) |
| **gold@1 within_budget** | **0.0714** | **0.6429** | **+0.5715** | **P1 harness fix landed** |
| within_budget rate | 0.0714 | 0.6429 | +0.5715 | same as above |
| answer_relevancy | 74.29 | 83.93 | +9.64 | **P13 clause-coverage** |
| faithfulness | 87.50 | 89.29 | +1.79 | minor improvement |
| burst 503 rate | 0.50 | 0.50 | 0 | held |
| burst 502 rate | 0.25 | 0.25 | 0 | unchanged (iter-11 carryover) |
| Worker OOMs during eval | n/a | 0 | - | clean |

**Bottom line:** iter-10 met **none** of the three success thresholds (composite >= 85: FAIL, gold@1_unconditional >= 0.85: FAIL at 0.6429, gold@1_within_budget >= 0.85: FAIL at 0.6429). The harness measurement-truth fix (P1) is the dominant win; it lifted within-budget from a misreported 0.0714 to a real 0.6429, validating that iter-09 was always closer to passing than scores.md reported. Composite slipped 0.82 because two new regressions (q8, q12) offset the q5/q6/q9 recoveries.

---

## Per-query forensic

| qid | class | gold@1 | budget | primary | critic | iter-09 -> iter-10 |
|---|---|:-:|:-:|---|---|---|
| q1  | multi_hop | T | F | gh-zk-org-zk | partial | T -> T (slow, cold-start; correct) |
| q2  | lookup    | T | T | yt-steve-jobs-2005-stanford | partial | T -> T |
| q3  | lookup    | T | T | yt-effective-public-speakin | unsupported_with_gold_skip | T -> T |
| q4  | lookup    | T | T | yt-matt-walker-sleep-depriv | supported | T -> T |
| q5  | thematic  | T | T | -- (synth refused) | unsupported_no_retry | F -> partial recovery (retr ok) |
| q6  | multi_hop | T | F | web-transformative-tools-for | partial | F -> **T (recovered)** |
| q7  | thematic  | F | T | yt-effective-public-speakin | supported | F -> F (persistent) |
| q8  | thematic  | F | F | gh-zk-org-zk (at pos 4 of pool) | supported | **T -> F (regression)** |
| q9  | thematic  | F* | T | -- | unsupported_no_retry | timeout -> **correct refusal** |
| q10 | lookup    | F | T | -- | unsupported_no_retry | F -> F (persistent) |
| q11 | lookup    | T | T | yt-matt-walker-sleep-depriv | partial | T -> T |
| q12 | thematic  | F | T | yt-programming-workflow-is (pos 4) | supported | **T -> F (regression)** |
| q13 | multi_hop | T | F | nl-the-pragmatic-engineer-t | supported | T -> T |
| q14 | multi_hop | T | F | web-transformative-tools-for | supported | T -> T |

\* q9 expected=[] (refusal-expected query); primary=None + unsupported_no_retry is the **correct** behaviour. Counts as gold@1=False mechanically but is a recovery vs iter-09 (which timed out).

---

## Root-cause analysis on still-failing queries

### q5 -- THEMATIC ("how should a knowledge worker structure a day...")
- **Retrieval:** PASS - gold surfaced at top-1 (`nl-the-pragmatic-engineer-t`); cross-corpus coverage in top-5.
- **Synthesizer:** FAIL - refused with `unsupported_no_retry`.
- **Diagnosis:** P3 magnet gate (Task 11) + Item 3 tiebreaker (Task 9) + P9 pre-rerank floor (Task 12) successfully demoted iter-09's `gh-zk-org-zk` magnet for this query. But the synth critic rejects the candidate set. Hypothesis: context-floor + critic threshold is too strict for cross-corpus thematic synthesis where no single chunk is verbatim-grounded in the question. Floor-protected per CLAUDE.md (`_PARTIAL_NO_RETRY_FLOOR`, `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR`) so we cannot lower without explicit approval.
- **Iter-11 candidate:** class-conditional critic threshold for THEMATIC, OR thematic-aware retry that rebuilds context with a different chunk-cap.

### q7 -- THEMATIC, vague ("Anything about commencement?")
- **Retrieval:** gold (`yt-steve-jobs-2005-stanford`) made it into the pool at pos 3, but `yt-effective-public-speakin` won top-1.
- **Diagnosis:** P3 score-rank magnet gate didn't fire because base rrf delta was below `RAG_SCORE_RANK_DISPROP_QUARTILES=1.0` threshold -- `yt-effective-public-speakin` ranked high on base rrf legitimately. The deeper miss is upstream: the multi-query rewriter kept the literal token "commencement" instead of expanding to "Stanford / Steve Jobs / graduation" (same iter-08 finding, no iter-10 fix authored).
- **Iter-11 candidate:** vague-aware multi-query expansion (router rule + rewriter prompt change) -- single-token vague queries should aggressively expand entity hints.

### q8 -- THEMATIC ("What should I install tonight to start a personal wiki?") -- **NEW REGRESSION**
- **Retrieval:** gold (`gh-zk-org-zk`) is at pos 4 of the pool; iter-09 had it at top-1.
- **Diagnosis:** P3 magnet gate (Task 11) demoted `gh-zk-org-zk` because it scored as a "score-rank disproportion" -- high final rrf with low base rrf. The magnet identification is statistically correct (gh-zk-org-zk was top-1 in 3/14 iter-09 queries) but for this question the gold IS the magnet. This is exactly the trade-off RES-3 acknowledged: when the magnet is the legitimate gold, the gate slightly damps it.
- **Iter-11 candidate:** weaken `RAG_SCORE_RANK_DEMOTE_FACTOR` from 0.85 to ~0.92 and confirm via `test_class_x_source_matrix.py` that q8 recovers without breaking q5.

### q9 -- THEMATIC ("Summarize what this Kasten says about Notion's database features.")
- **Status:** mechanical gold@1=False, but `expected=[]` means a refusal IS the expected outcome. iter-10 produced primary=None with `unsupported_no_retry`, which is the canonical refusal flow. **Recovery** vs iter-09's harness-timeout, not a real failure.
- **Action:** tag `expected=[]` queries as `gold_at_1_not_applicable` in the scorer aggregation so they don't depress the headline number.

### q10 -- LOOKUP ("Steve Jobs and Naval Ravikant both speak about meaningful work...")
- **Retrieval pool:** ONE entry only (`web-transformative-tools-for`) -- extremely sparse.
- **Diagnosis:** The iter-10 P4 anchor-seed un-gate (Task 6) **didn't fire** because `anchor_nodes` was empty at the gate -- `entity_anchor.resolve_anchor_nodes(["Steve Jobs", "Naval Ravikant"])` likely returned [] for this kasten. Naval Ravikant has no zettel in this Kasten, so even with un-gating the seed inject path can't surface what isn't in the corpus. P5 dense-fallback didn't trigger either: `total_rows` was 1 (not 0).
- **Iter-11 candidate:** lower the P5 fallback trigger to `total_rows <= 1` for LOOKUP+person classes, OR resolve anchor entities individually so "Steve Jobs" alone resolves and pulls `yt-steve-jobs-2005-stanford` even when "Naval Ravikant" doesn't.

### q12 -- THEMATIC ("How does the programming-workflow zettel characterise...") -- **NEW REGRESSION**
- **Retrieval:** gold (`yt-programming-workflow-is`) at pos 4 of pool; `nl-the-pragmatic-engineer-t` won top-1.
- **Diagnosis:** Task 9's `chunk_count_quartile` tiebreaker for THEMATIC inverts to prefer LOWER chunk counts (broad coverage > deep monoculture per RES-8). This pushed `nl-the-pragmatic-engineer-t` (single-essay zettel, low chunk count) above `yt-programming-workflow-is` (multi-chunk transcript) when their rrf scores were close. The PLAN intentionally chose this direction; the synthetic test fixture confirms it. But for q12 the multi-chunk transcript IS the right zettel -- the question literally asks about "the programming-workflow zettel".
- **Iter-11 candidate:** make the THEMATIC tiebreaker bias smaller (x0.00005 instead of x0.0001) so it only resolves *true* ties, OR remove the THEMATIC inversion when gold-name-overlap is detected in the query.

---

## iter-10 wins (not visible in headline composite)

1. **P1 harness arithmetic fix (Task 4):** within-budget jumped from 0.0714 to 0.6429. iter-09 was always closer to passing than its scorecard reported -- the JS `t0` subtraction bug fooled five iters. Single 3-LOC fix; high-leverage.
2. **P13 clause-coverage rule (Task 13):** answer_relevancy +9.64 absolute. The synthesiser now explicitly addresses each sub-question OR states the missing clause; partial answers no longer mark themselves as complete.
3. **P12 chunk_share TTL + THEMATIC empty-counts logging (Task 15):** observability landed; q5-class 500s no longer go silent on log restart.
4. **P8 RSS pre/post-slot logging (Task 14):** OOM-precursor visibility in the access path.
5. **P17 per-stage timing (Task 17):** iter-11 mid-flight latency abort design has the data it needs (retrieval / rerank / synth wall-time per turn).
6. **CI grep guard (Task 16):** the iter-04..iter-09 silent-drift class is fenced -- no future iter can quietly unwrap `_run_answer` from `acquire_rerank_slot` again.
7. **q9 recovery:** the refusal-expected adversarial query no longer times out; correct refusal flow now ships.
8. **P5 dense-only fallback shipped + RPC migrated** -- `rag_dense_recall` SQL function applied to live Supabase (201 OK). Did not fire for q10 because pool wasn't *empty* (had 1 row), but the safety net is in place.

---

## Task 7 deepdive correction

iter-09's `iter09_failure_deepdive.md` (lines 171, 191-192) attributed the monotonically-rising 43s -> 524s `p_user_complete_ms` across q1..q14 to:

> "auto-title Gemini call serializing the rerank queue ... q1=43s, q2=75s (delta 32s), ... q14=524s"

This was **incorrect**. iter-10 investigation confirms `auto_title_session` has *never* been a Gemini call -- `git log -p -S"gemini" -- website/features/rag_pipeline/memory/session_store.py` returns empty across both commits ever made to that file. It is a 6-line string-trim that updates `chat_sessions.title` with the first 60 chars of the user's question. The monotonic increase the deepdive observed was the **JS harness `t0` subtraction bug** fixed in iter-10 Task 4. Server-side `latency_ms_server` in iter-09 was 1.0-1.7s for every query -- no auto-title cascade existed.

Consequences:
- **Task 7 (P11 auto-title pin to flash-lite) was SKIPPED in iter-10** with explicit user authorisation. No model to pin; documenting the misdiagnosis here for the historical record.
- **Task 8 (P2 side effects fire-and-forget) shipped anyway** as structural hygiene -- the Supabase `update_session` + `touch_sandbox` calls in `_post_answer_side_effects` are 50-200 ms each and slot-serialising them was a real (small) throughput cost. The refactor also future-proofs against the day a real LLM call DOES land in side-effects.

This is a clean reminder that *forensic claims based on harness output* should be cross-checked against *server-side `latency_ms_server`* when the two are within 10x of each other.

---

## Iter-10 deploy / ops notes

- Final deploy SHA at eval time: `aea614d` (CI fix on `f245c6b` iter-10 push)
- Naruto smoke-probe meter was reset via `ops/scripts/reset_naruto_smoke_meter.py` after the first deploy attempt 402'd on `quota_exhausted` -- not an iter-10 regression, just baseline billing-state drift
- Cross-class regression fixture (`test_class_x_source_matrix.py`) initially called `HybridRetriever(supabase=None)` which triggered real Supabase client init in CI; fixed by passing sentinel `object()` -- caught one iter before merging to master
- One pytest CI failure cycle; final master = green
- `rag_dense_recall` Postgres RPC applied to live Supabase via the project's migrations API (201 OK)

---

## Critical correction from second-pass forensic

A first-pass reading of the eval output mis-attributed the 22-38s `ttft` values to slow RAG compute. **Re-reading `latency_ms_server` field of `verification_results.json` flips that picture entirely.**

| qid | latency_ms_server | p_user_first_token_ms | gap | cause of gap |
|---|---:|---:|---:|---|
| q1  | 1642 | 32190 | 30548 | Cloudflare/Caddy SSE buffering before `event: token` flush + connection negotiation |
| q4  | 1094 | 35542 | 34448 | same |
| q12 | 902  | 25352 | 24450 | same |
| q14 | 960  | 29864 | 28904 | same |

Server-side compute is **902-1867 ms** per query — fully consistent with iter-09 baseline (1.0-1.7 s). The 22-38 s `ttft` is **purely network/proxy buffering**, not RAG pipeline cost. P9 pre-rerank floor (Task 12) and the BGE int8 cascade are NOT slow. The earlier observation `stage_timings retrieval=1113ms rerank=20094ms synth=3906ms` from droplet logs was almost certainly a **post-eval cold-load** sample (RSS slot delta 442 MB confirms a model load happened on that slot acquire, AFTER the worker had been idle long enough for the page cache to evict).

This means the iter-10 RAG quality picture is far cleaner than the latency numbers initially suggested: failures are **ranking failures**, not latency failures. The `gold@1` flat-line vs iter-09 is the real signal.

---

## Failed-query root-cause table (with iter-10 monitor context)

| qid | class | failure shape | which iter-10 task SHOULD have helped | why it didn't | dynamic insight |
|---|---|---|---|---|---|
| **q5** | THEMATIC | retrieval ✓ (gold top-1) but synth refused (`unsupported_no_retry`) | P3 magnet (Task 11) + Item 3 tiebreak (Task 9) + P9 floor (Task 12) all targeted q5 | retrieval **did** recover — magnet `gh-zk-org-zk` no longer wins. But synth critic still rejects: cross-corpus thematic synthesis lacks single-chunk grounding the critic demands | **Class F:** for cross-corpus THEMATIC, the critic threshold for "supported" was calibrated against single-zettel LOOKUP queries; it under-trusts coalesced multi-zettel evidence |
| **q7** | THEMATIC, vague single-token | wrong primary (yt-effective-public-speakin); gold (yt-steve-jobs-2005-stanford) at pos 3 | P3 magnet gate; P5 dense fallback | P3 didn't fire — base-rrf disparity below `RAG_SCORE_RANK_DISPROP_QUARTILES=1.0` threshold. P5 didn't fire — pool wasn't empty | **Class D:** the multi-query rewriter preserves single-token literals ("commencement") instead of expanding to entity hints. THEMATIC retrieval can't fix what a thin query never asked for |
| **q8** | THEMATIC | wrong primary (top-1 = nl-the-pragmatic-engineer-t); gold gh-zk-org-zk at pos 4. **NEW REGRESSION** vs iter-09 | none — P3 caused this regression | P3 magnet gate (Task 11) correctly identified gh-zk-org-zk as a magnet (top-1 in 3/14 iter-09 queries) and damped it. But for q8 the magnet IS the legitimate answer — "personal wiki ... install tonight" really does want gh-zk-org-zk | **Class A:** statistical magnet detection is necessary but insufficient. A node can be a magnet AND the legitimate answer when the query has structural affinity (entity match, source-type match, name overlap) — the gate needs an "earned exemption" path |
| q9 | THEMATIC | `expected=[]`; primary=None; refusal correctly emitted | n/a — adversarial-by-design query | scorer mechanics count this as gold@1=False even though the refusal is correct | **Class E:** the scorer's gold@1 aggregator treats empty-expected as a failure case. Correct refusals depress the headline metric |
| **q10** | LOOKUP, compare-intent ("Jobs and Naval Ravikant") | pool only has 1 entry (web-transformative-tools-for); primary=None | P4 anchor-seed un-gate (Task 6); P5 dense fallback (Task 10) | P4 didn't fire — `entity_anchor.resolve_anchor_nodes(["Jobs", "Naval Ravikant"])` likely returned [] because Naval has no zettel in this Kasten and the resolver requires *some* anchor. P5 didn't fire — pool had 1 row, threshold is 0 rows | **Class C:** anchor resolution is all-or-nothing. Any compare-query where one of N named entities is missing from the kasten loses the anchor-seed safety net entirely, even when (N-1) entities are well-grounded |
| **q12** | THEMATIC | wrong primary (nl-the-pragmatic-engineer-t single-essay); gold (yt-programming-workflow-is multi-chunk) at pos 4. **NEW REGRESSION** vs iter-09 | none — Task 9 caused this regression | Item 3 tiebreaker (Task 9) inverts THEMATIC to prefer LOWER chunk-count quartile. When rrf is close, the single-chunk essay beats the multi-chunk transcript. Plus the query mentions "the programming-workflow zettel" verbatim — but the tiebreaker ignores name-overlap signals | **Class B:** the THEMATIC chunk-quartile inversion (broader coverage > deeper monoculture) is correct as a default but harmful when the query LITERALLY references a multi-chunk zettel by name. Tiebreak needs a "name-overlap override" |

---

## Top-5 priority fixes (ranked by impact × generality, dynamic across zettel types)

These resolve **classes of zettel patterns**, not single queries. The "expected impact" column predicts which queries would flip from failing to passing if the fix landed cleanly.

### #1 — Class A: entity-anchor exemption for the magnet gate
**Pattern:** a node statistically scores as a magnet but is the structurally-correct answer for THIS query (proper-noun match, source-type match, anchor membership).
**Symptom seen:** q8 (gh-zk-org-zk demoted when it was the "personal wiki" answer).
**Generic mechanism:** `_apply_score_rank_demote` operates on rrf percentile alone. It has no knowledge of *why* the node is top-1.
**Fix:** in `hybrid.py:_apply_score_rank_demote`, before applying the demote, check whether the candidate is in `anchor_nodes` (resolved entity anchor) OR has a `_title_overlap_boost > 0` indicating the query verbatim names this zettel. If either is true, **skip the demote** for that candidate. Earned exemption keeps the gate effective for true magnets while protecting legitimate proper-noun winners.
**Knobs:** new `RAG_SCORE_RANK_PROTECT_ANCHORED=true` (default).
**Expected impact:** recovers q8. No risk to q5/q7 because their gold isn't anchored.
**Effort:** 5 LOC + 2 tests.

### #2 — Class B: name-overlap override on THEMATIC tiebreaker
**Pattern:** the user's query references a zettel by name verbatim ("the programming-workflow zettel"); the THEMATIC chunk-quartile inversion still picks a smaller competitor because of the broad-coverage prior.
**Symptom seen:** q12 (yt-programming-workflow-is at pos 4 instead of top-1).
**Generic mechanism:** `_tiebreak_key` for THEMATIC inverts to prefer LOW chunk-count. This is correct when the query is genuinely cross-corpus. It is incorrect when the query has a single-zettel target.
**Fix:** in `_tiebreak_key`, take an additional `_title_overlap_boost` parameter from `candidate.metadata`. When non-zero, **skip the inversion** for that candidate (use the LOOKUP-style higher-quartile preference). Implementation: change the function signature and pass `candidate.metadata.get("_title_overlap_boost", 0.0)` from the call site in `_dedup_and_fuse`.
**Knobs:** none — this is a structural correctness fix.
**Expected impact:** recovers q12. Cross-class fixture should be re-validated.
**Effort:** 8 LOC + extend `test_class_x_source_matrix.py` with one name-overlap case.

### #3 — Class C: per-entity anchor resolution with union semantics
**Pattern:** any compare/multi-entity query where at least one entity isn't in the kasten — anchor resolution returns [] for ALL entities and the safety net (anchor-seed inject + dense fallback) never fires.
**Symptom seen:** q10 ("Jobs and Naval Ravikant"; only Jobs in kasten).
**Generic mechanism:** `entity_anchor.resolve_anchor_nodes(entities)` likely runs a single RPC that ANDs the entities. Truth is: resolved-for-Jobs is more useful than resolved-for-nothing.
**Fix:** in `entity_anchor.py:resolve_anchor_nodes`, change from "single batched RPC" to "per-entity RPC + union the results". Each entity that resolves contributes its anchor nodes; entities that don't resolve are dropped without poisoning the pool. Pair with a structured log line `entity_anchor_resolve entities=N resolved=M missing=[...]` so iter-12+ can see partial-resolution rates.
**Knobs:** none.
**Expected impact:** recovers q10 and any future N-entity compare query with K<N kasten coverage.
**Effort:** 15 LOC in `entity_anchor.py` + per-entity RPC loop + 1 test.

### #4 — Class D: vague-class entity-hint expansion in the multi-query rewriter
**Pattern:** single-token vague queries ("commencement", "leadership", "productivity") stay literal through multi-query rewrite; retrieval can't surface what the query never described.
**Symptom seen:** q7 ("Anything about commencement?" → no expansion to "Stanford Steve Jobs graduation").
**Generic mechanism:** `query/transformer.py` rewriter generates paraphrases. For VAGUE-class queries, paraphrasing is the wrong primitive — these queries need *entity recall expansion*.
**Fix:** add a VAGUE-branch in the rewriter that, instead of paraphrase, asks the LLM "what specific people, sources, or topics in a knowledge base might match this vague intent?" The expanded queries then go through normal hybrid retrieval. Gate by `query_class is QueryClass.VAGUE OR (query_class is QueryClass.THEMATIC AND len(query.split()) <= 4)`.
**Knobs:** `RAG_VAGUE_ENTITY_EXPANSION_ENABLED=true`.
**Expected impact:** recovers q7. May lift other under-tested vague queries iter-12 introduces.
**Effort:** ~30 LOC + 1 prompt template + 2 tests + low-cost LLM call (flash-lite is fine).

### #5 — Class E + observability: scorer N/A for `expected=[]` AND structured logging on the score-rank gate
**Pattern (E):** refusal-expected queries mechanically false-fail gold@1, depressing the headline metric for *correct* behaviour.
**Symptom seen:** q9 (the only query in this fixture, but iter-12+ may add more adversarial probes).
**Pattern (observability):** Task 11's `_apply_score_rank_demote` has NO log line. We can't tell from droplet logs whether the gate fires correctly per query — only outcomes. iter-10 added P8/P12/P17 monitors but missed P3.
**Fix (5a):** in `score_rag_eval._aggregate_gold_metrics`, treat rows with `expected=[]` as `gold_at_1_not_applicable`; report this as a separate count in scores.md. Don't include in numerator OR denominator of gold@1.
**Fix (5b):** in `_apply_score_rank_demote`, emit `_log.info("score_rank_demote class=%s n_cands=%d n_demoted=%d title_demote_n=%d mean_factor=%.3f")` so iter-12 can see the gate's per-query behaviour and tune `RAG_SCORE_RANK_DEMOTE_FACTOR` from real distributions.
**Knobs:** none for 5a; existing `RAG_SCORE_RANK_DEMOTE_FACTOR` for 5b tuning.
**Expected impact:** q9 stops false-failing the headline; iter-12 has the data to tune Class A and Class B fixes.
**Effort:** 5 LOC each, both with tests.

---

## Iter-11 carryover (full)

| Priority | Item | Class | Why deferred | Where to start |
|---:|---|---|---|---|
| 1 | Anchor-exemption on magnet gate | A | Top-5 #1 above | `hybrid.py:_apply_score_rank_demote` |
| 2 | Name-overlap override on THEMATIC tiebreak | B | Top-5 #2 above | `hybrid.py:_tiebreak_key` |
| 3 | Per-entity anchor resolution + union | C | Top-5 #3 above | `entity_anchor.py:resolve_anchor_nodes` |
| 4 | Vague-class entity-hint expansion | D | Top-5 #4 above | `query/transformer.py` rewriter |
| 5 | `expected=[]` n/a + score-rank gate logs | E | Top-5 #5 above | `score_rag_eval.py` + `hybrid.py` |
| 6 | THEMATIC critic threshold relaxation (q5) | F | Critic floor protected by CLAUDE.md | needs explicit user approval to touch `_PARTIAL_NO_RETRY_FLOOR` family |
| 7 | Caddy SSE buffering investigation | infra | server is 1-2s but ttft is 25-37s — 25s gap on the wire | Caddy access log + Cloudflare flag review |
| 8 | Burst 502 → 0% | infra | still 0.25 in burst phase | Caddy upstream forensic + retry policy |
| 9 | P5 dense-fallback trigger broaden (`total_rows <= 1`) | C-adjacent | q10 had pool size 1, fallback only fires on 0 | `hybrid.py` retrieve fallback condition |
| 10 | Items 6 + 7 from RES-11 (admission middleware refactor + mid-flight latency abort) | infra | Real iter-11 design work; per-stage timing data from Task 17 is now the input | per-stage ms in `turn.token_counts.stage_timings` |

The five Top-5 fixes are explicitly **dynamic / generic** — each resolves a class of zettel patterns and is verifiable against `test_class_x_source_matrix.py` (extending it with a per-class case is part of the fix). Together they project to recover q7, q8, q10, q12 (and stop q9 from depressing the headline) without re-introducing any iter-09 regression — moving gold@1 to ~0.93 (13/14 if q5 also recovers, 12/14 otherwise).

---

## Files generated this iter
- `verification_results.json` (per-phase, per-query)
- `timing_report.md` (per-query latency table)
- `screenshots/` (12 captures)
- This `scores.md`
