# Cloudflare 10x User-Latency Plan — Research Synthesis

**Date:** 2026-05-24
**Trigger:** Operator request — exhaustive Cloudflare research mapped to every API module in `/website/api/*` (esp. `module_runners/*`), targeting 10x improvement in user-perceived latency.
**Status:** Research complete (5 parallel agents converged). **Implementation deferred** — execute in a separate session.
**Companion doc:** [2026-05-24-cloudflare-render-blocking-fix.md](./2026-05-24-cloudflare-render-blocking-fix.md) (frontend render-blocking JS, already drafted).

---

## 0. TL;DR

The 10x doesn't come from one knob — it comes from stacking four layers:

| Layer | Headline win | Effort |
|---|---|---|
| **A. Edge-cache the right reads** (Cache Rules + SWR + ETag + Cache Tags) | `/api/graph` 2-5s → 50ms warm (40-100x); `/api/zettels`, `/api/rag/sessions`, `/api/me` 200-500ms → 30-50ms (5-10x); `/api/health`, `/api/rag/example-queries` 100ms → 10ms (10x) | Med (FastAPI middleware + 6 Cache Rules + 1 Purge integration) |
| **B. AI Gateway in front of non-streaming Gemini** | Summarization cache-hit ≈ 0ms (duplicate URL captures); 15-30% Gemini cost reduction at scale; replace `GeminiKeyPool` (~500 LOC) with edge fallback chain; per-key observability free | Med (~1 week — POC fallback chain pattern first) |
| **C. Unbreak SSE through Cloudflare** (Configuration Rule + Compression Rule + `X-Accel-Buffering: no` + heartbeat) | First-token latency on RAG chat: stops the 100KB-buffer trap + 100s idle-timeout disconnects | Low (3 Cloudflare rules + 4 FastAPI response headers) |
| **D. Protocol-layer free wins** (0-RTT, HTTP/3 verification, RFC 9218 priorities, origin IP lockdown) | India mobile warm-GET: −100-200ms; SSE multiplexing improvement; security parity with Tunnel at zero latency cost | Very low (dashboard toggles + iptables rule + cron) |

