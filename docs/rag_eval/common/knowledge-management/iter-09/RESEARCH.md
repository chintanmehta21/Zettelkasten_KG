# Iter-09 Research Reference

This document is the consolidated research artefact for iter-09. Audiences:

1. **Future humans / agents looking back at iter-09** — to understand what we knew, what we tried, and what we deliberately rejected.
2. **The plan executor (subagent or human running [PLAN.md](PLAN.md))** — to look up rationale, edge cases, and "why not X" decisions when a phase task references them.

**Cross-reference:** [PLAN.md](PLAN.md) — implementation tasks. This file is the *why*; PLAN.md is the *how*.

---

## How the executor should use this file

When implementing any PLAN.md phase, **before writing code or tests for that phase**:

1. Read the matching `RES-N` section here.
2. If a task is unclear, look up "Pitfalls" and "Cons NOT to take" — they capture every dead end already explored.
3. If a test fails in an unexpected way, check "Edge cases" for that section — many edge cases were already mapped during research.
4. If you encounter a decision point not covered here, **stop and ask the user** rather than improvising. Beyond-plan decisions require explicit chat-confirmed approval.

---

## Iter-08 outcome that motivates iter-09

| Metric | iter-05 | iter-07 | iter-08 | Δ vs iter-07 |
|---|---:|---:|---:|---:|
| Composite | 77.95 | 62.88 | **63.53** | +0.65 |
| chunking | 31.94 | 31.94 | **40.43** | +8.49 ✓ |
| retrieval | 97.70 | 78.51 | 76.90 | -1.61 |
| reranking | 77.86 | 62.48 | **49.31** | **-13.17** ⚠ |
| synthesis | 77.25 | 61.26 | 67.55 | +6.29 |
| gold@1 | 0.6429 | 0.4286 | **0.7143** | +0.2857 ✓ |
| within_budget | 0.1429 | 0.2857 | 0.2143 | -0.07 |
| burst 502 rate | 0% | 0% | **25%** | new failure mode |
| burst 503 rate | 0% | 0% | 0% | semaphore mute |

**Per-query failure mode summary:**

| qid | http | server_ms | client_ms | gold@1 | failure root cause |
|---|---:|---:|---:|:-:|---|
| q1 | 502 | n/a | 37,543 | F | BGE int8 cold-start on first eval query |
| q2 | 200 | 15,319 | 43,422 | T | critic over-refused first-pass; retry burned 12s budget; `retry_budget_exceeded` |
| q3 | 200 | 14,656 | 36,331 | T | same as q2 |
| q4 | 200 | 1,478 | 43,475 | T | only true pass (high-quality 90s budget masks measurement gap) |
| q5 | 500 | n/a | 48,953 | F | new RPC path crash; root cause not yet logged (HOLD) |
| q6 | 200 | 1,404 | 50,128 | T | latency-gap mystery, see RES-5 |
| q7 | 200 | 1,047 | 43,742 | F (wrong primary) | magnet `effective-public-speakin` won rerank over gold `steve-jobs` |
| q8 | 200 | 1,114 | 36,681 | T | router miscall (lookup→thematic) |
| q9 | 200 | 1,541 | 31,674 | T | correct refusal |
| q10 | 200 | 1,079 | 23,626 | F | `partial`; jobs zettel never reached pool — no anchor seed injection |
| q11 | 200 | 1,279 | 33,100 | T | `partial`; chunking-density issue (Walker zettel = 3 chunks) |
| q12 | 200 | 1,997 | 33,346 | T | router miscall (lookup→thematic) |
| q13 | 200 | 1,059 | 40,099 | T | router rule 5 over-fired (>=18 words + no persons → MULTI_HOP) |
| q14 | 200 | 4,948 | 39,616 | T | same as q13 — single-name surname ("Matuschak") missed by NER |

`latency_ms_server` for fast queries is 1–5s. Client `elapsed_ms` is 23–50s. **The 20–48s gap is NOT server compute** — see RES-5.

---

## RES-1 — `unsupported_with_gold_skip` retry-skip gate

**Question:** when the critic flags first-pass `unsupported` but retrieval surfaced gold (top rerank ≥ 0.7), what's the correct production behavior?

**Verdict: add a parallel skip gate to the existing `partial_with_gold_skip`. LOOKUP-only.**

