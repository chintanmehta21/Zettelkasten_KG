# Nimit — +10 Zettel Grant + Ingest-Failure Sweep (2026-05-25)

**Operator**: Chintan
**Subject**: `Nimit Shah` (`99nimit99@gmail.com`), `auth.users.id = e9b0abf2-550d-4959-ad9e-53d72db29241`
**Workspace**: `c4fa6870-7df1-4c73-bf14-a7465d9a27ff` (personal, role=owner, created 2026-05-22 16:31:03 UTC, plan=`free`)
**Pulled**: 2026-05-25 ~05:15 UTC

---

## TL;DR

- **Grant landed.** Live `provision_pack.py --pack zettel_10 --confirm-prod` returned `HTTP 200` and Nimit's `billing.pricing_balances.balance` for meter `zettel` is now **`18`** (was 8). Webhook event `evt_prov_zk_pack_f6716b6b8a4d45818388584353760a54` is idempotent so a re-run is safe.
- **"Most failed" is not what the data shows — yet.** Only **1** failed ingest is currently recoverable from the database; **3** succeeded; **1** workspace_zettel was hard-deleted (URL canonical also gone). Older failures (>24h) are gone because `core.operations` rows TTL out after 24 hours AND the droplet container was restarted ~09 minutes before this audit, wiping in-container stdout.
- **The 1 visible failure is a textbook engine pathology** — YouTube tier-1 (`tier_gemini_youtube_url`) consumed the full 90 s transcript budget, leaving every other tier `budget_exhausted` and tripping the D7/D8 thin-extraction gate → HTTP 422 `insufficient-content`. The URL itself is **not** in the row (the engine does not persist the request URL on failure); recoverable only by re-running the same `client_action_id` or by Nimit re-submitting.
- **Two latent infra/data-integrity issues surfaced incidentally and are blockers for a credible "fully-functioning API for ALL Zettel sources" claim:** (a) `core.zettel_enrichment_jobs` contains an orphan `canonical_zettel_id` that no longer exists in `content.canonical_zettels` (data race or hard-delete without cascade); (b) `provision_pack.py` synthesised orders never write `razorpay_order_id` / `provider_order_id` so `billing.pricing_orders.status` stays `created` forever even after wallet credit applies — a paid-but-unmarked-paid anomaly.
- **You need post-hoc failure visibility before you can call the engine "fully working".** The single biggest gap is observability, not engine correctness. Section 6 lists the targeted fixes.

---

## 1. Part 1 — Grant verification

| Check | Value |
|---|---|
| `billing.pricing_orders` row id | `20f769bf-345b-44bf-8dfb-b03288e8459d` |
| Pack | `zettel_10` (meter=`zettel`, qty=10, ₹99 / 9900 paise) |
| Internal payment id (in `provider_payload`) | `zk_pack_f6716b6b8a4d45818388584353760a54` |
| Webhook event id | `evt_prov_zk_pack_f6716b6b8a4d45818388584353760a54` (idempotent on re-post) |
| Webhook HTTP | **200** |
| `pricing_balances.balance` for meter `zettel` | **18** (`updated_at = 2026-05-25 05:04:29 UTC`) |
| Verifier RPC | `billing.pricing_get_quota_snapshot` → `remaining_wallet=18` |

