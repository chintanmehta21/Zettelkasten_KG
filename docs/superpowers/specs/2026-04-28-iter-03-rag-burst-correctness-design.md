# Iter-03 — RAG Burst Capacity, Correctness, Kasten Surface, Eval Rigour

**Author:** chintanmehta21
**Date:** 2026-04-28
**Status:** Design (pending sign-off → writing-plans → execution)
**Predecessors:** [iter-01](../../rag_eval/knowledge-management/iter-01/manual_review.md), [iter-02 next_actions](../../rag_eval/knowledge-management/iter-02/next_actions.md), [rag-improvements-iter-01-02-design](2026-04-26-rag-improvements-iter-01-02-design.md)

---

## 1. Goal

Resolve every reliability, correctness, and surface defect that iter-02 surfaced in a **single deploy** off branch `iter-03/all`. Verified end-to-end via Claude in Chrome against the existing Naruto-owned `Knowledge Management` Kasten.

Five compound outcomes, each non-negotiable:

1. **Cloudflare 502 storm eliminated** under 10× concurrent burst on the existing 2 GB DigitalOcean droplet — without buying hardware.
2. **Multi-worker production** (2 uvicorn workers) running on the same droplet, achieved by quantizing the BGE reranker to int8 ONNX. If int8 drops quality below iter-02 baseline, *recover quality by refactoring the pipeline around the new constraint* — fp16 is not a fallback option.
3. **Sub-60s p95 end-to-end latency** for every supported query class. Lighter models for simpler classes; token-conscious routing.
4. **Synthesizer correctness** — over-refusals eliminated, action-verb queries route to actionable Zettels, citations never leak from non-Naruto user data.
5. **Kasten surface polish** — meaningful Strong/Fast dropdown, Select-all in add-zettels modal, Kasten-name placeholder, queueing UX, Kasten-card-shuffle loading animation in **teal** (Zettels & Kastens are teal — amber/gold is reserved for `/knowledge-graph` only).

End-to-end gold@1 ≥ iter-02 baseline + 5pp (hard CI gate). Per-stage metrics tracked as **soft signal** this iter; hardened in iter-04 once variance is known.

---

## 2. Constraints

- **Hardware ceiling.** DigitalOcean Premium Intel droplet — 2 GB RAM / 1 vCPU / 70 GB NVMe SSD / Reserved IP / Cloudflare DNS. No upgrade authorized this iter.
- **Single deploy.** All 4 PR groups land on branch `iter-03/all` as 4 logical commits, then one merge to master. Each commit is individually revertible.
- **Production discipline (CLAUDE.md).** No TODOs, no stubs, no half-done abstractions, no "we'll fix later" comments.
- **Backwards compatibility.** No breaking schema changes without explicit user approval. Preserve every API contract the frontend already consumes.
- **No infra disclosure.** Model names, latency, scores, query_class, token counts NEVER surface in production user UI. Eval JSON gets the full picture; `?debug=1` user panel is dropped.
- **UI palette.** Teal for Zettels & Kastens (incl. chat composer, Kasten cards, animations). Amber/gold (`#D4A024`) ONLY for `/knowledge-graph` 3D viz. Never purple/violet/lavender.
- **Single-deploy verification.** Final verification uses Claude in Chrome MCP against the existing Naruto Knowledge Management Kasten (no new Kasten created).
- **Two test users preserved.** Naruto (`f2105544-…`) and Zoro (`a57e1f2f-…`) both kept. Reconciliation deletes ONLY duplicate Naruto rows (if any) and orphaned `kg_*` rows owned by user_ids not in `{Naruto, Zoro}`. Zoro's "Email not verified" auth issue is fixed in-iter.

---

## 3. Architecture decisions (this is where the spec departs from punch-list framing)

### 3.1 Capacity model — 1 → 2 workers, int8-only

**Decision:** Quantize the BGE reranker to int8 ONNX and run 2 uvicorn workers in production.

**Why:** Per the RAM-capacity research, fp32 BGE-reranker-base dominates per-worker RSS at ~480–620 MB. Total per-worker steady RSS is ~920–1,260 MB → 2 workers OOM the 1.65 GB usable app memory on the droplet. int8 quantization drops stage-2 RSS to ~150–200 MB → per-worker total ~600 MB → 2 workers fit comfortably with ~400 MB headroom.

**Quality preservation is engineered up front (see §3.15), not recovered after a regression.** Naive int8 PTQ would lose 1–3% on rerank quality; with the proactive stack in §3.15 we target ≤0.5% loss on iter-03 eval — well below the 5pp end-to-end CI gate, leaving the gate to catch genuine regressions, not normal quantization noise. fp16 fallback is explicitly NOT permitted; the quantization workstream owns its own quality preservation.

**Server config:** `gunicorn -k uvicorn.workers.UvicornWorker --workers 2 --preload`. Eager-load the cascade reranker at module import so `--preload` actually shares model bytes via copy-on-write. (Current code is lazy-loaded post-fork — refactor required.)