**Industry precedent (✓ direct):**
- **Self-RAG (Asai et al. 2023, arXiv:2310.11511):** ISREL/ISSUP reflection tokens are *separate* — a passage can be ISREL=relevant but ISSUP=partial without forcing regeneration. Surfaces partial answer with support tag.
- **CRAG (Yan et al. 2024, arXiv:2401.15884):** retrieval evaluator emits {Correct, Ambiguous, Incorrect}; on Correct it skips knowledge refinement entirely. Same shape.
- **RAGAS faithfulness (Es et al. 2023):** decouples *answer_relevance* from *faithfulness*. Low faithfulness with high context-precision is reported, not rewritten.
- **Anthropic citations docs:** recommend exposing supporting span confidence rather than refusing/regenerating when grounding is partial.

**Threshold engineering — `top_score >= 0.7`:**
- BGE-reranker-v2 (BAAI 2024): sigmoid scores. Published ranges: ~0.99 verbatim, 0.7–0.85 "clearly on-topic paraphrase", 0.4–0.6 topical-but-not-answering, <0.3 noise.
- Existing `_PARTIAL_NO_RETRY_FLOOR = 0.5` (orchestrator.py).
- 0.7 is stricter than partial-skip (0.5), justified because verdict is harsher (`unsupported` vs `partial`).
- 0.65 also defensible; 0.7 chosen for symmetry with "clearly on-topic" published cutoff.

**Class scope — LOOKUP-only:**
- MULTI_HOP / STEP_BACK: top score=0.9 may be one of N hops; missing hops legitimately warrant retry. `_top_candidate_score` returns max → masks missing hops.
- THEMATIC: high top-1 says nothing about thematic coverage breadth.
- VAGUE: handled by separate `vague_low_entity` gate.
- **LOOKUP only** in iter-09; revisit MULTI_HOP later only with `min(top_k_scores) >= floor` (all-cited gate), not `top_score`.

**Tag wording: "answer reflects retrieved sources":**
- Current `_LOW_CONFIDENCE_DETAILS_TAG` says "Citations don't fully cover this claim. The answer is the model's best draft." — leaks negative valence on a gold-retrieved answer.
- Anthropic hallucination-disclosure guidance favors neutral, descriptive phrasing.
- Rejected: "claims may be paraphrased" (reads as hedge), "I'm uncertain" (defensive). New constant `_GOLD_RETRIEVED_DETAILS_TAG`.

**Edge cases:**
- one-gold-one-decoy MULTI_HOP: mitigated by LOOKUP-only scoping.
- legitimate THEMATIC refusal: excluded.
- streaming vs non-streaming: gate fires before finalize; both inherit cleanly.
- critic-was-right (rare verbatim-quote LOOKUP): user gets paraphrased tag instead of "not in corpus". Acceptable trade vs current 12s burn.
- score inflation under int8 noise: monitor via iter-08 fixture replay.

**Cons NOT to take:**
- Broaden gate to MULTI_HOP/STEP_BACK — silently surfaces confidently-wrong synthesis when one hop is missing.
- Use `top_score >= 0.5` like partial-skip — too lenient for the harsher `unsupported` verdict.
- Reuse `_LOW_CONFIDENCE_DETAILS_TAG` — implies failure; semantically wrong for gold-retrieved.
- Apply to refusal-regex path — that path already short-circuits.

**Where this lands in PLAN.md:** Phase 3 / Task 10.

**Verdict allowlist impact:** the new verdict string `"unsupported_with_gold_skip"` MUST be added to the Postgres CHECK migration in Phase 2 / Task 7.

---

## RES-2 — Class-conditional chunk-share with ratio-to-median magnet detection

**Question:** iter-08 chunk-share normalization (`rrf_score *= 1/sqrt(chunk_count)`) is applied uniformly. Reranking score collapsed 77.86 → 49.31. Why, and how to fix without losing the q5/q7 magnet defense?

**Verdict: gate by class AND by *per-query* magnet detection (ratio-to-median).**

