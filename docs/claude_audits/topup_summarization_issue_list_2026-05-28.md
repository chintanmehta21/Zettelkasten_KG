# Naruto Topup + Summarization API Issue List — 2026-05-28

## TL;DR

- The "81 zettels / 88 estimate / 7 paywall drops" framing **understates** the original gap. The actual original ingestion delta was **13 missing canonicals** (32% of the 41-URL topup).
- A fresh **re-run today at 12:35Z** under proper API keys reduced it to **2 persistent external-publisher failures**. The other 11 were transient (Gemini 429 storm + Reddit OAuth fallback rate-limit cascading during the original 4-way concurrent run).
- **3 latent production-summarization-API issues** also surfaced in droplet logs (unrelated to the topup itself).

---

## 1. Topup reconciliation

Source script: `docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py` runs `run_add_zettel_pipeline` **in-process** — Gemini calls go local→Google; **the droplet is bypassed**.

### Original ingestion state (before today's re-run)

Read-only Supabase query (`_diag_topup_supabase_reconcile.py`):

| Section | Listed | Found in v2 | Missing | Hit rate |
|---|---:|---:|---:|---:|
| Newsletter | 12 | 11 | 1 | 92% |
| Web | 10 | 8 | 2 | 80% |
| GitHub | 10 | 8 | 2 | 80% |
| **Reddit** | **8** | **0** | **8** | **0%** |
| Arxiv-like | 1 | 1 | 0 | 100% |
| **Total** | **41** | **28** | **13** | **68%** |

The "81 vs 88 = 7" reconciles as: 28 ingested topup canonicals (13 missing) **plus** ~6 that ingested but fell below the freeze script's `len(ai_summary) > 2000` threshold and were filtered from the manifest.

### After today's re-run (12:35–12:41Z, concurrency=4)

| Metric | Count |
|---|---:|
| Succeeded | 39 |
| Cache-hit (dedup short-circuit) | **0** ← see Issue C below |
| Failed | 2 |

The 8 Reddit URLs all succeeded on retry, indicating the original 8/8 Reddit failure was **transient**, not a structural extractor bug. The two persistent failures are external publisher blocks.

---

## 2. The 2 persistent failures (post-retry)