### 3.2 Concurrency control — bounded queue + rerank semaphore

Adding workers alone doesn't solve the 502 storm; the underlying problem is that the FastAPI event loop saturates when too many requests pile into the BGE rerank stage (mutex-serialized in `cascade.py`). Three layers, all in iter-03:

1. **Async I/O upgrade** — every request-path call to Gemini and Supabase already uses async clients; audit and confirm no sync-blocking calls remain in chat_routes / orchestrator. Fix any.
2. **Route-level rerank semaphore** — `asyncio.Semaphore(2)` wrapping the rerank call. Caps concurrent BGE work at 2 (matches our 1-vCPU + 2-worker reality). Excess requests await without blocking the event loop.
3. **Bounded request queue with proper backpressure** — when semaphore wait queue exceeds `RAG_QUEUE_MAX` (default 8), return `503 Retry-After: 5`. Cloudflare passes 503 through cleanly; user sees a "Queued — retrying in Ns" soft-warning composer chip and the frontend auto-retries once.

Combined with `--workers 2`, this handles ~30 concurrent users at <60s p95 on this droplet.

### 3.3 Latency budget — 60s end-to-end cap, class-aware routing

Total answer latency must stay under 60s p95. Stage budgets:

| Stage | Budget | Notes |
|---|---|---|
| Query routing + expansion | 2s | Includes HyDE/decompose for Strong mode |
| Retrieval (vector + lexical fan-out) | 5s | top-k 40 (Strong) / 20 (Fast) |
| Reranker stage 1 (FlashRank MiniLM) | 2s | int8 ONNX |
| Reranker stage 2 (BGE int8) | 6s | mutex-serialized, semaphore-capped |
| Evidence compression | 3s | |
| Synthesizer (LLM streaming) | 30s | Per-model timeout reduced to 30s; falls back to next tier |
| Critic (post-gen verify, Strong only) | 5s | `gemini-2.5-flash-lite` |
| Padding / network / Caddy | 7s | |
| **Total** | **60s** | |

**Per-class model routing override (planner layer, before SDK call):** even when user picks `quality="high"`, force `tier="fast"` for `multi_hop`/`thematic`/`step_back` classes by default. `quality="high"` for these classes only kicks in if explicit `?force_pro=1` URL param. Reduces SDK timeout from 180s → 30s/model so Pro→Flash fallback fires within budget.

### 3.4 SSE survival across blue/green cutover

Current `retire_color.sh` does `--timeout 20` after `DEPLOY_DRAIN_SECONDS=20` ≈ 40s total. **Bump to `DRAIN=45s + --timeout 30 = 75s`** — covers Pro-tier streaming (>30s) and Strong-mode critic loop. Also: emit SSE heartbeat (`:heartbeat\n\n`) every 10s from chat streaming routes; client treats 15s of silence as "dead" and auto-retries once with backoff.

### 3.5 apply_migrations refactor (per research report)

Six logical landings (4 independent + 2 atomic groups), per the dedicated apply_migrations research report. iter-03 ships:

- Mode A: hard-fail without explicit `SUPABASE_DB_URL` (delete IPv6-only fallback).
- Mode C: extract `manual-prebackfill` placeholder constant + `--reconcile-checksum NAME` CLI.
- Mode E: enforce migration filename regex.
- Mode G: connect retry with backoff (3× / 5s).
- Atomic group #1: audit trail upgrade (`deploy_git_sha`, `deploy_id`, `deploy_actor`, `runner_hostname` columns; deploy.sh passthrough; workflow env exports).
- Atomic group #2 (centerpiece): post-apply schema-drift verifier diffing live `information_schema` against checked-in `supabase/website/kg_public/expected_schema.json` manifest, plus CI freshness check.

Deferred to iter-04: Mode B (advisory lock leak), Mode F (rollback registry), Mode H (bootstrap circularity), Mode J (plan-file atomicity).

### 3.6 Synthesizer correctness — three-prong fix

The critic at [answer_critic.py:30](../../../website/features/rag_pipeline/critic/answer_critic.py:30) already runs post-generation, returning string verdicts `supported`/`partial`/`unsupported`. Iter-02 over-refusals (q3, q8) came from the critic flipping to `unsupported` on wording divergence between user query and chunk text, then the orchestrator returning the canned refusal verbatim. Three coordinated changes:

