# iter-09 Failure Deep-Dive

Captured: 2026-05-04. Diagnosis only — no fixes proposed.

Sources cross-referenced:
- `docs/rag_eval/common/knowledge-management/iter-09/verification_results.json` (per-query observed)
- `docs/rag_eval/common/knowledge-management/iter-09/eval.json` (RAGAS / DeepEval)
- `docs/rag_eval/common/knowledge-management/iter-09/scores.md`
- `/tmp/eval_run_logs.txt` (droplet container + caddy + dmesg + free)
- `website/api/chat_routes.py`, `website/features/rag_pipeline/{orchestrator,retrieval/{hybrid,anchor_seed}}.py`

---

## Section 1 — Per-failed-query forensic table

Failed = `gold_at_1=False` OR pipeline error OR `unsupported_no_retry` with primary=None. Adversarial-negative q9 excluded.

### q1 — Network timeout dropped a working answer (gold_at_1=True but recorded as fail)

| Field | Value |
|---|---|
| Question | "Which programming language is the zk-org/zk command-line tool written in, and what file format does it use for notes?" |
| Expected primary | `gh-zk-org-zk` |
| Actual primary | `gh-zk-org-zk` |
| Critic verdict | partial |
| HTTP status | 200 |
| elapsed_ms (client) | 40,022 |
| latency_ms_server | 1,674 |
| p_user_first_token_ms | 40,274 |
| p_user_complete_ms | 43,007 |
| TTFT - server gap | ~38.6 s |
| Retrieved node ids (top 5) | nl-the-pragmatic-engineer-t, yt-programming-workflow-is, yt-programming-workflow-is, yt-effective-public-speakin, web-transformative-tools-for |
| Gold in retrieved? | yes (positions 7-8 of 8) |
| Magnet bias evidence | gh-zk-org-zk is BOTTOM of pool, but reranker still selected it as primary citation — magnet did NOT corrupt q1 |
| Router class | multi_hop |
| Rerank top-3 scores | retrieval=84.3 / rerank=0.0 (eval.json q1.component_breakdown) |

- **What failed:** No retrieval/synthesis failure — answer is correct. The user's "q1 timeout" claim is incorrect; q1 returned 200 OK with the right answer in 1.67 s server-side. The 38.6 s gap is **client-side wall** spent waiting for worker accept queue.
- **Step that broke:** infra (worker queueing), not pipeline. Falsely flagged "fail" because `within_budget=False` (40 s > 30 s budget).
- **Root cause hypothesis:** All 14 queries serialised through a single rerank slot (Hypothesis A), so q1 (the first long query) waits behind warmup_ping completion + worker cold-load. See Section 3 / Hyp A.
- **Falsifiable test:** Run iter-10 with `acquire_rerank_slot` scoping reduced to `orchestrator.answer` only (excluding `_post_answer_side_effects`); expect p_user_complete to drop from ~278 s avg to ~30 s avg.

### q5 — Magnet bias confirmed; primary swung from gold to gh-zk-org-zk

| Field | Value |
|---|---|
| Question | "Across these zettels, what is the implicit theory of how a knowledge worker should structure a day to do their best thinking? Cite at least four sources." |
| Expected primary | yt-programming-workflow-is, yt-steve-jobs-2005-stanford, web-transformative-tools-for, yt-matt-walker-sleep-depriv, nl-the-pragmatic-engineer-t |
| Actual primary | **gh-zk-org-zk** (NOT in expected set) |
| Critic verdict | partial |
| HTTP status | 200 |
| elapsed_ms | 49,872 |
| latency_ms_server | 1,275 |
| p_user_first_token_ms | 197,830 |
| p_user_complete_ms | 199,914 |
| TTFT - server gap | ~196.5 s queue wait |
| Retrieved node ids | nl-the-pragmatic-engineer-t, yt-effective-public-speakin, **gh-zk-org-zk**, yt-programming-workflow-is, yt-programming-workflow-is |
| Gold in retrieved? | partially (3/5 expected gold present; walker + jobs absent) |
| Magnet bias evidence | gh-zk-org-zk in pos 3, then chosen as primary — same pattern as q8/q12 (thematic class with gh-zk-org-zk recurring) |
| Router class | thematic |
| Rerank scores | retrieval=84.0 / rerank=40.9 (eval.json q5) |

