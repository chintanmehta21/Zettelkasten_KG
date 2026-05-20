# PR #39 — `summarization_async_api_fixes1.md` Coverage Matrix

**Status:** PR #39 MERGED to master `d187c93e` on 2026-05-20T18:54Z, deploy ✓.
**Wave-4 follow-up PR:** `exec/wave-4-robustness-and-coverage` (this branch).

This matrix maps every actionable item from
`docs/research/summarization_async_api_fixes1.md` to its landing commit,
verification tests, and current state. Every P1 from the report has either
landed or has a follow-up explicitly justified.

---

## A. Transport & async-ops

| Report ID | Item | Status | Landed in | Tests |
|---|---|---|---|---|
| A1 | Single-pipeline path: remove probe + always 202 | ✅ shipped | PR #39 commit 44ad756a | `test_async_operations_transport.py` (5×) + `test_youtube_422_diagnostics.py` (2×) + `test_pr39_wave4.py::test_d1_pipeline_runs_exactly_once_per_slow_add` |
| A2 | Drop `mode` field | ✅ shipped | PR #39 commit 44ad756a | `test_add_zettel_shared_helper.py::test_add_zettel_helper_is_async_only_and_cache_busted` |
| A3 | Idempotency-Key header from JS | ✅ shipped | Wave-4 (this branch) | `test_pr39_wave4.py::test_a3_helper_sends_idempotency_key_header_on_url_path` + `test_d2_duplicate_idempotency_key_resolves_to_single_canonical_op` |
| A4 | Inline-200 path writes ops row | ✅ moot | A1 removed the inline-200 path entirely; every request now writes the row | (covered by A1 tests) |
| A5 | Retry `ops_finalize` on transient | ✅ shipped | Wave-4 (this branch) | `test_pr39_wave4.py::test_a5_finalize_retries_then_succeeds_on_transient_failure` + `test_a5_finalize_returns_false_after_exhausting_retries` |
| A6 | Delete stale module dicts | ✅ scope-corrected | Wave-4 (this branch) | `test_pr39_wave4.py::test_a6_document_idempotency_caches_scoped_to_doc_path` — dicts are **actively used** by the synchronous document upload path; the original "dead" assertion in the report was wrong. Comments + variable aliases updated to make scope explicit. |

## B. Summarization & concurrency

| Report ID | Item | Status | Landed in | Tests |
|---|---|---|---|---|
| B1 — `_SUMMARIZE_SEMAPHORE` low + minimal work under it | ✅ shipped | Wave-3 persist split (839e4817) means chunking/embedding no longer holds the semaphore | `test_persist_multichunk.py` |
| B2 — short/medium/long classification | ⏸️ deferred | Out of PR #39 scope per dashboard decision (Wave 3 lazy enrichment already eliminates the inline-chunk cost). Tier classification adds telemetry but not user-facing latency wins; can land standalone. | n/a |

## C. Persistence & lazy enrichment

| Report ID | Item | Status | Landed in | Tests |
|---|---|---|---|---|
| C1 (B-section) Split persist into Phase 1 + 2 | ✅ shipped | PR #39 commit 839e4817 + migration 60 | `test_persist_multichunk.py::test_persist_enqueues_chunk_embed_after_canonical_write` + `test_pr39_wave4.py::test_d5_persist_returns_with_no_chunks_inline_and_enqueues_payload` |
| C1 Path B — Postgres queue (operator choice) | ✅ shipped | Migration 60 `core.zettel_enrichment_jobs` + RPCs `enrich_enqueue` / `enrich_claim_next` / `enrich_finalize` / `enrich_requeue` | `test_lazy_enrichment.py` (12×) |
| C1 In-process poller (SKIP LOCKED) | ✅ shipped | `website/features/summarization_engine/lazy_enrichment/worker.py` started from `website/main.py` lifespan | `test_lazy_enrichment.py::test_process_one_*` |
| C1 Re-enrichment idempotency guard | ✅ shipped | Partial unique index `(canonical_zettel_id, kind) WHERE status IN (queued,running,succeeded)` in migration 60 | `test_lazy_enrichment.py::test_enqueue_chunk_embed_duplicate_returns_is_new_false` |
| Enrichment-jobs reaper (operator follow-up) | ✅ shipped | Migration 61 (`reap_stuck_running_enrichment_jobs` pg_cron, 5-min threshold) | (DB-level cron, no unit test) |

## D. Frontend UX

