# Handoff: Knowledge Graph Render & Correctness Overhaul

**Plan to execute:** [`docs/superpowers/plans/2026-05-23-kg-render-correctness-overhaul.md`](2026-05-23-kg-render-correctness-overhaul.md)
**Repo:** chintanmehta21/Zettelkasten_KG • **Branch:** `claude/vigilant-proskuriakova-475b7a` (worktree)
**Auth basis:** 3-source convergence (8-subagent dispatch + `docs/research/kg_fixes1.md` + `docs/research/kg_fixes2.md`) + 9th-agent re-research for the 3 divergent items now codified in the plan's **Locked Design Decisions** table (LD-1 … LD-10).

You are the execution engine. Your job is to implement Phases 1 → 2 → 3 → 4 in order, one task at a time, with operator approval at the gates explicitly called out. The plan is bite-sized, TDD-shaped, and self-contained — every step has the code, the test, and the commit message. Read the plan top-to-bottom once before starting; do not skim.

---

## Non-negotiables (drawn from CLAUDE.md "Critical Infra Decision Guardrails")

These knobs are NEVER to be touched, regardless of what a task body looks like:

- `GUNICORN_WORKERS` (must stay ≥ 2), `--preload` flag, `GUNICORN_TIMEOUT` (≥ 180s), Caddy upstream timeouts (`read_timeout 240s`).
- BGE int8 cascade settings, rerank semaphore / bounded queue, SSE heartbeat wrapper, schema-drift gate, `kg_users` allowlist gate.
- Anything UI-color-wise outside the existing teal/amber rule. No purple. Amber only on `/knowledge-graph`; teal elsewhere.
- The D-KG-1 scoring weights are LOCKED. The plan's **Task 3.15 Phase 3-α** rebalance is the ONLY path to change them, and it explicitly halts for operator approval — do NOT roll it into adjacent commits.

If any task body appears to require touching one of these, STOP and surface to operator. Production change discipline (CLAUDE.md §1) overrides task velocity.

---

## Operator-approval gates (explicit halts inside the plan)

| Gate | Where | What you must do |
|---|---|---|
| Migration 47 (`kg_edges.updated_at` + trigger) | Task 2.8 | Apply locally, verify, then halt for operator chat approval before prod-apply |
| Migration 48 (partial index for edge-driven assembly) | Task 2.4a | Same pattern |
| Migration 49 (`pipeline_runs` state machine — `succeeded_empty`, `failed_retryable`, `retry_eligible_after`, `attempt_count` + partial index + backfill) | Task 3.1 | Same pattern. **Critical:** Postgres cannot drop enum values; the down migration documents this — surface it when requesting approval |
| **Phase 3-α — D-KG-1 weight rebalance** | Task 3.15 | This is the highest-stakes change in the plan. Halt with the exact proposal: `(embedding=0.65, tag=0.20, structural=0.10, temporal=0.05)` + embedding fast-path at `cos ≥ 0.80`. Do NOT proceed without an explicit "approved" in chat. If rejected, mark Phase 3-α as skipped and continue to Phase 4 |
| Migration 50 (`derived_tags` column + backfill) | Task 4.3 | Same pattern. Note the backfill is lossy on down — confirm explicitly |
| Tag-normalization backfill (X5) | Task 4.13 | Folded into Migration 50; SQL is idempotent — but verify `unaccent` extension exists on prod |

For each gate: pause, present the diff, name the trade-off, wait for explicit chat approval. "Audit/verify" is not authorization (per `feedback_audit_is_not_authorization` memory).

---

## Phase-by-phase pitfalls (the things research surfaced)

### Phase 1 (Stabilization)
- **LD-2 has BOTH a server filter AND a client cull.** Fixing only one of them leaves the regression in place. Tasks 1.1 and 1.2 BOTH must land before Phase 1 verification — they are not independent.
- **Asset cache-busters** (`?v=20260426d` etc.) appear in three places in `index.html`. Bump them all to the same new token whenever you touch JS or CSS — otherwise Cloudflare/Caddy will serve stale.
- **`graph.json` backfill (Task 1.7) is idempotent.** Re-running it on already-backfilled data is safe; assert this in the smoke (the script prints `backfilled 0 link(s).` on second run).
- **The metrics-input subgraph filter** in `_enrich_graph_with_analytics` (routes.py:151-164) ALSO drops null-strength links and must be updated to match LD-2 (Task 1.1 Step 4) — easy to miss.
- **F1 fix** removes a stale `applyFilters()` call BEFORE the async fetch; do NOT re-add an `applyFilters()` inside `_onStrengthChange`'s body afterwards. The success callback of `loadGraphData` is the only place filters should re-run.

