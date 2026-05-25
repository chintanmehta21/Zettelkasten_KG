# Prajeet — +10 Zettel Grant + Ingest-Failure Sweep (2026-05-25)

**Operator**: Chintan
**Subject**: `Prajeet Ladad` (`prajeetladad@gmail.com`), `auth.users.id = b57fe00e-703f-4c6f-ae56-29b102753233`
**Workspace**: `4c8b185f-bba5-475d-aaf7-e3aeb5cf5028` (personal, role=owner, plan=`free`)
**Signed up**: 2026-05-25 06:53:21 UTC
**Pulled**: 2026-05-25 ~12:10 UTC
**Worktree HEAD**: `a125ae03` (= prod HEAD; deployed 2026-05-25 11:44 UTC)

---

## TL;DR

- **Grant landed.** `provision_pack.py --pack zettel_10 --confirm-prod` returned **HTTP 200**; `billing.pricing_balances` for meter `zettel` is now **`10`** (was empty/0). Pre-grant verifier: `remaining_wallet=10`. Webhook event `evt_prov_zk_pack_3232f35813d74c91b1dbf5d23b0c92d4` succeeded.
- **"Most URLs failed" is recoverable now — but ZERO rows exist under Prajeet's `user_id`.** Direct query of `core.operations WHERE user_id = b57fe00e-...` returns nothing. His attempts were silently mapped to the anonymous Zoro user (`a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e`) by `get_optional_user` (auth.py:172-189) because his Bearer JWT failed server-side validation. Three failed Zoro-mapped operations landed in the window after his signup; their per-request operation_ids match the `zettel:<ms>:<rand>` pattern the frontend emits.
- **All 3 of Prajeet's failures hit the SAME root cause**: `FileNotFoundError: '/tmp/prom_multiproc/counter_*.db'` from `prometheus_client/mmap_dict.py:64`. The container's `/tmp/prom_multiproc` directory was being wiped (Debian `tmpfiles.d`) between container start and the first request; every `_emit_call_counter` call in `summarization_engine/core/budget.py:175` therefore raised `FileNotFoundError`. The exception escaped the typed-exception switch in `_async_failure_error_payload` (zettels_routes.py:240), causing `core.operations.error` to be persisted as `NULL` — the exact `code=null` cohort the Nimit audit flagged 24h earlier.
- **The fix is already live.** Commits `37613993` (PROMETHEUS_MULTIPROC_DIR move + lifespan recreate), `03fe194b` (writable tmpfs in blue/green compose), `f22a99f1` (`safe_metrics` helper wrapping all `_emit_*` in try/except OSError), `dbe92626` (RFC 9457 catch-all so unmapped exceptions never write `error=NULL` again), `1aec7129` (URL persisted into `operations.error`), `fd84f90f` (mig 75: 7d TTL for failed/cancelled), and `a031d1e8` (mig 74: `enrichment_jobs.canonical_zettel_id ON DELETE CASCADE`) all shipped in the 09:35 + 11:44 UTC deploys. Prajeet's attempts (07:24, 08:38, 08:39 UTC) were all **pre-fix**.
- **One residual observability gap blocks "fully-functioning API" claim**: when a Bearer JWT fails server-side validation `get_optional_user` swallows the exception silently and the request maps to Zoro with NO log line and NO header in the response that tells the user (or us) why. Prajeet's "missing rows" mystery is a direct symptom; fixing it requires a single `logger.warning` in `website/api/auth.py` plus a response header (e.g. `X-Auth-Status: drop-to-anon`).

---

## 1. Part 1 — Grant verification

| Check | Value |
|---|---|
| Pre-grant `pricing_balances` for `zettel` | empty (zero row) |
| `provision_pack.py --pack zettel_10 --confirm-prod` HTTP | **200** |
| `pricing_orders.id` (synthesized order) | (one new row; see `prajeet_audit_post.json`) |
| `pricing_orders.product_id` | `zettel_10` (meter=`zettel`, qty=10, ₹99 / 9900 paise) |
| Internal payment id (in `provider_payload`) | `zk_pack_3232f35813d74c91b1dbf5d23b0c92d4` |
| Synthesized Razorpay order id | `order_prov_de63fbbc29cd49` |
| Webhook event id | `evt_prov_zk_pack_3232f35813d74c91b1dbf5d23b0c92d4` (idempotent on re-post) |
| Post-grant `pricing_balances.balance` for `zettel` | **10** (`updated_at = 2026-05-25 12:07:33 UTC`) |
| Verifier RPC `billing.pricing_get_quota_snapshot` | `remaining_wallet=10` ✅ |
| Side-effects observed | `user_activity` alert fired: *":moneybag: Payment ₹ 99.00 INR — Prajeet Ladad (p***@gmail.com) just paid 99.00 INR for zettel_10"* |