- **What failed:** Primary citation flipped to a tool node that has nothing to do with the asked question; gold seeds (walker + jobs) never made the pool.
- **Step that broke:** retrieval (recall) + rerank tie-breaking.
- **Root cause hypothesis:** Anchor-seed RPC is NOT the cause for q5 (anchor-seed is gated to LOOKUP+entity OR compare_intent — q5 is THEMATIC; see `hybrid.py:266-282`). Real cause: thematic 5-source recall failure — the query lacks anchor entities, hybrid pool returns the dense-similarity-magnet `gh-zk-org-zk` because it is densely linked to many tags, then reranker has no contrastive signal because gold seeds (walker, jobs) were never retrieved.
- **Falsifiable test:** Run q5 with anchor-seed disabled (`ANCHOR_SEED_ENABLED=false`) → expect identical ranking (proves anchor-seed is NOT the cause). Then run with `MULTI_QUERY_N=5` (vs current 3) → expect walker/jobs to appear.

### q6 — primary=None despite gold retrieved

| Field | Value |
|---|---|
| Question | "The Matuschak essay calls for 'tools for thought.' Which other zettels in this Kasten describe tools, practices, or rituals that perform this same function — augmenting cognition rather than just storing information?" |
| Expected primary | web-transformative-tools-for, yt-effective-public-speakin, gh-zk-org-zk |
| Actual primary | **None** (citations=[]) |
| Critic verdict | unsupported_no_retry |
| HTTP status | 200 |
| elapsed_ms | 29,437 |
| latency_ms_server | 1,521 |
| p_user_first_token_ms | 230,180 |
| p_user_complete_ms | 232,363 |
| TTFT - server gap | ~228.7 s queue wait |
| Retrieved node ids | web-transformative-tools-for (only one; pool collapsed) |
| Gold in retrieved? | partial (1/3 expected) |
| Magnet bias evidence | inverse problem — gh-zk-org-zk and yt-effective-public-speakin both expected gold but ABSENT from pool |
| Router class | lookup (mis-classified — should be step_back/thematic) |
| Rerank scores | retrieval=73.3 / rerank=73.5 |

- **What failed:** Synth produced an answer with no `[id=...]` citation tokens for the body, so the citation extractor returned `[]`. Verdict gate then fired `unsupported_no_retry` because critic deemed the answer ungrounded → no retry burned.
- **Step that broke:** synth grounding (critic) + retrieval pool collapse.
- **Root cause hypothesis:** Router classified this multi-source step-back query as `lookup` (`scores.md` line 35: lookup=6 includes q6). LOOKUP path narrows the retrieval pool aggressively. Verify against `query/router.py` (rule-5 narrow at 18→25 words). The query is 35 words but the RES-1 `unsupported_with_gold_skip` only fires for `query_class is QueryClass.LOOKUP` — it short-circuits the retry that would have repaired the citation set.
- **Falsifiable test:** Force-classify q6 as THEMATIC; expect citations to be extracted from the multi-source draft.

### q7 — primary=None; refusal on vague single-token query

| Field | Value |
|---|---|
| Question | "Anything about commencement?" |
| Expected primary | yt-steve-jobs-2005-stanford |
| Actual primary | **None** |
| Critic verdict | unsupported_no_retry |
| HTTP status | 200 |
| elapsed_ms | 33,232 |
| latency_ms_server | 1,320 |
| p_user_first_token_ms | 266,041 |
| p_user_complete_ms | 268,604 |
| TTFT - server gap | ~264.7 s queue wait |
| Retrieved node ids | nl-the-pragmatic-engineer-t, yt-programming-workflow-is, web-transformative-tools-for, yt-effective-public-speakin, yt-effective-public-speakin |
| Gold in retrieved? | **NO** (yt-steve-jobs-2005-stanford absent from pool) |
| Magnet bias evidence | jobs node missing entirely; pool returned the same 4-node "magnet quintet" seen in q5/q8/q12 |
| Router class | thematic |
| Rerank scores | retrieval=0.0 / rerank=0.0 (eval.json q7) |

