# RUN-ME: Iter-03 Prod Memory-Bounded — Engine Handoff

**Read this entire file before doing anything else. It is the only thing the running engine needs to know.**

You are the executor. Your job is to mechanically execute the plan at `docs/superpowers/plans/2026-04-28-iter-03-prod-memory-bounded.md` against this repository (the Zettelkasten production system). The plan is paired with the design at `docs/superpowers/specs/2026-04-28-iter-03-prod-memory-bounded-design.md` — read both before you start.

You do NOT need to invent anything. Every diff, file path, test, and commit message is in the plan.

---

## Context (one paragraph)

Production runs on a 2 GB / 1 vCPU DigitalOcean droplet. The cgroup-confined containers were hard-capped at 1024m / 1024m (zero swap budget) — kernel cgroup-OOM was killing gunicorn workers mid-`/api/rag/adhoc`, surfacing as 502s from Caddy. Live droplet log evidence: `Worker (pid:14) was sent SIGKILL! Perhaps out of memory?`. Real-world smoke run produced 2/3 502s with q1@14s and q3@6s failing while q2@26s succeeded — pattern consistent with worker death not Caddy timeout. iter-03 quantization is doing its job (idle RSS ~531 Mi) but inference-time peak demand exceeds the 1 GB cgroup ceiling. The plan applies nine targeted, independently revertable changes to bound peak RSS within a 1300m / 2300m cgroup envelope while preserving every protected iter-03 knob.

---

## Critical constraints (DO NOT VIOLATE)

These are codified in `CLAUDE.md` "Critical Infra Decision Guardrails" and "When to ask vs when to keep moving". The user has been bitten by past sessions silently undoing these. You will be too if you try.

1. **`GUNICORN_WORKERS=2` STAYS.** Do not drop to 1. Quantization is the entire reason 2 fits.
2. **`--preload` STAYS.** Workers inherit master via COW; without preload they re-pay each model.
3. **Int8 cascade STAYS.** Phase 1A is settled.
4. **`RAG_FP32_VERIFY=on` is LAST RESORT.** This rollout sets `RAG_FP32_VERIFY=off` as the steady-state default. If the post-deploy eval shows quality regression, **DO NOT FLIP fp32 BACK ON FIRST**. Triage in the order specified in spec §3 / plan Phase 11.3 Step 3 (verify regression is real → inspect critic verdicts → inspect retrieval recall → try non-fp32 fixes: re-arena on int8 only, bump stage-1 candidate count, retune per-class margins, retune score calibration). Only after 1-4 fail to recover do you escalate to the user before any fp32 flip.
5. **Phase 1B rerank semaphore + bounded queue + 503 backpressure STAYS.**
6. **Phase 1B.4 SSE heartbeat wrapper STAYS.**
7. **Caddy 240s upstream timeouts STAY.**
8. **Schema-drift gate + kg_users allowlist gate STAY.**
9. **Palette: TEAL on Kasten surfaces; AMBER ONLY on `/knowledge-graph`. NEVER purple/violet/lavender.**
10. **No silent infra reverts.** If logs/eval reveal a problem you cannot solve without touching items 1-9, STOP and ask the user before pushing.

---

## How to ask vs. keep moving (per CLAUDE.md "When to ask vs when to keep moving")

**Skip questions** when:
- You're inside this locked execution loop where every step is mechanical.
- In dashboard-only progress reporting.

**Ask the user** when:
- Any change with production blast-radius would deviate from the plan.
- A test fails in a way the plan didn't anticipate.
- A file's actual content does not match the plan's "current state" snippet.
- You're tempted to touch any of the 10 protected knobs above.
- The eval gate fails after deploy.

---

## Pre-flight (run before Phase 0)

1. Confirm you're on a clean working tree:
   ```bash
   git status --short
   git log --oneline -3
   ```
2. Confirm CLAUDE.md is the latest version (auto-mirrored to `AGENTS.md` for Codex):
   ```bash
   grep -q "Critical Infra Decision Guardrails" CLAUDE.md || echo "STOP — CLAUDE.md guardrails missing"
   ```
3. Confirm the spec + plan + helper docs exist:
   ```bash
   ls docs/superpowers/specs/2026-04-28-iter-03-prod-memory-bounded-design.md
   ls docs/superpowers/plans/2026-04-28-iter-03-prod-memory-bounded.md
   ls docs/runbooks/droplet_swapfile.md
   ls ops/scripts/eval_iter_03_playwright.py
   ```
   All four must exist. If any is missing, STOP — the branch is not ready.

---

## Execution recipe (the only thing you do)

For each task in the plan, in order:

