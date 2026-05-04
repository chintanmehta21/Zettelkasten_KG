# Iter-10 Research Reference

This document is the consolidated research artefact for iter-10. Audiences:

1. **Future humans / agents looking back at iter-10** — to understand what we knew, what we tried, and what we deliberately rejected.
2. **The plan executor (subagent or human running [PLAN.md](PLAN.md))** — to look up rationale, edge cases, and "why not X" decisions when a phase task references them.

**Cross-reference:** [PLAN.md](PLAN.md) — implementation tasks. This file is the *why*; PLAN.md is the *how*.

**Sister artefacts (read before any phase):**
- `iter-09/iter09_failure_deepdive.md` — per-query forensic
- `iter-09/prior_attempts_knowledge_base.md` — iter-04..iter-08 changelog
- `iter-09/iter10_solutions_research.md` — Agent C's P1-P14 matrix
- `iter-09/iter10_followup_research.md` — Agent E's deep-dive on the 7 follow-up items
- `iter-09/guardrails_review.md` — Agent F's 16-guardrail review
- `iter-09/q5_500_traceback.txt` — q5 500 HOLD note (logs unrecoverable)

---

## How the executor should use this file

When implementing any PLAN.md phase, **before writing code or tests for that phase**:

1. Read the matching `RES-N` section here.
2. If a task is unclear, look up "Pitfalls" and "Cons NOT to take" — they capture every dead end already explored.
3. If a test fails in an unexpected way, check "Edge cases" for that section.
4. If you encounter a decision point not covered here, **stop and ask the user** rather than improvising. Beyond-plan decisions require explicit chat-confirmed approval per CLAUDE.md.

---

## Iter-09 outcome that motivates iter-10

| Metric | iter-08 | iter-09 (raw) | iter-09 (after P1 hypothesised fix) | iter-10 target |
|---|---:|---:|---:|---:|
| Composite | 63.53 | 65.32 | ~80 (estimated) | ≥ 85 |
| chunking | 40.43 | 40.43 | 40.43 | held |
| retrieval | 76.90 | 97.08 | held | held |
| reranking | 49.31 | 57.14 | held | ≥ 70 |
| synthesis | 67.55 | 56.85 | held | ≥ 75 |
| gold@1 (unconditional) | 0.7143 | 0.6429 (true) / 0.5714 (mis-reported) | 0.6429 (audited) | ≥ 0.85 |
| within_budget | 0.2143 | 0.0714 (harness-distorted) | ~0.85 (post P1) | ≥ 0.85 |
| burst 503 rate | 0% | 0.50 | held | ≥ 0.08 |
| burst 502 rate | 25% | 21% (3/14) | drop with P2 | 0% |
| answer_relevancy (RAGAS) | n/a | 74.29 | held | ≥ 80 |
| faithfulness (RAGAS) | n/a | 87.50 | held | held |

**Per-query failure mode after iter-09 (verified disk facts, not screenshots):**

| qid | http | server_ms | gold@1 | failure root cause (verified) |
|---|---:|---:|:-:|---|
| q1 | 200 | 1674 | T | NOT a failure; harness arithmetic bug mislabelled it |
| q2-q4 | 200 | ~1300 | T | pass |
| q5 | 200 | 1275 | F | gh-zk-org-zk wins THEMATIC top-1; small-chunk lexical magnet; chunk-share doesn't damp 2-chunk nodes; pre-existing iter-08+ issue not introduced by iter-09 |
| q6 | 200 | 1521 | F | primary=None unsupported_no_retry; recall miss (verify pool-empty in Task 2 scout) |
| q7 | 200 | 1320 | F | primary=None unsupported_no_retry; same recall pattern as q6, THEMATIC class |
| q8 | 200 | 1200 | T | pass |
| q9 | 0 | n/a | F | adversarial-negative + harness timeout; expected refusal — separate issue |
| q10 | 200 | 1212 | F | primary=None; anchor-seed `(n_persons+n_entities)>=1` re-gate rejected because NER missed "Steve Jobs" as person entity (single-name surname) |
| q11-q14 | 200 | ~1300 | T | pass |

`latency_ms_server` for ALL fast queries: 1.0-1.7s. The "4.6 min/query" appearance is the harness arithmetic bug (P1) — `firstTokenAt`/`lastTokenAt`/`doneAt` returned page-relative absolute times instead of relative to per-query fetch `t0`.

