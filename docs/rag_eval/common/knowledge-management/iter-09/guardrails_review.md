# Iter-10 Guardrails Review — should we revisit any "do-not-touch" knob?

Captured 2026-05-04. Author: planning agent (research-only, no code changes).
Decision frame: **default to HOLD**. CLAUDE.md "blind mitigation" rule applies — guardrails encode multi-iter rationale; reverting requires logs in hand + explicit user approval.

Sources cross-referenced:
- `CLAUDE.md` Critical Infra Decision Guardrails
- `docs/rag_eval/common/knowledge-management/iter-{04..09}/{PLAN,RESEARCH,scores,verification_results}.{md,json}`
- `iter-09/prior_attempts_knowledge_base.md` (Agent A iter-by-iter changelog)
- `iter-09/iter09_failure_deepdive.md` (Agent B per-query forensics)
- `iter-09/iter10_solutions_research.md` (Agent C iter-10 punch list)
- Current implementation: `run.py`, `ops/docker-compose.{blue,green}.yml`, `ops/deploy/deploy.sh`, `ops/caddy/upstream.snippet` (via deploy.sh), `website/api/_concurrency.py`, `website/api/chat_routes.py`, `website/features/rag_pipeline/{orchestrator,rerank/cascade,query/router}.py`

---

## Section 1 — Audit table