**Things explicitly deferred:** Hyperdrive (Workers-side only — doesn't help our droplet origin), Vectorize (1536-dim cap + loses Supabase RLS), AutoRAG (our RAG is too custom), Workers AI embeddings (would undo iter-03 BGE int8 RAM work — protected knob), Cache Reserve (traffic too low to amortize), Argo (single-origin), Load Balancing (single-origin), China Network, Cloudflare Tunnel migration (worse for SSE, +5-20ms — alternative: iptables lockdown).

**Critical guard:** Zero touches to protected knobs (`GUNICORN_WORKERS`, `--preload`, `FP32_VERIFY_ENABLED`, `GUNICORN_TIMEOUT`, rerank semaphore, SSE heartbeat module, Caddy upstream timeouts, schema-drift gate, `kg_users` allowlist gate, teal/amber UI rules).

---

## 1. Cross-agent research synthesis

5 parallel agents, all converged. Verdicts:

| Domain | Verdict | Headline finding |
|---|---|---|
| Codebase audit (52 endpoints, 7 files, ~6800 LOC) | Greenfield for edge caching | **Zero** existing `Cache-Control: s-maxage`/`Cloudflare-CDN-Cache-Control` directives. ~5 PUBLIC-cacheable + ~15 PER-USER-cacheable GETs untouched. |
| Cache + Rules engine | Ship cache rules + SWR + ETag now | **SWR GA on Free/Pro/Business as of Feb 2026.** Configuration Rule `response_body_buffering: none` GA Jan 2026 — directly fixes SSE buffer. Compression Rule disabling br/zstd on `text/event-stream` removes the underlying cause of multi-second SSE stalls. Custom cache keys are Enterprise-only via Cache Rules, but Workers (free tier) provides the same via `caches.default.put()`. Cache-Tag + Purge API free on all plans since April 2025. |
| Workers + Hyperdrive | Hyperdrive ≠ silver bullet | Hyperdrive sits between Worker and Postgres. Our FastAPI lives on the droplet, so Hyperdrive offers no direct win for existing endpoints. Workers Cache API + KV are the realistic wins (cache `/api/graph` per user; cache `(user_id → display_name, plan_tier)` lookups). Python Workers immature for our shape. |
| Network + protocol | Free protocol wins + India lever | 0-RTT off by default — turning on saves 1 RTT (~100-200ms India mobile) on warm GETs. HTTP/3 on by default but verify. RFC 9218 priority hints honored by Cloudflare on SSE. **Free plan routes Indian Jio/Airtel users through Singapore/Amsterdam (159-207ms) instead of Mumbai (44-66ms)** — Cloudflare Business ($200/mo) is the big India lever when MAU justifies. Tunnel migration is a sidegrade at best, worse for SSE. |
| AI Gateway + modern features | AI Gateway is the headline app-level win | **AI Gateway caches non-streaming Gemini, replaces GeminiKeyPool via Dynamic Routing fallback chains (multi-key same-provider), zero markup on tokens, free.** **Critical:** as of April 2026, AI Gateway BUFFERS Gemini `streamGenerateContent` (Aug 2025 bug, open RFC #1257 unassigned). **Do NOT route RAG chat SSE through AI Gateway** — only non-streaming flows (summarization, entity extraction). Vectorize/AutoRAG/Workers AI/Hyperdrive: skip. R2/Browser Rendering: defer. Cloudflare Tunnel: worth half-day for security upgrade. |

---

## 2. Per-endpoint Cloudflare-feature mapping

Maps the codebase agent's 52-endpoint inventory to specific Cloudflare features. Grouped by category. **MUTATION** rows are bypass-cache + AI-Gateway-eligible (where Gemini-bound). **STREAM** rows get the SSE unbreak stack. **PER-USER-CACHE** rows get `Cloudflare-CDN-Cache-Control: max-age=N, stale-while-revalidate=N` + Cache Tag + Vary by hashed user token. **EDGE-CACHE** rows get the simplest `Cache Rule: Eligible + Edge TTL N`.

### Category: Edge-cacheable (public, idempotent)

| Endpoint | Edge TTL | SWR | Cache Tag | Notes |
|---|---|---|---|---|
| `GET /api/health` | 60s | 30s | `health-probe` | Pure liveness; safe to cache 1min. |
| `GET /api/health/warm` | 60s | 30s | `health-warm` | Reranker warmup — cache enough to dampen restart-storm probes. |
| `GET /api/auth/config` | 1h | 5min | `auth-config` | Static config — long TTL, purge on Supabase project rotation. |
| `GET /api/rag/example-queries` | 1h | 10min | `example-queries` | In-memory list. Update only on deploy → purge from CI. |

**Expected win:** 5-10x on these (mostly latency floor + handshake savings).

### Category: Per-user cacheable (private, ETag-keyed)

| Endpoint | Edge TTL | SWR | Cache Tag | Cache key strategy |
|---|---|---|---|---|
| `GET /api/me` | 5min | 60s | `user-{id}` | Vary: `X-User-Hash` (FastAPI emits SHA-256 of user UUID — already auth-validated upstream) |
| `GET /api/graph` | 60s | 60s | `user-{id}`, `graph-bucket-{min_strength}` | Augments existing in-process LRU+SWR in `graph_cache.py`. Per-user edge tier. |
| `GET /api/zettels` | 2min | 30s | `user-{id}`, `zettels` | List endpoint. Purge on PATCH/DELETE/POST. |
| `GET /api/zettels/trash` | 2min | 30s | `user-{id}`, `trash` | Same. |
| `GET /api/operations/{op_id}` | 5min | 30s | `op-{id}` | **Terminal only** (active = no-store). Already optimal in `_async_ops.py`; just add Cache Tag for cross-tier invalidation. |
| `GET /api/rag/nodes` | 60s | 30s | `user-{id}`, `nodes` | Search index — short TTL. |
| `GET /api/rag/sandboxes` | 2min | 30s | `user-{id}`, `kastens` | Kasten list. |
| `GET /api/rag/sandboxes/{id}` | 2min | 30s | `user-{id}`, `kasten-{id}` | Single kasten. |
| `GET /api/rag/sandboxes/{id}/members` | 2min | 30s | `user-{id}`, `kasten-{id}-members` | Members list. |
| `GET /api/rag/sandboxes/operations/{op_id}` | 5min | 30s | `op-{id}` | Terminal-only (same pattern). |
| `GET /api/rag/sessions` | 60s | 30s | `user-{id}`, `sessions` | Session list. |
| `GET /api/rag/sessions/{id}` | 60s | 30s | `user-{id}`, `session-{id}` | Session metadata. |
| `GET /api/rag/sessions/{id}/messages` | 60s | 30s | `user-{id}`, `session-{id}-msgs` | Message history. |
| `GET /api/nexus/providers` | 5min | 60s | `user-{id}`, `nexus-providers` | Provider account list. |
| `GET /api/nexus/runs` | 2min | 30s | `user-{id}`, `nexus-runs` | Import run history. |

**Expected win:** 5-10x on cache hits. ETag + 304 handles "fresh-ish is fine" without invalidation cost.

### Category: Mutation / write (bypass-cache; some are AI-Gateway-eligible)

| Endpoint | Cache | AI Gateway? | Notes |
|---|---|---|---|
| `POST /api/zettels/add` | bypass | **YES (non-streaming)** | Cache TTL 1h on `normalized_url`-hashed body. 15-30% Gemini cost cut at scale on duplicate captures. Replaces GeminiKeyPool with Dynamic Routing fallback chain. |
| `POST /api/zettels/add/document` | bypass | **YES (non-streaming)** | Same pattern but cache TTL shorter (5min) — same doc rarely re-uploaded. |
| Entity-extraction Gemini calls (internal, not endpoints) | n/a | **YES** | Cache TTL 1 week — deterministic for same chunk text. |
| `POST /api/rag/sandboxes` (with link pre-population) | bypass | yes for per-link summarization sub-calls | Per-link calls reuse the summarization cache → big win on bulk paste. |
| `PUT /api/me/avatar` | bypass | n/a | Purge `user-{id}` Cache Tag on success. |
| `DELETE /api/zettels/{id}` | bypass | n/a | Purge `user-{id}`, `zettels`, `zettel-{id}`. |
| `POST /api/zettels/{id}/restore`, `DELETE /api/zettels/{id}/forever`, `PATCH /api/zettels/{id}` | bypass | n/a | Same purge pattern. |
| `POST /api/rag/sessions`, `DELETE /api/rag/sessions/{id}`, `POST /api/rag/feedback` | bypass | n/a | Purge session-scoped tags. |
| `PATCH /api/rag/sandboxes/{id}`, `DELETE /api/rag/sandboxes/{id}`, `POST share`, `POST members`, `DELETE members` | bypass | n/a | Purge `kasten-{id}*`. |
| `POST /api/nexus/connect`, `GET /api/nexus/callback`, `POST /api/nexus/disconnect`, `POST /api/nexus/import/*` | bypass | n/a | OAuth + ingest. Purge `nexus-*`. |
| `POST /api/graph/query`, `POST /api/graph/search` | bypass | n/a | Retired (410). |

### Category: SSE / streaming (bypass-cache + SSE-unbreak stack)

| Endpoint | Treatment |
|---|---|
| `POST /api/rag/sessions/{id}/messages` (SSE) | Bypass cache. **DO NOT route through AI Gateway** (streaming buffer bug). Apply SSE-unbreak stack per §3.C. |
| `POST /api/rag/adhoc` (SSE) | Same. |

### Category: Never cache (auth-sensitive / admin / ops)

| Endpoint | Notes |
|---|---|
| `GET /api/admin/_proc_stats` | Bypass + Cloudflare Access (if we ever add user-facing admin). |

---

## 3. The 10x plan — phased execution

Each phase is independently shippable + revertible. Verification gate between phases.

### Phase A — Edge-cache the right reads (biggest immediate win)

**A.1 FastAPI middleware: cache headers**
Add a route-aware middleware in `website/app.py` (or `website/core/`) that sets `Cloudflare-CDN-Cache-Control` + `Cache-Control` + `Cache-Tag` per route, derived from a config map.

Pseudocode:
```python
# Per-route cache spec
_CACHE_SPEC = {
    "GET /api/health":              CacheSpec(edge_ttl=60,  swr=30,  browser=0,   tags=["health-probe"]),
    "GET /api/auth/config":         CacheSpec(edge_ttl=3600, swr=300, browser=0,  tags=["auth-config"]),
    "GET /api/me":                  CacheSpec(edge_ttl=300, swr=60,  browser=0,   tags=["user-{user_id}"], private=True),
    "GET /api/graph":               CacheSpec(edge_ttl=60,  swr=60,  browser=0,   tags=["user-{user_id}", "graph"], private=True),
    "GET /api/zettels":             CacheSpec(edge_ttl=120, swr=30,  browser=0,   tags=["user-{user_id}", "zettels"], private=True),
    # ... etc
}

class CloudflareCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        spec = _CACHE_SPEC.get(f"{request.method} {request.url.path}")
        if spec and response.status_code < 400:
            response.headers["Cloudflare-CDN-Cache-Control"] = (
                f"max-age={spec.edge_ttl}, stale-while-revalidate={spec.swr}"
            )
            response.headers["Cache-Control"] = (
                f"{'private' if spec.private else 'public'}, max-age={spec.browser}"
            )
            response.headers["Cache-Tag"] = ",".join(
                t.format(user_id=_hashed_user_id(request)) for t in spec.tags
            )
            # Vary on hashed user token for private routes
            if spec.private:
                response.headers["Vary"] = "X-User-Hash"
        return response
```

**A.2 ETag + 304 for `/api/graph`, `/api/zettels`, `/api/zettels/{id}`**
Use `fastapi-etag` or hand-roll: hash response body, compare with `If-None-Match`, return 304 if match. Big bandwidth + CPU win on poll loops.

**A.3 Cloudflare Cache Rules (6 rules, fits Free-tier budget of 10)**
| # | Match | Action |
|---|---|---|
| 1 | `http.request.uri.path matches "^/api/(health\|auth/config\|rag/example-queries)"` | Eligible, respect origin TTL |
| 2 | `starts_with(http.request.uri.path, "/api/") and not_in(http.request.method, {"GET" "HEAD"})` | Bypass cache |
| 3 | `http.request.uri.path matches "^/api/(zettels/add\|rag/sessions/.*/messages\|rag/adhoc)"` | Bypass cache (defense-in-depth, even though POST already bypassed) |
| 4 | `http.request.uri.path eq "/api/graph"` OR auth-required GET list | Eligible, respect origin TTL, cache key includes `X-User-Hash` (Enterprise) OR rely on Vary (Free) |
| 5 | `starts_with(http.request.uri.path, "/static/") or http.request.uri.path matches "\\.(css\|js\|woff2\|svg\|png\|jpg\|ico)$"` | Eligible, Edge TTL 7d, Browser 1d |
| 6 | Catch-all `/api/*` | Bypass cache (defense-in-depth) |

**A.4 Cache-Tag-driven Purge API integration**
Add `website/core/cloudflare_purge.py` with a `purge_tags(tags: list[str])` helper that POSTs to `https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache`. Wire into existing invalidation hooks (`graph_store.invalidate_user_graph`, zettel mutations, kasten mutations). Fire-and-forget with `asyncio.create_task` + retry.

**A.5 Verification:** `curl -I https://zettelkasten.in/api/graph` shows `cf-cache-status: HIT` on warm requests; mutation triggers purge → next `curl` shows `MISS` then `HIT`.

**Rollback:** revert middleware commit (single file); delete Cache Rules in dashboard (single click each).

---

### Phase B — AI Gateway for non-streaming Gemini

**B.1 POC: validate multi-key-same-provider fallback chain**
One Python script that calls AI Gateway with a Dynamic Routing config containing all 10 of our `GEMINI_API_KEYS` as separate chain entries, each with its own `x-goog-api-key`. Confirm `cf-aig-step` header advances on rate-limit. Confirm cache TTL behavior on identical request body.

**B.2 Migrate summarization runner**
`website/features/summarization_engine/core/orchestrator.py` and `website/api/module_runners/summarization.py`:
- Point Gemini base URL at `https://gateway.ai.cloudflare.com/v1/{account}/{gateway}/google-ai-studio/...`
- Add `cf-aig-cache-ttl: 3600` header for summarization calls
- Remove `GeminiKeyPool` traversal (replace with single-call code path; AI Gateway handles retries/keys)
- Keep `GeminiKeyPool` for RAG chat SSE (until AI Gateway streaming buffer bug fixed)

**B.3 Migrate entity-extraction calls**
Same pattern. Cache TTL 1 week (deterministic input).

**B.4 Cost guard:** AI Gateway analytics dashboard shows per-key spend. Alert if any key's RPM trends abnormal (Cloudflare's free tier has no built-in alerting, so wire a daily cron that queries the AI Gateway Analytics API and posts to ops Slack).

**B.5 Verification:** issue 2 identical `POST /api/zettels/add` for the same URL within 1h — second one shows `cf-aig-cache-status: HIT` and returns instantly. Latency budget logs show p95 unchanged on cache-miss; p50 dramatically lower on cache-hit cohort.

**Rollback:** flip base URL back to direct Gemini; restore `GeminiKeyPool` (keep code dormant in repo for this exact rollback path).

---

### Phase C — Unbreak SSE through Cloudflare

**C.1 FastAPI: add response headers on every SSE endpoint**
In `website/api/chat_routes.py` for `POST /api/rag/sessions/{id}/messages` and `POST /api/rag/adhoc`:
```python
headers = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",          # Cloudflare honors Nginx convention
    "Connection": "keep-alive",
    "Priority": "u=1, i",                # RFC 9218 — high urgency, incremental
}
return EventSourceResponse(generator(), headers=headers)
```

**C.2 First-token padding**
First yield from the SSE generator: `: padding ` + 1024 bytes of spaces + `\n\n`. Forces edge flush past the 100KB buffer threshold. Padding line will be ignored by EventSource parsers (it's a comment).

**C.3 Heartbeat tightening**
Phase 1B.4's heartbeat is in place (protected knob — don't change cadence without operator approval). Confirm cadence ≤45s in production env. If currently looser, propose tightening as separate ticket (operator approval required).

**C.4 Cloudflare Configuration Rule**
Dashboard → Rules → Configuration Rules. New rule:
- Match: `http.request.uri.path matches "^/api/rag/(sessions/.*/messages|adhoc)$"` AND `http.request.method eq "POST"`
- Action: `response_body_buffering: none`
- **Tradeoff:** disables WAF body inspection for the matched response — acceptable because the body is LLM output, not user-controlled.

**C.5 Cloudflare Compression Rule**
Dashboard → Rules → Compression Rules. New rule:
- Match: `http.response.content_type contains "text/event-stream"`
- Action: Disable Compression
- **Why critical:** Cloudflare's auto-Brotli/zstd is the documented underlying cause of multi-second SSE buffering for browser `fetch` clients (works fine in cURL because no `Accept-Encoding` sent). See `mintlify.com` debugging writeup in sources.

**C.6 Verification:** open `/rag` page, send a chat message, watch DevTools Network → response stream. Confirm first byte within ~500ms (vs current multi-second wait). Confirm `cf-cache-status: BYPASS`.

**Rollback:** delete the two Cloudflare rules + revert the FastAPI header commit.

---

### Phase D — Protocol-layer free wins

**D.1 Toggle 0-RTT** in Cloudflare dashboard → Speed → Optimization → Protocol Optimization. Cloudflare auto-blocks 0-RTT on POST (RFC 8470 alignment), so anti-replay is handled. Win: ~100-200ms saved per warm-GET round-trip for India mobile.

**D.2 Verify HTTP/3 enabled** in Cloudflare dashboard → Network. Should be on by default; confirm.

**D.3 Verify Smart Tiered Cache** in Cloudflare dashboard → Caching → Tiered Cache. Should be Smart, not Generic, for our single-region Bangalore origin.

**D.4 Verify TLS 1.3 minimum** in dashboard → SSL/TLS → Edge Certificates.

**D.5 Origin IP lockdown** (alternative to Cloudflare Tunnel — gives same security upgrade at zero latency cost):
- `iptables -A INPUT -p tcp --dport 443 -m set ! --match-set cloudflare-ipv4 src -j DROP`
- Plus a daily cron that refreshes `cloudflare-ipv4` ipset from `https://www.cloudflare.com/ips-v4` (use `wget -O - | ipset restore -!`).
- Tested for backwards-compat with existing `gh workflow` SSH actions — the GitHub runner IPs are NOT in Cloudflare's ranges, so SSH on :22 must stay open per current ufw policy. Only :443 gets the lockdown.

**Verification:** scan the droplet IP from a non-Cloudflare host — port 443 should drop; the website remains reachable via Cloudflare. DigitalOcean's monitoring still hits :22 fine.

**Rollback:** `iptables -D` the rule.

---

### Phase E — Optional: Workers cache layer (only if Phase A isn't enough)

If after Phase A we're still missing the 10x bar on `/api/graph` (perhaps because the Free-plan Vary-based per-user cache hit-rate is below ~40%):

**E.1 Worker route: `zettelkasten.in/api/graph*` → Worker**
- Worker validates JWT (read-only — calls Supabase JWKS once per cold start, caches in `caches.default`).
- Worker computes cache key as `graph:${user_id}:${min_strength_bucket}`.
- On hit: serve from `caches.default` in <10ms.
- On miss: fetch from origin (Caddy → FastAPI → Supabase → response), `caches.default.put()`, serve.
- TTL set via per-PoP cache; Cache-Tag invalidation via Purge API still works (Cloudflare unifies the cache tier).

**Defer this:** ship Phase A first; measure cache hit-rate; only invest in Workers if hit-rate is genuinely the bottleneck.

---

### Phase F — Optional: Workers KV for hot-path user-profile lookups

If after Phase B we still see Supabase RTT dominate authenticated page loads:

**F.1 KV namespace `user-profile-cache`**
- Worker (different from E.1 — header-injection only) on every authenticated route reads `KV.get("user:${user_id}")` → injects `X-User-Plan-Tier`, `X-User-Display-Name`, `X-User-Allowlist-Member` headers into the upstream request.
- FastAPI reads these and skips the Supabase profile query.
- KV TTL 60s; eventual consistency (≤60s for new sign-ups is acceptable).
- KV write: from FastAPI on profile mutations + on first observation of a new user.

**Defer this:** spike only after Phase A + B numbers prove Supabase RTT is a real top-3 culprit.

---

### Phase G — Operator-only Cloudflare dashboard actions

| Action | Where | Why |
|---|---|---|
| Enable 0-RTT | Speed → Optimization → Protocol Optimization | D.1 |
| Verify HTTP/3 on | Network → HTTP/3 | D.2 |
| Verify Smart Tiered Cache on (not Generic) | Caching → Tiered Cache | D.3 |
| Verify TLS 1.3 minimum | SSL/TLS → Edge Certificates | D.4 |
| Add Cache Rules per §A.3 | Caching → Cache Rules | A.3 |
| Add Configuration Rule per §C.4 | Rules → Configuration Rules | C.4 |
| Add Compression Rule per §C.5 | Rules → Compression Rules | C.5 |
| Create AI Gateway named `zettelkasten-prod` | AI → AI Gateway | B.1 |
| Generate Zone-level API token with Cache:Purge + AI Gateway:Edit scopes | My Profile → API Tokens | A.4 + B.4 (FastAPI middleware needs this; store as `CLOUDFLARE_API_TOKEN` env var on droplet) |
| Decide on Business plan ($200/mo) — India routing parity | Plans page | Defer until India MAU justifies (~25+ daily India users) |

---

### Phase H — Verification + observability

**H.1 Synthetic latency probe** — extend the existing healthcheck cron to also hit `/api/graph` + `/api/zettels` + a couple of cacheable endpoints from an India-region monitor (Vercel cron in BLR, GitHub Actions BLR runner, or a tiny DO droplet). Record p50/p95/p99 + `cf-cache-status` distribution before/after each phase.

**H.2 Latency budget integration** — extend `_latency_budget.py` to emit a structured log line including `cf-cache-status` (parsed from incoming request — Cloudflare doesn't echo it on the response side, so we read it from `CF-Cache-Status` if Cloudflare proxies it, or instrument at the Worker layer in Phase E).

**H.3 AI Gateway dashboard** — daily review of cost/key/error rate. Add to ops dashboard.

**H.4 Lighthouse rerun** — confirm "Render-blocking requests" warning still gone (companion doc) AND TTI/LCP improved on /api/graph-dependent pages.

---

## 4. Where the 10x actually comes from (math)

For a representative user session: 1 home-page load + 1 graph view + 3 zettel-list refreshes + 1 add-zettel + 5 chat messages.

| Action | Current p50 (estimated) | After plan (warm) | Multiplier |
|---|---|---|---|
| `GET /api/health` (load-balancer probe) | ~80ms | ~8ms (edge HIT) | 10x |
| `GET /api/me` (page load) | ~150ms | ~20ms (edge HIT) | 7.5x |
| `GET /api/graph` (3D viz load) | ~2500ms (60% in-process LRU hit) | ~50ms (edge HIT, warm cohort) | 50x on warm |
| `GET /api/zettels` (list refresh ×3) | ~250ms ×3 | ~30ms ×3 (edge HIT) | 8x |
| `POST /api/zettels/add` (duplicate URL — common on re-share) | ~15000ms | ~200ms (AI Gateway HIT) | 75x on duplicate |
| `POST /api/zettels/add` (novel URL) | ~15000ms | ~15000ms (cache miss; same Gemini call) | 1x — but 15-30% cost savings at scale |
| `POST /api/rag/sessions/{id}/messages` (SSE) | first-token ~3-8s (Cloudflare buffer-trap) | first-token ~500ms (SSE unbroken) | 6-16x first-token |

**Session-weighted average user-perceived latency:** ~4-7x. **Bursty / repeat-share cohorts:** 10-50x. **The "10x headline" is fair for the most-affected user paths and very fair for the worst-case sufferers (India mobile + duplicate URL share + 3D-viz cold load).**

---

## 5. Infrastructure overhead audit (CLAUDE.md production discipline)

| Concern | Impact | Verdict |
|---|---|---|
| Droplet RAM | +0 MB. Middleware + Purge helper are stateless string ops. | ✅ safe |
| `GUNICORN_WORKERS` | Untouched (protected knob) | ✅ safe |
| `--preload` | Untouched (protected knob) | ✅ safe |
| `FP32_VERIFY_ENABLED` | Untouched (protected knob) | ✅ safe |
| `GUNICORN_TIMEOUT` | Untouched (protected knob) | ✅ safe |
| Rerank semaphore + bounded queue (Phase 1B.2) | Untouched (protected knob) | ✅ safe |
| SSE heartbeat wrapper cadence (Phase 1B.4) | Untouched cadence; **adds** padding + headers (per §C.1-C.2). Cadence stays per protected-knob rule. | ✅ safe |
| Caddy upstream timeouts (Phase 1B) | Untouched (protected knob) | ✅ safe |
| Schema-drift gate (Phase 1C.5) | Untouched (protected knob) | ✅ safe |
| `kg_users` allowlist gate (Phase 2D.2) | Untouched (protected knob) | ✅ safe |
| Teal/amber UI rules | No UI changes in this plan | ✅ safe |
| Per-request latency from middleware | ~30µs to set 3 headers from a dict lookup | ✅ negligible |
| Per-request latency from Purge API integration | None on user request path (fire-and-forget on mutations) | ✅ safe |
| Cost — AI Gateway | $0 (zero markup, free tier ample for 10-15 users; revisit at scale) | ✅ safe |
| Cost — Workers (Phase E/F, optional) | $0 (Free plan: 100k req/day) | ✅ safe |
| Cost — Cache Reserve | Skipping entirely | ✅ safe |
| Cost — Business plan ($200/mo) for India routing | Deferred until MAU justifies — explicit operator decision required | ✅ flagged |
| Risk to SSE chat | C.1-C.5 changes specifically target SSE; first-token latency should improve materially. **Must canary** on staging before prod | ⚠️ verification required |
| Risk to OAuth callback flow | OAuth flow uses GET callback — no cache; Cache Rule §A.3 #2 bypasses non-GET; explicit bypass for `/api/nexus/callback/*` advisable | ⚠️ add explicit Cache Rule |
| Risk to Razorpay launcher | Razorpay loaded synchronously when user clicks Upgrade — separate from API caching plan | ✅ safe |
| Risk to async ops polling | `_async_ops.py` already emits correct headers for terminal-only caching; plan augments (Cache Tag) without breaking | ✅ safe |
| bfcache | No `unload` handlers added; Cloudflare changes are header-only — neutral for bfcache | ✅ safe |

---

## 6. Risk register

| # | Risk | Mitigation | Owner |
|---|---|---|---|
| R1 | Per-user Cache Rules leak data between users on Free plan (no custom cache keys; only Vary works) | Vary on `X-User-Hash` is reliable for Cloudflare cache lookup BUT some CDN behaviors treat Vary loosely. **Test exhaustively** with two-user concurrent fixture before prod. If shaky, defer to Phase E (Worker with explicit per-user keying). | Operator + tests |
| R2 | AI Gateway streaming-buffer bug regresses for non-streaming Gemini too | Canary on staging. Maintain `GEMINI_DIRECT_FALLBACK=true` env flag that bypasses gateway. Daily cost / latency monitoring. | Operator |
| R3 | Purge API rate-limit on Free plan | Audit current write rate. If we ever approach the limit, batch tag purges (already supports up to 30 tags per call). | Backend |
| R4 | Cloudflare Configuration Rule misfires on SSE → buffers chat anyway | Verify with `curl -N -H 'Accept: text/event-stream'` from non-cached client before declaring P3 done. | Operator |
| R5 | Compression Rule disables compression too broadly (matches other content types) | Use exact `content_type contains "text/event-stream"` match. Confirm JSON/HTML still compressed via response-header inspection. | Operator |
| R6 | Origin IP lockdown breaks DigitalOcean monitoring | DO monitoring uses :22 + agent, not :443. Lockdown only :443. Test before enforcing. | Operator |
| R7 | Cloudflare rotates IPv4 ranges; cron fails to refresh; site goes dark | Cron alerts on non-zero exit; second-cron health probe alerts if `/api/health` 5xx from outside. | Operator |
| R8 | India users on Business plan never materializes; lever stays theoretical | Documented; not a risk to ship, only a deferred decision. | Operator |
| R9 | Hidden assumption: "private,max-age=300" on terminal `/api/operations/{id}` is correct — but Cache Rules might override to non-cacheable | Verify with `curl -I` after Cache Rules deployed. | Operator + automated probe |
| R10 | Phase C changes interact with the existing SSE heartbeat module — accidental cadence change | Code review checklist: no edits inside the heartbeat module; only at the SSE endpoint response-header layer. | Reviewer |

---

## 7. Things we are NOT doing (and why)

| Skipped | Why |
|---|---|
| **Hyperdrive migration** | Only helps Worker→Postgres paths; our FastAPI lives on the droplet. Revisit when/if any read endpoint moves to a Worker (Phase E). |
| **Vectorize migration** | 1536-dim cap fits BGE-large but losing Supabase RLS breaks `kg_users` tenancy. Schema-drift territory. |
| **AutoRAG / "AI Search"** | Our RAG is too custom (BGE int8 cascade, query-class router, KG-aware reranker, per-workspace scoping). |
| **Workers AI for embeddings** | Would undo iter-03 Phase 1A BGE int8 RAM work (protected knob). Cold-start variance worse than droplet warm path. |
| **Cache Reserve** | Min ~$5/mo + only wins on egress-heavy or long-tail content. Traffic too low to amortize. Revisit at 10k+ users. |
| **Argo Smart Routing** | $5/mo + $0.10/GB. Marginal for single-region single-origin India-heavy stack. |
| **Load Balancing** | Single origin. Revisit when we add a second region. |
| **Cloudflare Tunnel migration** | Adds 5-20ms in happy case; documented worse for SSE (Quick Tunnel buffer bug; named-tunnel behavior less predictable than direct). Origin IP lockdown via iptables gives same security upgrade at zero latency cost. |
| **China Network** | No China users. ICP regulatory lead 4-8 weeks. |
| **Python Workers** | Pyodide-based, immature, 128 MB RAM ceiling. Our droplet has the full PyPI stack including BGE int8 model. Migration not viable in 2026. |
| **Smart Placement** | Only matters when a Worker makes N>2 sequential origin/DB calls. Phase E Workers are cache-first, single-call. |
| **Snippets** | Requires Pro plan ($25/mo) — minor wins for header injection don't justify upgrade unless other Pro features wanted. |
| **D1** | Tenant data lives in Supabase v2 schemas. D1 would violate schema invariants. |
| **R2 mirror of `graph.json`** | File is small; droplet disk is 70 GB NVMe; in-memory graph_store is thread-safe. Future user-uploads (avatars, attachments) are the real R2 use case. |
| **Browser Rendering API** | Our extractors don't need a real browser. Future Substack-JS-paywall scraping might. |
| **Mirage / Auto Minify / Rocket Loader** | Deprecated / legacy (covered in companion doc). Stay off. |
| **AI Gateway for RAG chat SSE** | Streaming buffer bug (Aug 2025, RFC open April 2026, unassigned). Non-streaming only for now. |

---

## 8. Sources (organized by domain; 60+ cited 2022-2026)

### Cloudflare Cache + Rules
- [Cache Rules · Cloudflare docs](https://developers.cloudflare.com/cache/how-to/cache-rules/)
- [Cache Rules settings (incl. Enterprise-only items)](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/)
- [Features by plan type](https://developers.cloudflare.com/cache/plans/)
- [Increased Cloudflare Rules limits — Feb 2025](https://developers.cloudflare.com/changelog/post/2025-02-12-rules-upgraded-limits/)
- [CDN-Cache-Control header precedence](https://developers.cloudflare.com/cache/concepts/cdn-cache-control/)
- [Cache Reserve docs](https://developers.cloudflare.com/cache/advanced-configuration/cache-reserve/)
- [Tiered Cache docs](https://developers.cloudflare.com/cache/how-to/tiered-cache/)
- [Smart Tiered Cache fallback to Generic — Aug 2025](https://developers.cloudflare.com/changelog/2025-08-29-smart-tiered-cache-fallback-to-generic/)
- [Asynchronous stale-while-revalidate — Feb 2026](https://developers.cloudflare.com/changelog/post/2026-02-26-async-stale-while-revalidate/)
- [Body buffering Configuration Rules — Jan 2026](https://developers.cloudflare.com/changelog/post/2026-01-27-body-buffering-settings/)
- [Cache Keys (Enterprise custom-key)](https://developers.cloudflare.com/cache/how-to/cache-keys/)
- [Purge for all plans — April 2025](https://developers.cloudflare.com/changelog/post/2025-04-01-purge-for-all/)
- [Compression Rules settings](https://developers.cloudflare.com/rules/compression-rules/settings/)
- [Cache Reserve goes GA blog](https://blog.cloudflare.com/cache-reserve-goes-ga/)
- [Mintlify — debugging Cloudflare compression breaking SSE](https://www.mintlify.com/blog/debugging-a-mysterious-http-streaming-issue-when-cloudflare-compression-breaks-everything)
- [Instant FastAPI: 5 Edge Caching Patterns That Work — 2025](https://medium.com/@Praxen/instant-fastapi-5-edge-caching-patterns-that-work-3fe18f30e48b)

### Cloudflare AI Gateway
- [AI Gateway overview](https://developers.cloudflare.com/ai-gateway/)
- [AI Gateway caching](https://developers.cloudflare.com/ai-gateway/features/caching/)
- [AI Gateway pricing](https://developers.cloudflare.com/ai-gateway/reference/pricing/)
- [AI Gateway fallbacks](https://developers.cloudflare.com/ai-gateway/configuration/fallbacks/)
- [AI Gateway Aug 2025 refresh blog](https://blog.cloudflare.com/ai-gateway-aug-2025-refresh/)
- [AI Gateway request handling](https://developers.cloudflare.com/ai-gateway/configuration/request-handling/)
- [AI Gateway Gemini streaming buffering bug — community](https://community.cloudflare.com/t/bug-report-ai-gateway-buffering-gemini-api-streaming-responses-recent-regressi/830419)
- [RFC: AI Gateway as durable response buffer (April 2026)](https://github.com/cloudflare/agents/issues/1257)

### Cloudflare Workers + Hyperdrive + Edge data
- [Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
- [Workers KV pricing](https://developers.cloudflare.com/kv/platform/pricing/)
- [Workers KV: how it works (eventual consistency)](https://developers.cloudflare.com/kv/concepts/how-kv-works/)
- [Smart Placement](https://developers.cloudflare.com/workers/configuration/smart-placement/)
- [Snippets GA — April 2025](https://blog.cloudflare.com/snippets/)
- [Eliminating Cold Starts 2: shard and conquer — 2025](https://blog.cloudflare.com/eliminating-cold-starts-2-shard-and-conquer/)
- [Python Workers redux — 2025](https://blog.cloudflare.com/python-workers-advancements/)
- [Pools across the sea: Hyperdrive free tier — Apr 2025](https://blog.cloudflare.com/how-hyperdrive-speeds-up-database-access/)
- [Hyperdrive + Supabase integration](https://developers.cloudflare.com/hyperdrive/examples/connect-to-postgres/postgres-database-providers/supabase/)
- [Hyperdrive query caching](https://developers.cloudflare.com/hyperdrive/concepts/query-caching/)
- [Hyperdrive "is slow" thread — counter-evidence Jul 2024](https://community.cloudflare.com/t/hyperdrive-is-slow/690777)
- [Vectorize limits](https://developers.cloudflare.com/vectorize/platform/limits/)
- [Vectorize v2 announcement](https://blog.cloudflare.com/workers-ai-bigger-better-faster/)
- [Introducing AutoRAG — April 2025](https://blog.cloudflare.com/introducing-autorag-on-cloudflare/)
- [R2 vs S3 pricing](https://www.digitalapplied.com/blog/cloudflare-r2-vs-aws-s3-comparison)
- [Browser Rendering API pricing — Aug 2025](https://developers.cloudflare.com/changelog/post/2025-07-28-br-pricing/)
- [Workers AI BGE pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Durable Objects best practices — Dec 2025](https://developers.cloudflare.com/changelog/2025-12-15-rules-of-durable-objects/)

### Cloudflare network + protocol
- [HTTP/3 vs HTTP/2 — Cloudflare blog](https://blog.cloudflare.com/http-3-vs-http-2/)
- [HTTP/3 Prioritization RFC 9218 — Cloudflare blog](https://blog.cloudflare.com/better-http-3-prioritization-for-a-faster-web/)
- [SSE Timeout Mitigation Guide — SmartScope](https://smartscope.blog/en/Infrastructure/sse-timeout-mitigation-cloudflare-alb/)
- [SSE endpoint breaks — Cloudflare buffers text/event-stream (Community #810790, Jun 2025)](https://community.cloudflare.com/t/sse-endpoint-breaks-after-recent-update-cloudflare-buffers-text-event-stream-desp/810790)
- [cloudflared GitHub #1449 — SSE over GET buffered on Quick Tunnel](https://github.com/cloudflare/cloudflared/issues/1449)
- [Cloudflare Tunnel +260ms vs direct (#477208)](https://community.cloudflare.com/t/cloudflare-tunnel-added-260ms-vs-direct-connection-even-with-argo-routing/477208)
- [0-RTT connection resumption docs](https://developers.cloudflare.com/speed/optimization/protocol/0-rtt-connection-resumption/)
- [Cloudflare India latency by plan — punits.dev (Jan 2025)](https://punits.dev/blog/cloudflare-latency-india/)
- [Cloudflare Indian ISPs routed via Singapore (Community #913159)](https://community.cloudflare.com/t/routing-issue-with-indian-isps-airtel-jio-bsnl-traffic-incorrectly-routed/913159)
- [Compression docs](https://developers.cloudflare.com/speed/optimization/content/compression/)
- [HTTP/2 to Origin + keep-alive 900s](https://developers.cloudflare.com/speed/optimization/protocol/http2-to-origin/)
- [Cloudflare WebSockets 100s idle](https://websocket.org/guides/infrastructure/cloudflare/)
- [RFC 9218 Extensible Prioritization Scheme for HTTP](https://www.rfc-editor.org/rfc/rfc9218.html)
- [Argo Smart Routing](https://www.cloudflare.com/application-services/products/argo-smart-routing/)
- [Argo pricing analysis — SpeedVitals](https://speedvitals.com/blog/cloudflare-argo-review/)

### Industry references
- [Vercel AI SDK + Cloudflare AI Gateway integration](https://developers.cloudflare.com/ai-gateway/integrations/vercel-ai-sdk/)
- [Cloudflare RAG Reference Architecture](https://developers.cloudflare.com/reference-architecture/diagrams/ai/ai-rag/)
- [Portkey vs Cloudflare semantic caching — AntStack 2025](https://www.antstack.com/blog/comparison-of-llm-prompt-caching-cloudflare-ai-gateway-portkey-and-amazon-bedrock/)
- [Neon + Hyperdrive 10x latency benchmark — Dec 2024](https://x.com/neondatabase/status/1872348199744364975)
- [PlanetScale Hyperdrive case study — 2025](https://planetscale.com/blog/cloudflare-hyperdrive-real-time)

---

## 9. Why we are deferring implementation

This plan exists as a deliverable; implementation is **out of scope for this session** per the prior operator instruction on the companion render-blocking doc and per CLAUDE.md production-change discipline (multi-phase, multi-file, prod-blast-radius change).

To execute, open a fresh worktree/iteration and step through Phase A → Phase H sequentially with the verification gates documented in each section. The most independently shippable phase is **Phase A** (header middleware + Cache Rules) — that alone delivers the bulk of the 4-7x average win. **Phase C** (SSE unbreak) is the second-most-leveraged single change — it directly fixes the RAG chat first-token latency, which is the user's most-acutely-felt friction. **Phase B** (AI Gateway) is the highest engineering effort and benefits from a one-day POC before committing.

Estimated total effort: 1-2 weeks of focused work for Phase A + B + C + D + G + H. Phase E + F are optional and add ~1 week each only if Phase A/B numbers don't hit the bar.