---

## RES-1 — P1 harness arithmetic bug (3 LOC fix recovers ~15 composite points)

**Verdict: ✓ ship Phase 1.**

**The bug:** `ops/scripts/eval_iter_03_playwright.py:666-668` returns `Math.round(firstTokenAt)` etc. without subtracting `t0` (which is captured at L593). Since `performance.now()` is page-relative, every subsequent query's TTFT/TTLT looks ~3s higher than the previous one's, monotonically — q1=43k, q14=524k.

**Evidence:** `latency_ms_server` is 1.0-1.7s for every iter-09 query. The Python parity parser at `ops/scripts/_sse_reader.py` already subtracts `t0` correctly and its unit tests pass; only the JS-side arithmetic is wrong.

**Cons NOT to take:**
- Don't replace `performance.now()` with `Date.now()` — `performance.now()` is the right primitive for sub-second wall-time, just needs the subtraction.
- Don't switch the eval back to `stream:false` to "avoid SSE complexity" — the SSE path is what gives us TTFT, which we need for true UX measurement.

**Where this lands:** PLAN.md Phase 1 / Task 4.

---

## RES-2 — P2 auto-title outside `acquire_rerank_slot` (asyncio.create_task)

**Verdict: ✓ ship Phase 3.**

**The problem:** iter-09 RES-4 fix wrapped `_run_answer` in `acquire_rerank_slot()` to make burst-503 work. Side effect: `_post_answer_side_effects` (which contains `auto_title_session`, a 15-40s Gemini call for first-message-of-session turns) runs INSIDE the slot. Slots are now held for the FULL pipeline + auto-title. Concurrency throughput collapses.

**Why `asyncio.create_task` and NOT `BackgroundTasks`:**
- FastAPI's `BackgroundTasks` runs AFTER the response is returned — but in some configs (sync handlers, certain middleware orderings) it BLOCKS the response. Source: https://github.com/fastapi/fastapi/discussions/11210
- `asyncio.create_task` runs concurrently with response return AND releases the slot immediately. This is the correct primitive for fire-and-forget work that must not block the response or the slot.

**Exception isolation:** the create_task'd coroutine MUST NOT raise — wrap in `try/except + logger.exception` so a failed auto-title doesn't crash the worker.

**Cons NOT to take:**
- Don't use a thread pool — the side effects are async I/O (Supabase, Gemini); a thread is overkill.
- Don't queue side effects to a separate worker process — over-engineering for a 2GB droplet; iter-11 if needed.

**Where this lands:** PLAN.md Phase 3 / Task 8.

---

## RES-3 — P3 q5 magnet: score-rank-correlation gate (THEMATIC/STEP_BACK only)

**Verdict: ✓ ship Phase 5.**

**The problem:** iter-09 q5 (THEMATIC) had `gh-zk-org-zk` (a 2-chunk node) win primary over 5 thematic gold candidates. iter-09 RES-2 chunk-share ratio-to-median didn't catch it because gh-zk-org-zk is a SMALL-chunk magnet (ratio 0.33, below the 2.0 threshold), not a chunky one. The win came from title/lexical match on "zk".

**The gate:** broaden "magnet" definition from chunk-share-based to **score-rank-correlation**. A node is a magnet if its top-1 ranking is disproportionate to its retrieval percentile. Compute each candidate's percentile of `_base_rrf_score` (the rrf BEFORE all class boosts) and demote any candidate whose post-boost rank is ≥ 1 quartile higher than its base percentile.

**Class scope: THEMATIC and STEP_BACK only. NOT VAGUE.**

| Class | Why included / excluded |
|---|---|
| LOOKUP | EXCLUDED. Proper-noun lookups legitimately boost a single high-relevance node to top-1 even when base rrf was lower. Gating LOOKUP would regress q11/q12/q14 (single-name surname queries that should win on title-match alone). |
| THEMATIC | INCLUDED. Cross-corpus synthesis where one magnet drowns siblings is the exact failure mode. q5 + q7 are THEMATIC. |
| STEP_BACK | INCLUDED. Same magnet vulnerability as THEMATIC; symmetric for safety. |
| VAGUE | EXCLUDED. VAGUE has its own `vague_low_entity` gate (orchestrator.py:202-213). Stacking another magnet penalty on top creates two interfering gates and risks collapsing recall on legitimately broad queries. |
| MULTI_HOP | EXCLUDED. Multi-hop already broadens via fan-out; double-penalising a magnet that surfaced on hop-1 risks losing hop-2 anchors. |