| ID | Guardrail | Current state (verified) | Last verified iter | Evidence supporting NO CHANGE | Counter-evidence | Verdict |
|---|---|---|---|---|---|---|
| **A** | `GUNICORN_WORKERS=2` | `run.py:35` default `"2"`; not overridden in compose | iter-09 (deepdive Hyp 3, OOM logs) | (1) Phase 1A int8 quantization sized for 2-worker viability via COW + `--preload`. (2) Iter-09 OOM events occurred even at 2 workers — dropping to 1 worker would be a reflex revert that doesn't address root cause (auto-title slot leak) | iter-09 deepdive S2: 2 workers OOM'd mid-eval (pid 16 SIGKILL 05:02:20, pid 284 05:06:13). RSS pressure real | **HOLD** |
| **B** | `--preload` (gunicorn fork-share for BGE int8) | `run.py:36` hardcoded | iter-03 Phase 1A | ~110 MB COW saving is the only thing keeping 2 workers under cgroup ceiling 1600m. Disabling re-explodes RAM | None | **HOLD** |
| **C** | `FP32_VERIFY` top-3 only | `cascade.py:89` env `RAG_FP32_VERIFY="on"`; `cascade.py:389` `k=3` hardcoded | iter-03 Phase 1A.5 | int8 cascade memory budget; top-3 verifier absorbs int8 outliers without full fp32 re-score | None — eval shows BGE int8 produces sensible rerank when input pool is healthy (q2/q3/q11/q13/q14 rerank ≥66) | **HOLD** |
| **D** | `GUNICORN_TIMEOUT >= 180s` | `run.py:38` default **`"90"`**; deploy.sh comment claims 180s but no env override found in repo | last *claimed* iter-03; **never verified post-iter-04** | Caddy upstream `read_timeout 240s` is the outer fence; gunicorn timeout only matters if a request actually exceeds it | **DRIFT.** `latency_ms_server` in iter-09 is 1.0–1.7s, never approaches 90s. Functional behavior is unaffected — but the documented rationale ("180s minimum for Strong/Pro multi-hop synth") and the actual default disagree. Current default `90` would prematurely kill a true 91-180s synth | **REVISIT** (observability + alignment, not a behavior change) |
| **E** | Rerank semaphore + bounded queue (`RAG_QUEUE_MAX=3`) | `_concurrency.py` + `chat_routes.py:177,256`; compose sets `RAG_QUEUE_MAX=3, RAG_RERANK_CONCURRENCY=2` | iter-09 RES-4 (admission wire fix shipped) | Burst probe 503 rate hit 0.50 in iter-09 — **target ≥0.08 met first time across all iters**. Cleanest WIN of iter-09 | None | **HOLD** |
| **F** | SSE heartbeat wrapper | `chat_routes.py:201` `SSE_HEARTBEAT_INTERVAL_SECONDS=10.0`; line 226 keepalive in stream loop | iter-03 Phase 1B.4 | Cloudflare 502 prevention on idle SSE connections. Iter-09 502 rate is 0.25 (3/12) but those occurred during burst OOM, not on idle-SSE — heartbeat is doing its job | None | **HOLD** |
| **G** | Caddy `read_timeout 240s` upstream | `deploy/deploy.sh:354-357` writes `transport http { read_timeout 240s … }` | iter-03 Phase 1B / iter-04 max_conns_per_host | Strong/Pro multi-hop synth can take 60-120s; 240s upstream window is the outer fence | None | **HOLD** |
| **H** | Schema-drift gate | `ops/scripts/apply_migrations.py` present | iter-03 Phase 1C.5 | Verdict-allowlist migration v2 (iter-08 → iter-09) applied cleanly. Gate prevented silent INSERT-fail contamination of `record_hit` data | None | **HOLD** |
| **I** | `kg_users` allowlist gate | `deploy.sh:135-164` — gated by env `DEPLOY_ALLOWLIST_GATE=1` | iter-03 Phase 2D.2 | Cross-tenant safety. Iter-09 RES-7 anchor-seed RPC explicitly INNER JOINs `rag_sandbox_members` → leaning on the same tenancy invariant. Removing this gate would invalidate the q10 anchor-seed safety story | None | **HOLD** |
| **J** | Teal default; amber only on `/knowledge-graph` | UI guardrail — verified in iter-09 verification_results.json color audit (passed=true on `/`) | iter-09 | Brand consistency. No color regressions detected | None | **HOLD** |
| **K** | BGE int8 cross-encoder (do not swap to ms-marco-MiniLM) | `cascade.py:85-86` int8 path; eager-load at module import | iter-03 Phase 1A | Reranker swap = multi-iter project: re-quantize, re-tune 4 threshold floors, re-run iter-04..09 fixtures, RAM measurement. Iter-10 has cleaner wins (P1 harness fix, P2 auto-title) | iter-09 rerank score 57.14 still **-20** below iter-05 peak 77.86. BGE-vs-magnet drag IS a real pain point. But Agent C (P9) explicitly recommends defer; **keep reranker, add pre-rerank quality gate** instead | **HOLD** |
| **L** | Router structural changes (RES-6 option c — tag-based author detection) | Not implemented; deferred | iter-09 RES-6 | iter-09 RES-6 narrowed rule-5 (18→25) + 3 new rules + LRU cache + ROUTER_VERSION=v3. Routing now correct on iter-09 fixture. Tag-author detection adds router LLM call cost. | iter-09 q7 ("Anything about commencement?") + q14 (Matuschak surname-only) miss is partly NER recall; tag-author matching could help. But Agent C P10 explicitly says "no iter-10 router change" | **HOLD** |
| **M** | Magnet penalty at rerank stage (RES-3 deferred) | Not implemented | iter-09 RES-3 | Class-gated chunk-share (RES-2) shipped iter-09; rerank-stage penalty would double-discount with chunk-share. RES-3 deferred unless chunk-share fails. **It is failing on q5** (small-chunk magnet `gh-zk-org-zk` wins THEMATIC top-1 — chunk-share doesn't damp small-chunk magnets) | **q5 magnet IS unsolved.** Agent C P3 recommends a *different* fix (semantic-relevance gate at xQuAD slot 1, anchor-seed tightening) — NOT reviving rerank-stage penalty. So the guardrail's specific deferral remains correct | **HOLD** (but the broader q5 magnet is iter-10 P3, addressed via different path) |
| **N** | Threshold floors: `_PARTIAL_NO_RETRY_FLOOR=0.5`, `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR=0.7`, `_RETRY_TOP_SCORE_FLOOR=0.10`, `_REFUSAL_SEMANTIC_GATE_FLOOR=0.5` | All present in `orchestrator.py:67-99`, env-overridable | iter-09 RES-1 (gold-skip floor was 0.7) | Each is calibrated on iter-04..09 fixtures. Changing without an A/B replay risks silent regressions across past iters. Iter-10 should not move them | None | **HOLD** |
| **O** | q5 500 speculative fix (HOLD until logs) | No fix shipped; `q5_500_traceback.txt` exists but content unrecoverable | iter-09 | CLAUDE.md "blind mitigation" rule explicit. Agent C P12 recommends only logging, not a fix | iter-09 q5 still 500-ing with THEMATIC + new RPCs in path. But pushing a speculative fix without traceback violates CLAUDE.md | **HOLD** (ship iter-10 §3a logging instead) |
| **P** | Admission middleware refactor (RES-4 iter-11+) | Not implemented; per-route `acquire_rerank_slot()` pattern shipped iter-09 | iter-09 RES-4 | Admission wire is now correct on both stream + non-stream paths; refactoring to ASGI middleware is durable but not critical-path. Mis-ordering auth → admission would be a single-knob risk. | None | **HOLD** |

**Counts:** 14 HOLD / 1 REVISIT / 0 CHANGE PROPOSED. (Total 16 — D + multiple HOLDs include observability sub-recommendations.)

---

## Section 2 — Per-guardrail deep dive (REVISIT only)

### D — `GUNICORN_TIMEOUT` documentation/default drift

**Why it was put in place originally:** CLAUDE.md and iter-03 Phase 1B reasoned: *"180s minimum for Strong/Pro multi-hop synth"*. `deploy/deploy.sh:342` carries the comment `Must be >= GUNICORN_TIMEOUT (180s) for sane semantics`.

**What's changed since:** `run.py:38` default is `"90"`. `ops/.env.example`, compose YAMLs, and `deploy.sh` env_file (`/opt/zettelkasten/compose/.env`) do not set `GUNICORN_TIMEOUT` in the repo. Either the droplet `.env` overrides to 180+ (not visible in repo — would need droplet inspection) OR the actual deployed timeout is 90s and has been since iter-03. Iter-09 `latency_ms_server` is 1.0-1.7s for all 14 queries, so the gap has never been exercised in production data.

**Proposed change:** **Observability + alignment, NOT a behavior change.**
1. Iter-10 — read `/opt/zettelkasten/compose/.env` on droplet (operator action, no code) and confirm whether `GUNICORN_TIMEOUT` is set. If absent, the actual timeout is 90s.
2. If the actual is 90s, either:
   - (a) explicitly set `GUNICORN_TIMEOUT=180` in `compose/.env` to match documented intent, OR
   - (b) update CLAUDE.md to reflect the observed working value (90s is sufficient given current synth latencies).
3. Either way, add a single `_logger.info("[gunicorn] timeout=%ds workers=%d", t, w)` startup line so future drift surfaces.

**Risk if we change it (option a → 180s):** None. Outer Caddy fence is 240s, so a 90→180 bump is safely inside that envelope. Workers that hang already get killed by Caddy upstream-503 path.

**Risk if we don't:** Low. No production data shows a synth taking 90+ seconds. The drift is documentation hygiene, not a live failure mode.

**Falsifiable A/B test plan:** Not needed — this is purely an operational alignment task. If the operator confirms `compose/.env` has `GUNICORN_TIMEOUT=180`, the documentation is correct; close the item. If not, choose (a) or (b) and ship the one-liner change with a CLAUDE.md note.

---

## Section 3 — The two FOR-CERTAIN ship-this-iter items

### 3a. Structured logging around `chunk_share` TTL + `_ensure_member_coverage` THEMATIC empty-counts path (iter-09 RES-7 + Agent C P12 — the q5 500 mystery)

**Goal:** next time q5 (or any THEMATIC query touching the new RPCs) 500s, the traceback is in droplet stdout — not lost to container restart as in iter-09.

**Files + exact log lines to add:**

1. `website/features/rag_pipeline/retrieval/chunk_share.py`

   - At the top of the function that calls `rag_kasten_chunk_counts` RPC (cache miss branch):
     `_logger.info("[chunk_share] cache miss kasten=%s ttl_age=%ds fetching counts", kasten_id, age)`
   - Immediately after the RPC returns (success):
     `_logger.info("[chunk_share] rpc_ok kasten=%s n_nodes=%d median=%.2f", kasten_id, len(counts), median)`
   - Inside the `except` block of the RPC call (currently silent except-return-empty):
     `_logger.exception("[chunk_share] rpc_fail kasten=%s — proceeding without damp", kasten_id)`

2. `website/features/rag_pipeline/retrieval/hybrid.py` — `_ensure_member_coverage` (THEMATIC empty-counts path):

   - Before the empty-counts early return:
     `_logger.warning("[member_coverage] empty kasten=%s class=%s n_pool=%d — skipping coverage backfill", kasten_id, query_class, len(pool))`
   - When backfill IS attempted:
     `_logger.info("[member_coverage] backfill kasten=%s class=%s missing=%d", kasten_id, query_class, len(missing))`

3. `website/api/chat_routes.py` `_run_answer` — bracket the slot:

   - At line 177 (just before `async with acquire_rerank_slot()`):
     `t_slot_acquire = time.perf_counter()`
   - At line 184/185 (just after `await _post_answer_side_effects(...)` exits):
     `_logger.info("[slot] held=%.3fs side_effects_started=%.3fs", time.perf_counter() - t_slot_acquire, t_side_start - t_slot_acquire)`
     (where `t_side_start` is captured between orchestrator.answer return and side_effects await — single new local variable)

**How iter-10 eval will use them:**

- After eval run, grep droplet logs for `[chunk_share] rpc_fail` — directly answers "did q5's 500 come from the chunk_count RPC?".
- `[member_coverage] empty` lines correlate THEMATIC failures with the empty-counts code path (Agent C / Agent B both flagged this branch).
- `[slot] held=` quantifies Hyp 1 (auto-title slot leak) — once iter-10 §3b P2 ships, this number drops dramatically; the log is the verification gate.
- All three lines are read by the iter-10 `score_rag_eval.py` extension to populate a new "infra_diagnostics" block in scores.md.

**LOC budget:** ~12 LOC across 3 files. Zero behavior change. Zero deploy risk.

### 3b. iter-10 ship-list (which P-items land in iter-10 vs deferred)

User explicit framing: *"Other changes approved! Lets make most of the changes, not just top-6; unless there's a strong reason not to"*. Verdict per item:

| P# | Item | iter-10? | Rationale |
|---|---|:-:|---|
| P1 | Harness `t0`-subtract fix (3 LOC, harness only) | **SHIP** | Pre-approved. Single biggest composite lift (Agent C: 65→80). Zero production touch. |
| P2 | `_post_answer_side_effects` outside `acquire_rerank_slot` (asyncio.create_task) | **SHIP** | Pre-approved. RES-5 explicitly flagged for iter-10. ~20-40 LOC with exception-isolation + logging. |
| P3 | q5 magnet — anchor-seed tighten + xQuAD slot-1 semantic gate | **RESEARCH FIRST → iter10_followup_research.md** | Multi-knob, medium-risk (~50 LOC). Cross-encoder semantic gate threshold (0.3) is unverified; needs A/B against iter-09 fixtures. Touches retrieval + rerank — needs Phase 0 scout to print actual rerank scores for q5 before threshold pick. |
| P4 | Drop entity-count re-gate in anchor-seed inject (3 LOC) | **RESEARCH FIRST → iter10_followup_research.md** | Looks like 3-LOC fix but inverts a tenancy-adjacent gate. Need to verify (a) `entity_anchor.py` resolution already filters by member-scope, (b) no NER backstop is lost. 30-min research, then ship. |
| P5 | q6/q7 dense fallback when recall@8 misses kasten golden-set | **SHIP** with Phase 0 scout gate | Pre-approved by user. Ship behind a single `RAG_KASTEN_GOLDEN_FALLBACK_ENABLED` flag (default off), gate on Phase 0 scout printing q6/q7 actual `used_candidates`. If scout confirms pool is genuinely empty post-rerank, enable. |
| P6 | gold@1 score-audit (separate "unconditional" from "within-budget") | **SHIP** | Pre-approved. Pure scorer change in `ops/scripts/score_rag_eval.py`. Zero production touch. Removes iter-08→iter-09 metric drift (0.5714 vs 0.6429). |
| P7 | Within-budget rate (artifact of P1) | **AUTO-RESOLVES** with P1 | No code; verification step in iter-10 Phase 1. |
| P8 | Burst RSS observability (~10 LOC pre/post slot RSS log) | **SHIP** | Pre-approved. Pure log additions. Pairs with §3a `[slot] held=` line above. Zero behavior change. |
| P9 | Reranker swap (BGE int8 → ms-marco-MiniLM) | **DEFER iter-11+** | Multi-iter project; threshold re-tune across 4 floors; RAM measurement on droplet; replay all fixtures. Agent C P9 explicitly defers. Iter-10 alternative: candidate-quality gate pre-rerank (see P3 research). |
| P10 | Router rule changes | **NO CHANGE iter-10** | iter-09 RES-6 narrow + LRU cache shipped; classifications correct on iter-09 fixture. Tag-author detection (RES-6 option c) deferred to iter-11+. |
| P11 | Auto-title flash-lite pin (1 LOC config) | **RESEARCH FIRST → iter10_followup_research.md** | Looks like 1 LOC. But (a) need to verify flash-lite is in the key-pool's allowed model list, (b) verify auto-title quality on 5 sample sessions, (c) confirm flash-lite quota headroom. 20-min research, then ship. |
| P12 | Logging around chunk_share TTL + `_ensure_member_coverage` empty-counts | **SHIP** | This section's §3a item. ~12 LOC observability. |
| P13 | Self-check clause-coverage prompt addition | **SHIP** | Pre-approved. Prompt change in `generation/prompts.py` (~30 LOC + 1 RAGAS re-eval). Targets answer_relevancy 74.29 → ~85+. |
| P14 | Admission middleware refactor | **DEFER iter-11+** | Per-route guards correct now; refactor risk > value. Agent C P14 explicit defer. |

**Iter-10 ship count: 8 items (P1, P2, P5*, P6, P8, P12, P13, plus the 3a logging which IS P12).**
**Research-first count (in iter10_followup_research.md): 4 items (P3, P4, P11, plus P5 Phase 0 scout).**
**Defer to iter-11+: 3 items (P9, P10, P14).**

(* P5 ships *behind a flag* with a Phase 0 scout gate before enabling.)

---

## Section 4 — Summary

- **Guardrails surveyed:** 16 (A through P).
- **Verdicts:** 15 HOLD / 1 REVISIT / 0 CHANGE PROPOSED.
- **Most surprising finding:** `GUNICORN_TIMEOUT` documented as "≥180s minimum" in CLAUDE.md and `deploy/deploy.sh` comment, but the actual default in `run.py:38` is **90s** and the repo doesn't override it. Either the droplet `.env` quietly sets it, or the documented invariant has been stale since iter-03. Resolution is operational hygiene (read droplet env, then either set to 180 or update CLAUDE.md), not a behavior change.
- **Most important guardrail to keep locked:** **E (rerank semaphore + `RAG_QUEUE_MAX=3`)**. iter-09 RES-4 admission wire fix produced the cleanest single WIN of the program (503 rate 0% → 50%, target ≥0.08 met first time). Touching this regresses burst correctness immediately.
- **Iter-10 P-items definitely shipping:** **8** (P1, P2, P5 behind flag + scout, P6, P8, P12 = §3a logging, P13). 4 to research-first (P3, P4, P11, P5 scout). 3 deferred to iter-11+ (P9, P10, P14).
- **Approvals still required from user before iter-10 PLAN.md author starts:**
  1. Confirm REVISIT on **D** (operator: read `/opt/zettelkasten/compose/.env` for `GUNICORN_TIMEOUT`; choose alignment direction).
  2. Approve P5 ship-behind-flag with Phase 0 scout gate (vs holding until research completes).
  3. Approve sending P3, P4, P11 to a separate `iter10_followup_research.md` rather than blocking iter-10 on them.