- **What failed:** Hard retrieval failure — gold node never reached rerank.
- **Step that broke:** retrieval (query rewriting / vague-expansion).
- **Root cause hypothesis:** Vague single-token "commencement" did not expand to "Stanford / Steve Jobs / graduation"; multi-query rewriter kept the literal keyword which doesn't appear in the jobs zettel transcript. The router classified as `thematic` (which fires the multi-query expansion), but rewrites missed the obvious entity. Same failure mode as iter-08 q7 — **iter-09 made no fix here.**
- **Falsifiable test:** Manually inspect the multi-query variants emitted for "Anything about commencement?" — expect they remain literal-token-bound.

### q10 — primary=None despite jobs node being a valid match

| Field | Value |
|---|---|
| Question | "Steve Jobs and Naval Ravikant both speak about meaningful work. Compare their views as covered in this Kasten." |
| Expected primary | yt-steve-jobs-2005-stanford |
| Actual primary | **None** |
| Critic verdict | unsupported_no_retry |
| HTTP status | 200 |
| elapsed_ms | 36,512 |
| latency_ms_server | 1,212 |
| p_user_first_token_ms | 372,220 |
| p_user_complete_ms | 373,653 |
| TTFT - server gap | ~371 s queue wait |
| Retrieved node ids | web-transformative-tools-for (only) |
| Gold in retrieved? | **NO** (yt-steve-jobs-2005-stanford absent — and Naval is correctly absent) |
| Magnet bias evidence | inverse — pool collapsed to 1 node and it was wrong |
| Router class | lookup |
| Rerank scores | retrieval=0.0 / rerank=0.0 |

- **What failed:** Anchor-seed was supposed to surface jobs node via `compare_intent + n_persons>=1`, but pool returned `web-transformative-tools-for` only.
- **Step that broke:** anchor-seed RPC OR FTS person-entity resolution.
- **Root cause hypothesis:** Two candidates:
  (a) `compare_intent` was NOT set on `query_metadata` for this query (q10 phrases compare via "both speak ... compare" — the intent-detection regex may not catch this). Without `compare_intent`, anchor-seed only fires when `query_class is LOOKUP and (n_persons + n_entities) >= 1`. Router classified as LOOKUP, so the gate hinges on `n_persons >= 1` — was "Steve Jobs" extracted as an author? Likely yes. So anchor-seed SHOULD have fired.
  (b) anchor-seed RPC fired but `rag_fetch_anchor_seeds` returned empty (silent except-return-[] in `anchor_seed.py:31-32`) — RPC may not exist, may return nothing for this kasten, or may have been rate-limited.
- **Falsifiable test:** Re-run q10 with `print(anchor_seeds)` instrumentation in `hybrid.py:282`; check Supabase logs for `rag_fetch_anchor_seeds` RPC calls during the eval window.

---

## Section 2 — Per-query stage breakdown (memory + time)

The droplet log dump does NOT contain per-stage timings (no `[stage]` / `[timing]` lines for retrieval/rerank/synth split). Only `[latency-budget]` totals at end-of-pipeline are present (`api/_latency_budget.py:46-60`). Memory snapshot is single-point (taken AFTER eval at 05:17:38, ~10 min after queries finished).

| qid | Total wall (ms) client | Server-reported (ms) | Queue gap (ms) | Retrieval (ms) | Rerank (ms) | Synth (ms) | Auto-title (ms) | Peak RSS (MB) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| q1  | 40,022  | 1,674 | 38,348  | ? | ? | ? | ? | ? |
| q2  | 28,687  | 1,342 | 27,345  | ? | ? | ? | ? | ? |
| q3  | 23,961  | 1,218 | 22,743  | ? | ? | ? | ? | ? |
| q4  | 42,344  | 1,679 | 40,665  | ? | ? | ? | ? | ? |
| q5  | 49,872  | 1,275 | 48,597  | ? | ? | ? | ? | ? |
| q6  | 29,437  | 1,521 | 27,916  | ? | ? | ? | ? | ? |
| q7  | 33,232  | 1,320 | 31,912  | ? | ? | ? | ? | ? |
| q8  | 34,163  | 1,200 | 32,963  | ? | ? | ? | ? | ? |
| q9  | 25,339  | (network err) | n/a | ? | ? | ? | ? | ? |
| q10 | 36,512  | 1,212 | 35,300  | ? | ? | ? | ? | ? |
| q11 | 31,824  | 1,342 | 30,482  | ? | ? | ? | ? | ? |
| q12 | 34,357  | 1,088 | 33,269  | ? | ? | ? | ? | ? |
| q13 | 37,095  | 1,350 | 35,745  | ? | ? | ? | ? | ? |
| q14 | 35,059  | 1,228 | 33,831  | ? | ? | ? | ? | ? |