**Title-overlap secondary demote:** if a candidate's `_title_overlap_boost` ≥ 0.10, multiply rrf by 0.95 even if score-rank delta is small. Catches the "title carries the win" pattern that score-rank misses on small candidate pools.

**Knobs (env-flag tunable):**
- `RAG_SCORE_RANK_DEMOTE_FACTOR=0.85` (multiplicative damp)
- `RAG_SCORE_RANK_DISPROP_QUARTILES=1.0` (delta threshold in quartiles)
- `RAG_TITLE_OVERLAP_DEMOTE_FACTOR=0.95`
- `RAG_TITLE_OVERLAP_DEMOTE_FLOOR=0.10`

**Cons NOT to take:**
- DO NOT extend to LOOKUP (regresses q11/q12/q14).
- DO NOT extend to VAGUE (interferes with vague_low_entity).
- DO NOT use a fixed threshold like `chunk_count >= 8` (iter-09 RES-3 already rejected — false-positives steve-jobs which is gold).
- DO NOT subtract from rrf — multiplicative damp keeps score-tie ordering stable.

**Edge cases:**
- Pool with < 4 candidates: skip gate entirely (rank percentile is unstable).
- All candidates have identical base rrf: gate is a no-op (delta is always 0).
- LOOKUP misclassified as THEMATIC (router error): gate fires; mitigated by Item 3's cross-class regression fixture catching the regression on subsequent eval.

**Where this lands:** PLAN.md Phase 5 / Task 11.

---

## RES-4 — P4 q10 anchor-seed un-gate + 4 mitigations

**Verdict: ✓ ship Phase 2.**

**The problem:** iter-09 P4 introduced anchor-seed RPC (`rag_fetch_anchor_seeds`). For LOOKUP queries with `anchor_nodes` resolved, the RPC fetches seed candidates and injects them at floor 0.30. **But** the iter-09 wiring at `hybrid.py:262-282` re-gates on `(n_persons + n_entities) >= 1` — q10's "Steve Jobs" was missed by NER (single-name surname), so n_persons=0 even though `entity_anchor.py:resolve_anchor_nodes` correctly resolved `yt-steve-jobs-2005-stanford` via tag/title-substring match. The re-gate rejected the inject; q10 surfaced primary=None.