| # | URL | Section | Sub-module | Error | Latency | Verdict |
|---|---|---|---|---|---:|---|
| 1 | `densediscovery.com/issues/381` | newsletter | **Generic-web extractor (`httpx` fetch)** | `HTTPStatusError: 403 Forbidden` | 28.6 s | **Publisher anti-bot block.** Site refuses the fetcher's User-Agent / lacks JS to render. Not a Zettelkasten bug. |
| 2 | `lesswrong.com/.../irretrievability-…-asi` | web | **Generic-web extractor (`httpx` fetch)** | `HTTPStatusError: 429 Too Many Requests` | 32.4 s | **LessWrong rate-limited our IP** (we don't back off / no auth token). The 4-concurrency run amplified this. |

**Where each failed** in the pipeline: both stop at the **source extractor** stage (`website/features/summarization_engine/summarization/{newsletter,web}`). They never reach Gemini, persistence, KG, or RAG — so no quota wasted, no half-written canonicals.

---

## 3. Other signals captured during the re-run

| Signal | Where | Evidence | Severity |
|---|---|---|---|
| **Gemini 429 storm** | `engine-v2-pro` & `engine-v2-flash`, key[0] AND key[1] simultaneously | Cooldowns of 25–30 s on both keys multiple times during the 6-min window | Working as designed (KeyPool retried & succeeded), but **3 keys is tight for concurrency=4** |
| **Redirect-resolver timeouts** | URL preflight | `Timeout resolving redirects for {themarkup, noahpinion/china-quietly, quantum.country/search, github.com/dendronhq}` → falls back to original URL | Cosmetic — final ingest succeeded |
| **Single 202.8 s ingest** | `gwern.net/spaced-repetition` | 202867 ms latency, just under the 240 s Caddy timeout floor | **Edge case** — a few seconds slower would have hit Caddy 504 on production path |

---

## 4. Production summarization-API issues (droplet logs, separate from topup)

Pulled via `gh workflow run read_recent_logs.yml` (run **26574818401**, color=green). Caddy: 465 × 200, 26 × 304, 8 × 404, 1 × 401, **0 × 5xx** — production is not crashing. But three latent issues recur:

### Issue A — Reddit OAuth credentials missing on droplet

```
WARNING:website.core.settings:Reddit OAuth credentials missing (REDDIT_CLIENT_ID
and/or REDDIT_CLIENT_SECRET are unset). Reddit ingestion will use public JSON
fallback; set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for full-quality extraction.
```

- **Impact:** any user submitting a Reddit URL on production gets the degraded public-JSON path, which CLAUDE.md explicitly warns about: "caps RAG chunk density at ~1 chunk per post" and frequently fails Reddit's anti-bot wall.
- **Almost certainly why the original topup had 0/8 Reddit success** — the topup script runs locally but the same env-var gap likely existed there too at the time.
- **Fix:** add `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` to `/etc/secrets/api_env` or `/opt/zettelkasten/compose/.env` on the droplet, and to the worktree `.env` for local repro.

### Issue B — JWT silently downgraded to anonymous

```
WARNING:website.api.auth:JWT validation failed; dropping request to anonymous
  (InvalidAlgorithmError)

Caddy: status=401 X-Auth-Status=jwt-dropped-to-anon
  error_description="JWT silently downgraded to anonymous"
```

- **Impact:** a real user (`/api/zettels` GET, 2026-05-28 12:01:17Z) hit a 401 because their JWT used an unsupported algorithm. Recurring pattern in logs.
- **Likely cause:** a mismatch between issued JWT alg (HS256? RS256?) and validator config. Worth a 1-day investigation.

### Issue C — Heartbeat httpx.ConnectError loop

```
ERROR:website.heartbeat:heartbeat beat failed; continuing
httpx.ConnectError: All connection attempts failed
```

- Recurs every cadence cycle (300 s). The full traceback chains httpcore → httpx without naming the host, but it's likely the heartbeat trying to reach an external endpoint that's been removed or moved.
- **Impact:** noisy; not user-facing; but it makes real errors harder to spot in log grep.

### Issue D — KG graph edge drop (5/19, 26%)

```
WARNING:website.api:v2 graph edge_drop_unresolved ws=c4fa6870-7df1-4c73-bf14-…
  dropped=5 of=19 (endpoints unresolved via chunk_node_mentions + metadata fallback)
```

- 26% edge drop rate on a single workspace fetch. May be a quality regression in entity-resolution.

---

## 5. Two diagnostic bugs found during this investigation

### Bug X — `candidate_api_env_paths` misses Claude Code worktrees

Location: `website/features/api_key_switching/key_pool.py:296-300`

```python
for parent in current.parents:
    if parent.name == ".worktrees":          # ← Render convention
        main_checkout_root = parent.parent
        break
```

Claude Code worktrees live in `<repo>/.claude/worktrees/<name>`, not `<repo>/.worktrees/<name>`. The check never matches → main-repo `api_env` never added to candidates → today's 09:18 re-run **failed all 41 URLs** with `ValueError: No Gemini API keys found` from a worktree that should have inherited keys.

**Workaround used:** copied `<main>/api_env` → `<worktree>/api_env`.

**Real fix (1 line):** also match `parent.name == "worktrees" and parent.parent.name == ".claude"` (or equivalent).

### Bug Y — Topup report's `workspace_zettel_id` is always null

Location: `docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py:124-127`

```python
if isinstance(result.get("persistence"), dict):
    record["workspace_zettel_id"] = result["persistence"].get("workspace_zettel_id")
else:
    record["workspace_zettel_id"] = result.get("workspace_zettel_id")
```

The fresh re-run report has all 39 succeeded entries with `workspace_zettel_id: null`, which means the actual shape returned by `run_add_zettel_pipeline` doesn't match either branch. Consequence: `verify_ingested()` returns `checked=0` so the in-script verify step is silently no-op.

**Fix:** instrument one successful call to see the real return shape, then update the extraction.

---

## 6. Recommended action list (priority order)

| # | Action | Risk | Effort |
|---|---|---|---|
| 1 | **Set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET** on droplet (`/opt/zettelkasten/compose/.env`) + in worktree `.env` | None (additive) | 5 min |
| 2 | **Investigate JWT InvalidAlgorithmError** — find which alg is being rejected, fix validator or issuer | Touches auth — protected knob; do not silently revert | 1 day |
| 3 | **Bug X** — patch `candidate_api_env_paths` to recognize `.claude/worktrees/` | None | 15 min |
| 4 | **Bug Y** — fix topup script `workspace_zettel_id` extraction so verify works | None | 30 min |
| 5 | Document the **2 persistent failures** as "expected upstream blocks" in the eval methodology (don't count against the engine) | None | 15 min |
| 6 | Heartbeat ConnectError — identify the dead host, remove or fix the heartbeat target | Low | 1 hour |
| 7 | KG edge_drop 26% — confirm whether regression vs baseline, file as a separate iter | Investigation only | 2 hour |

## Out of scope this audit

- **Supabase Postgres / PostgREST logs** — no Supabase MCP installed (verified `claude mcp list`), no `supabase` CLI on PATH, no direct dashboard access from this session. Recommended dashboard filter for operator: project → Logs → Postgres Logs, time window `2026-05-28T09:18Z → 12:45Z`, search `naruto OR canonical_zettels OR workspace_zettels`. For PostgREST, filter by `path=/rest/v1/canonical_zettels` and `status>=400`.