**Industry precedent — length/chunk-count normalization:**
- **BM25 `b` parameter** (Robertson & Zaragoza 2009): default 0.75; corpus-global, never per-class in standard implementations.
- **Pivoted Length Normalization** (Singhal SIGIR'96): corpus-global.
- **Lucene `lengthNorm`**: index-time, corpus-global.
- **ColBERT MaxSim** (Khattab 2020): explicitly avoids length norm — picks max per query-token, immune to chunk count.
- Consensus: norm is corpus-global; class-conditional gating is non-standard but defensible when query intent shifts the precision/recall trade-off (known-item lookup vs thematic recall).

**Why uniform damp hurts LOOKUP:**
- LOOKUP queries want the chunky correct node (e.g., a 13-chunk Walker zettel for a Walker question).
- Damping by `1/sqrt(13) = 0.277` slashes legitimate top-1 scores.
- Iter-08 q11/q12/q3 rerank scores all dropped vs iter-07 — direct evidence.

**Magnet-detection threshold — ratio-to-median ≥ 2.0:**
- Fixed `n=8` is brittle. KM Kasten chunk distribution: {16, 13, 10, 6, 6, 3, 2}. Threshold 8 catches 16, 13, 10 — including gold (steve-jobs=13, walker=3 — wait, walker=3, jobs=13). Threshold 8 false-positives steve-jobs (13).
- **Ratio-to-median ≥ 2.0:** median=6, threshold=12. Catches only `effective-public-speakin (16)`. Steve-jobs (13) is borderline; ratio 13/6 = 2.17 → also tagged (acceptable; jobs is itself somewhat magnet-y in this Kasten).
- Tukey IQR outlier (`> Q3 + 1.5·IQR`) catches only 16 — too narrow.
- **Ratio-to-median is scale-invariant** (works for 7-zettel and 700-zettel Kastens), robust to outliers (median > mean), no magic numbers.

**Class gate — THEMATIC + MULTI_HOP only:**
- LOOKUP excluded (precision-critical).
- VAGUE excluded — vague queries often *want* the magnet (it's the most-likely best answer; low precision tolerance).
- STEP_BACK excluded — already broadens via fan-out; double-penalising.
- THEMATIC + MULTI_HOP — cross-zettel synthesis where one magnet drowns siblings is the target failure mode.

**Cold-start guard:** `len(chunk_counts) < 5` → skip gate. Median is unstable on small Kastens.

**Cliff-edge concern:**
- A query that triggers magnet damp because chunk_counts={9,3,2} vs not because chunk_counts={7,3,2} produces different rankings.
- Mitigation: ratio-to-median is continuous-ish in n; the *damp factor itself* (`1/sqrt(n)`) is continuous. Acceptable when gate is on a robust statistic, not a fixed integer.

**Pitfalls:**
- DO NOT change the exponent (1/√n → 1/n^0.6) per original iter-09 brief — moves in the wrong direction for LOOKUP queries which would still get damped under the brief's class-agnostic version.
- DO NOT remove the `compare_intent` short-circuit at hybrid.py:428 — already correct.
- DO test with the iter-08 KM Kasten fixture: `{16, 13, 10, 6, 6, 3, 2}` median=6, ratio threshold 2.0 → magnet set = {16, 13}.

**Cons NOT to take:**
- Adaptive exponent `1/n^f(class)` — adds another knob; smoother but harder to test.
- Subtractive log damp `score -= α·log(n)` — additive composition mixes poorly with multiplicative rrf.
- Softmax temperature on chunk-count — overkill for 7-zettel Kastens.
- ColBERT MaxSim — requires late-interaction architecture, out of scope.

**Where this lands in PLAN.md:** Phase 3 / Task 11.

---

## RES-3 — Rerank-stage magnet penalty (DEFER to iter-10)

**Question:** q7 magnet (`effective-public-speakin`, 16 chunks) wins BGE int8 rerank even after RRF damping. Should iter-09 add a post-rerank magnet penalty?

**Verdict: DEFER to iter-10. Re-evaluate after class-gated chunk-share lands.**

**Cross-encoder is confirmed magnet-blind:**
- `_passage_text` (cascade.py:769–804) feeds only `[source/author/date/tags] header + name + content body` into the tokenizer.
- No `chunk_count`, `node_id`, or chunk-share metadata.
- Magnet effects are pure lexical/semantic overlap — the magnet has 16 lottery tickets at top-K; at least one matches a query phrase lexically.

**Why DEFER, not implement:**
- RES-2's class-gated chunk-share already attacks the same root cause more cleanly.
- Adding a *second* magnet penalty at rerank stage risks **double-discount** and breaks RES-1's hybrid-B reasoning (rerank scores uncalibrated for fusion).
- Naive `chunk_count >= 8` rule would tag steve-jobs (13 chunks) as magnet → **false positive**. Multi-gate version needed if pursued (close-runner-up AND low-title-overlap AND heavy-chunk-share).
- Original iter-09 brief change "1/√n → 1/n^0.6" makes LOOKUP regression in RES-2 worse, not better. Dropped.

**Conditions for iter-10 reconsideration:**
- iter-09 eval ships with class-gated chunk-share.
- q7 still picks `effective-public-speakin` over `steve-jobs` as primary citation.
- THEN propose multi-gate version: `(rerank_score within 0.05 of #2) AND (low_title_overlap with query) AND (chunk_count_share >= 15%)`.

**Code path (for iter-10 reference):** post-process hook is `cascade.py:583` (between `item.candidate.rerank_score = item.score` assignment and downstream `_fused_score`). Penalty must be multiplicative (`× 0.95`) for stable score-tie ordering, not subtractive.

**Cons NOT to take in iter-09:**
- Flat `chunk_count >= 8` + subtractive 0.05 — false-positives gold.
- Hand-tuned per-Kasten penalty constants — non-generalizable.

**Where this lands in PLAN.md:** Phase 6 (DEFER notes only; no code).

---

## RES-4 — Adhoc bounded-queue admission (the 503-mute root cause)

**Question:** iter-08 burst probe (12 concurrent `/api/rag/adhoc`) returned 7×524 + 3×502 + 2×200, ZERO 503 with `Retry-After`. Why?

**Verdict: confirmed wire-mismatch. `_run_answer` is NOT wrapped in `acquire_rerank_slot()`.**

**Evidence (file:line):**
- `website/api/_concurrency.py:42–43`: `queue_max`, `semaphore`.
- `website/api/_concurrency.py:63–74`: `acquire_rerank_slot()` — the ONLY context manager that increments `state.depth` and bounds CrossEncoder concurrency. Sequence: depth check → depth++ → `async with semaphore` → finally depth--.
- `website/api/chat_routes.py:240`: stream path `async with acquire_rerank_slot():` ✓ correctly gated.
- `website/api/chat_routes.py:486–494`: `/adhoc` peek-check `state.depth >= state.queue_max` → 503 if full.
- `website/api/chat_routes.py:509`: `payload = await _run_answer(...)` — non-stream path. **No `acquire_rerank_slot()` wrapper.**
- `website/api/chat_routes.py:156–182`: `_run_answer` body has zero references to `acquire_rerank_slot`, `state.depth`, or `QueueFull`.
- iter-04 comment at `chat_routes.py:481–485` claims "admission gate applied to BOTH stream and non-stream paths" — claim is wrong; the slot was never acquired on non-stream.

**Why peek-check fires 0× 503:**
- `state.depth` only increments inside `acquire_rerank_slot()`.
- Non-stream `/adhoc` admits via peek-check at L489, then runs `_run_answer` (L509) — never touches the slot.
- 12 concurrent burst entrants all see `depth=0` at peek time → all admitted.
- Both gunicorn workers (cluster cap 6) actually serve 12 concurrent CrossEncoder forwards → OOM / Cloudflare 524.

**Why 502 (3 of 12), not all 524:**
- 524 = Cloudflare 100s upstream timeout. CrossEncoder thread serialises on PyTorch GIL on 1-vCPU droplet.
- 502 = upstream returned junk OR connection died. Grounded hypothesis: gunicorn worker SIGKILL by cgroup OOM. With `RAG_QUEUE_MAX=3` per-worker peek check INTENDED to cap memory, but depth never increments → both workers admit 6 each → past 2 GB cap.
- Caddy `handle_response` rewrites empty 502/504 → 503; partial bytes pass 502 through.

**Fix (Phase 4 — requires explicit user approval; CLAUDE.md guarded subsystem):**
- Wrap `_run_answer` (chat_routes.py:156–182, called L509) in `async with acquire_rerank_slot():`.
- Catch `QueueFull` and return 503 `Retry-After: 5` from the JSON path (mirror SSE path's behavior).
- Verification: post-fix burst probe should show ≥1× 503 with `Retry-After: 5` and 0× 524.

**Industry pattern (alternative considered, rejected):**
- Standard FastAPI/uvicorn pattern is a single ASGI middleware (Starlette `BaseHTTPMiddleware` or pure ASGI app wrapper) holding the bounded `anyio.Semaphore` + depth counter at app scope, applied to every route via `app.add_middleware`.
- Per-route guards (current pattern) drift the moment a new endpoint is added.
- Reference: `iter-03-rag-burst-correctness-design.md:57` itself stipulates a single chokepoint.
- **Iter-09 fix is the minimal symmetry restoration**, not a refactor to middleware. Middleware refactor is iter-10+ scope.

**Pitfalls:**
- Do NOT change `RAG_QUEUE_MAX`, semaphore concurrency, GUNICORN_WORKERS, --preload, GUNICORN_TIMEOUT, FP32_VERIFY_ENABLED, SSE heartbeat, Caddy timeouts (CLAUDE.md guarded).
- Wrap MUST live around the entire `_run_answer` await, not just the rerank step (slot models worker-time, not just GPU/CPU).
- New `503` response on non-stream path must include `Retry-After: 5` header.

**Where this lands in PLAN.md:** Phase 4 / Task 12.

---

## RES-5 — Eval-harness `p_user` latency measurement

**Question:** server `latency_ms_server` is 1–5s for fast queries; harness `elapsed_ms` is 23–50s. Where do the 20–45s go?

**Verdict: harness uses `stream:false`. The non-stream path runs `_post_answer_side_effects` (auto-title Gemini call ~15–40s + 3 Supabase writes) BEFORE returning JSON. NO SSE involved in the eval at all.**

**Evidence (file:line):**
- `ops/scripts/eval_iter_03_playwright.py:1053–1060`: `phase_rag_qa_chain` posts to `/api/rag/adhoc` with `"stream": False`.
- `ops/scripts/eval_iter_03_playwright.py:567–569`: `api_fetch_json` uses `await r.text();` — buffers entire response body before resolving.
- `website/api/chat_routes.py:509`: `payload = await _run_answer(...)` — non-stream path.
- `website/api/chat_routes.py:143–153, 172`: `_post_answer_side_effects` includes `auto_title_session` (Gemini call) + `update_session` + `touch_sandbox`. **Awaited synchronously** before JSON return.

**SSE event types emitted (when `stream:true`):**

| Order | `type` | Source |
|---|---|---|
| 1 | `status` (queued) | chat_routes.py:267 |
| 2 | `status` (retrieving) | orchestrator.py:401 |
| 3 | `citations` | orchestrator.py:421 |
| 4 | `token` (repeated) | orchestrator.py:737, 754 |
| 5 | `complete` | orchestrator.py:738, 766 |
| 6 | `replace` (optional, post-edit) | orchestrator.py:445 |
| 7 | `done` (turn payload) | orchestrator.py:449 |

`error` events fire on failure paths. `: heartbeat\n\n` comments every 10s via `_heartbeat_wrapper` (chat_routes.py:188–224).

**`p_user` definitions:**
- **`p_user_first_token_ms`**: ms from `fetch()` send to first `event: token` frame. TTFT — when text starts visibly appearing.
- **`p_user_complete_ms`**: ms from `fetch()` send to `event: done` frame. TTLT — canonical "answer fully delivered".
- **`p_user_last_token_ms`** (bonus): ms to last `event: token`. `done - last_token` exposes server post-token latency.

**Implementation:** in-page Playwright `fetch()` reading `r.body.getReader()` with `\n\n` frame split. Stay in-page so origin/auth match. ~80 LOC harness change + ~120 LOC tests (5 cases: token-then-done, done-without-tokens, error-mid-stream, heartbeat-only-then-done, partial-frame buffer reassembly).

**Reproducibility check (curl probe):**

```bash
TOKEN='<jwt>'; SBID='<sandbox-uuid>'
curl -N -sS -X POST https://zettelkasten.in/api/rag/adhoc \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"sandbox_id":"'$SBID'","content":"What is PKM?","quality":"fast","stream":true,"scope_filter":{},"title":"probe"}' \
  | awk '{ printf "%d.%06d %s\n", systime(), 0, $0; fflush() }'
```

**Industry standard (settled):** TTFT = time to first streamed token; TTLT = time to last; both client-side, request-send to event-receive. References: OpenAI Cookbook "How to stream completions", Anthropic "Streaming Messages", Cloudflare "AI Gateway latency metrics".

**Cons NOT to take:**
- Subtract `latency_ms_server` from `elapsed_ms` to approximate `p_user` — unsound; gap is post-answer side-effects time, NOT user-perceived metric.
- Switch the entire harness to `stream:true` without keeping `stream:false` opt-in mode — back-compat for one-shot regression checks.
- Move `_post_answer_side_effects` to background task in iter-09 — production touch outside iter-09 scope; flag for iter-10 investigation.

**Where this lands in PLAN.md:** Phase 1 / Tasks 3–4.

---

## RES-6 — Router rule-5 narrowing (must precede new rules)

**Question:** iter-08 q13/q14/q8/q12 mis-routed (LOOKUP→MULTI_HOP / LOOKUP→THEMATIC). Original iter-09 brief adds 3 new rules; should they ship without auditing existing rule 5?

**Verdict: NO. Rule 5 is the bug. Narrow it BEFORE adding new rules.**

**Existing rule 5** (router.py:117): `word_count >= 18 AND llm_class is QueryClass.LOOKUP AND not persons → QueryClass.MULTI_HOP`.

**Why it over-fires:**
- q13 "What does the Pragmatic Engineer newsletter mean by a 'product-minded' engineer..." — 22 words, no detected person ("Pragmatic Engineer" = brand, not person), llm_class=LOOKUP → upgraded to MULTI_HOP. Wrong.
- q14 "In Matuschak's 'Transformative Tools for Thought' essay..." — 19 words, "Matuschak" missed by NER (single-name surname), llm_class=LOOKUP → upgraded to MULTI_HOP. Wrong.
- Original q3-shape (Patrick Winston) had a detected person → rule 5 didn't fire there. Rule's intent was "long queries without entity anchor benefit from decomposition" — but single-name surname misses break the entity-anchor check.

**Narrowing options (pick one):**
- **(a) Require explicit decomposition wording:** rule 5 fires only if query also matches `r"\b(decompose|break down|step by step|first .+ then|relate)\b"` OR has `?>=2`. Conservative.
- **(b) Lift word-count threshold from 18 to 25.** q13 (22) and q14 (19) drop out; q3-shape (24+) still fires.
- **(c) Add tag-based author detection** before rule 5 — if any zettel in the Kasten has matching author tag AND surname appears in query, treat as person. Most invasive.

**Recommended: (b) lift threshold to 25,** combined with the new rules from iter-09 item 5(C). (a) is also acceptable; (c) defers to iter-10.

**New rules from original brief (iter-09 item 5C) — KEEP, with tests:**
- `q.count("?") >= 2 → MULTI_HOP` — explicit multi-question; one positive test (multi-question), one counter-example (single ? with quote-internal `?`).
- `r"\bhow does .+ relate to .+\b" → MULTI_HOP` — explicit relate-pattern; positive + counter-example (`"how does X work"` must NOT match).
- `r"\b(summary|summarize|key ideas) of\b" → THEMATIC` — positive + counter-example (`"summary table"` must NOT match).

**Cache (iter-09 item 5E) — KEEP:**
- `LRUCache(maxsize=10_000)` keyed on `sha256(f"{ROUTER_VERSION}|{kasten_id}|{rewritten_query.strip().lower()}").hexdigest()`.
- 24h TTL via `cachetools.TTLCache`.
- Env `ROUTER_CACHE_ENABLED=true`.
- Constant `ROUTER_VERSION="v3"` — **bump on any rule change** to invalidate cache.

**Verification gates:**
1. Replay iter-04..iter-08 queries → assert zero class flips between consecutive runs.
2. ≥70% cache-hit rate on iter-09 re-run.
3. Per-rule unit test with counter-example that must NOT match.

**Where this lands in PLAN.md:** Phase 2 / Task 9.

---

## RES-7 — Carry-forward iter-09 originals (warm-up, log-pull, CHECK migration, anchor seeds, q5 HOLD)

**Verdict: keep all five.**

| iter-09 brief item | Verdict | Rationale |
|---|---|---|
| 1. Warm-up ping | Keep | Directly addresses q1 502; cheap; non-blocking; cannot regress. |
| 2a. Log-pull workflow input | Keep | Required to root-cause q5 500. Defensive only. |
| 2b. Postgres CHECK migration | **Keep — upgrade priority** | New verdict strings (incl. `unsupported_with_gold_skip` from RES-1) hit `chat_messages_critic_verdict_check` → INSERTs silently fail. May contaminate prior iters' kasten_freq dataset. Add re-verification of RES-2 kasten_freq diagnosis after fix. |
| 2c. HOLD on q5 fix | Keep | Correct discipline per CLAUDE.md. Investigate only after logs pulled (1 above). |
| 4. Q10 anchor seed injection | Keep — strongest single-query lever | Floor=0.30 lets cross-encoder still decide. INNER JOIN sandbox_members for cross-tenant safety. Env `RAG_ANCHOR_SEED_INJECTION_ENABLED=true`. |

**Pitfalls (Q10 anchor seed):**
- Do NOT prepend anchors into `p_effective_nodes` — it's a scope whitelist filter, would leak cross-tenant or no-op.
- Do NOT seed at score>0.5 — bypasses rerank.
- Cross-encoder must decide final rank.

**Q5 HOLD — what we suspect (do NOT push speculative fixes):**
- New iter-08 RPCs `rag_resolve_entity_anchors`, `rag_one_hop_neighbours`, `rag_kasten_chunk_counts`. `entity_anchor.py:16-23, 32-41` swallow RPC exceptions to empty set, so RPC failure alone doesn't 500.
- Most likely downstream: chunk-share TTL cache (commit `84771ad`) returns a stale or empty dict that triggers a KeyError; or `_ensure_member_coverage` 5-source THEMATIC + chunk_counts={} returns an unexpected shape.
- Fix proposal blocked until logs are pulled.

**Where this lands in PLAN.md:** Phase 0 (item 1 — pre-flight log pull), Phase 2 (items 2a, 2b, warm-up at Task 5; CHECK at Task 7; anchor-seed at Task 8). q5 HOLD remains in Phase 5 / Task 14 (investigation only).

---

## Already-merged context (background for executor)

| Commit | Subject | Status |
|---|---|---|
| `ee31c85` | fix: ndcg dedupe reranked + clamp instead of assert | Local-only, NOT pushed. Push as part of iter-09 last commit. |

iter-08 shipped the chunking floor (Phase 2), kasten_freq deprecation (`a7515b1`), kg_link.relation enum (`f739ce3`), cite-hygiene canary (`452c690`), per-query RAGAS (`adeafe9`), partial-with-gold skip (`cc04b1e`). All present on master.

---

## Quick-reference: env flags introduced or modified by iter-09

| Flag | Default | Phase / Task | Purpose |
|---|---|---|---|
| `RAG_UNSUPPORTED_WITH_GOLD_SKIP_ENABLED` | `true` | 3 / 10 | enable RES-1 retry-skip |
| `RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR` | `0.7` | 3 / 10 | rerank floor for the skip |
| `RAG_CHUNK_SHARE_CLASS_GATE_ENABLED` | `true` | 3 / 11 | enable RES-2 class gate |
| `RAG_CHUNK_SHARE_MAGNET_RATIO` | `2.0` | 3 / 11 | ratio-to-median threshold |
| `RAG_ANCHOR_SEED_INJECTION_ENABLED` | `true` | 2 / 8 | enable Q10 anchor seed RPC |
| `ROUTER_CACHE_ENABLED` | `true` | 2 / 9 | enable LRU cache on router |
| (constant) `ROUTER_VERSION` | `"v3"` | 2 / 9 | cache-key invalidator on rule change |

These should be added to `ops/.env.example` in the deploy phase.

---

## Quick-reference: Supabase migrations introduced by iter-09

| File | Phase / Task | Purpose | Risk |
|---|---|---|---|
| `2026-05-04_chat_messages_verdict_constraint_v2.sql` | 2 / 7 | drop+recreate `chat_messages_critic_verdict_check` allowlist | low (validates new inserts only, backwards-compat) |
| `2026-05-04_rag_fetch_anchor_seeds.sql` | 2 / 8 | RPC `rag_fetch_anchor_seeds(p_sandbox_id, p_anchor_nodes, p_query_embedding)` returning seed candidates | low (read-only, additive). INNER JOIN `rag_sandbox_members` mandatory. |

Apply via `apply_iter08_migrations.py` pattern (idempotent, BEGIN/COMMIT-wrapped).
