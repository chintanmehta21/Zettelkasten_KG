# YouTube transcript-chain research — design grounding for PR #91

**Date:** 2026-05-25
**Trigger:** PR #89 closed the prom-counter crash class. The remaining `ZvO5kikFVOk` failure is the YouTube-T1 90 s hang (`tier_gemini_youtube_url`). Per `live_url_repro_2026-05-25.md` and earlier `nimit_summarization_failures_2026-05-25.md` §6.2.
**Method:** 4 parallel WebSearch/WebFetch subagents, recency-weighted < 5 yr. No code edits during research.

---

## TL;DR — what the research says + what we ship

| Sub-decision | Research verdict | Ship in PR #91? |
|---|---|---|
| **(1) Race T1+T2** (Webshare + yt-dlp) for ~15 s, cancel loser | `asyncio.wait(FIRST_COMPLETED)` is canonical; 2 racers optimal; `gather(*pending, return_exceptions=True)` mandatory to flush sockets | ✅ |
| **(2) Demote `tier_gemini_youtube_url`** to T3, 20 s sub-cap | Gemini-URL is still flaky in 2026: open issues `python-genai#1898` (truncation), `#1359` (timestamp drift, closed "not planned"), forum reports of "wrong video returned" unresolved since Sept 2025. Feature still "preview". | ✅ (T3 per operator) |
| **(3) Drop `tier_invidious_pool` + `tier_piped_pool`** | Only 6 Invidious instances officially listed (down from ~40 in 2023); subtitles "extremely limited and prone to fail"; Piped status page returned 502 in April 2025; mass-blocking event Dec 19 2024 | ✅ |
| **(4) Add new Supadata tier** (~$17/mo, 3k transcripts) | Single-vendor insurance, absorbs PO-token + proxy churn | ⏸ deferred (operator call; can fold in later if T1+T2 success drops below ~95%) |
| **(5) Per-tier caps** (15/15/20/30/5 s) via double-bound | Envoy/Polly/Resilience4j/gRPC deadline-prop unanimous on per-attempt + total-budget; AWS Builders' Library: p99.9 + padding | ✅ |
| **(6) Surface per-tier health on `/api/health`** | gives operators visibility before users hit 422s | ✅ |
| **(7) Adaptive timeouts** (`Retry-After` consumption, AWS adaptive mode) | AWS itself: "advanced mode, not recommended for typical use cases" | ❌ skipped |

---

## A · Concurrent races — `asyncio.wait(FIRST_COMPLETED)`

- **Canonical primitive:** `done, pending = await asyncio.wait(tasks, return_when=FIRST_COMPLETED, timeout=15)` in Python 3.12. Not `TaskGroup` (cancels on *exception* not success), not `gather` (never cancels siblings), not `as_completed` (cancellation interplay is `httpx#2736` footgun).
- **Mandatory cleanup pattern:**
  ```python
  done, pending = await asyncio.wait(tasks, return_when=FIRST_COMPLETED, timeout=race_cap_s)
  for t in pending: t.cancel()
  await asyncio.gather(*pending, return_exceptions=True)   # drain — else socket leak
  ```
- **Two production footguns:**
  - **Socket leak on cancel** (`httpx#1461`, `httpcore#149`): `CancelledError` is `BaseException` since 3.8 → `except Exception` cleanup skips it → socket never returned to pool. Use `try/finally`, not `try/except Exception`.
  - **`CancelledError` swallowing**: a `try/except CancelledError: pass` over the loser breaks the cancel contract → "completed" report + leaked socket.
- **2 racers, not 3:** Webshare and yt-dlp are the two uncorrelated providers. A 3rd racer would be another proxy region (correlated failure with one of the two) → marginal benefit ≈ 0, RAM doubled.
- **Cost of 2 parallel HTTPS vs 1:** ~50-200 KB RAM per in-flight request; doubled bandwidth (10-200 KB transcript payloads → ~400 KB extra peak per zettel — trivial on a 1 vCPU droplet); doubled load on the loser provider.
- **Hedged-with-delay (Google Tail-at-Scale)** beats pure race when you have a stable P80; we don't (T1 hangs 90 s — no useful P80). Pure race is right.