1. **Read the task header** (Files, Test paths).
2. **Smart-explore the file you're about to touch** (`smart_outline` / `smart_search`).
3. **Execute every step in the task as written** — every code block is verbatim, every command is exact.
4. **Run the verification commands shown** under each step. If a command's expected output does not match, STOP and re-read the step. Do not improvise.
5. **Commit with the exact message shown** at the end of the task. No `Co-Authored-By` trailers, no AI/tool names in the message body.
6. **Mark the task done** in your TodoWrite (or equivalent).
7. **Move to the next task.**

There are 22 tasks across Phases 0-12. Total budget: ~5-7 hours of execution time excluding the 24h observation window in Phase 12.2.

---

## What to do when something deviates

| Situation | Action |
|---|---|
| Test passes when the plan says it must fail | STOP. Re-read step. The plan expected the helper not to exist yet. |
| Test fails when the plan says it must pass | Re-read your edit; common cause is a typo in the test or the implementation. Fix and re-run. Do NOT change the plan. |
| `git ls-files <path>` shows file does not exist where the plan says "Modify" | STOP. Plan is out of sync with repo. Tell the user; do not invent. |
| Phase 11.3 acceptance gate fails | Follow the §3 triage order. Do NOT flip fp32. Escalate to user after Triage steps 1-4. |
| Cgroup verification in Phase 11.2 Step 4 returns wrong values | STOP. Compose limits did not apply. Confirm the deploy ran (`gh run list --branch master --limit 1`), confirm the runbook ran (`ssh deploy@<droplet> swapon --show`), then escalate. |
| You hit `Worker SIGKILL` again post-deploy | Pull `[proc_stats]` log lines via `gh workflow run read_recent_logs.yml`. If `cgroup_swap_current` was 0 when it died, the swap is not reaching the cgroup — re-verify `memory.swap.max`. If swap was being used, the threshold guard's 90% is too high — escalate to user before lowering. |

---

## When you're done

After Phase 11.3 lands green:

1. Phase 12.1 (squash) — purely git history hygiene; no behavior change.
2. Phase 12.2 (24h observation) — operator-driven; you may schedule a `/loop` or simply note the start time and ask the user.
3. Final summary: post the eval scorecard (`docs/rag_eval/common/knowledge-management/iter-03/scores.md`) summary back to the user, with the 3-way iter-01 / iter-02 / iter-03 numbers.

You're done. Do not start a new iteration without a new spec.

---

## Files this rollout will create or modify

**Created** (new files — must not exist before this rollout):
- `docs/rag_eval/common/knowledge-management/iter-03/baseline_pre_mem_bounded.json`
- `tests/unit/quantization/test_arena_off.py`
- `tests/unit/website/test_static_body_has_fp32_off.py`
- `tests/unit/rerank/test_flashrank_preload.py`
- `tests/unit/rag/test_query_cache_lru.py`
- `tests/unit/website/test_run_py_emits_max_requests.py`
- `tests/unit/api/test_proc_stats_helper.py`
- `tests/unit/api/test_proc_stats.py`
- `tests/unit/api/test_lifespan_proc_stats_task.py`
- `tests/unit/api/test_memory_guard.py`
- `tests/unit/api/test_memory_guard_exempts_health.py`
- `website/api/_proc_stats.py`
- `website/api/admin_routes.py`
- `website/api/_memory_guard.py`
- `docs/rag_eval/common/knowledge-management/iter-03/scores.md`

**Modified** (existing files):
- `ops/docker-compose.blue.yml` (lines 21-22)
- `ops/docker-compose.green.yml` (lines 21-22)
- `website/features/rag_pipeline/rerank/cascade.py` (multiple regions)
- `.github/workflows/deploy-droplet.yml` (STATIC_BODY block, lines 213-224)
- `website/features/rag_pipeline/ingest/embedder.py` (top imports + line 25)
- `run.py` (cmd block in `main()`)
- `website/main.py` (entire file replaced)
- `website/app.py` (imports + create_app body)
- `tests/stress/test_burst_capacity.py` (append one test)
- `docs/runbooks/droplet_swapfile.md` (full rewrite)

**Files NOT to touch under any circumstances:**
- `website/features/rag_pipeline/rerank/cascade.py:_score_one`, `score_batch` body, `_apply_score_calibration`, `_threshold_for_class`, `_fp32_verify_top_k` — all Phase 1A logic.
- Anything in `website/api/_concurrency.py` (Phase 1B).
- Anything in `website/api/chat_routes.py:_heartbeat_wrapper` (Phase 1B.4).
- `ops/caddy/upstream.snippet` (Phase 1B / earlier iter-03 fix).
- `ops/scripts/apply_migrations.py` (Phase 1C — schema-drift gate).
- `ops/deploy/expected_users.json` (Phase 2D allowlist).

---

## You're ready. Open the plan and start at Phase 0 / Task 0.1.