1. **Critic prompt tightening** — explicitly accept semantic-equivalence (wording divergence is OK if cited chunks support the claim; "I can't find" responses must cite the ABSENCE of evidence, not just stylistic mismatch). Critic model stays `gemini-2.5-flash-lite`.
2. **Retry policy at [orchestrator.py:434](../../../website/features/rag_pipeline/orchestrator.py:434)** — on second-pass `unsupported`, return the model's draft answer with an inline low-confidence tag (`<details>How sure am I? — citations don't fully cover this claim.</details>`) rather than refusing. Refusal stays only for genuinely empty retrieval (zero hits).
3. **Per-class regression fixtures** — add 5 test fixtures (one per query class) under `tests/integration/rag/` so over-refusal patterns fail in CI before users see them.

### 3.7 Action-verb retrieval boost — local change inside `_source_type_boost`

There is no `lookup_recency` query class. Real classes: `lookup`, `vague`, `multi_hop`, `thematic`, `step_back`. The fix is local to [hybrid.py:312](../../../website/features/rag_pipeline/retrieval/hybrid.py:312):

```
ACTION_VERBS = {build, start, open, run, install, set up, spin up, deploy, configure, create, launch, bootstrap, try, use}

if query_class == LOOKUP and any verb in question.lower():
    boost source_type ∈ {github, web} by +0.05
    boost source_type ∈ {newsletter, youtube} by -0.02