**What this table shows even with gaps:**
- Server-reported `latency_ms_server` is consistently 1.0–1.7 s — the pipeline itself is FAST.
- Client wall is 23–50 s — the gap is **queue wait + auto-title-side-effects holding the rerank slot**.
- Cumulative `p_user_complete_ms` runs 43 s → 524 s across q1..q14 = monotonically rising → **proof of full serialization** (each query waits for the previous to release the slot, including the 5-30 s `auto_title_session` Gemini call wrapped inside `acquire_rerank_slot`).

**Logging gaps that block iter-10 diagnosis:**
1. `orchestrator.answer` does not emit per-stage timings (retrieval/rerank/synth/critic split). `[latency-budget]` only emits totals. Add stage-bracket `_logger.info("[stage] retrieval done elapsed=%.2f", t)` at 4 stages.
2. `_post_answer_side_effects` does not log entry/exit. Add `[stage] auto_title_done elapsed=...` so we can quantify exactly how much of the slot wall is the side-effects.
3. No request_id correlation between Caddy access log and app log — cannot tie a Caddy `duration` to an app `[latency-budget]`. Cf-Ray header is per-edge and not propagated into app logs.

**Memory evidence (single snapshot at 05:17:38, post-eval):**
- `Mem: 1.9Gi total / 1.1Gi used / 705Mi available`
- `Swap: 1.0Gi total / 780Mi used / 243Mi available` ← critical: heavy swapping during eval
- 1 active gunicorn worker visible (pid 213993, RSS 657 MB) at snapshot time. Earlier in eval there were 2 workers (pid 15, 16 at 04:51:44) but **pid 16 was SIGKILL'd at 05:02:20 (OOM)** and **pid 284 was SIGKILL'd at 05:06:13 (OOM)**. Net effect during the eval window: between 1 and 2 workers, with at least one OOM kill mid-run.

---

## Section 3 — Aggregate root-cause hypothesis (ranked by evidence strength)

### 1. Slot scope leak: `acquire_rerank_slot` wraps `_post_answer_side_effects` including `auto_title_session` (Gemini call), serializing the 14-query eval through a single in-flight slot

**Supported by:**
- `chat_routes.py:177-185` (verified) — `async with acquire_rerank_slot(): turn = await runtime.orchestrator.answer(...); await _post_answer_side_effects(...)`. The `await` chain holds the slot through both. `_post_answer_side_effects` (line 143-153) calls `runtime.sessions.auto_title_session(...)` which is a Gemini API call when `session.title == "New conversation"`.
- Eval probe creates a NEW session per query (`/adhoc` line 486-491 — `runtime.sessions.create_session` every call), so `title` is always the body.title default. If body.title is left null/`"New conversation"`, the Gemini auto-title call fires every query.
- Cumulative wall-clock arithmetic from per-query `p_user_complete_ms`: q1=43 s, q2=75 s (delta 32 s), q3=102 s (delta 27 s), ..., q14=524 s (delta 38 s). Inter-query deltas are ~22-43 s and remarkably uniform. This matches "each query holds the slot for orchestrator.answer (1.3 s) + auto-title (~20-30 s Gemini call) before next query can start".
- `latency_ms_server` reported as 1.0–1.7 s for ALL queries — proves orchestrator.answer is fast; the wall comes from elsewhere.
- 1 worker with RAG_QUEUE_MAX=3 means up to 3 concurrent slots, but eval was sequential so only 1 used. Slot serialization is 100% the bottleneck.

**Contradicted by:** Nothing in the logs contradicts this. The hypothesis fully explains TTFT≈TTLT (no streaming on `/adhoc` non-stream), p_user_avg=278 s (= 14 × ~20 s/query serialized + cold-start), and within_budget=0.07 (only q3 within 30 s).

**Falsifiable test:** Move `_post_answer_side_effects` outside the `acquire_rerank_slot` block in `chat_routes.py:179`. Re-run eval; expect avg p_user_complete to drop from 278 s to 30-40 s.

**File/line if hypothesis holds:** `website/api/chat_routes.py:177-185`.