### Phase 2 (Correctness)
- **Task 2.4b is the largest single rewrite in the plan** (`_v2_assemble_graph`). Read the entire new shape before touching code. The inversion is: edges first → endpoint canonical IDs → batched overlay fetch. Do NOT try to keep the old page-driven path in parallel; remove it cleanly.
- **`tier` is REMOVED from the wire payload** (LD-5). Frontend now computes tier from `connection_strength`. If you find any remaining backend tier emission, delete it — the per-workspace classifier (`_build_tier_classifier`) becomes dead code after this phase.
- **C5 self-loop fix**: the condition is `src == dst AND src_id == dst_id` for true drop; `src == dst AND src_id != dst_id` is the multi-mention case that becomes a `co_mention` link (NOT dropped). Easy to invert.
- **K2 cache key extension** could explode cardinality if all `limit`/`offset` variants are cached. LD-7 says: ONLY cache the default `(5000, 0)` page; non-default pagination bypasses cache. Implement that bypass in `view_graph.run_view_graph`, not in `graph_cache.py`.
- **Migration 47** reuses `core.fn_set_updated_at` from `_v2/16_nexus_tokens.sql:59`. Verify that function exists on the target Supabase BEFORE applying (it should, but the migration assumes it).

### Phase 3 (Quality)
- **Migration 49's `ALTER TYPE … ADD VALUE`** cannot run inside a transaction with other DDL in older Postgres versions. The SQL file works in modern Supabase but if you encounter `cannot run inside a transaction block`, split the file into two `psql -c` runs (the enum extension first, the rest second).
- **`kg_metrics.py` MUST degrade gracefully** when `prometheus_client` is missing (e.g. in unit tests that don't install ops/requirements). The plan's Task 3.5 Step 2 includes the `try/except ImportError` no-op double — keep it.
- **Cosine clamp (LD-4)** keeps `max(0, cos)`. Don't be tempted to "preserve negatives" — that was the divergent recommendation and the 9th-agent research explicitly settled on KEEP THE CLAMP for L2-normalized Gemini RETRIEVAL_DOCUMENT embeddings. The Prometheus counter is the escape hatch for model-drift detection.
- **BLAKE3 content hash (LD-9)** excludes per-node metric fields and edge `connection_strength`/`tier` so a re-scored graph still hits the cache. Don't include those in the hash input.
- **Render perf** — `onBeforeRender` per Sprite (Task 3.9) is the key win. The HTML overlay (`_updateActiveLabel`) keeps its OWN rAF loop because it's only updating ONE active node — that's fine. Don't try to consolidate them.
- **`linkDirectionalParticles` accessor** (Task 3.10) returns `0` when no node is hovered/selected. After hover state changes, you MUST call `graph.refresh()` so 3d-force-graph re-evaluates the accessor — easy to forget.

### Phase 4 (Hardening)
- **Source registry (Task 4.1)** — the frontend MUST wait for `/api/meta/source-types` before calling `loadGraphData()`. The plan uses `Promise.all([_loadExpectedProjectRef(), _registryReady]).then(loadGraphData)` — do not move `loadGraphData()` outside that promise chain.
- **`tldextract` pre-warm in lifespan** is critical: it materializes the parsed PSL tree once in the master process, then `--preload` shares it across workers via COW. Skipping the pre-warm means each worker parses the snapshot separately (~5 MB × 2 workers wasted).
- **Y4 (FastAPI lifespan repos)**: each gunicorn worker has its own globals after fork. The lazy-init helpers `_get_core_repo()` / `_get_content_repo()` are thread-safe — keep the `threading.Lock` around them.
- **B7 backfill SQL** (Migration 50) splits `user_tags` on the `source_domain:` / `modality:` / `speaker:` prefixes. Verify the prefix list matches exactly what `pseudo_tags.derive_pseudo_tags` emits — if you add a fourth pseudo-tag prefix later, the backfill is one-shot and historical rows won't auto-update.
- **X5 NFKC backfill** requires the `unaccent` Postgres extension. Guard the migration with `CREATE EXTENSION IF NOT EXISTS unaccent;` (already in the SQL).
- **Dead-code deletion (Task 4.16)** — grep for callers across `website/` AND `tests/` before deleting. The plan calls this out, but it's the most common place a "harmless cleanup" breaks CI.

---

## Execution mode

Use **subagent-driven-development** (the user's existing pattern; see `superpowers:subagent-driven-development`):

1. For each task (in order Phase 1.1 → 4.17), dispatch a fresh subagent with the task body verbatim plus the LD-table from the plan header.
2. After the subagent reports completion, run the verification command embedded in the task. If it fails, dispatch a follow-up subagent with the failure log; do not edit the code yourself.
3. After each Phase's acceptance gate, commit the closeout marker, run the full test suite, and surface a one-paragraph status update to the operator.
4. At each operator-approval gate, halt and wait.

If you encounter a task body that conflicts with the LD table, the LD table wins. If you find a defect not addressed in the plan, flag it via `mcp__ccd_session__spawn_task` rather than handling it inline — scope creep is a plan failure (per the `feedback_anything_beyond_plan_needs_approval` memory).

---

## Acceptance signals

Run the 12-item checklist at the bottom of the plan after Phase 4's closeout. Hardest items: (1) anonymous `/api/graph` returns ≥50 links, (2) 10 identical calls return identical link counts, (4) all four `pipeline_runs.status` terminal states appear, (10) `/api/metrics` counters move during Add-Zettel, (11) 5k-node fixture at ≥30 fps, (12) no protected-knob revert. Surface a final report with plan filename, migration audit trail, commit range, and open backlog items.

---

**Begin with Task 1.1. Halt at every operator-approval gate. The plan is the contract.**