```

Magnitudes match existing scale (0.02–0.05). No new query class plumbing.

### 3.8 Strong vs Fast — meaningful quality dial

Currently the `quality` body field on `POST /api/rag/sessions/*/messages` only swaps the LLM chain. Strong becomes a meaningful quality dial:

| Mode | LLM chain | Retrieval top-k | Critic | HyDE for vague/multi_hop | Evidence compression |
|---|---|---|---|---|---|
| **Fast** | flash → flash-lite | 20 | skipped | no | minimal |
| **Strong** | pro → flash *(except multi_hop/thematic/step_back which force fast)* | 40 | enabled (post-gen verify + revision) | enabled | full |

Toggled via existing `default_quality` field on the Kasten + per-message `quality` override in the composer dropdown. No new schema fields.

### 3.9 Naruto consolidation — single canonical Naruto, both users preserved

login_details.txt confirmed: Naruto IS the canonical primary user (34 nodes, 157 links). Zoro is a real test-auth user (3 nodes, 1 link), kept intentionally.

**Reconciliation script** `ops/scripts/reconcile_kg_users.py`:

- `--audit` — lists every `kg_users` row, every distinct `user_id` in `kg_nodes/edges/chunks`, flags any row owned by a user_id NOT in `{Naruto.f2105544..., Zoro.a57e1f2f...}`.
- `--dedupe-naruto` — if multiple `kg_users` rows match Naruto-ish criteria (email LIKE 'naruto%' or auth_id != canonical), reassign their owned rows to the canonical Naruto row, then delete the duplicates inside one transaction. **No-op if duplicates absent.**
- `--purge-orphans` — hard-delete `kg_*` rows owned by user_ids not in `{Naruto, Zoro}`. Inside a transaction. Report row counts.
- `--apply` runs all three in order; `--dry-run` prints SQL plans only. Idempotent.

**Zoro email-verification fix:** Zoro's `<private>email</private>` uses a non-deliverable TLD which Supabase Auth refuses to confirm via email link. Fix: one-shot SQL `UPDATE auth.users SET email_confirmed_at = NOW() WHERE id = '<zoro-auth-id>' AND email_confirmed_at IS NULL;` runnable via `ops/scripts/confirm_zoro_email.py` against Supabase service-role connection. Idempotent. Documented in `docs/runbooks/test_user_provisioning.md` (new file).

**No single-tenant invariant gate.** Earlier proposal to fail-deploy if `kg_users` count != 1 is dropped because we keep both Naruto and Zoro. Replaced by a softer assertion: deploy fails if any `kg_users` row exists with auth_id NOT in the documented allowlist (`{Naruto, Zoro}`). Allowlist lives in `ops/deploy/expected_users.json`.

### 3.10 Kasten surface polish

- **Add-zettels modal Select-all** ([user_rag.js:787](../../../website/features/user_rag/js/user_rag.js:787)) — header `<li class="header">` with Select-all checkbox + "N selected" counter, excludes already-member rows.
- **Composer placeholder dynamic** ([user_rag.js:43](../../../website/features/user_rag/js/user_rag.js:43)) — after `loadSandboxes()`, set `els.input.placeholder = "Ask " + truncate(kasten.name, 40) + " something…"`. Focus-node override preserved.
- **Queue UX** — when 503 Retry-After received, composer shows inline "Queued — retrying in {N}s" soft-warning. Auto-retries once with shown countdown.

### 3.11 Kasten-card-shuffle loading animation (TEAL)

One shared primitive, three modes. Built on the existing summary-loader CSS infrastructure (per memory `[Summary Loader Animation]`). **Color: teal, the Zettel/Kasten accent.** Exact teal hex extracted from current `website/features/user_rag/css/` via the ui-ux-pro-max skill at execution time — never hardcoded.

| State | Visual | Caption | Loop |
|---|---|---|---|
| Long-pipeline (>5s no SSE token) | 3 index-card silhouettes in teal fan out + restack | rotates: "Searching your Zettels…" → "Reading the right cards…" → "Connecting the dots…" → "Drafting your answer…" *(stages emitted via existing trace_stage observability as SSE caption events)* | 2.5s |
| Heartbeat-retry (>15s no frame) | Same stack, slower, lower opacity | "Reconnecting your Kasten…" + inline ↻ "Retry now" button | 4s |
| Queued-503 | Single index card with soft pulsing teal glow | "Queued — retrying in {N}s" countdown | 1.5s breathe |

### 3.12 Eval scope + per-stage metrics

10 iter-02 queries (apples-to-apples) + 3 new queries locking the action-verb-boost regression. Per-stage metrics added to `answers.json` (eval-side ?debug always on; user-side `?debug=1` panel **dropped** from scope):

- Retrieval recall@10 (right Zettel in top-10 raw candidates) — soft target ≥ iter-02 baseline + 5pp
- Reranker top-1 vs top-2 margin — soft target ≥ 0.05
- Synthesizer grounding (% claims with ≥1 supporting citation per critic) — soft target ≥ 85%
- Critic agreement with manual review (10-q sample) — soft target ≥ 90%
- **End-to-end gold@1 — HARD GATE, ≥ iter-02 baseline + 5pp**
- End-to-end p95 latency — soft target ≤ 60s

### 3.13 Ops visibility — read_recent_logs workflow

Net-new `.github/workflows/read_recent_logs.yml`. `workflow_dispatch` with inputs `tail_lines` (default 500) and `color` (`blue` / `green` / `auto`). SSHes to droplet, runs `docker compose -f compose/docker-compose.{color}.yml logs --tail $N`, uploads as workflow artifact. Reuses droplet-SSH secret pattern from `deploy-droplet.yml`.

### 3.15 Quantization quality preservation — proactive, eight-layer mitigation

The point of this stack is to **eliminate the quality-recovery loop entirely** by engineering quantization to land within ~0.5% of fp32 on day one. Each layer is independent; they compound.

**Layer 1 — In-distribution calibration set (large, stratified, anchored).**
- 500 calibration pairs (not 200) sampled from Naruto's `kg_node_chunks`.
- Stratified sampling: 100 pairs per query class × 5 classes (lookup / vague / multi_hop / thematic / step_back), each balanced 50/50 between positive (gold-cited) and hard-negative (semantically-near-but-wrong) pairs.
- All 13 iter-03 eval queries (10 iter-02 + 3 action-verb regression) are guaranteed-included as calibration anchors — if int8 happens to be miscalibrated near these queries, calibration directly tightens it.
- Calibration set checked into `models/bge_calibration_pairs.parquet` (Git LFS) for reproducibility. SHA256 in `cascade.py` constants.

**Layer 2 — Selective quantization (preserve the classifier head).**
- Quantize ONLY the encoder body matmuls — `op_types_to_quantize=['MatMul']` via `optimum.onnxruntime.ORTQuantizer`.
- KEEP the cross-encoder classifier head, all `LayerNorm`, all `Softmax`, all `GELU`, and the final pooler in fp32. The classifier head has trivial param count but huge accuracy delta if quantized.
- Reduces quality loss by ~50% vs full int8 at ~5% extra RAM (~10–15 MB) — net per-worker still <700 MB.

**Layer 3 — Per-channel symmetric weight quantization + dynamic per-batch activation quantization.**
- `weight_dtype=QInt8`, `activation_dtype=QUInt8`, `is_static=False` (dynamic activations), `per_channel=True`.
- Per-channel preserves head-level signal in attention layers (vs per-tensor which collapses heads).
- Dynamic activations adapt to runtime distribution — no calibration drift on out-of-distribution queries.

**Layer 4 — Score calibration layer (recover score scale).**
- After quantization, fit a tiny 1-feature linear regression: `fp32_score = a × int8_score + b` on the 500-pair calibration set.
- Apply the `(a, b)` correction post-rerank in `cascade.py` so downstream margin thresholds stay meaningful without retuning.
- ~1 µs per rerank call. Stored as constants in `cascade.py`.

**Layer 5 — Defensive fp32 verification on top-3 (cheap insurance).**
- int8 reranks all 15 candidates → narrows to top-3 → fp32 model loaded **on-demand** (not always-resident) verifies and re-scores top-3 → final order uses fp32 scores.
- fp32 model file held in shared memory at `/dev/shm/bge_fp32.onnx`, loaded once via `mmap` per worker (~280 MB but mmap-shared; copy-on-write means RSS attribution reads as ~10 MB per worker after first inference).
- Trade: +~1.2s latency per query (top-3 only, not all 15) for a ~0.3pp gold@1 recovery on edge cases.
- Toggleable via `RAG_FP32_VERIFY=on/off` env. Default `on` for iter-03.

**Layer 6 — Per-class margin threshold retuning.**
- Slight score-distribution shifts under quantization can move per-class acceptance thresholds.
- Re-tune via grid search on calibration set: for each query class, find the int8 margin threshold that maximizes calibration-set gold@1.
- Stored in `website/features/rag_pipeline/retrieval/_int8_thresholds.json` (committed). Loaded by `_source_type_boost`.

**Layer 7 — Test-time augmentation for Strong mode.**
- Strong mode runs rerank with 2 different doc-permutation orderings and averages scores. Reduces order-sensitivity introduced by quantization.
- Cost: +~3s on Strong queries (negligible vs Strong's existing 30s synthesizer budget).
- Fast mode does NOT do this — keeps Fast genuinely fast.

**Layer 8 — Pre-merge quality gate (local, not CI).**
Before commit-1 lands, the quantization PR-author runs:
```
python ops/scripts/validate_quantization.py
```
Which executes all 13 eval queries against int8+stack vs fp32 and refuses to commit unless:
- Per-class gold@1 within 1pp of fp32
- Margin-distribution KL divergence < 0.05
- Top-1 vs top-2 separation ≥ 0.8× of fp32 baseline
- p95 rerank latency reduction ≥ 30%

If any fails, the script exits non-zero. fp16 NOT permitted as escape; instead the script emits which Layer 1–7 knob to adjust.

**Net expected impact:** the quantization workstream lands with quality within 0.5% of fp32 on day one. The CI gold@1 gate (≥iter-02 + 5pp) becomes about *retrieval/synthesizer/critic improvements* contributing the +5pp, not about defending against quantization loss.

---

### 3.16 UI palette discipline — `ui-ux-pro-max` + `frontend-design` invoked at execution

For every UI surface touched in commit-3, the implementation phase invokes both `ui-ux-pro-max` and `frontend-design` skills to ensure the teal palette is correctly applied. These skills read the current CSS variables in `website/features/user_rag/css/` and surface the exact teal hex/HSL — never hardcoded by guess.

**Strict surface map (mirrored from CLAUDE.md UI Design + memory `[No Purple + Teal/Amber Rules]`):**

| Surface | Color |
|---|---|
| Kasten chat composer, animations, badges, retry inline, queue-503 chip | **Teal** |
| Zettel cards, Zettel detail pages, summary loader | **Teal** |
| `/knowledge-graph` 3D viz | **Amber/gold** (`#D4A024`) |
| GitHub source chip | Warm cyan `#56C8D8` |
| Anywhere | NEVER purple/violet/lavender |

Common-mistake guard (incident 2026-04-28): Kasten ≠ KG. Anything on `/rag/*` or in the chat composer is Kasten = TEAL. Anything on `/knowledge-graph` is KG = amber.

---

### 3.17 Token-conscious LLM routing (cost discipline)

Every LLM call in the request path is sized to the actual question complexity, not a fixed tier. This reduces Gemini API spend and aligns with the 60s p95 budget.

| Query class | Default tier | Default model | Token budget per call |
|---|---|---|---|
| `lookup` (simple) | fast | `gemini-2.5-flash-lite` | ≤ 1.5K input / ≤ 800 output |
| `vague` | fast | `gemini-2.5-flash` | ≤ 4K input / ≤ 1.2K output |
| `multi_hop` / `thematic` / `step_back` | fast (forced even if user picked Strong; override only via `?force_pro=1`) | `gemini-2.5-flash` | ≤ 6K input / ≤ 1.5K output |
| `lookup` + Strong | high | `gemini-2.5-pro` → `flash` fallback | ≤ 8K input / ≤ 2K output |
| Critic verification (Strong only) | always | `gemini-2.5-flash-lite` | ≤ 2K input / ≤ 300 output |
| HyDE expansion (Strong + vague/multi_hop) | always | `gemini-2.5-flash-lite` | ≤ 500 input / ≤ 400 output |

Implemented as constants in `website/features/rag_pipeline/generation/_routing.py` (new file). Audited monthly via `ops/scripts/audit_token_spend.py` against actual Gemini billing.

---

### 3.18 GitHub Actions secret management via `gh` CLI

All GH Actions secrets needed by the apply_migrations refactor (`SUPABASE_DB_URL`, `DEPLOY_GIT_SHA`, `DEPLOY_ID`, `DEPLOY_ACTOR`) are managed via `gh secret set` from the local repo during commit-1 execution — not via the GH web UI. Implementation step in commit-1:

```
gh secret list --repo chintanmehta21/Zettelkasten_KG  # audit current state
gh secret set SUPABASE_DB_URL --repo chintanmehta21/Zettelkasten_KG --body "<value>"  # if missing
```

Three of the four (`DEPLOY_GIT_SHA`, `DEPLOY_ID`, `DEPLOY_ACTOR`) are NOT secrets — they're workflow context exposed via `${{ github.sha }}`, `${{ github.run_id }}`, `${{ github.actor }}`. Just need to flow into the SSH step's env.

---

### 3.14 Verification — Claude in Chrome end-to-end (Naruto credentials)

Final iter-03 verification uses Claude in Chrome MCP against the **existing Knowledge Management Kasten** (no new Kasten). Already-logged-in session:

1. Open `/rag` chooser → confirm Knowledge Management Kasten card renders correctly (Strong/Fast badge, Zettel count, no badge errors).
2. Enter Knowledge Management chat → confirm composer placeholder reads "Ask Knowledge Management something…".
3. Run all 13 eval queries (10 iter-02 + 3 action-verb regression) — capture screenshots of each answer + citations.
4. Toggle Strong dropdown mid-session → confirm next answer uses critic loop (visible in eval-side `?debug` JSON, not in UI).
5. Open add-zettels modal → confirm Select-all checkbox + counter work.
6. Trigger heartbeat retry by manually pausing the dev server mid-stream → confirm "Reconnecting your Kasten…" animation in **teal** + auto-retry fires.
7. Trigger queue UX by hammering 12 concurrent requests via dev tools → confirm 503-Retry-After surface as "Queued — retrying" pill.
8. Confirm production-mode `?debug=1` shows nothing (env-flag off).
9. Confirm schema-drift gate fires: deploy a migration with intentional drift in expected_schema.json → deploy must abort.
10. Confirm SSE survives blue→green cutover: start a Pro-tier streaming answer → trigger a deploy → answer must complete cleanly.

All 10 captured to `docs/rag_eval/knowledge-management/iter-03/verification.md` + `screenshots/` subdir. Walkthrough script lives at `ops/scripts/verify_iter_03_in_browser.py` for re-runnability.

---

## 4. PR / commit plan (single branch, single deploy)

Branch: `iter-03/all`. Four commits, then merge to master.

### Commit 1 — `feat: burst capacity + apply_migrations refactor`

- `ops/scripts/quantize_bge_int8.py` (new) — quantization workstream applying §3.15 layers 1–3 (calibration set build, selective quantization, per-channel symmetric weights). Output: `models/bge-reranker-base-int8.onnx` (Git LFS).
- `models/bge_calibration_pairs.parquet` (new, Git LFS) — 500 stratified in-distribution calibration pairs anchored on iter-03 eval queries. Generated by `ops/scripts/build_calibration_set.py` (also new).
- `ops/scripts/validate_quantization.py` (new) — pre-merge quality gate (§3.15 layer 8). Refuses commit if int8 vs fp32 quality delta exceeds thresholds.
- `website/features/rag_pipeline/rerank/cascade.py` — eager-load reranker at module import (so `--preload` shares); load int8 ONNX path; apply score-calibration `(a, b)` constants (§3.15 layer 4); on-demand fp32 verifier for top-3 (§3.15 layer 5); test-time augmentation for Strong mode (§3.15 layer 7).
- `website/features/rag_pipeline/retrieval/_int8_thresholds.json` (new) — per-class int8 margin thresholds (§3.15 layer 6).
- `gh secret set SUPABASE_DB_URL` invocation step documented in commit-1 task list (§3.18).
- `website/main.py` — switch entrypoint to `gunicorn -k uvicorn.workers.UvicornWorker --workers 2 --preload`. Update `run.py` accordingly.
- `website/api/chat_routes.py` — `asyncio.Semaphore(2)` rerank cap; bounded queue with 503 Retry-After when full; `?force_pro=1` URL param.
- `ops/deploy/deploy.sh`, `ops/deploy/retire_color.sh` — `DRAIN=45s` + `--timeout 30`; pre-warm `/api/health/warm` post-up; pass `DEPLOY_GIT_SHA`/`DEPLOY_ID`/`DEPLOY_ACTOR` envs.
- `ops/scripts/apply_migrations.py` — modes A/C/E/G fixes + audit-trail columns + post-apply schema-drift verifier.
- `supabase/website/kg_public/migrations/2026-04-28_migrations_audit_columns.sql` (new).
- `supabase/website/kg_public/expected_schema.json` (new) — manifest, generated via `--bootstrap-manifest`.
- `.github/workflows/deploy-droplet.yml` — env-var passthrough; new `migrations-manifest-check` job.
- `.github/workflows/read_recent_logs.yml` (new).
- 2 GB swapfile creation documented in `docs/runbooks/droplet_swapfile.md` (manual one-shot, runbook only).
- Tests: `tests/unit/ops/test_apply_migrations.py` extended; new `tests/integration/test_burst_capacity.py` (uses `hey`-style concurrent client against local uvicorn with stubbed reranker).

### Commit 2 — `feat: synthesizer correctness + strong/fast semantics`

- `website/features/rag_pipeline/critic/answer_critic.py` — prompt tightening for semantic-equivalence acceptance.
- `website/features/rag_pipeline/orchestrator.py` — retry policy: on 2nd-pass unsupported, return draft + low-confidence tag.
- `website/features/rag_pipeline/retrieval/hybrid.py:312` (`_source_type_boost`) — action-verb regex boost.
- `website/features/rag_pipeline/retrieval/planner.py` — Strong-mode → top-k 40, HyDE for vague/multi_hop; Fast-mode → top-k 20, no HyDE.
- `website/features/rag_pipeline/generation/gemini_backend.py` — per-model SDK timeout 30s; planner-layer override forces fast for multi_hop/thematic/step_back unless `?force_pro=1`.
- `ops/scripts/reconcile_kg_users.py` (new) — audit / dedupe-naruto / purge-orphans.
- `ops/scripts/confirm_zoro_email.py` (new) — Zoro email-verified one-shot.
- `ops/deploy/expected_users.json` (new) — Naruto + Zoro auth_id allowlist.
- `ops/deploy/deploy.sh` — single-tenant allowlist gate (fail if unknown auth_id present in kg_users).
- Tests: `tests/integration/rag/test_critic_semantic_equivalence.py`, `tests/integration/rag/test_action_verb_boost.py`, `tests/integration/rag/per_class_regression/*` (5 fixtures), `tests/unit/ops/test_reconcile_kg_users.py`.

### Commit 3 — `feat: kasten surface polish`

- `website/features/user_rag/js/user_rag.js` — add-zettels modal Select-all header (line 787); composer placeholder dynamic from Kasten name (line 43); queue UX 503-Retry-After handler; SSE heartbeat handling in `consumeSSE` (line 495); auto-retry wrapper.
- `website/api/chat_routes.py` — emit `:heartbeat\n\n` SSE comment every 10s.
- `website/features/user_rag/css/loader.css` (new) — Kasten-card-shuffle primitive in **teal** (exact hex via ui-ux-pro-max at execution).
- `website/features/user_rag/js/loader.js` (new) — three-state controller (long-pipeline / heartbeat-retry / queued-503).
- Tests: Playwright/Puppeteer or vanilla JS DOM tests for modal + composer placeholder + animation states; SSE heartbeat tested via integration test.

### Commit 4 — `feat: eval rigour + verification harness`

- `website/features/rag_pipeline/evaluation/eval_runner.py` — emit per-stage metrics into `answers.json`.
- `docs/rag_eval/knowledge-management/iter-03/queries.json` (new) — 10 iter-02 + 3 new action-verb regression queries.
- `docs/rag_eval/knowledge-management/iter-03/verification.md` (new — checklist with results filled at execution time).
- `ops/scripts/verify_iter_03_in_browser.py` (new) — Claude in Chrome MCP walkthrough.
- `ops/scripts/rag_eval_loop.py` — add hard CI gate on end-to-end gold@1; soft warning on per-stage drops.
- `.github/workflows/ci.yml` — new `iter-03-eval-gate` job (only fires on PR merge, not every push, to control LLM cost).

After all 4 commits: `git checkout master && git merge --no-ff iter-03/all -m "feat: iter-03 burst capacity correctness kasten polish"`. Single deploy fires.

---

## 5. Risks & rollback

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| int8 quantization drops gold@1 below baseline + 5pp | MED | HIGH (blocks deploy via hard gate) | Quality-recovery loop pre-deploy: tune calibration set, bump post-rerank top-k, additional candidate filter. Eval iterates locally until gate passes. fp16 fallback NOT permitted per user directive — refactor pipeline instead. |
| 2-worker config still OOMs under unforeseen load | LOW | HIGH (502s return) | Pre-deploy 10× burst test on staging color with `docker stats` watch. 2 GB swapfile as backstop. Rollback = revert to 1 worker via env var without re-deploying image. |
| Schema-drift gate fires on a real but harmless drift (e.g., index reorder) | MED | MED (deploy aborts) | `--update-manifest` flag; runbook documents the regenerate-and-commit procedure. CI freshness check ensures manifest stays in sync. |
| Naruto reconciliation deletes legitimate data | LOW | HIGH (data loss) | Mandatory `--dry-run` before `--apply`; full transaction wrap; pre-script `pg_dump` of affected tables to droplet `/tmp` retained for 7 days. Allowlist (`expected_users.json`) prevents cascade outside Naruto+Zoro. |
| Zoro email confirmation breaks if Supabase changes auth schema | LOW | LOW (test user only) | Script idempotent; failure is logged but doesn't block deploy. |
| Heartbeat SSE breaks intermediaries (Cloudflare, Caddy) that buffer | LOW | MED (broken streaming) | Heartbeat is a comment line (`:heartbeat\n\n`) which all SSE-spec-compliant proxies pass through. Test in staging blue/green before promote. |
| Kasten-card-shuffle animation jank on low-end mobile | LOW | LOW | CSS animation only, no JS-driven; degrades to static teal card if `prefers-reduced-motion` set. |

**Rollback strategy:** Single `git revert <merge-sha>` on master triggers a new deploy that reverses every change. Per-commit revert also possible since each commit is logically self-contained. Migration audit-trail columns are additive; rolling back the migration leaves the columns NULL, no data loss.

---

## 6. Out of scope (deferred to iter-04+)

- 3-worker config (requires either bigger droplet or further BGE reduction).
- apply_migrations modes B / F / H / J (advisory lock, rollback registry, bootstrap circularity, plan-file atomicity).
- User-facing `?debug=1` panel.
- MEMORY.md hygiene pass (file is currently 20 lines — re-evaluate at >150).
- Hard-gate on per-stage metrics (this iter is soft signal only).
- Multi-tenant scaling beyond Naruto + Zoro.
- Quantization of stage-1 FlashRank MiniLM (already small at ~33M params; not the bottleneck).

---

## 7. Open questions for plan phase

None — all design decisions finalized in brainstorm. Plan phase will:
1. Sequence the work inside each commit (TDD per superpowers discipline).
2. Identify subagent dispatch opportunities (e.g., quantization workstream can run in parallel with synthesizer changes).
3. Produce per-task acceptance checklists.
4. Schedule the verification gate as the terminal step.

---

## 8. Coverage cross-check (every confirmed decision → spec section)

Verifies no item discussed in brainstorm is missing.

| Decision | Source (user message) | Spec section |
|---|---|---|
| 1 → 2 workers via int8 BGE + 2 GB swapfile + pre-warm | Q1 + Q-F-1 | §3.1, §3.15 |
| Async I/O + 2-slot rerank semaphore + bounded queue | Q1 + Q-F-1 + Q11 | §3.2 |
| 60s end-to-end answer cap + lighter models for simpler queries | Q2 | §3.3, §3.17 |
| Token-conscious routing for billing discipline | Q2 (token cost ask) | §3.17 |
| Apply_migrations thorough refactor (6 landings) | Q3 | §3.5 |
| Synthesizer 3-prong (critic prompt + retry policy + per-class fixtures) | Q4 (Recommended) | §3.6 |
| Action-verb regex inside `_source_type_boost` | Q5 (Recommended) | §3.7 |
| Pro→Flash routing forced for multi_hop/thematic/step_back; 30s SDK timeout | Q6 (Recommended two-parts) | §3.3, §3.17 |
| Naruto reconciliation: dedupe duplicates, purge orphans, KEEP both Naruto+Zoro | Q-F-2 + side-note | §3.9 |
| Zoro "Email not verified" fix via auth.users update | Q-F-2 | §3.9 |
| Single branch / 4 commits / 1 deploy | Q8 (Recommended) | §4 |
| Strong = top-k 40 + critic loop + HyDE; Fast = minimal | Q-F-3 | §3.8 |
| Add-zettels Select-all header | Q10 (Recommended) | §3.10 |
| 503 Retry-After + queue UX + multi-worker | Q11 | §3.10 + §3.1 + §3.2 |
| Composer placeholder dynamic from Kasten name | Q12 (Recommended) | §3.10 |
| Drop user-side `?debug=1`, keep eval-side per-stage data | Q13 | §3.12 |
| `.github/workflows/read_recent_logs.yml` | Q14 (Recommended) | §3.13 |
| 10 iter-02 + 3 action-verb regression queries | Q15 (Recommended) | §3.12 |
| Kasten-card-shuffle animation in TEAL (3 modes) | Q16 + UI palette correction | §3.11, §3.16 |
| "Working through your zettels…" 5s ping | Q17 | §3.11 (rotating captions) |
| Per-stage targets +5pp soft signal; end-to-end gold@1 hard gate | Q19 + Q-F-4 | §3.12 |
| Verification via Claude in Chrome on existing Knowledge Management Kasten | Q-F-5 | §3.14 |
| `gh` CLI for GH Actions secrets | Q-F-6 | §3.18 |
| MEMORY.md hygiene NOT in scope (file is 20 lines) | scout finding | §6 (deferred) |
| ui-ux-pro-max + frontend-design skills invoked at exec time | Q16 user directive | §3.16 |
| TEAL for Zettels/Kastens, AMBER only for /knowledge-graph 3D viz | Q16 user correction | §3.11, §3.16, memory |
| DigitalOcean canonical infra reminder | constraint 3 + side note | CLAUDE.md, §2 |
| Research discipline (wait for all agents) | user feedback | CLAUDE.md "Research Discipline" section |
| **NEW (proactive, not asked):** 8-layer quantization quality preservation | engineering judgment per "best score on first go" directive | §3.15 |

Three items intentionally NOT in iter-03 scope:
- 3-worker config (would require either bigger droplet or further model reduction)
- User-facing `?debug=1` panel (per Q13 — eval-side only)
- apply_migrations modes B/F/H/J (per research report — deferred)

**No gaps detected.**