### 2. Anchor-seed gating + magnet topology jointly cause primary-citation drift to `gh-zk-org-zk` for thematic queries

**Supported by:**
- `gh-zk-org-zk` is top-1 citation in 3/14 queries (q1, q5, q8) per `eval.json holistic.primary_citation_magnets`.
- For q5 and q12, the retrieved-pool head is the SAME 5-tuple `[nl-the-pragmatic-engineer-t, yt-effective-public-speakin, gh-zk-org-zk, yt-programming-workflow-is, yt-programming-workflow-is]` — proves the rerank/RRF fusion is producing identical pools across distinct thematic queries.
- `gh-zk-org-zk` README is dense, well-tagged, well-linked → it accumulates RRF score from many query variants (chunk_share gate `chunk_share.py` is class-conditional but doesn't appear to suppress this node).
- For q5 specifically, anchor-seed is gated OFF (THEMATIC class, no compare_intent), so anchor-seed CANNOT be the cause of q5's miss. The cause is base hybrid retrieval failing to surface walker/jobs.

**Contradicted by:**
- For q1 (LOOKUP-style multi_hop, gold=gh-zk-org-zk), the magnet correctly matched gold. So gh-zk-org-zk is not always wrong.
- Anchor-seed RPC `rag_fetch_anchor_seeds` is silent on failure (`anchor_seed.py:31-32`) — we have no evidence it's actively pulling gh-zk-org-zk into wrong pools (the user's framing in the task brief). It is more likely **NOT firing at all** for thematic queries (gated by `is_lookup or compare_intent`).