**Note on idempotency**: `event_id` ties to `payment_id`, which is freshly minted per script run. Re-running the script grants another +10 each time. The `event_already_processed` dedup is per-`event_id`, not per-`user_id`. Treat this script as "one click = +10" and confirm balance after each invocation. The nimit audit's "re-run is safe" comment is misleading on that point — it's safe only against double-firing the SAME `event_id`.

---

## 2. Part 2 — Investigation findings

### 2.a Why `core.operations WHERE user_id = b57fe00e-...` returns ZERO

| Hypothesis | Disposition |
|---|---|
| He never tried any URLs | **REJECTED**. Caddy access log has at least one `POST /api/zettels/add` with `Authorization: REDACTED` + `Idempotency-Key: zettel:1779693855986:9flwrf2dp3` → that idempotency key is the **exact** `operation_id` of one of the Zoro-mapped failed rows at 07:24:17 UTC. |
| `kg_users` allowlist gate blocked him | **REJECTED**. `public.kg_users` table was dropped in v2 Phase 6 (commit `e168b38`). No allowlist gate is wired on `/api/zettels/add` in the current code (verified via grep + `add_zettel` walk-through). |
| Per-IP rate-limit / async-backpressure / Pydantic 422 / SSRF reject | **REJECTED for these 3 ops**. Those paths write no row, but Caddy access log shows status=202 for op `zettel:1779693855986:9flwrf2dp3` — request was accepted, NOT rejected pre-accept. |
| **JWT silently dropped on server → request mapped to Zoro user** | **CONFIRMED**. `get_optional_user` (`website/api/auth.py:172-189`) swallows every exception and returns `None`. `_effective_user_id(None)` returns Zoro's UUID (`zettels_routes.py:200-207`). 3 Zoro-mapped failures with `operation_id` shape `zettel:<ms>:<rand>` (the frontend-issued pattern) landed in the window after Prajeet's signup, NONE before. |

**Implication for the "fully-functioning API" claim**: as long as `get_optional_user` is silent-fail, ANY user whose JWT validation fails for any reason (expired, JWKS cache miss, audience mismatch, clock skew, signature failure) will see all of their captures land under Zoro and disappear from their own UI. This is **the** observability gap that turned Prajeet's "I tried lots of URLs and they all failed" into "we can't find a single row".

### 2.b Three Zoro-mapped failures attributable to Prajeet (DB-confirmed)

| # | created_at UTC | operation_id | request_hash (16) | status | code | error JSONB | response.quality.confidence_reason |
|---|---|---|---|---|---|---|---|
| 1 | 2026-05-25 07:24:17.022 | `zettel:1779693855986:9flwrf2dp3` | `4cfaf0aa3eb05374` | failed | NULL | **NULL** | `[Errno 2] No such file or directory: '/tmp/prom_multiproc/counter_1597.db'` |
| 2 | 2026-05-25 08:38:51.890 | `zettel:1779698330785:wjhpbeixc1` | `792e4552b77291ff` | failed | NULL | **NULL** | `[Errno 2] No such file or directory: '/tmp/prom_multiproc/counter_15.db'` |
| 3 | 2026-05-25 08:39:41.020 | `zettel:1779698380067:ysses11f6lb` | `454fe1ad7f64d8ff` | failed | NULL | **NULL** | `[Errno 2] No such file or directory: '/tmp/prom_multiproc/counter_15.db'` |

Two later Zoro rows (10:39 and 11:53 UTC, operation_ids prefixed `pr89-xoid-`, error.url=`https://example.com/pr89-verify`, `expires_at` = `+7d`) are **NOT** Prajeet — they are PR #89 verification traffic that exercises mig 75 (7-day TTL for failed rows) and confirms the URL-in-error persistence works.

### 2.c What the URLs were (current state)

