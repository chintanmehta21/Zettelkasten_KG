# Iter-10 Solutions Research — KM-Kasten RAG Eval

**Goal:** composite >= 85, gold@1 >= 0.85, all 14 queries running with high confidence under multi-user concurrency.

**Inputs verified before recommendations:**

- `docs/rag_eval/common/knowledge-management/iter-09/RESEARCH.md` (full, all "Cons NOT to take" sections)
- `docs/rag_eval/common/knowledge-management/iter-09/PLAN.md` (full)
- `docs/rag_eval/common/knowledge-management/iter-09/scores.md` (composite 65.32, gold@1=0.5714 *score-file figure*; raw verification_results.json yields 9/14 = 0.6429 — see Section 3 / harness drift)
- `docs/rag_eval/common/knowledge-management/iter-09/verification_results.json` (per-query primary, expected, verdict, latency)
- `docs/rag_eval/common/knowledge-management/iter-09/q5_500_traceback.txt` (HOLD — logs unrecoverable, container restart wiped stderr)
- `docs/rag_eval/common/knowledge-management/iter-09/timing_report.md`
- `website/api/chat_routes.py:143-198` (`_post_answer_side_effects`, `_run_answer` with rerank-slot wrap)
- `website/features/rag_pipeline/orchestrator.py:91-240` (skip-retry policy)
- `website/features/rag_pipeline/retrieval/hybrid.py:262-372, 475-505` (anchor-seed inject, chunk-share gate)
- `ops/scripts/eval_iter_03_playwright.py:586-685, 1175-1281` (SSE harness reader, qa_chain caller)
- `CLAUDE.md` Critical Infra Decision Guardrails (full)

**Sister files NOT available** (polled, absent at run time): `iter09_failure_deepdive.md`, `prior_attempts_knowledge_base.md`. Recommendations below cite the artifacts that ARE present and the live code; if the deepdive lands later it should be cross-checked against Section 1.

**Verified facts that contradict the user prompt's pre-known outcomes:**

| Prompt claim | Verified fact (source) | Implication |
|---|---|---|
| "p_user_avg = 277,773 ms (~4.6 min/query) because acquire_rerank_slot wraps auto_title" | `chat_routes.py:177-185` confirms slot wraps `_post_answer_side_effects` AND `runtime.orchestrator.answer`. BUT `latency_ms_server` shows 1.0-1.7s/query in iter-09. The 4.6 min is a HARNESS BUG, not a server bug. | Auto-title wrap is real but is NOT the visible 4.6 min. The harness's `performance.now()` reader never subtracts `t0`, so `firstTokenAt`/`doneAt` accumulate across the whole eval (q1 ttft=40k, q14 ttft=522k — strictly monotonic). See Section 1 row "Harness p_user accumulates". |
| "5 queries failed: q1 (timeout)" | q1 verification: `http=200, primary=gh-zk-org-zk, gold=True, verdict=partial, server_ms=1674`. Failure is `within_budget=False`, not timeout. | q1 is actually correct gold@1; failed only on the broken budget check (which uses the broken p_user). Fixing the harness bug recovers q1 within_budget. |
| "q5 wrong primary = gh-zk-org-zk" | Confirmed (`primary=gh-zk-org-zk`, expected=5 thematic nodes, none of which are gh-zk-org-zk). | gh-zk-org-zk magnet is THEMATIC, not LOOKUP-shape. RES-2 chunk-share gate IS firing for THEMATIC queries — still missed. |
| "q6/q7/q10 unsupported_no_retry, primary=None" | Confirmed for all three. | These are real recall misses. |
| "TTFT ≈ TTLT (streaming appears broken)" | p_user_first_token_ms - p_user_complete_ms is ~1.5-2s for every query — suggests TTFT measurement is off OR genuine pre-token stall. Need re-measurement after harness fix to disambiguate. | Don't trust the streaming-broken claim until harness arithmetic is fixed. |
| "Magnet: gh-zk-org-zk top-1 in 3/14 queries" | Confirmed: q1 (correct), q5 (wrong — magnet drag), q8 (correct). Only q5 is a magnet failure. | iter-09 anchor-seed RPC is one suspect; chunk-share class gate excluding LOOKUP+MULTI_HOP is another (q1 is multi_hop, gh-zk-org-zk passes for the right reason). |