**Falsifiable test:** (a) Set `ANCHOR_SEED_ENABLED=false` and re-run — expect q5/q12 pools UNCHANGED (proves anchor-seed isn't the magnet driver). (b) Inspect the iter-08 retrieval pools for the same queries — if they also contain the magnet 5-tuple, the regression is older than iter-09 and chunk_share/anchor_seed is innocent.

**File/line if hypothesis holds:**
- For magnet topology (older issue): `website/features/rag_pipeline/retrieval/chunk_share.py` (class-conditional gate threshold).
- For anchor-seed false-positives if (a) shows changes: `website/features/rag_pipeline/retrieval/hybrid.py:266-282` and `anchor_seed.py:8-32`.

### 3. Worker OOM + swap thrashing inflated all elapsed times and ate at least one query

**Supported by:**
- Container log: `[2026-05-04 04:51:44] Booting worker pid:15, pid:16` then `[05:02:20] Worker (pid:16) was sent SIGKILL! Perhaps out of memory? ... Booting worker with pid: 284` then `[05:06:13] Worker (pid:284) was sent SIGKILL!`
- Eval ran 04:45–05:06 per timestamp metadata (`captured_at: 2026-05-04T05:06:51Z`), so **two workers OOM'd DURING the eval**.
- Free memory at snapshot: 1.9 GB total used 1.1 GB, swap 1.0 GB used 780 MB. Heavy swap.
- q9 reported `http_status: 0, error: TypeError: network error` — exactly what a client sees when the upstream worker is mid-restart.

**Contradicted by:**
- Most queries got 200 OK with valid (if slow) responses — the OOM was not catastrophic.
- `latency_ms_server` is consistent ~1.2–1.7 s — server-side pipeline did not show swap thrashing (which would 10x stage times).

**Falsifiable test:** Add a 1 GB swapfile + bump droplet to 4 GB; re-run eval. If `p_user_complete` improves by >50% AND q9 succeeds, OOM was a major contributor.

**File/line if hypothesis holds:** Infra (droplet sizing, swapfile config, gunicorn worker count) — NOT a code file. Touches the protected `GUNICORN_WORKERS` knob in `CLAUDE.md` Critical Infra Decision Guardrails — DO NOT silently revert; pull logs and ask first.

### Pre-seeded hypothesis verifications

**A (slot scope leak):** **CONFIRMED.** See Hyp 1.

**B (anchor-seed pulling magnet):** **REFUTED for the queries cited.** Anchor-seed only fires for LOOKUP+entity or compare_intent — q5 (THEMATIC, no compare) cannot trigger it. q12 (THEMATIC) cannot trigger it. q8 (THEMATIC, no anchor entity) cannot trigger it. The magnet drift in q5/q8/q12 is a pre-existing chunk_share/RRF-fusion issue, not iter-09 anchor-seed. q10 (LOOKUP, person entity = Jobs) IS a candidate for anchor-seed firing — and yet the pool returned only `web-transformative-tools-for`, suggesting the RPC silently returned [] (anchor_seed.py:31-32).

**C (q1 timeout):** **REFUTED as a timeout.** q1 returned 200 in 40 s with a correct answer (`primary_citation: gh-zk-org-zk`, gold_at_1=True). The "fail" in `verification_results.json` is the within_budget check (40 s > 30 s budget), not a timeout. The user's framing was wrong.

**D (`unsupported_with_gold_skip` swapping a partial draft):** **PARTIALLY CONFIRMED.** Fired exactly 1 time (q3). q3's answer was: *"I can't find that in your Zettels. <details>Answer reflects retrieved sources; some details may be paraphrased rather than quoted verbatim.</details>"* — this is NOT a useful answer. The gold node `yt-effective-public-speakin` was top-1 retrieved (rerank=100), so the verdict gate fired correctly per spec, but the SYNTH still produced a literal refusal because it couldn't extract the "verbal punctuation" term verbatim. The skip-retry was correct (would not have improved); the synth grounding is the upstream bug.

**E (router cache stale class):** **NO EVIDENCE EITHER WAY.** No router-cache log lines in `/tmp/eval_run_logs.txt`. ROUTER_VERSION="v3" should have invalidated the cache, but we cannot verify hit/miss rates without instrumentation. q7 is mis-classified as THEMATIC (probably should be VAGUE) and q6 as LOOKUP (should be step_back/THEMATIC) — these are router rule errors, not cache errors. **Iter-10 needs router classify hit/miss logging to close this gap.**

---

## Section 4 — Things that ACTUALLY worked in iter-09

| Surface | iter-08 | iter-09 | Verdict |
|---|---:|---:|---|
| chunking score | 40.43 | 40.43 | flat — no regression |
| retrieval score | 76.90 | 97.08 | **+20.18 — biggest win** |
| reranking score | 49.31 | 57.14 | +7.83 — partial recovery |
| synthesis score | 60.30 (est) | 56.85 | -3.45 — small dip |
| composite | 63.53 | 65.32 | +1.79 |
| burst 503 rate | 0% | 50% | **admission gate is now firing on /adhoc non-stream — RES-4 worked** |
| burst 502 rate | n/a | 25% | regressed (3/12 hit Cloudflare 502 — need per-bucket investigation) |
| Verdict allowlist (Postgres CHECK) | n/a | 1 unsupported_with_gold_skip persisted | gate-7 schema migration shipped cleanly |
| Router rule-5 narrow | q13/q14 mis-class | q13 multi_hop, q14 multi_hop | **q13 NOT lookup (rule-5 narrowed too much?) — verify next iter** |
| q14 retrieval | regressed iter-08 | 220.0 (capped) — top-4 all `web-transformative-tools-for` | gold-magnet recall (q14 = the gold zettel itself) — iter-09 actually works perfectly here |

**Note on q13:** queries.json says `class: lookup`, but eval.json reports `query_class: multi_hop`. Rule-5 narrowing may have *over-corrected* — q13 is a single-source newsletter lookup but got promoted to multi_hop. Did not regress score (q13 retrieval=140, gold_at_1=True), so non-blocking, but flagging for iter-10 router-classify audit.

---

## Required iter-10 instrumentation (before any fix proposals)

1. `_logger.info("[stage] %s elapsed=%.3fs", stage, t)` at 4 boundaries in `orchestrator.answer`: post-retrieval, post-rerank, post-synth, post-critic.
2. `_logger.info("[slot] held=%.3fs side_effects=%.3fs", t_slot, t_side)` in `chat_routes.py:_run_answer` to quantify Hyp 1.
3. `_logger.info("[router] cache_hit=%s class=%s", hit, cls)` in `query/router.py` `classify()` to verify Hyp E.
4. `_logger.info("[anchor_seed] rpc_n=%d rpc_returned=%d", len(anchor_nodes), len(anchor_seeds))` after `hybrid.py:282` to verify Hyp 2 q10 path.
5. Propagate Cf-Ray (or generate a request_id) into app logs so Caddy `duration` correlates with `[latency-budget]`.