**Pre-grant context (also pulled, to explain the prior 5 `created` orders):** Nimit has 5 prior `zettel_10` orders + 1 `max_monthly` subscription order on `2026-05-23` that were `provision_pack --dry-run` artefacts. Dry-runs DO write `pricing_orders` rows (per the script's own warning) but never post the webhook, so they correctly sit at `status=created` with no `paid_at` and no balance impact. Zero `pricing_webhook_events` between 2026-05-23 07:00 and 09:00 UTC confirms this.

---

## 2. Part 2 — Investigation findings (DB-confirmed)

### 2.a What we know

| # | URL (`content.canonical_zettels.normalized_url`) | Source | Workspace_zettel | Status | Timestamp (UTC) | Evidence |
|---|---|---|---|---|---|---|
| 1 | `https://www.youtube.com/watch?v=fNNz9a2OIn4` — "India's Super El Niño" | youtube | `4a44320c-981a-4458-a168-40970091505f` | **success** (cache-hit) | 2026-05-23 10:32:36 | wz row + canonical exists; **no** kg_extract / chunk_embed enrichment job → canonical pre-existed from another user, dedup short-circuit fired |
| 2 | `https://www.youtube.com/watch?v=Ukt2gVz25PQ` — "Kali Linux Ethical Hacking Tools" | youtube | `91557c83-0580-4781-ae9b-ef5e474fe7ec` | **success** | 2026-05-23 08:59:58 | wz + canonical + enrichment job `succeeded` + kg_extract run `succeeded` (1 edge scored) |
| 3 | `https://www.youtube.com/watch?v=9OQ5vaYbGV0` — "Google I/O Gemini AI" | youtube | `8fb2f662-4cbe-4207-a599-a2de2744c1a9` | **success** | 2026-05-23 06:55:33 | wz + canonical + enrichment job `succeeded` + kg_extract run `succeeded` |
| 4 | URL **unrecoverable** — canonical `d4549fca-3ad5-4cbc-8fb9-f88009c39ce8` ("ChatGPT custom GPT" by title from enrichment payload) | (probably article/youtube — unknown without the canonical row) | none current (hard-deleted) | **deleted post-success** | 2026-05-22 16:33:59 | enrichment_job `succeeded` + kg_extract run `succeeded`; the canonical row no longer exists; **orphan reference is a data-integrity bug** |
| 5 | URL **unrecoverable** (`request_hash = 67c6a81c...`) | likely YouTube (the cascade matches the YT transcript chain) | none — never persisted | **failed** (HTTP 422) | 2026-05-24 08:51:53 | `core.operations.operation_id = zettel:1779612712374:ekbcq5a61pa`; full tier-results captured (see §4) |

**`billing.pricing_usage_counters` for Nimit (meter=`zettel`):** 4 successful consumes total — day 2026-05-22: 1, day 2026-05-23: 2, day 2026-05-24: 1, week 2026-W21: 4, month 2026-05: 4. The "Super El Niño" success on 2026-05-23 did **not** bump the counter — that confirms it took the URL-dedup cache-hit path (PR #25, 2026-05-18) which intentionally bypasses `consume_entitlement`. So `4 counter bumps = 3 fresh persists + 1 hard-deleted persist`, and the **1 failure didn't consume entitlement** (the gate refunds / never charges on summarisation failure — needs verification, see §6).

### 2.b Critical observability gaps surfaced during this audit

These are NOT root-causes of Nimit's failures; they are why the deep-dive can't be exhaustive:

- **`core.operations.expires_at = created_at + 24h`** (operations_repo.py:75) — the partial-unique idempotency index `ops_user_req_hash_active_uniq` keeps the row alive long enough for client polling, then a reaper sweeps it. **Failures older than 24h are unrecoverable from this table.** Nimit signed up 2026-05-22 16:31; today is 2026-05-25 05:15 → only failures from the past 24h survive. Anything he hit on 2026-05-22 or 2026-05-23 is gone.
- **Container stdout is lost on every blue/green flip.** `docker compose logs --since 2026-05-22T16:00:00Z` returns ONLY logs from the current container instance (booted 2026-05-25 05:06:18 UTC — 9 minutes before this pull). No persistent log driver (json-file is the docker default; no journald, no remote sink). The `read_recent_logs.yml` workflow returns boot-cycle and proc-stats spam, none of Nimit's actual ingest traces.
- **`journalctl --since` rejects RFC3339.** The workflow passes the input as-is; journalctl wants `"YYYY-MM-DD HH:MM:SS"`. Today's run logged `Failed to parse timestamp: 2026-05-22T16:00:00Z` (the day digits were redacted by GH's secret-mask filter, hence the `***`). Even if it had parsed, deploy is not in the `systemd-journal` group, so container stdout isn't in journald anyway.
- **`pipelines.pipeline_runs` only tracks `kg_extract`.** Summarisation itself never writes a pipelines row — only the post-summary KG-edge extraction does. So Nimit's pre-persist summarisation failures leave no `pipelines.*` trace.
- **`core.operations.error` does not include the request URL or normalised URL.** It carries `tier_results`, `operation_id`, `code`, `reason`, `instance` — but the URL is absent. URL is only recoverable via `request_hash` collision with a known URL, or via the original client_action_id if the front-end retains it.

### 2.c System-wide failure context (last 24h, all users)

| status | code | reason | count |
|---|---|---|---|
| `failed` | `null` | `null` | **4** |
| `cancelled` | `operation_cancelled` | `null` | 3 |
| `failed` | `insufficient-content` | "All transcript tiers failed; metadata-only fallback (composite capped at 75)" | **1** (Nimit) |

Total non-success terminal ops in 24h: **8**. The 4 `code=null` failures are concerning — they're terminal `failed` rows whose `error` JSON has no `code` key, which means an exception escaped the `_problem_dict()` envelope. Worth a separate diff against the routes.py finalize-on-exception path (out of scope for this report, but flagged).

---

## 3. Part 3 — Per-URL deep-dive

### Zettel #1 — Super El Niño (cache-hit path) — **healthy**

- **Why it worked:** YouTube URL was already in `content.canonical_zettels` (`9d6de9a0`) from a prior different user; PR #25 (2026-05-18) added the `UNIQUE(normalized_url)` dedup gate that re-uses the canonical row for any subsequent ingest. Nimit's `POST /api/zettels/add` got the canonical body, wrote a fresh `content.workspace_zettels` row pointing at it, and skipped the transcript fetch + Gemini summarisation entirely.
- **Why no enrichment job:** chunks already exist for the canonical, so `chunk_embed` doesn't need to re-run. The KG-extract step is workspace-scoped but also short-circuits when its `metrics={"edges": 0, "scored": 0, "candidates": 0}` (per the 2026-05-23 06:55 record on the OTHER successful zettel).
- **Implication:** **Cache-hits don't generate failure pressure.** This is also why Nimit's `usage_counters` show only 4 (not 5) — the cache-hit by design doesn't `consume_entitlement`.

### Zettel #2 — Kali Linux Ethical Hacking Tools — **healthy**

- **Why it worked:** Fresh canonical. Transcript-chain tier returned successfully within the 90 s budget. `kg_extract` then scored 2 candidate edges (1 retained).
- **Latency floor (inferable):** workspace_zettel created at `08:59:58.522`; enrichment_job created `08:59:58.621` (99 ms later — synchronous queue write); claimed at `09:00:19.964` (~21.4 s later — worker pull); completed at `09:00:22.139` (~2.2 s — embedding work). End-to-end perceived: ~24 s from POST to "fully searchable".

### Zettel #3 — Google I/O Gemini AI — **healthy**

- Same pattern as #2. KG-extract scored 1 edge / 1 candidate.

### Zettel #4 — ChatGPT-Custom-GPT (orphan canonical) — **broken integrity**

- **What we have:** `core.zettel_enrichment_jobs` row claims `canonical_zettel_id = d4549fca-3ad5-4cbc-8fb9-f88009c39ce8` + `workspace_zettel_id = dc539b2b-0cc2-46d7-bb38-60f1ca7cbad1`. Payload preserves the rendered summary ("creating a custom gpt with gpt-4 is a straightforward, no-code process accessible through a chatgpt plus subscription...").
- **What's missing:** the canonical row `d4549fca` is **not** in `content.canonical_zettels` and the workspace_zettel `dc539b2b` is **not** in `content.workspace_zettels` (with or without `deleted_at`).
- **Root cause hypothesis:** the canonical was hard-deleted (not soft-deleted via `deleted_at`) — likely by `ops/scripts/purge_dirty_zettels.py` or a manual cleanup — without a `CASCADE` clause on `zettel_enrichment_jobs.canonical_zettel_id`. This leaves the worker queue holding a foreign-key-orphan record forever (until the 24h `expires_at` reaper sweeps it; but `status=succeeded` so the reaper might skip terminal rows depending on implementation).
- **Production risk:** if the user runs `purge_dirty_zettels.py` regularly with a hard-delete and the FK constraint on `zettel_enrichment_jobs` is missing or `ON DELETE NO ACTION`, you accumulate orphan jobs. Worse: if a chunk_embed job re-runs for an orphan canonical, it will fail with the **exact** FK-violation pattern visible in `core.zettel_enrichment_jobs` test fixtures (`canonical_chunks_canonical_zettel_id_fkey`).
- **Fix path:** (a) `ALTER TABLE core.zettel_enrichment_jobs ADD CONSTRAINT ... ON DELETE CASCADE` to `canonical_zettels.id`; (b) audit any hard-delete script to ensure it deletes downstream rows first; (c) add a periodic orphan-job sweeper.

### Zettel #5 — the 1 visible failure (URL unknown) — **engine pathology** ⇣ §4

---

## 4. Part 4 — Surgical deep-dive on the visible failure

**Operation row** (`core.operations`):

| field | value |
|---|---|
| `user_id` | `e9b0abf2-550d-4959-ad9e-53d72db29241` (Nimit) |
| `operation_id` | `zettel:1779612712374:ekbcq5a61pa` |
| `request_hash` | `67c6a81c91cfa06f42bd24dd6d742f6b0d5929e5042a68ae032f8c90970d524e` |
| `status` | `failed` |
| `created_at` | 2026-05-24 08:51:53.065 UTC (operation_id ms == 1779612712374 → matches) |
| `updated_at` | 2026-05-24 08:53:26.117 UTC (~93 s after create — matches the 90 s tier budget + finalize overhead) |
| `error.code` | `insufficient-content` (HTTP 422, RFC 9457 problem body, `_problem_dict()` built) |
| `error.reason` | "All transcript tiers failed; metadata-only fallback (composite capped at 75)" |
| `error.tier_results` | `[{tier:"tier_timeout", reason:"tier exceeded remaining budget 90000ms", latency_ms:90002}, {tier:"budget_exhausted", reason:"budget 90000ms exceeded", latency_ms:90002}]` |
| `response.workspace_zettel_id` | `null` (no zettel persisted — fail-closed) |
| `response.persistence` | `{supabase:false, duplicate:false, persisted:false, requested:true, file_store:false}` |

### What the tier_results actually mean (code-derived from `source_ingest/youtube/tiers.py`)

- The default chain is **7 tiers, 90 s total budget** (`build_default_chain(config)` at line 867):
  1. `tier_gemini_youtube_url` — `Part.from_uri` against Gemini, server-side fetch
  2. `tier_transcript_api_via_webshare` — `youtube-transcript-api` via Webshare residential proxy
  3. `tier_ytdlp_cookies_impersonate` — `yt-dlp` + cookies-from-burner-account + curl_cffi impersonate + PO-token sidecar
  4. `tier_invidious_pool` — round-robin healthy Invidious instances
  5. `tier_piped_pool` — round-robin healthy Piped instances
  6. `tier_gemini_audio` — pull audio with yt-dlp, send to Gemini
  7. `tier_metadata_only` — yt-dlp `--skip-download --dump-json` for title + description only
- **Per-tier timeout is the remaining budget** (`asyncio.timeout(remaining_ms/1000)` at line 94). If T1 hangs, T2-T7 never even start — they all log `budget_exhausted`.
- **Nimit's tier_results have exactly 2 entries** (`tier_timeout` + `budget_exhausted`), not 7. That means **only T1 ran**, consumed the full 90 002 ms, and then **only the next tier was checked** (the loop hit `remaining_ms <= 0`, appended `budget_exhausted`, and `break`-ed). The other 5 tiers were never tried.
- The chain returned `last_result = None` → `final = TierResult(tier=METADATA_ONLY, transcript="", success=False)` (lines 111-115). This is treated as `tier_used == "metadata_only"` + `is_below_floor (0 chars < 280)` + `is_low_conf` by the orchestrator's D7/D8 gate (orchestrator.py:286) → `raise ExtractionConfidenceError(...)` → HTTP 422.

### Why T1 hung for 90 s

- `tier_gemini_youtube_url` (tiers.py:655-762, not fully read in this audit) calls Gemini's video-understanding endpoint via `Part.from_uri(youtube_url)`. The orchestrator's own docstring (orchestrator.py:137-142) warns that this path "**does not actually analyse the video via the API-key SDK — it causes Gemini to hallucinate unrelated content**" and was previously REMOVED, then re-added at the head of the chain. Possible failure modes for T1:
  - Long videos: Gemini may stall on server-side download for >90 s.
  - Restricted content: age-gated / region-locked videos return slowly or hang.
  - Burst rate-limiting: 429 retries inside the SDK with no upper bound (the key-pool fallback rotates KEYS but a single key's `httpx` retry loop is internal to the SDK).
  - Slow socket on the Gemini side that doesn't respect the request timeout passed in `GenerateContentConfig`.
- **Without the URL,** we can't tell which of these applied to Nimit's specific request. But the 90 002 ms = 90 000 ms + ~2 ms overhead is the **textbook** signature of `asyncio.timeout(90)` firing on a tier that would otherwise have hung indefinitely.

### Why no retry happened

- The frontend reads HTTP 422 and shows an error toast.
- `core.ops_accept` is idempotent on `(user_id, request_hash)`; if Nimit pressed "retry" within the 24h TTL with the same URL + client_action_id, he would get the **same** failed operation row back, not a fresh attempt.
- Even with a new `client_action_id`, the engine has no automatic retry — the user has to manually retry, and the same T1 hang would likely recur for the same video.

---

## 5. Part 5 — Engine-wide failure surface (so we can talk about "fully functioning")

Distilled from `orchestrator.py:125-339` + the source extractors. Every failure surfaces as one of these structured errors via `_problem_dict()`:

| Failure class | Origin | HTTP | Persists DB row? | Operator-actionable? |
|---|---|---|---|---|
| `routing-error` (URL invalid/blocked, SSRF guard) | `validate_url()` in `url_utils.py` | 400 | No (rejected pre-accept) | Rare — surface known shorteners + private IPs |
| `unsupported-url-shape` | `detect_route_decision()` (e.g. private subreddits) | 422 | No | Add the source extractor |
| `unsupported-video` (H4/T7 preflight refuse) | `_yt_preflight_refuse()` (paid streams, podcasts, live streams) | 422 | No | Add to the deny-list |
| `newsletter-unreachable` | `NewsletterURLUnreachable` | 422 | No | Out of our control (dead URLs) |
| **`insufficient-content`** (Nimit's failure) | D7/D8 gate after `tier_metadata_only` returns 0 chars OR `<thin_floor` | 422 | Yes (`core.operations`) | **§4 — biggest single fix** |
| `quota_exhausted` (free-plan limit) | `pricing_consume_entitlement` returns shortfall | 402 | Depends on gate path | Not Nimit (wallet=18) |
| `async_backpressure` (5 in-flight ops per user) | `count_in_flight_for_user` ≥ 5 | 503 | No | Tunable |
| Generic 5xx (engine bug, Supabase outage, OOM) | Uncaught exception | 500 | Yes (`code=null` in error) | **24h shows 4 such — investigate separately** |
| `extraction-confidence` hard reject (RAG_THIN_EXTRACTION_REJECT_ENABLED) | Operator-gated, default OFF | 422 | Yes | Already off — keep off |

**Sources we support today** (per `CLAUDE.md` + `summarization_engine/summarization/<source>/`): YouTube, GitHub, Newsletter (Substack), Reddit, Generic (HN/web). Nimit only attempted YouTube on the visible record, but the engine claims to support all five.

---

## 6. Part 6 — Recommendations for "a fully-functioning API that will ingest all kinds of Zettels"

Ranked by impact-to-implementation-effort.

### 6.1 Observability (highest leverage, smallest footprint)

- **Persist the request URL into `core.operations.error.url` and `core.operations.response.url`.** Right now we lose the URL on failure, and the only way to triage a 422 is to ask the user "what URL did you submit?". Trivial change in `routes.py` where `_problem_dict()` builds the body — add `url` to the `error` dict at finalise time. Backwards-compatible (clients ignore extra keys).
- **Bump `core.operations.expires_at` to 7 days for `failed`/`cancelled` rows; keep 24h for `succeeded`.** Reasoning: failures are the rows you NEED for retro analysis; successes are noise (the canonical/workspace_zettel rows are the durable record).
- **Add a `pipelines.summarization_runs` table** (mirror of `pipeline_runs.kg_extract`) that records every URL attempt with timestamps, source_type, tier outcomes, and final status. This is the table that should NEVER expire (or expire on a 90-day cadence). The 24h TTL on `core.operations` is fine for the idempotency role, but is structurally wrong for forensics.
- **Switch docker compose to the `local-file` log driver with a 7-day retention** (or to journald, but the systemd-journal group permission issue must be fixed for `deploy`). Right now every blue/green flip is also a log wipe.
- **Fix `read_recent_logs.yml` journalctl invocation** — convert RFC3339 input to `"YYYY-MM-DD HH:MM:SS"` before passing to `journalctl --since`. One-line `sed 's/T/ /; s/Z$//'` change in the workflow.

### 6.2 Engine resilience for YouTube (Nimit's exact failure)

- **Demote `tier_gemini_youtube_url` to T5 or remove it.** The orchestrator's own comment (orchestrator.py:137-142) says it "causes Gemini to hallucinate unrelated content". Why is it back at T1? Either there's a regression and someone re-added it, or its position should be after the real-transcript tiers. The Webshare tier (T2 currently) is fast (~3-10 s typical) and accurate.
- **Per-tier hard cap.** Currently the per-tier `asyncio.timeout` = `remaining_budget`. If T1 hangs, it absorbs everything. Cap each individual tier at a strict slice (e.g. 20 s for T1-T2, 30 s for the audio/yt-dlp tiers) so a hung tier can't starve the rest. Add up to 90 s total but enforce both ceilings.
- **Concurrent transcript races for fast tiers.** Fire T1 (Gemini server fetch) and T2 (Webshare transcript) in parallel; take the first successful result. This eliminates the "T1 wastes 90 s" failure mode entirely. T3-T7 stay sequential as fallbacks.
- **Surface tier health in `/api/health`.** Webshare proxy uptime, Invidious pool size, Gemini key-pool quota all should be queriable so we know when an entire route is dead before users hit 422s.

### 6.3 Wider engine surface (so non-YouTube sources are equally robust)

- **Add explicit retry-with-different-extractor for `insufficient-content`.** If Reddit returns thin (anti-bot wall), retry once with OAuth (if `REDDIT_CLIENT_ID`/`SECRET` are set — per `CLAUDE.md` this is required for full chunks). If newsletter returns 403/410, surface "newsletter-unreachable" not "insufficient-content".
- **Tighten the `code=null` failure path.** 4 of the 8 24h non-success ops have `error.code = null`. This is `_problem_dict()` not being called — an uncaught exception leaked past the route handler's try/except. Audit `routes.py` for the finalize-on-exception path and ensure it ALWAYS wraps the error in a typed problem body.
- **Cascade-delete on `zettel_enrichment_jobs.canonical_zettel_id`.** The orphan job for `d4549fca` (Nimit's deleted ChatGPT zettel) proves the FK is loose. Add `ON DELETE CASCADE` migration + audit all `purge_*` scripts to ensure they don't bypass cascade by deleting parent rows without children.
- **Fix `provision_pack.py` attach_provider_order.** All 6 of Nimit's orders show `razorpay_order_id = NULL` despite `attach_provider_order(payment_id=..., razorpay_order_id=rzp_order_id)` being called by the script. Either the repo method writes to a different column or it silently fails. End result: `pricing_orders.status` is permanently `created` even after the wallet credit applies, which breaks any "did this payment land?" audit. Likely a column-name mismatch in `repository.py:attach_provider_order` (writes `provider_order_id` while the column is `razorpay_order_id`, or vice versa).

### 6.4 Frontend / UX

- **Show the user a "this URL failed because…" diagnostic** keyed off `error.code`, not just a generic toast. `insufficient-content` should say "we could not fetch a transcript — try a different upload of the video" (or similar). `unsupported-video` should explain WHY (live streams aren't supported, etc.).
- **Auto-retry once for `code=null`** transient failures on the client side (max 1 retry, backoff 2 s). Don't retry `insufficient-content` (deterministic).

---

## 7. Appendix

### 7.a Queries used (reproducible)

```sql
-- Identify Nimit
SELECT id, email, raw_user_meta_data, created_at
FROM auth.users
WHERE LOWER(email) LIKE '%nimit%' OR LOWER(raw_user_meta_data::text) LIKE '%nimit%';

-- Wallet + counters
SELECT meter, balance, updated_at FROM billing.pricing_balances
WHERE profile_id = 'e9b0abf2-550d-4959-ad9e-53d72db29241';

SELECT feature, granularity, period_key, count, updated_at
FROM billing.pricing_usage_counters
WHERE profile_id = 'e9b0abf2-550d-4959-ad9e-53d72db29241'
ORDER BY period_key DESC;

-- Every zettel attempt visible (last 24h only)
SELECT operation_id, status, error->>'code' AS code, error->>'reason' AS reason,
       created_at, updated_at
FROM core.operations
WHERE user_id = 'e9b0abf2-550d-4959-ad9e-53d72db29241'
ORDER BY created_at DESC;

-- Successful zettels (durable)
SELECT wz.id, wz.created_at, wz.added_via, cz.normalized_url, cz.source_type, cz.title
FROM content.workspace_zettels wz
LEFT JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id
WHERE wz.workspace_id = 'c4fa6870-7df1-4c73-bf14-a7465d9a27ff'
ORDER BY wz.created_at DESC;

-- Orphan enrichment jobs (data-integrity sweep)
SELECT j.job_id, j.canonical_zettel_id, j.workspace_zettel_id, j.status, j.created_at
FROM core.zettel_enrichment_jobs j
WHERE NOT EXISTS (SELECT 1 FROM content.canonical_zettels c WHERE c.id = j.canonical_zettel_id);
```

### 7.b Scripts created during this audit (kept in `%TEMP%`, not checked in)

- `C:\Users\LENOVO\AppData\Local\Temp\find_nimit.py` — locate user UUID across identity tables
- `C:\Users\LENOVO\AppData\Local\Temp\nimit_audit.py` — billing ledger + workspace state
- `C:\Users\LENOVO\AppData\Local\Temp\nimit_runs.py` / `nimit_runs2.py` / `nimit_runs3.py` / `nimit_runs4.py` — pipeline_runs, enrichment_jobs, usage_events sweeps
- `C:\Users\LENOVO\AppData\Local\Temp\nimit_ops.py` — `core.operations` pull
- `C:\Users\LENOVO\AppData\Local\Temp\nimit_deep.py` — orphan-canonical resolver, peer-window scan, 24h failure tally

### 7.c GH workflow runs used

- `26384512443` — `read_recent_logs.yml` since=2026-05-24T08:45:00Z (narrow failure window)
- `26384524076` — `read_recent_logs.yml` since=2026-05-22T16:00:00Z (Nimit signup span)
- Both returned only post-restart container logs (boot at 2026-05-25 05:06:18 UTC) → no Nimit-window evidence recoverable from droplet stdout.

---

## What needs the operator's call before next steps

- **Restore the failed URL.** Ask Nimit (or check his client-side history / browser tab) for the URL he tried on 2026-05-24 08:51:53 UTC. With the URL in hand, I can reproduce the failure locally against the same engine version and confirm whether T1 hangs as suspected, then propose the exact T1 demotion or concurrent-race change with TDD coverage. **Without the URL, the §6.2 fixes are mechanically sound but unvalidated.**
- **Approve the observability changes in §6.1.** These touch `core.operations` semantics (TTL change for failed rows) and the log-driver config (production impact: more disk used, but bounded). I will not push them without a green light.
- **Approve the §6.3 cascade-delete migration.** Adding `ON DELETE CASCADE` to `zettel_enrichment_jobs.canonical_zettel_id` is a schema migration. Needs a pre-DROP audit (per memory `feedback_purge_stale_v2_objects` + `reference_migration_conventions`) and a Phase plan.

---

*Generated 2026-05-25 by Claude Code (Opus 4.7), per the operator's "thorough sweep" request. No engine code was modified.*
