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

## Iter-11 carryover

| Item | Why deferred | Where to start |
|---|---|---|
| Tune P3 demote factor (0.85 -> 0.92) | q8 regression -- magnet gate too aggressive | `RAG_SCORE_RANK_DEMOTE_FACTOR` env knob |
| Soften Task 9 THEMATIC tiebreak (x0.0001 -> x0.00005, or invert direction) | q12 regression | `_tiebreak_key` in `hybrid.py` |
| q5 critic threshold for THEMATIC | retrieval surfaces gold but synth refuses | `orchestrator._finalize_answer` critic gate |
| q7 vague-query rewriter expansion | "Anything about commencement?" stays literal | `query/transformer.py` multi-query rewriter |
| q10 anchor-seed for partial-resolve | only one of two named entities is in kasten | `entity_anchor.resolve_anchor_nodes` |
| Burst 502 -> 0% (still 0.25) | Caddy upstream timeout edge | Caddy access-log forensic + upstream tuning |
| `expected=[]` queries treated as "n/a" in gold@1 | q9 false-fail | `score_rag_eval._aggregate_gold_metrics` |
| Items 6 + 7 (admission middleware refactor + mid-flight latency abort) | RES-11: real iter-11 work, not iter-10 mitigations | Per-stage timing data from Task 17 is the input |

---

## Files generated this iter
- `verification_results.json` (per-phase, per-query)
- `timing_report.md` (per-query latency table)
- `screenshots/` (12 captures)
- This `scores.md`