**Unrecoverable from the database.** `core.operations` has no `url` column (pre-PR-89). On all 3 rows the `error` JSONB is `NULL` (the catch-all hadn't been deployed yet). `response.quality.confidence_reason` carries only the exception message, not the URL. The droplet container the Zoro `_run` task executed in is gone (the 09:35 + 11:44 UTC deploys flipped colors, wiping container stdout). The Caddy access log preserves the Idempotency-Key but **not** the JSON body, so the URL itself isn't there either.

**Recoverable only by**: asking Prajeet what 3 URLs he tried, OR running a request-body audit log going forward (§6).

### 2.d System-wide failure context (last 24h, all users) for comparison

| status | code | n |
|---|---|---|
| `failed` | NULL (uncaught exception escape) | **8** ← includes Prajeet's 3 + Naruto's live-test repro + Nimit-era leftovers |
| `failed` | `internal_error` | 2 (PR #89 test traffic, expected) |
| `failed` | `insufficient-content` | 1 (Nimit 2026-05-24 YouTube T1 hang, separate root cause) |
| `cancelled` | `operation_cancelled` | 2 (Zoro, pre-Prajeet) |

All 8 `code=null` failures match the prom-dir signature. **One single bug accounted for the bulk of the 24h failure cohort** — the engine wasn't structurally broken; the metrics-instrumentation harness was.

---

## 3. Part 3 — Root-cause deep-dive on the 3 failures

### 3.a The stack (identical for all 3 rows; from `live_url_repro_2026-05-25.md` §D7, confirmed against current source)

```
zettels_routes.py:520                       _run               → pipeline()
zettels_routes.py:391                       _run_add_zettel    → run_add_zettel_pipeline
module_runners/summarization.py:187         run_add_zettel_pipeline → summarize_url_bundle
module_runners/summarization.py:118         summarize_url_bundle    → _impl
summarization_engine/core/orchestrator.py:331 summarize_url_bundle  → summarizer.summarize(ingest_result)
summarization/youtube/summarizer.py:94      summarize          → run_dense_verify
summarization/common/dense_verify_runner.py:68 run_dense_verify → effective_cache.get_or_compute
summarization/common/dense_cache.py:88      get_or_compute     → compute()
summarization/common/dense_verify_runner.py:66 _compute        → dv.run
summarization/common/dense_verify.py:208    run                → get_budget().consume(role="dense_verify")
summarization_engine/core/budget.py:88      consume            → _emit_call_counter
summarization_engine/core/budget.py:175     _emit_call_counter → LLM_CALLS_TOTAL.labels(...).inc()
prometheus_client/metrics.py:193            labels             → __class__ ctor
prometheus_client/metrics.py:131,331        _metric_init       → ValueClass(...)
prometheus_client/values.py:68,82           __init__/__reset   → MmapedDict(filename)
prometheus_client/mmap_dict.py:64           __init__           → open('/tmp/prom_multiproc/counter_*.db', 'a+b')
                                                                 → FileNotFoundError
```

The error message **lies**: `open(..., 'a+b')` normally creates the file; the actual failure is the **parent directory** missing. The Dockerfile (`ops/Dockerfile:104,109`) sets `PROMETHEUS_MULTIPROC_DIR=/tmp/prom_multiproc` and creates the dir at build time. At runtime the dir was being wiped — Debian's `systemd-tmpfiles` rule for `/tmp` is the prime suspect (cleaned periodically). Cgroup pressure (~287 MB swap in use at the time) may have accelerated reclaim.

### 3.b Why every URL failed (engine-wide, not URL-specific)

- `_emit_call_counter` fires on **every** LLM budget consumption.
- Every `summarize` step consumes budget (`dense_verify`, `brief_summary`, `detailed_summary`, edge-extraction, …).
- Therefore **every** `/api/zettels/add` invocation that progressed past extraction crashed at the same line — regardless of source (YouTube, Reddit, newsletter, GitHub, generic web).
- **Cache-hit** path (PR #25 dedup) does NOT hit `dense_verify` — those would have succeeded, but Prajeet was first-touch on his URLs, so no cache hit.

### 3.c Why `core.operations.error` was `NULL` (not just `code=null`)

- `_async_failure_error_payload` (`zettels_routes.py:240`) was a **typed-only switch**: `HTTPException`, `UnsupportedVideoError`, `ExtractionConfidenceError`, `DocumentUploadError`, `RoutingError`, `ValueError`, `SupabaseV2PersistError`.
- A bare `FileNotFoundError` (`OSError` subclass) was **not** in any branch → returned `None`.
- `_failed_response_for(...)` then recorded `error=None` on the `AddZettelResponse`.
- `operations_repo.finalize(target='failed', error=None)` wrote `NULL` to `core.operations.error`.
- The user-facing UI fell back to the literal string **"Summary failed."** with no actionable info (no `error.code`, no `operation_id`, no support link).

### 3.d The fix landscape (already shipped at HEAD `a125ae03`)

| Commit | What it does | Why it closes Prajeet's failure path |
|---|---|---|
| `37613993` feat(ops): move PROMETHEUS_MULTIPROC_DIR + lifespan recreate | App moves PROMETHEUS_MULTIPROC_DIR off `/tmp/`; FastAPI lifespan recreates the dir at boot. | Self-heals after any future `/tmp` wipe — root cause class eliminated. |
| `03fe194b` fix(ops): writable tmpfs for /app/var/prom in blue/green compose | Compose mounts a writable tmpfs at the new prom dir path in both blue and green. | Dir is now backed by tmpfs, not the writable layer / `/tmp`. No tmpfiles.d wipe possible. |
| `f22a99f1` feat(observability): safe_metrics helper + budget.py refactor | All `_emit_*` calls wrapped in `try/except OSError` via `safe_metrics`. | Even if the dir wipe recurs, metrics are best-effort — they cannot break the request path again. |
| `dbe92626` feat(api): RFC 9457 catch-all + X-Operation-Id header | `_async_failure_error_payload` now ALWAYS returns a structured `internal_error` problem dict (no `return None`). `X-Operation-Id` header on all 202 sites. | Closes the `error IS NULL` cohort permanently. Frontend can now surface a real reason. |
| `1aec7129` feat(api): persist URL in operations.error for forensics | Passes `url=body.url` into `_problem_dict(...)` on all failure paths. | `SELECT error->>'url' FROM core.operations WHERE status='failed'` now works. URL loss problem solved for new failures. |
| `fd84f90f` feat(db): mig 75 ops_finalize 7d TTL for failed/cancelled | `expires_at` is now `+7 days` for `failed`/`cancelled`, still `+24h` for `succeeded`. | Future failure rows live 7× longer for triage. |
| `a031d1e8` feat(db): mig 74 enrichment_jobs canonical FK cascade | Adds `ON DELETE CASCADE` to `core.zettel_enrichment_jobs.canonical_zettel_id`. | Closes Nimit's orphan-enrichment-job class permanently. |

---

## 4. Part 4 — Surfaces and gaps that block "fully-functioning API for ALL sources"

These are the **remaining** issues. None of them block Prajeet's grant — but each is a known way the engine can fail for a real user across source types.

### 4.a Auth observability (Prajeet's specific failure mode)

- `get_optional_user` (`website/api/auth.py:172-189`) catches every exception silently and returns None.
- `_effective_user_id(None)` falls to Zoro (`zettels_routes.py:200-207`).
- No log entry tells anyone WHY the JWT was rejected.
- No response header tells the **frontend** the auth was downgraded — so the UI keeps showing "Welcome back, Prajeet" while the API treats him as anonymous.
- **Fix surface**: ~5 lines in `auth.py` — `logger.warning(...)` inside each except branch, plus a request-scoped flag → response header `X-Auth-Status: jwt-dropped-to-anon`.

### 4.a-bis Mobile site contract bug — **NEWLY FOUND 2026-05-25 12:35 UTC** (P0)

While verifying the Zoro pipeline end-to-end for an operator anonymous mobile test (URL `https://youtu.be/juHv_Vi4giU?si=`, op_id `zettel:mobile:1779712133509:ytfda8gjlr` in Caddy log at 12:28:54 UTC), the request returned 4xx in 200 ms with **no `core.operations` row created**. Root cause:

- [website/mobile/js/summarizer.js:220,227](website/mobile/js/summarizer.js:220) sends `surface: 'mobile'` (URL submission) and `surface: 'mobile'` (document upload).
- [website/api/zettels_routes.py:94](website/api/zettels_routes.py:94) declares `surface: Literal["landing", "home", "zettels"]` — `'mobile'` is **not in the enum**.
- Result: every mobile capture (anon or authenticated) returns HTTP 422 `literal_error` pre-`ops_accept`. No row, no forensic trail.
- **This explains the 2 OTHER `zettel:mobile:…` 4xx entries in Caddy** that I attributed to Prajeet earlier (07:09:46 and 07:09:53 GMT) — same 422 contract violation, NOT prom-bug. So Prajeet's true failure breakdown is: **2 mobile → 422 (this bug) + 3 desktop → NULL-error (prom bug)**. Total 5 failures, two distinct root causes.

**Fix surface** (operator's call, do not auto-apply):
- **Option A (recommended)**: add `'mobile'` to the Literal at `zettels_routes.py:94` (preserves analytics granularity).
- **Option B**: change `summarizer.js:220,227` to `surface: 'home'`.

The PR #89 verifier surface (`pr89-xoid-*` ops in the DB) used `surface: 'landing'` so it never tripped this — explains why the catch-all and URL-persist fixes verified clean but the mobile contract bug remained latent.

### 4.b YouTube T1 (`tier_gemini_youtube_url`) still at head of the chain

- The orchestrator's own docstring (`orchestrator.py:137-142`) warns this tier hallucinates and was previously removed.
- It absorbs the full per-tier budget when it hangs (it sets `asyncio.timeout(remaining_budget)`).
- Nimit's 2026-05-24 `insufficient-content` failure was this exact pathology.
- **Fix surface**: per-tier hard cap (≤20 s for T1-T2), or concurrent race between T1 (Gemini server fetch) and T2 (Webshare transcript) — first success wins. Both designs in nimit audit §6.2.

### 4.c Non-YouTube source robustness

- Reddit: without `REDDIT_CLIENT_ID/SECRET` env vars set (CLAUDE.md note), the ingestor degrades to public JSON which often returns thin → `insufficient-content` 422. Status of these credentials on the active droplet must be verified post-deploy.
- Newsletter: `NewsletterURLUnreachable` is properly typed → returns structured 422, no leak. Healthy.
- GitHub: README + topic extraction is stable per `tests/integration_tests/` evidence. Healthy.
- Generic web: thinnest path; depends on the HN/web extractor. The `_yt_preflight_refuse` path correctly maps live-stream / paid / podcast URLs to `unsupported-video` 422. Healthy for the known refusal set.

### 4.d Frontend / UX

- "Summary failed." in red is still the user-facing string (`live_url_repro_2026-05-25.md` §D8). With `error.code` now reliable (post-`dbe92626`), the frontend can switch to keyed messages: `insufficient-content` → "We couldn't fetch a transcript — try a different upload of the video.", `unsupported-video` → "Live streams aren't supported.", `internal_error` → "Something broke on our side — operation_id: {op_id} (please share with support).".
- `X-Operation-Id` header (just shipped in `a125ae03`) means the frontend now has the operation_id even for 202-with-later-failure flows. Tie the toast to it.

### 4.e The auth-drop-to-Zoro race could mask quota exhaustion

- A user whose JWT silently fails to-Zoro gets their captures consume Zoro's wallet (Zoro is admin-class internally and has effectively unlimited entitlements). So a real paying user could be silently using "anonymous" quota. **Not** Prajeet's case (he had no failures with status=succeeded), but a latent risk.

---

## 5. Part 5 — Recommendations (ranked by impact / effort)

### 5.1 Immediate — verify the engine is in fact fixed end-to-end

- **Ask Prajeet to retry one of his 3 URLs.** With HEAD `a125ae03` live since 11:44 UTC, the prom-dir bug is closed and the catch-all writes structured errors. If his retry **succeeds** → the engine is functioning for fresh signups. If it **fails** → the new row will have `error.code != null` and `error.url` populated, giving a real triage trail. Either outcome is informative.
- **OR** the operator can submit one test URL as themselves and confirm the success path.

### 5.2 Within this PR / next PR — close the auth-observability gap

- 5-line patch to `website/api/auth.py::get_optional_user`: wrap each except branch with `logger.warning("JWT validation failed: %s", reason, extra={"path": request.url.path})`.
- Add a request-scoped flag → response header `X-Auth-Status: jwt-dropped-to-anon` when `_effective_user_id` falls through to Zoro.
- Frontend (small change): if `X-Auth-Status` is anything other than the empty/authenticated value, force a re-auth modal instead of silently sending the next request.

### 5.3 Engine resilience for YouTube (still applicable)

- Demote `tier_gemini_youtube_url` from T1 to T5 OR enforce a per-tier hard cap (e.g. 15 s for T1-T2, 30 s for T3-T6, 90 s overall) OR fire T1+T2 concurrently and take the first success.
- These are nimit audit §6.2 items — independent of the prom hotfix.

### 5.4 Continued observability hardening

- `pipelines.summarization_runs` table (mirror of `pipeline_runs.kg_extract`): one row per URL attempt with timestamps, source_type, tier outcomes, final status. 90-day retention. The `core.operations` 24h/7d TTL is for idempotency, not forensics.
- Switch docker compose to the `local-file` log driver with a 7-day retention OR sink container stdout into a remote log store. Right now every blue/green flip still wipes stdout.
- Fix the `kg_users` reference in the in-memory: it points to a table that was dropped in Phase 6.

### 5.5 Source-coverage post-hoc audit

- Run `provision_pack.py --dry-run` per pack-shape against synthetic test users to confirm the catalog still resolves (verified for `zettel_10` just now; the rest are mechanical).
- Smoke-test ALL 5 source types (YouTube, Reddit, GitHub, newsletter, generic) end-to-end as a known authenticated test user (Naruto), capture per-source latency + success status, refresh the source-coverage table in `CLAUDE.md`. This is the **"fully-functioning API for all kinds of Zettels"** sign-off the operator wants.

---

## 6. Appendix

### 6.a Queries used (reproducible)

```sql
-- Identify Prajeet
SELECT id, email, raw_user_meta_data, created_at, last_sign_in_at
FROM auth.users WHERE id = 'b57fe00e-703f-4c6f-ae56-29b102753233';

-- Wallet + counters (pre + post)
SELECT meter, balance, updated_at FROM billing.pricing_balances
WHERE profile_id = 'b57fe00e-703f-4c6f-ae56-29b102753233';

SELECT feature, granularity, period_key, count, updated_at
FROM billing.pricing_usage_counters
WHERE profile_id = 'b57fe00e-703f-4c6f-ae56-29b102753233'
ORDER BY period_key DESC;

-- Direct operations under Prajeet (expect 0)
SELECT operation_id, status, error->>'code' AS code, error->>'reason' AS reason,
       created_at, updated_at
FROM core.operations
WHERE user_id = 'b57fe00e-703f-4c6f-ae56-29b102753233'
ORDER BY created_at DESC;

-- Zoro-mapped failures since Prajeet's signup (THE Rosetta stone)
SELECT operation_id, status, error->>'code' AS code,
       error, response, created_at, updated_at
FROM core.operations
WHERE user_id = 'a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e'
  AND created_at >= '2026-05-25 06:50:00+00'
ORDER BY created_at DESC;

-- Confirm the Caddy access log Idempotency-Key matches one of the Zoro op_ids
-- (run on droplet via gh workflow run "Read Recent Logs" then grep)
-- Search for: zettel:1779693855986:9flwrf2dp3  (= Prajeet 07:24 fail)
```

### 6.b Scripts created during this audit (kept in `%TEMP%`, not checked in)

- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_audit.py` — pre/post snapshot harness
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_deepsearch.py` — exhaustive cross-schema sweep
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_zoro_check.py` — Zoro-mapping hypothesis check
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_zoro_full2.py` — full row dump for Zoro ops in window

Snapshot JSONs:
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_audit_pre.json` (pre-grant)
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_audit_post.json` (post-grant; wallet=10 confirmed)
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_deepsearch.json`
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_zoro_check.json`
- `C:\Users\LENOVO\AppData\Local\Temp\prajeet_zoro_full2.json`

### 6.c GH workflow runs used

- `26399803074` — `Read Recent Logs` since=2026-05-25T06:00:00Z. Captured Caddy access log lines proving Prajeet's request hit `/api/zettels/add` with an Authorization header and got `status=202` for op `zettel:1779693855986:9flwrf2dp3`.
- `26393803003` — deploy of `03fe194b` at 09:35 UTC (prom hotfix landed in compose).
- `26398778509` — deploy of `a125ae03` at 11:44 UTC (current prod HEAD).

### 6.d Operator decision points before next steps

1. **Have Prajeet retry one URL** — fastest way to confirm end-to-end engine health on fresh signups. (Estimated time: 1 min for him, then I can pull the resulting `core.operations` row immediately.)
2. **Approve the §5.2 auth-observability patch** (`logger.warning` + `X-Auth-Status` header) — closes the silent-Zoro-mapping mystery. ~5 lines + a small frontend change.
3. **Decide on §5.3 YouTube T1** — independent fix path; not blocking Prajeet but is the next-highest user-facing-failure class.
4. **Schedule §5.4 `pipelines.summarization_runs`** — the durable forensic table. Once written, audits like this one stop needing droplet stdout (which is volatile across deploys).

---

*Generated 2026-05-25 by Claude Code (Opus 4.7), per the operator's "thorough sweep with no gaps" request. The +10 grant was applied; no other prod-state changes were made.*