| Report ID | Item | Status | Landed in | Tests |
|---|---|---|---|---|
| D1 — Poll budget 240–300 s + backoff | ✅ shipped | PR #39 commit 44ad756a — `POLL_BUDGET_MS = 300000`, schedule `[1000, 2000, 4000, 8000]` ms | `test_add_zettel_shared_helper.py::test_poll_accepted_budget_covers_300s_and_respects_retry_after` |
| D1 — Reaper threshold > poll budget | ✅ shipped | Migration 59 bumped operations reaper 5→7 min | (DB-level cron) |
| D2 — Distinguished status states (accepted/running/...) | ✅ shipped | PR #39 commit 9e220869 — backend `phase` field on 202 body; `pollAccepted` `onStatus` callback | (visual; covered by D3 typewriter test) |
| D3 — Graceful poll-exhaust UX + auto-refresh | ✅ shipped | PR #39 commit 9e220869 — `err.code === 'poll_exhausted'` branches in user_zettels.js / home.js / mobile / landing with 30s `loadZettels()` / `refreshMyZettelsBadge()` follow-up | manual visual verification on prod required (Wave-4 follow-up) |
| D5 — Out-of-the-box quirky typewriter (operator request) | ✅ shipped | PR #39 commit 9e220869 — `zk_skeleton_typewriter.js` (queued/running/long vocabularies, ▍ caret, monospace, teal accent) | the module exposes `_PHRASES` for future eval tests |
| D4 — Disable Add button while in flight | ⏸️ deferred | Each caller already has its own submit-disable on `submitBtn.disabled = true` (zettels.js:885, home.js, mobile, landing). Per-key dedup is now A3 + DB partial unique index — covers the race more robustly than client-side button locking alone. | (existing behavior) |

## E. Tests & verification

| Report ID | Item | Status | Landed in |
|---|---|---|---|
| Pipeline-runs-exactly-once invariant | ✅ shipped | `test_pr39_wave4.py::test_d1_pipeline_runs_exactly_once_per_slow_add` |
| Same-key dedup | ✅ shipped | `test_pr39_wave4.py::test_d2_duplicate_idempotency_key_resolves_to_single_canonical_op` |
| User isolation (BOLA) | ✅ shipped | `test_pr39_wave4.py::test_d3_user_isolation_get_operation_returns_pending_for_other_user` |
| Lazy enrichment E2E | ✅ shipped | `test_pr39_wave4.py::test_d5_persist_returns_with_no_chunks_inline_and_enqueues_payload` |
| Edge-case URLs (bad/redirect-loop/unsupported/slow/empty/malformed/429) | ⏸️ deferred | Pre-existing coverage in `test_youtube_422_diagnostics.py`, `test_pricing_preflights.py`. New cases (redirect loop, malformed) sit outside the report's scope; tracked for a follow-up PR. |
| Telemetry per-operation metrics | ⏸️ deferred | Logging already in place (`logger.exception` at every fallback site); structured per-op latency split is Wave-5+. |

## F. Out of scope (report items explicitly deferred)

| Item | Justification |
|---|---|
| F7 — SSE push completion | D10 in the original async-ops redesign decisions doc. The 300s poll budget + 7-min reaper window already resolves the visible-latency hang. SSE adds 1 endpoint + Caddy/Cloudflare config; defer until polling proves insufficient on prod. |
| Pre-existing env-leak in `test_db_routing` | ✅ fixed in Wave-3 follow-up commit aa2082b1 (test now also deletes the `SUPABASE_*` canonical fallback names). |
| 3 known not-live flakes (quantize_bge_int8 ×2, cascade_int8) | Pre-existing per CLAUDE.md; unrelated to this PR. |

---

## Migrations introduced by PR #39

| # | File | Purpose |
|---|---|---|
| 59 | `_v2/59_reaper_threshold_7m.sql` | Bump operations stuck-running reaper from 5→7 min |
| 60 | `_v2/60_zettel_enrichment_jobs.sql` | Lazy enrichment queue + 4 state-guarded RPCs |
| 61 | `_v2/61_enrichment_jobs_reaper.sql` | pg_cron watchdog for stuck enrichment handlers |

All three applied successfully on the 2026-05-20T18:54Z deploy.

---

## What still requires operator hands-on

1. **Live YouTube smoke test on `zettelkasten.in`** — re-run the original failure case (the `fmOPM1cSrY4` URL or similar long content) and verify:
   - Skeleton + typewriter render with quirky messages
   - 202 returned in <1s
   - `/api/operations/{id}` polled with 1s→8s exponential backoff
   - Zettel appears in My Zettels well within 5 min
   - No 524 / no stuck spinner
2. **Visual QA of the typewriter** — confirm vocabulary feels intentional, caret blinks, animation doesn't jitter under network jitter.
3. **Decision on Wave 4 merge** — this branch is ready for review.