**The fix:** drop `(n_persons + n_entities) >= 1`. `anchor_nodes` non-empty already proves entity match at the kasten level (RPC is INNER JOIN'd against `kg_nodes.name ILIKE '%' || e || '%' OR e = ANY(n.tags)`). Re-gating on metadata.entities is double-filtering.

**4 defense-in-depth mitigations (all MUST land together):**

| # | Mitigation | Why |
|---|---|---|
| 1 | `is_lookup AND query_class is not QueryClass.THEMATIC` | Defence-in-depth: even if router misclassifies, THEMATIC gets ZERO seed inject. Compare-intent is the only exception. |
| 2 | Min entity-length floor 4 chars | `rag_resolve_entity_anchors` uses `n.name ILIKE '%' || e || '%'`. Short entities like "AI" / "ML" / "JS" tag-collide on every kasten. Skip inject when ALL resolving entities are <4 chars. |
| 3 | Cap seeds to top-3 (not RPC LIMIT 8) | If entity_anchor over-resolves due to greedy substring match, only top-3 by score get injected. Cross-encoder still has final say. |
| 4 | Structured log every inject (`anchor_seed_inject qid= class= n_anchors= n_seeds= floor=`) | Catches over-pulls in eval. |

**Multi-speaker zettel scenarios (verified):**

| Scenario | Effect after fix |
|---|---|
| Single-name surname (q10 "Steve Jobs", q14 "Matuschak") | ✓ FIX (the intended improvement) |
| Multi-speaker zettel, query mentions one speaker | ✓ no change (NER catches name; gate still passes) |
| Multi-speaker zettel, query mentions topic only | ✓ no change (anchor_nodes empty; gate skipped on `no_anchor_nodes`) |
| Generic-tag false-positive ("engineer" matches `nl-the-pragmatic-engineer-t`) | ⚠ pre-existing risk, NOT amplified — top-3 cap + 0.30 floor + cross-encoder bound it |
| Short-entity false-positive ("AI" matches every AI-tagged kasten) | ✓ NEW PROTECTION via mitigation 2 |

**Cons NOT to take:**
- DO NOT add a confidence threshold on `entity_anchor.resolve_anchor_nodes` (RPC has no confidence; would require schema change — iter-11+).
- DO NOT keep the entity-count gate "just in case" — that defeats the q10 fix.
- DO NOT lower the anchor_seed floor to 0.20 (iter-10 followup_research rejected this; no evidence floor=0.30 is too high).

**Where this lands:** PLAN.md Phase 2 / Task 6.

---

## RES-5 — P5 q6/q7 dense-only fallback (gated by Phase 0 scout)

**Verdict: ⚠ ship-with-mitigation IF scout confirms pool empty.**

**The problem:** q6/q7 returned `primary=None` with `unsupported_no_retry`. Two possible root causes:
- **A.** Rerank pool was empty of expected gold node ids (recall miss before rerank).
- **B.** Rerank pool had gold but ranking surfaced wrong primary (magnet drag — covered by P3).

These have different fixes. Without the Phase 0 scout, we'd ship one and break the other.

**The scout (PLAN Phase 0 / Task 2):** add temporary verbose logging in `_dedup_and_fuse` that prints `(node_id, rrf_score)` of the top 5 candidates per query when `RAG_SCOUT_LOG_USED_CANDIDATES=true`. Run a single eval with the flag, pull droplet logs, inspect q6/q7's actual pool. Decide A vs B BEFORE writing the fallback.

**If A: ship the fallback.** Add `rag_dense_recall` RPC (single dense-similarity pass scoped to all kasten members) and trigger it ONLY when `total_rows == 0` after the main hybrid fan-out. This is a defensive "we missed everything, throw a wide net" — never the primary path.

**If B: skip Task 10.** Document the decision; rely on P3 + P9 to surface gold from the existing pool.

**Cons NOT to take:**
- DO NOT trigger the fallback on `len(pool) < N` for any N — that becomes the default path and bypasses BM25/embedding fusion (the whole point of hybrid).
- DO NOT make the fallback class-conditional — recall miss is a recall miss; class is irrelevant at that point.
- DO NOT use a separate model for the fallback dense pass — keep the same embedder + same vector index.

**Where this lands:** PLAN.md Phase 4 / Task 10 (gated on Task 2 scout decision).

---

## RES-6 — P9 pre-rerank adaptive percentile floor

**Verdict: ✓ ship Phase 6.**

**The problem:** BGE int8 cross-encoder is the dominant rerank cost (~250-400ms per pair). Iter-09 reranked the entire post-fusion pool. Many low-rrf candidates (rrf<0.10) are clearly noise but still consume cross-encoder cycles. Worse, magnet drag is amplified when the input set is large — more chances for a small-chunk magnet to match a query token lexically.

**The fix: adaptive percentile floor.** Drop the bottom 30% of candidates by rrf BEFORE the cross-encoder sees them, with a hard `min_keep=8` floor so cold-start small kastens never lose recall.

**Why NOT a hard `rrf<0.10` floor:** absolute thresholds are corpus-dependent. A 7-zettel kasten may have all candidates below 0.10 on a cold-start query (BM25 + embedding both weak). Hard floor would empty the pool. Sources:
- BAAI/bge-reranker-base docs: "scores are NOT calibrated probabilities; do not use absolute thresholds"
- OpenAI Cookbook on cross-encoder reranking: "use percentile cuts, not absolute scores"

**Class-conditional floors (mirrors pre-existing droplet `RAG_CONTEXT_FLOOR_*` convention):**
- `RAG_RERANK_INPUT_FLOOR_LOOKUP=0.30` (precision-critical)
- `RAG_RERANK_INPUT_FLOOR_THEMATIC=0.05` (broad recall)
- `RAG_RERANK_INPUT_FLOOR_DEFAULT=0.10` (multi_hop / step_back / vague)
- `RAG_RERANK_INPUT_MIN_KEEP=8` (cold-start protection floor)

**Algorithm:**
1. If `len(candidates) <= min_keep`: return as-is.
2. Apply absolute floor (drop candidates with rrf < class_floor).
3. If post-floor count < min_keep: fall back to percentile (keep top 70%, but no fewer than min_keep).
4. Else: also drop bottom 30% of those above the floor (densifies the rerank input).

**Cons NOT to take:**
- DO NOT use a single global floor — different classes have different precision/recall trade-offs.
- DO NOT use a fixed `keep_n` regardless of pool size — a 100-candidate pool and a 10-candidate pool have different distributions.
- DO NOT rerank on full pool "for safety" — that's the iter-09 status quo and it's expensive.

**Where this lands:** PLAN.md Phase 6 / Task 12.

---

## RES-7 — P11 auto-title pin to flash-lite

**Verdict: ✓ ship Phase 3.**

**Why:** auto-title is a 1-2 sentence summarization task. Gemini 2.5 flash-lite is plenty (Vertex docs Sep 2025 + Simon Willison Sep 2025 benchmarks). Today's auto-title runs through the key-pool with whatever default gen pool gives — which can be flash or pro depending on quota state. iter-09 timing report shows auto-title hit Pro rate-limit cascades.

**Mechanism:** add `RAG_AUTO_TITLE_MODEL=gemini-2.5-flash-lite` env. Inside `auto_title_session`, pass `starting_model=_AUTO_TITLE_MODEL` to the key-pool. The pool's existing fallback chain handles flash-lite quota exhaustion by walking to flash anyway, so this is fail-safe.

**Cons NOT to take:**
- DO NOT hardcode the model in code — env-driven so it's flippable in operations.
- DO NOT pin to flash (mid-tier) — flash-lite is sufficient and cheaper.

**Where this lands:** PLAN.md Phase 3 / Task 7.

---

## RES-8 — Item 3: zettel-type discriminator (chunk_count_quartile tie-breaker)

**Verdict: ✓ ship Phase 4.**

**The meta-problem:** when we fix one zettel-type failure (q10 LOOKUP+person+single-name surname), how do we NOT regress another (q5 THEMATIC+small-chunk magnet)?

**The discriminator:** add `chunk_count_quartile` as a **tie-breaker** (not a gate) in the final dedup-and-fuse sort. When two candidates have identical rrf_score, the class-conditional bias picks the better one:
- LOOKUP / VAGUE: prefer HIGHER quartile (chunky relevant zettels win ties)
- THEMATIC / MULTI_HOP / STEP_BACK: prefer LOWER quartile (broad coverage > deep monoculture)

**Why a tie-breaker, not a gate:**
- Gates change behavior abruptly at thresholds; tie-breakers nudge in the right direction without changing the overall ordering.
- Sub-floor bias (×0.0001) means it ONLY matters when rrf is exactly equal — no risk of overriding real score differences.

**The cross-class regression fixture (PLAN Task 9):** `tests/unit/rag/integration/test_class_x_source_matrix.py` replays a 6-query mini-suite spanning `{LOOKUP, THEMATIC, MULTI_HOP} × {youtube, github, newsletter, web}`. Any retrieval-stage change in Phases 4-6 that regresses a previously-passing intersection fails the test. This is the iter-10 mechanism for "fixing one type doesn't break another".

**Cons NOT to take:**
- DO NOT promote chunk_count_quartile from tie-breaker to gate — that's a behavior change, not a discriminator.
- DO NOT add MORE discriminator signals in iter-10 (e.g., `has_author_metadata`, `content_kind`) — one at a time, with regression fixture, per HetaRAG (2024) heterogeneous-corpus principle.

**Where this lands:** PLAN.md Phase 4 / Task 9.

---

## RES-9 — P6 gold@1 score audit + P8 RSS observability + P12 chunk_share/THEMATIC empty logging + Per-stage timing + CI grep guard

**Verdict: ✓ ship Phase 1 (P6) + Phase 8 (rest).**

**Why grouped:** these are all observability / drift-prevention items. None change RAG behavior; all surface signal we currently lack.

- **P6:** scores.md mis-reported gold@1 in iter-09 (0.5714 vs 0.6429 in verification_results.json). Cause: the within_budget filter silently AND'd into the gold count. Fix: emit BOTH `gold_at_1_unconditional` and `gold_at_1_within_budget` in scores.md.
- **P8:** RSS pre/post-slot log line. Catches OOM-precursor patterns under burst. iter-09 droplet logs showed 2 worker SIGKILLs at 780MB/1GB swap thrashing — we want this in the access path so it's visible without pulling cgroup logs.
- **P12:** chunk_share TTL hits/misses + RPC errors + THEMATIC empty-counts warning. Necessary to root-cause q5 500 (still HOLD per iter-09 — logs were unrecoverable due to deploy restart). Iter-10 logs will survive the next 500 if it recurs.
- **Per-stage timing:** `t_retrieval_ms`, `t_rerank_ms`, `t_synth_ms` in response payload + log. Required input for iter-11 mid-flight latency abort design.
- **CI grep guard:** scans `website/api/*.py` for `@router.post`-decorated functions that call `runtime.orchestrator.answer` (directly or via helper) without a nearby `acquire_rerank_slot`. Catches the iter-04..iter-09 silent-drift class.

**Cons NOT to take:**
- DO NOT add OpenTelemetry traces in iter-10 — too much surface area; iter-11+.
- DO NOT log Gemini API call latencies — they're already captured by the key-pool observability.

**Where this lands:** PLAN.md Phase 1 / Task 5 (P6); Phase 8 / Tasks 14-17.

---

## RES-10 — P13 clause-coverage self-check in SYSTEM_PROMPT

**Verdict: ✓ ship Phase 7.**

**Why:** iter-09 RAGAS `answer_relevancy=74.29` vs `faithfulness=87.50` — model is faithful but doesn't fully address every clause of multi-part questions. This is "synthesizer over-refusal" iter-08 noted but never addressed.

**Mechanism:** append a `COVERAGE CHECK` block to SYSTEM_PROMPT instructing the model to:
1. Identify each distinct sub-question/clause.
2. Confirm each is addressed OR explicitly state which clauses are uncovered.
3. Don't invent — say "the available sources don't address <clause>" briefly.

**Cons NOT to take:**
- DO NOT use a separate clause-checker LLM call — adds latency + cost; the in-prompt rule is enough.
- DO NOT make the rule recursive ("check that you checked that you...") — Gemini gets stuck in self-reference loops.

**Where this lands:** PLAN.md Phase 7 / Task 13.

---

## RES-11 — Items 6 + 7 deferred to iter-11 (with iter-10 cheap mitigations)

**Verdict: ✗ defer iter-11. Iter-10 ships LOGGING-only mitigations.**

**Item 6 — admission middleware refactor:**
- Per-route guards drift. iter-09 fixed exactly this drift on `_run_answer` (unwrapped for 5 iters).
- Defer reason: auth-ordering risk (Starlette `BaseHTTPMiddleware` runs BEFORE auth dependency resolves; current per-route guard correctly runs AFTER auth). Getting middleware ordering wrong could cause 401-bypassed requests to acquire slots.
- iter-10 mitigation: CI grep guard (Task 16) catches drift WITHOUT a refactor.

**Item 7 — per-query mid-flight latency abort:**
- Slow query holds slot beyond budget under multi-user load.
- Defer reason: asyncio TaskGroup cancellation edges (CPython #94398 + #116720 still open). BGE int8 inference threads can leak under cancel. Gemini API calls don't propagate cancellation cleanly from httpx.
- iter-10 mitigation: per-stage timestamp instrumentation (Task 17) gives iter-11 the data to design abort points where they're SAFE.

**Cons NOT to take:**
- DO NOT ship a half-baked mid-flight abort in iter-10 — leaks > savings.
- DO NOT ship the middleware refactor in iter-10 — auth-ordering footgun.

---

## Already-merged context (background for executor)

| Commit | Subject | Status |
|---|---|---|
| `ee31c85` | fix: ndcg dedupe reranked + clamp instead of assert | Already pushed in iter-09 final push. |
| `f098383` | ops: dump GUNICORN RAG EVAL ROUTER env in log workflow | Pre-iter-10 prep; pushed. |

iter-09 shipped: SSE harness reader (with the t0 bug — fixed in iter-10 P1), warm-up ping, log-pull workflow inputs, chat_messages verdict CHECK v2 migration, anchor-seed RPC + injection (with re-gate bug — fixed in iter-10 P4), router rule-5 narrowing + 3 new rules + LRU cache, unsupported_with_gold_skip retry gate, class-conditional chunk-share, `_run_answer` admission wire fix.

iter-10 verified droplet env (run 25330459384):
- `GUNICORN_TIMEOUT=240` (>=180 satisfies CLAUDE.md guardrail D)
- `GUNICORN_WORKERS=2` ✓
- `RAG_CONTEXT_FLOOR_LOOKUP=0.30`, `RAG_CONTEXT_FLOOR_SYNTH=0.05`, `RAG_CONTEXT_MIN_KEEP_LOOKUP=1`, `RAG_CONTEXT_MIN_KEEP_SYNTH=5` (P9 mirrors this naming convention)

---

## Quick-reference: env flags introduced or modified by iter-10

| Flag | Default | Phase / Task | Purpose |
|---|---|---|---|
| `RAG_AUTO_TITLE_MODEL` | `gemini-2.5-flash-lite` | 3 / 7 | P11 auto-title model pin |
| `RAG_ANCHOR_SEED_MIN_ENTITY_LENGTH` | `4` | 2 / 6 | P4 mitigation 2 — short-entity floor |
| `RAG_ANCHOR_SEED_TOP_K` | `3` | 2 / 6 | P4 mitigation 3 — seed cap |
| `RAG_RERANK_INPUT_FLOOR_ENABLED` | `true` | 6 / 12 | P9 master switch |
| `RAG_RERANK_INPUT_FLOOR_LOOKUP` | `0.30` | 6 / 12 | P9 LOOKUP class floor |
| `RAG_RERANK_INPUT_FLOOR_THEMATIC` | `0.05` | 6 / 12 | P9 THEMATIC class floor |
| `RAG_RERANK_INPUT_FLOOR_DEFAULT` | `0.10` | 6 / 12 | P9 multi_hop / step_back / vague floor |
| `RAG_RERANK_INPUT_MIN_KEEP` | `8` | 6 / 12 | P9 cold-start protection |
| `RAG_SCORE_RANK_DEMOTE_FACTOR` | `0.85` | 5 / 11 | P3 magnet damp |
| `RAG_SCORE_RANK_DISPROP_QUARTILES` | `1.0` | 5 / 11 | P3 trigger threshold |
| `RAG_TITLE_OVERLAP_DEMOTE_FACTOR` | `0.95` | 5 / 11 | P3 secondary damp |
| `RAG_TITLE_OVERLAP_DEMOTE_FLOOR` | `0.10` | 5 / 11 | P3 trigger threshold |
| `RAG_DENSE_FALLBACK_ENABLED` | `true` | 4 / 10 | P5 fallback master switch |
| `RAG_SLOT_RSS_LOG_ENABLED` | `true` | 8 / 14 | P8 observability |
| `RAG_SCOUT_LOG_USED_CANDIDATES` | `false` | 0 / 2 | Phase-0 scout (TEMPORARY — remove after Task 2) |

---

## Quick-reference: Supabase migrations introduced by iter-10

| File | Phase / Task | Purpose | Risk |
|---|---|---|---|
| `2026-05-04_rag_dense_recall.sql` | 4 / 10 (gated on scout) | RPC `rag_dense_recall(p_user_id, p_effective_nodes, p_query_embedding, p_limit)` returning best chunks scoped to kasten members for the recall fallback | low (read-only, additive). Same JOIN pattern as iter-09's `rag_fetch_anchor_seeds`. |

Apply via the `apply_iter08_migrations.py`-style pattern (idempotent, BEGIN/COMMIT-wrapped).

---

## Success criteria (the "all queries pass + multi-user safe" bar)

iter-10 final eval MUST hit ALL of:

| Metric | Target | Source |
|---|---|---|
| Composite | ≥ 85 | Approved by user |
| gold@1_unconditional | ≥ 0.85 | Approved by user |
| gold@1_within_budget | ≥ 0.85 | Approved by user |
| within_budget (alone) | ≥ 0.85 | Implicit from above |
| Burst 503 rate | ≥ 0.08 | iter-04 admission target (already achieved 0.50 in iter-09; must hold) |
| Burst 502 rate | 0% | Multi-user safety |
| Per-query failures (q1-q14, q9 excluded as adversarial) | 0 | All queries pass |
| Worker OOM events during eval | 0 | Multi-user safety |

If any one of these fails, iter-10 is incomplete and iter-11 carries the remainder.