**Real failing-query taxonomy (from verification_results.json):**

| qid | class | primary | expected | gold | verdict | root cause |
|---|---|---|---|:-:|---|---|
| q5 | thematic | gh-zk-org-zk | (5 thematic) | F | partial | wrong primary; thematic-vs-magnet drag still alive after RES-2 |
| q6 | lookup | None | 3 nodes | F | unsupported_no_retry | primary=None; pool returned no candidates |
| q7 | thematic | None | yt-steve-jobs | F | unsupported_no_retry | primary=None; pool empty |
| q10 | lookup | None | yt-steve-jobs | F | unsupported_no_retry | primary=None even though anchor-seed RPC supposedly seeds at floor 0.30 |

`primary=None + unsupported_no_retry` means the orchestrator didn't surface ANY citation — the rerank pool came back empty or the synthesizer refused. Anchor-seed for q10 should have prevented this.

---

## Section 1 — Pain-point matrix (centerpiece)

| Issue | Best possible suggestion (research-backed) | Prior eval of the same |
|---|---|---|
| **(P1) Harness p_user_*_ms accumulates monotonically across the eval** (q1=43k → q14=524k). Root cause: `ops/scripts/eval_iter_03_playwright.py:666-668` returns `Math.round(firstTokenAt)` (page-relative time since navigation) instead of `Math.round(firstTokenAt - t0)` (relative to fetch start). `t0` is captured at L593 but never subtracted. **This is the single biggest reason composite is 65 instead of >=80.** | ✓ **One-line fix:** subtract `t0` from `firstTokenAt`, `lastTokenAt`, `doneAt` before returning. Cost: 3 LOC, zero deploy risk (harness only), zero production touch. Verification: re-run eval, expect TTLT 1-5s for fast queries (matching `latency_ms_server`). | iter-09 RES-5 specified the SSE-aware reader as the fix for harness measurement. The reader was implemented but the timing arithmetic was never sanity-checked against `latency_ms_server`. **Not a known dead end** — undiscovered bug shipped iter-09. |
| **(P2) `_post_answer_side_effects` runs INSIDE `acquire_rerank_slot()`** (`chat_routes.py:177-185`). Auto-title invokes Gemini (~15-40s); wraps a Supabase write + sandbox touch. Holds slot AND blocks JSON return. Will compound under concurrent load (slots stay occupied for the full Gemini call instead of just orchestrator.answer). | ✓ **`asyncio.create_task` outside the slot, not FastAPI BackgroundTasks.** Web research (Source 1) confirms BackgroundTasks blocks response return for sync handlers and even async ones run BEFORE response in some FastAPI versions; `asyncio.create_task` is the correct fire-and-forget primitive that releases the slot. Wrap only `orchestrator.answer` in the slot. Cost: ~20 LOC, low risk if exception isolation + structured logging are added (the create_task must not silently swallow). Verification: server `latency_ms_server` already 1-1.7s; this brings true server p95 down ~30s for first-message-of-session turns. | RES-5 explicitly flagged: *"Move `_post_answer_side_effects` to background task in iter-09 — production touch outside iter-09 scope; flag for iter-10 investigation"*. **This IS the iter-10 task.** Phase 5 / Task 13 was supposed to motivate it post-iter-09 eval; iter-10 should ship the fix. |
| **(P3) q5 magnet: gh-zk-org-zk wins THEMATIC primary over 5 thematic gold** | ✓ **Tighten anchor-seed gating + lower the floor: (a) `_ANCHOR_SEED_FLOOR_RRF` 0.30 → 0.20`, (b) only inject when seed embedding cosine sim with anchor-name >= 0.4 (per-seed quality gate), (c) cap to top-3 seeds per query, not LIMIT 8.** Background: `hybrid.py:266-282` invokes anchor-seed when LOOKUP+entities>=1 OR compare_intent. q5 is THEMATIC so the gate shouldn't fire — but gh-zk-org-zk is winning anyway, so the magnet is from chunk-share NOT damping enough on a 2-chunk node. Re-evaluate the median calculation: KM={16,13,10,6,6,3,**2**} median=6, gh-zk-org-zk=2 chunks → ratio 2/6=0.33 → NOT damped (correct: it's small) but ALSO not boosted. The win must come from another path — probably title/lexical match. **Real fix:** add a "is this candidate semantically related to query topics" cross-encoder check at xQuAD slot 1 only; if score < 0.3 and it's a small-chunk magnet via lexical overlap, demote. Cost: ~50 LOC, medium risk. | iter-08 RES-4 magnet hypothesis was confirmed; iter-09 RES-2 ratio-to-median magnet detector was meant to catch this. **Did NOT catch q5** because gh-zk-org-zk is *low-chunk* magnet, not high-chunk. The "magnet" definition needs to broaden to "node winning top-1 disproportionate to its semantic relevance" — score-based, not chunk-share-based. This is the iter-10 evolution of RES-2. |
| **(P4) q10 anchor-seed produced primary=None** | ✓ **Verify the seed actually injects.** `hybrid.py:262-282` only fires when `is_lookup AND (n_persons + n_entities) >= 1` OR `compare_intent`. q10 is LOOKUP — so the gate may have rejected it because `n_persons + n_entities = 0` (Steve Jobs not extracted as entity in iter-09's NER). **Fix:** when `anchor_nodes` is non-empty (set by `entity_anchor.py` resolution), DON'T re-gate on entity-count — anchor resolution itself proves an entity match. Drop the `(n_persons + n_entities) >= 1` clause from the L276 condition. Cost: 3 LOC, low risk. Verification: q10 should surface `yt-steve-jobs-2005-stanford` as primary. | RES-7 anchor-seed was the strongest single-query lever. Implementation appears correct, but the gate predicate is too strict — entity_anchor resolution already filtered, gating on metadata.entities count is double-filtering. **Not previously identified** as a defect. |
| **(P5) q6/q7 returning primary=None (`unsupported_no_retry`)** | ✓ **Investigate retry path.** `_should_skip_retry` at orchestrator.py:176-240 returns True early on multiple paths: `no_candidates`, `evaluator_low_score (<0.10)`, `vague_low_entity`. q6 LOOKUP with 3 expected zettels likely hits "no_candidates" (rerank pool empty). Fix: dispatch a Phase-0 scout agent to print the actual `used_candidates` list for q6/q7 from a reproduced run. Until then, hypothesise: the candidate pool is empty AFTER rerank because the dense retrieval missed the gold node entirely. Look at base recall — `chunk_count={web-tools:6,...}` for q6 expected; if dense+FTS recall@8 misses, rerank can't recover. | iter-08 q10 had identical `partial; jobs zettel never reached pool — no anchor seed injection`. iter-09's anchor-seed was supposed to fix exactly this; it didn't because of P4 above. q6 isn't covered by anchor-seed yet — needs a separate "if recall@8 misses gold-known nodes for this kasten, dispatch a single high-precision dense-only retrieval pass" fallback. |
| **(P6) `gold@1` reporting drift** | scores.md says 0.5714 (8/14); verification_results.json gold count is 9/14 (0.6429). Discrepancy is in `score_rag_eval.py` re-aggregation. ✓ **Audit the scorer:** the within_budget filter likely excludes one passing query from the gold count. Fix: separate "gold@1 unconditional" from "gold@1 AND within_budget" — they are different metrics. | Not previously surfaced. iter-08→iter-09 metric pipelines diverged silently. |
| **(P7) `within_budget_rate = 0.0714` (1/14)** | ✓ **Mostly an artifact of P1.** After harness fix, true server times are 1.0-1.7s (fast) and 1.3s (high), well under all budgets. Expected: within_budget jumps to ~0.85+ on identical responses. Secondary: `_post_answer_side_effects` does add 15-40s when first-message auto-title fires; fixing P2 returns this to baseline. | iter-08 `within_budget = 0.1429`, iter-09 `0.0714` — regression. Root cause is P1, not real latency growth. |
| **(P8) Burst pressure: 503=6, 502=3, 200=3** (iter-09 scores.md) | iter-09 RES-4 wired `_run_answer` into `acquire_rerank_slot()` and 503 rate hit 0.5 (target >=0.08) — **fix worked**. The 3x 502s remain (one per worker OOM). ✓ **Add ulimit / cgroup memory pressure logging on burst** — log RSS pre/post each burst slot acquire. Cost: ~10 LOC observability, zero behavior change. Not a guarded knob. | RES-4 fix shipped successfully. 502s during burst likely from the model-loaded worker — the BGE int8 model + 12 concurrent rerank requests across 2 workers can spike RAM. Don't lower workers (CLAUDE.md guarded). |
| **(P9) BGE int8 cross-encoder is the rerank bottleneck (~250-400ms per pair, magnet-blind)** | ✗ **Do NOT swap for ms-marco-MiniLM-L-6 in iter-10.** Replacing the reranker is a multi-iter project: requires (a) re-quantizing in production, (b) re-tuning all thresholds (rerank floors live in 4+ files: orchestrator partial-no-retry 0.5, unsupported-with-gold 0.7, refusal-semantic 0.5, retry-floor 0.10), (c) re-running iter-04..iter-09 fixtures to confirm no regression, (d) RAM measurement on droplet. **Defer to iter-11+.** Iter-10 fix is to keep BGE and add a **candidate-quality gate pre-rerank** — drop rrf<0.10 rows BEFORE the cross-encoder sees them (fewer pairs, same model). Cost: ~15 LOC. | RES-3 already deferred a "rerank-stage magnet penalty" to iter-10 with conditions. Reranker swap was never proposed in iter-04..iter-09 — too disruptive. The pre-rerank quality gate is the gentle path. |
| **(P10) Router rule-5 was narrowed in iter-09 (18→25), but new rules added simultaneously** | iter-09 PLAN Phase 2/Task 9 shipped both. q1 (multi_hop), q5 (thematic), q13/q14 (multi_hop) classifications in iter-09 look correct now. ✓ **No iter-10 router change.** | RES-6 dead-end list explicitly: do NOT add "tag-based author detection" yet (option c) — kept as iter-10+ option. Iter-10: leave router alone, focus on retrieval + concurrency. |
| **(P11) Auto-title Gemini call fails when one of two paths exhausts model quota** | Observed in `timing_report.md`: `gemini-2.5-pro-rate-limited` repeatedly. Auto-title falls back through key-pool, but the fallback walk itself takes 5-10s. ✓ **Use flash-lite for auto-title** instead of flash/pro. Auto-title is a 2-line summarization task — flash-lite is plenty. Saves both quota AND latency. Cost: 1 LOC config change in `auto_title_session`. Low risk. | Never tried. Auto-title was added in early iters using whatever default model the key-pool gave. **First-time consideration.** |
| **(P12) q5 500 root cause is HOLD** | iter-09 logs unrecoverable per `q5_500_traceback.txt`. ✓ **Do not push speculative fix.** Add structured logging around `chunk_share` TTL cache + `_ensure_member_coverage` THEMATIC empty-counts path so the next 500 yields the traceback. Cost: ~10 LOC logging. | Per CLAUDE.md guardrails: q5 stays HOLD until logs in hand. iter-10 ships only the logging diff. |
| **(P13) RAGAS `answer_relevancy=74.29` (vs `faithfulness=87.50`)** | The model is faithful to retrieved context but doesn't fully answer the question. ✓ **Add a "self-check did I address every clause of the question" step before final synthesis.** Current SYSTEM_PROMPT in `generation/prompts.py` doesn't enforce clause coverage. Re-prompt to: "Before finalizing, list each sub-question/clause and confirm coverage; if uncovered, say so explicitly." Cost: ~30 LOC prompt change + 1 RAGAS re-eval. | Iter-08 noted "synthesizer over-refusals" (3 still in iter-09). Connected — over-refusal AND incomplete-answer share the same prompt-rigor root. **Not previously addressed.** |
| **(P14) Per-route slot-acquire pattern is fragile** | RES-4 already noted: middleware refactor is the durable fix. ✗ **Defer to iter-11.** Reason: not on the critical path to composite >=85. Single-knob risk if middleware mis-orders auth → admission. | RES-4 explicitly classified as iter-10+ scope. Confirmed defer. |

**Summary of Section 1:** P1 (harness fix) + P2 (auto-title outside slot) alone likely lift composite from 65 → 80. P3+P4+P5 push gold@1 from 0.64 → ~0.85. P11 + P13 polish synthesis. P9/P14 stay deferred. P12 stays defensive-only.

---

## Section 2 — Architectural refactor candidates (multi-module)

### A. Move `_post_answer_side_effects` to `asyncio.create_task` outside the rerank slot
- **Modules touched:** `website/api/chat_routes.py` (both `_run_answer` and `_stream_answer` paths). Add small `_BackgroundExecutor` helper or use `asyncio.create_task` directly with a wrapped exception logger.
- **Why now:** RES-5 flagged this as the iter-10 task; iter-09 confirmed the slot is held for the side-effects duration; first-message-of-session auto-title is a 15-40s Gemini call that ties up rerank capacity.
- **Estimated impact:** server-perceived latency for FIRST turn of session drops from ~30s to ~3s. Slot turnover under burst load improves dramatically (one slot per active rerank, not per active synth+side-effect).
- **Cost / risk:** ~20-40 LOC, medium risk if exception isolation is sloppy. Tests: 2 unit (slot released before side effects complete; side-effect failure does not 500 the response). Production blast radius low — failure mode is "auto-title silently doesn't apply", which is recoverable.
- **Prior research:** ✓ flagged in iter-09 RES-5 cons-NOT-to-take ("flag for iter-10 investigation"). Web research (Source 1, FastAPI BackgroundTasks discussion) confirms `asyncio.create_task` is correct primitive; FastAPI BackgroundTasks blocks response in some configurations.

### B. Pre-rerank candidate-quality gate (drop rrf < 0.10 before BGE int8 sees them)
- **Modules touched:** `website/features/rag_pipeline/retrieval/cascade.py` (just before the rerank loop), `website/features/rag_pipeline/retrieval/hybrid.py` (pass `_RERANK_INPUT_FLOOR` env).
- **Why now:** 5 iters of single-knob tuning on the magnet hypothesis; the cleanest win remaining is reducing the input set the magnet-blind cross-encoder sees.
- **Estimated impact:** rerank latency drops 20-40% (fewer pairs); reduced magnet drag on q5/q7-shape queries (small-chunk lexical magnets get filtered before cross-encoder sees them).
- **Cost / risk:** ~15 LOC + 3 unit tests. Risk: if rrf<0.10 is set too aggressive, recall drops. Default 0.10 matches `_RETRY_TOP_SCORE_FLOOR`; safe.
- **Prior research:** ✓ implicit in RES-3 (rerank-stage magnet penalty deferred). Pre-rerank gate is the orthogonal angle never previously proposed.

### C. Per-query latency budget aborter (mid-flight)
- **Modules touched:** `website/features/rag_pipeline/orchestrator.py` `answer` / `answer_stream`, retrieval planner.
- **Why now:** under multi-user concurrency a slow query can hold the slot longer than budget — better to abort retrieval at 80% budget and synth on what we have.
- **Estimated impact:** within_budget_rate floor lifts; tail latency p99 caps at budget instead of trailing 60s+.
- **Cost / risk:** ~60 LOC + asyncio.wait_for sprinkled across retrieval stages. **Higher risk** — partial-pool synthesis can degrade quality if mis-applied to MULTI_HOP. Gate by class.
- **Prior research:** ✗ never proposed. Worth iter-10 spec but not the 1st thing to ship.

### D. Auto-title model downgrade to flash-lite
- **Modules touched:** `website/features/sessions/auto_title.py` (or wherever `auto_title_session` lives) — pin model.
- **Why now:** Auto-title is 1-2 sentences; flash-lite handles it. Removes Gemini-2.5-pro rate-limit cascade.
- **Estimated impact:** auto-title latency 15-40s → 1-3s. Frees the API key pool for actual answer generation.
- **Cost / risk:** 1-3 LOC. Trivial. Verify with 5 sample sessions that titles are still meaningful.
- **Prior research:** ✗ never tried. P11 in Section 1.

### E. Tag-based author detection in router (RES-6 option c)
- **Modules touched:** `website/features/rag_pipeline/query/router.py`, `website/features/rag_pipeline/query/metadata.py`, kasten tag indexer.
- **Why now:** Q14's "Matuschak" surname-only miss is a recurring failure pattern; if any zettel in the kasten has author=Matuschak, single-name surname queries should match.
- **Estimated impact:** improves NER-recall edge cases (single-name authors, brand names mistaken for orgs). Fixes 1-2 iter-09 misses.
- **Cost / risk:** ~50 LOC. Risk: increases router LLM call count if tag fetch isn't cached.
- **Prior research:** ✓ RES-6 option (c), explicitly deferred to iter-10. Iter-10 timing: ship only after A+B+D land.

---

## Section 3 — Per-query intervention plan

| qid | iter-09 outcome | Root cause | Fix (Section 1 row) | Expected outcome |
|---|---|---|---|---|
| q1 | http=200, primary=gh-zk-org-zk (correct), gold=True, within_budget=False | Harness `p_user` arithmetic bug; query is actually correct under 2s server | **P1** harness fix | within_budget=True, query passes |
| q5 | primary=gh-zk-org-zk (wrong; 5 thematic gold expected) | Magnet drag on a 2-chunk node winning THEMATIC top-1 via lexical/title overlap (chunk-share doesn't damp small-chunk magnets) | **P3** tighten anchor-seed gating + add semantic-relevance check at xQuAD slot 1 | Primary becomes one of {yt-programming-workflow, web-transformative-tools, yt-steve-jobs}; gold@1 flips True |
| q6 | primary=None, verdict=unsupported_no_retry | Rerank pool empty for the 3 expected zettels (web-tools, public-speakin, gh-zk-org-zk); `_should_skip_retry` no_candidates path | **P5** dispatch scout to confirm; if confirmed, add fallback dense-only pass when recall@8 misses kasten golden-set | Pool acquires at least one expected node; verdict shifts to partial or supported |
| q7 | primary=None, verdict=unsupported_no_retry | Same recall miss (yt-steve-jobs not in pool for THEMATIC) | **P5** + **P3** (semantic-relevance gate may pull steve-jobs back in if it's in the larger candidate set) | Primary surfaces yt-steve-jobs |
| q10 | primary=None, verdict=unsupported_no_retry | Anchor-seed `(n_persons+n_entities)>=1` re-gate rejected the inject because NER missed Steve Jobs as entity (single-name surname) | **P4** drop the entity-count re-gate; trust `anchor_nodes` non-empty as sufficient evidence | Anchor-seed inject fires; yt-steve-jobs surfaces at floor 0.30; cross-encoder picks it |

---

## Section 4 — What we should NOT touch

Per CLAUDE.md "Critical Infra Decision Guardrails" + iter-N RESEARCH "Cons NOT to take":

- **GUNICORN_WORKERS=2 stays.** No reduction even if iter-10 burst probes 502 again. Phase 1A int8 quantization is justified by 2-worker viability.
- **`--preload` stays.** Removing re-explodes RAM.
- **`FP32_VERIFY_ENABLED` stays top-3 only.** Phase 1A.5 decision.
- **`GUNICORN_TIMEOUT >= 180s` stays.** No reduction.
- **Rerank semaphore / bounded queue stays.** RES-4 fix MUST remain wrapped.
- **SSE heartbeat wrapper stays.** Cloudflare 502 protection.
- **Caddy `read_timeout 240s` upstream stays.**
- **Schema-drift gate (Phase 1C.5) and `kg_users` allowlist (Phase 2D.2) stay.**
- **No purple anywhere; teal default; amber only on `/knowledge-graph`.**
- **Reranker swap (BGE int8 → ms-marco-MiniLM) NOT in iter-10.** P9 row. Multi-iter project; stays for iter-11+ with explicit user approval, eval-fixture replay, RAM measurement.
- **Router rule structural changes NOT in iter-10.** RES-6 already narrowed; tag-author detection (option c) stays deferred until A+B+D land.
- **Magnet penalty at rerank stage (RES-3) stays deferred.** Multi-gate version only — and only if Section 1 P3 (anchor-seed tightening + semantic gate) doesn't fix q5.
- **Don't change `_PARTIAL_NO_RETRY_FLOOR`, `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR`, `_RETRY_TOP_SCORE_FLOOR`** without an A/B replay against iter-04..iter-09 fixtures.
- **Don't speculatively fix q5 500.** iter-09 q5_500_traceback.txt: HOLD until logs in hand.
- **Don't push admission middleware refactor in iter-10.** RES-4 alternative; per-route guards stay until middleware refactor has its own iter spec.

---

## Section 5 — Iter-10 phased plan outline

### Phase 0 — Pre-flight (no code)
- Verify the 3 sister artefacts (`iter09_failure_deepdive.md`, `prior_attempts_knowledge_base.md`) — if landed, cross-check Section 1 rows against them; revise before Phase 1.
- Dispatch a scout subagent to print actual `used_candidates` (with rerank scores) for q6, q7, q10 from a reproduced run. (Section 1 P5)
- Re-confirm `latency_ms_server` baseline by hitting `/api/rag/adhoc` with `stream:false` from curl, 3 sample queries — establish ground truth before harness fix verification. (Section 1 P1)

### Phase 1 — Harness truth (the unblocker)
- **Task 1.1:** Fix `eval_iter_03_playwright.py:666-668` — subtract `t0`. (Section 1 P1)
- **Task 1.2:** Re-run iter-09 fixture; confirm TTLT 1-5s for fast queries, within_budget jumps. Update score_rag_eval.py to separate "gold@1 unconditional" from "gold@1 within budget". (Section 1 P6, P7)
- **Verification gate:** if composite jumps from 65 → 75+ on identical iter-09 server outputs, P1 was the dominant pain. Proceed.

### Phase 2 — Recall fixes (q6/q7/q10)
- **Task 2.1:** Drop entity-count re-gate in `hybrid.py:262-282` anchor-seed inject path. (Section 1 P4)
- **Task 2.2:** Add `_RERANK_INPUT_FLOOR=0.10` candidate-quality gate before cross-encoder. (Section 2 B)
- **Task 2.3:** If Phase 0 scout confirms q6/q7 pool-empty: add the dense-only fallback for kasten-golden recall miss. (Section 1 P5)
- **Verification:** q6/q7/q10 each surface a non-None primary; gold@1 climbs to >=0.78.

### Phase 3 — Concurrency unblock + auto-title speedup
- **Task 3.1:** Move `_post_answer_side_effects` to `asyncio.create_task` outside `acquire_rerank_slot()`. (Section 2 A)
- **Task 3.2:** Pin auto-title to `gemini-2.5-flash-lite`. (Section 2 D)
- **Verification:** server p95 (true) drops; first-turn-of-session latency drops 30s; burst probe 503 rate stable >= 0.08.

### Phase 4 — q5 magnet (multi-module)
- **Task 4.1:** Tighten anchor-seed: lower floor to 0.20, add per-seed cosine-sim quality gate, cap top-3 seeds. (Section 1 P3)
- **Task 4.2:** Add semantic-relevance check at xQuAD slot 1: if top-1 candidate cross-encoder score < 0.3 AND it's a small-chunk lexical-magnet shape, demote one slot. (Section 1 P3)
- **Verification:** q5 primary becomes one of the 5 expected thematic nodes.

### Phase 5 — Synthesis polish (optional, only if composite < 85 after Phases 1-4)
- **Task 5.1:** Clause-coverage self-check in SYSTEM_PROMPT. (Section 1 P13)
- **Task 5.2:** Add structured logging around chunk_share TTL cache + `_ensure_member_coverage` empty-counts path so next q5 500 yields traceback. (Section 1 P12)

### Phase 6 — Verification
- Re-run full eval; require composite >= 85, gold@1 >= 0.85, within_budget_rate >= 0.85, burst 503 rate >= 0.08, burst 502 rate <= 0.10.
- Replay iter-04..iter-08 fixtures through router/orchestrator; assert zero class-flip regressions.
- Manual smoke test: 3 concurrent users hitting `/api/rag/adhoc` for 1 minute; assert no 5xx, no slot starvation.

**Honest staging assessment:** composite >=85 + gold@1 >=0.85 + multi-user safe is **achievable in iter-10** if Phases 1-3 succeed (high-confidence fixes). Phase 4 (q5 magnet) is moderate-confidence — may need a second iter pass if the semantic gate over-fires. If Phase 4 misses, ship iter-10 at composite ~80 and target iter-11 for q5+reranker swap.

---

## Sources

- [FastAPI Background Tasks docs](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [BackgroundTasks blocks entire FastAPI application — fastapi/discussions/11210](https://github.com/fastapi/fastapi/discussions/11210)
- iter-09 RESEARCH.md (in-repo, all RES-N sections)
- iter-09 PLAN.md (in-repo, all phases)
- iter-09 verification_results.json (in-repo, raw per-query data)
- iter-09 q5_500_traceback.txt (in-repo, HOLD documentation)
- CLAUDE.md (in-repo, Critical Infra Decision Guardrails section)