**Citations:** [Global Payments + AWS hedging](https://aws.amazon.com/blogs/database/how-global-payments-inc-improved-their-tail-latency-using-request-hedging-with-amazon-dynamodb/) 2025-08; [Hedging tactic](https://blog.alexoglou.com/posts/hedging/) 2025-03; [Shiriev asyncio shield](https://shiriev.ru/posts/2025-01-30-asyncio-shield/) 2025-01; [CPython#100928 — wait() cancels remaining tasks](https://github.com/python/cpython/issues/100928); [httpcore#149 — socket leak on CancelledError](https://github.com/encode/httpcore/issues/149); [Dean & Barroso, Tail at Scale](https://cacm.acm.org/research/the-tail-at-scale/).

---

## B · Per-tier caps — double-bound is industry standard

- **Pattern:** per-attempt timeout + total-budget — every major resilience stack codifies it as two distinct knobs:
  - **Envoy/Istio:** `per_try_timeout` + route `timeout`. Formula: `overall_timeout >= per_try_timeout * (attempts+1) + buffer`.
  - **gRPC:** client deadline per call + propagated parent deadline.
  - **AWS SDK (Smithy standard mode):** call-level + `max_attempts` + 20 s backoff cap.
  - **Polly v8 (.NET):** inner Timeout + outer Timeout strategies.
  - **Resilience4j (JVM):** `TimeLimiter` + enclosing `Retry`.
- **Per-tier fire → move to next tier** (unanimous: Envoy, gRPC, Polly, Resilience4j). Only total-budget fire fails the whole chain.
- **Practical numbers:**
  - Fast tier (typical 3-10 s): **20-25 s** per-cap (p99.9 + padding rule).
  - Slow tier (Gemini server-side, 15-30 s typical, heavy right tail): **30-45 s** per-cap.
  - But our T3 (`tier_gemini_youtube_url`) hangs are the exact reason this PR exists → **20 s tight bound** (operator override of research-default 30 s).
- **Adaptive timeouts:** skip. AWS Builders' Library: *"not recommended for typical use cases."* Engineering cost > benefit for a 7→5-tier chain.

**Citations:** [Envoy per_try_timeout](https://oneuptime.com/blog/post/2026-02-24-how-to-configure-per-retry-timeout-in-istio/view); [AWS SDK retry behavior](https://docs.aws.amazon.com/sdkref/latest/guide/feature-retry-behavior.html); [gRPC deadlines](https://grpc.io/docs/guides/deadlines/); [AWS Builders' Library — timeouts/retries/backoff](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/); [Polly v8 pipelines](https://www.pollydocs.org/pipelines/); [Resilience4j TimeLimiter](https://reflectoring.io/time-limiting-with-resilience4j/).

---

## C · YouTube production reality 2024-2025

- **Major bot-wall tightening Dec 19 2024 + through 2025.** All major datacenter IPs (AWS/GCP/Azure/DigitalOcean/Vercel/Render) now return `RequestBlocked` / "Sign in to confirm you're not a bot" on InnerTube transcript endpoints and yt-dlp web/android/ios clients.
- **PO-token (Proof-of-Origin) is mandatory** for GVS streaming on `web/mweb/tv_simply/web_music/web_creator`, subtitles on `web`, and player requests on `android/ios`. Now bound to **video-id** (one token per video — no more long-lived sessions).
- **`iv-org/youtube-trusted-session-generator` is DEPRECATED** (2025); replacement is `invidious-companion` PO-token service + `bgutil-ytdlp-pot-provider` plugin (yt-dlp ≥ 2025.05.22).
- **Per-tier reliability (mid-2025 industry estimates):**

| Tier | Mechanism | Success | Maint. |
|---|---|---|---|
| Webshare residential + youtube-transcript-api | rotating residential IP pool | **85-95%** | Low |
| yt-dlp + cookies + bgutil PO-token | browser-attested token + cookies + TLS impersonate | **70-85%** | **HIGH** (updates every 2-6 weeks) |
| Gemini server-fetch (`Part.from_uri`) | Google's own infra | **85-95%** but **NOT verbatim** (hallucinates timestamps, summarises) | None |
| Gemini audio (yt-dlp audio + Gemini File API) | audio-only ingestion | **95%+** transcription quality (Gemini 3 Pro near-verbatim with diarisation) | Low |
| Invidious public pool | 6 instances officially listed | **10-30%** | None |
| Piped public pool | many dead instances | **10-25%** | None |
| Metadata-only | yt-dlp `--dump-json` | **100%** (degraded mode) | None |

- **Drop Invidious + Piped:** maintenance cost > value contributed; "extremely limited and prone to fail" per Invidious's own docs.

**Citations:** [yt-dlp PO-Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide); [yt-dlp#15865 — login required](https://github.com/yt-dlp/yt-dlp/issues/15865); [iv-org/youtube-trusted-session-generator DEPRECATED](https://github.com/iv-org/youtube-trusted-session-generator); [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider); [Webshare YouTube docs](https://help.webshare.io/en/articles/11432234-youtube-proxies); [Invidious instances doc](https://docs.invidious.io/instances/); [HN — Google killed Invidious instances Feb 2025](https://news.ycombinator.com/item?id=43033066); [Scrapfly — How to Scrape YouTube 2026](https://scrapfly.io/blog/posts/how-to-scrape-youtube).

---

## D · `tier_gemini_youtube_url` — still flaky in 2026

- Google **officially launched** YouTube-URL support on the API-key path on **2025-03-12** ("Added support for YouTube URLs as a media source" — changelog); re-promoted at Gemini 2.5 announcement 2025-05-09. Feature is **still tagged "preview"** — not GA.
- **Hallucination/truncation bugs remain unfixed in May 2026:**
  - `python-genai#1898` (open, Dec 2025): first-time YouTube processing truncates transcripts to 0.5-27% of actual content; subsequent (cached) calls work, hiding the bug.
  - `python-genai#1359` (closed "not planned", Sept 2025): timestamp drift — 30-min videos return ~17-min-truncated transcripts.
  - Forum: "Wrong video returned (Rick Roll) for valid YouTube IDs" — unresolved since Sept 2025.
  - Forum: certain valid IDs return `400 contents.parts must not be empty`.
- **Latency:** docs sample video at 1 fps; "analysing a 101-minute video with Gemini 2.0 Pro may take **several minutes**" — consistent with our 90 s hang.
- **Best fallback if we ever need a Gemini-side path for safety:** upload mp4 via `client.files.upload(...)` + `Part.from_uri(file.uri, file.mime_type)`. Bypasses the YouTube-URL ingestion code path entirely. Pays the bandwidth cost; eliminates the hallucination class.

**Citations:** [python-genai#1898 open truncation](https://github.com/googleapis/python-genai/issues/1898); [python-genai#1359 closed not-planned](https://github.com/googleapis/python-genai/issues/1359); [Forum — wrong video Rick Roll](https://discuss.ai.google.dev/t/gemini-video-understanding-wrong-video-returned-rick-roll-for-valid-youtube-ids/102072); [Gemini changelog 2025-03-12](https://ai.google.dev/gemini-api/docs/changelog); [Gemini 2.5 video understanding announcement](https://developers.googleblog.com/gemini-2-5-video-understanding/); [Video understanding docs](https://ai.google.dev/gemini-api/docs/video-understanding).

---

## Synthesised new chain (after operator's T3 override)

```
                  ┌── T1: tier_transcript_api_via_webshare ──┐   each 15 s cap
   t = 0…15 s  →  │            (RACE — first success wins)    │   loser cancelled
                  └── T2: tier_ytdlp_cookies_impersonate    ──┘   + socket drained
   if both fail:
   t = 15…35 s →  T3: tier_gemini_youtube_url   (DEMOTED from T1; 20 s tight cap)
   t = 35…65 s →  T4: tier_gemini_audio                                (30 s cap)
   t = 65…90 s →  T5: tier_metadata_only                                (5 s cap)
                  → terminal — H4 D7/D8 thin-extraction gate decides 422 vs persist
                  DROPPED: tier_invidious_pool, tier_piped_pool          (dead pools)
```

**Total wall-clock ≤ 85 s + ~3 s finalize overhead ≈ 88 s ≤ 90 s budget** (with race window). Compared to old: 7 tiers, single-tier-could-burn-full-90s, no race.

## Implementation notes (for the PR reviewer)

- New types in `tiers.py`: `TierSpec(fn, name, cap_ms)`, `TierStage(spec)`, `RaceStage(specs, cap_ms)`, `Stage = TierStage | RaceStage`.
- `TranscriptChain` signature changes: `__init__(stages: list[Stage], budget_ms: int)` — replaces flat `tiers: list[TierFn]`.
- `TranscriptChain.run` rewritten:
  - Track `start = time.monotonic()` and `remaining_ms` per-stage.
  - `TierStage`: `async with asyncio.timeout(min(remaining_ms, spec.cap_ms) / 1000): result = await spec.fn(...)`.
  - `RaceStage`: launch all `specs` as tasks (each with own per-spec `asyncio.timeout`); `asyncio.wait(FIRST_COMPLETED, timeout=stage.cap_ms / 1000)`; cancel pending; `await gather(*pending, return_exceptions=True)`; first done-task with `result.success=True` wins.
- Delete `tier_invidious_pool` + `tier_piped_pool` + the `_try_pool` + `_load_health` + `_save_health` + `_is_healthy` + `_mark_unhealthy` + `_extract_caption_url_from_pool_response` + `_caption_text_to_plaintext` helpers (only those tiers used them).
- Drop `TierName.INVIDIOUS_POOL` + `TierName.PIPED_POOL` enum members.
- New `website/features/summarization_engine/source_ingest/youtube/tier_health.py`: module-level dict of `(tier_name → {last_success_at, last_error_at, last_error_reason})`. `record_success(name)` + `record_failure(name, reason)` helpers called from each tier. Exposed via `/api/health` under `yt_tier_health` subkey.
- Tests in `tests/unit/website/test_yt_tier_chain_race.py` (new file): parametrised over race-T1-wins / race-T2-wins / both-timeout / per-tier-cap-fires-then-next + static "dropped-tiers-no-longer-in-chain" guard.

Acceptance test (post-merge, post-deploy): re-submit `https://www.youtube.com/watch?v=ZvO5kikFVOk&t=5s` as Naruto. Expected: succeeds with summary OR fails fast on Webshare/yt-dlp race (not 90 s starvation on Gemini-URL).
