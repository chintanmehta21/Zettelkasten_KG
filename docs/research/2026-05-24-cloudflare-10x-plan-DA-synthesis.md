# Cloudflare Desktop-Latency Plan — Post-DA Synthesis (Authoritative)

**Date:** 2026-05-24
**Status:** Authoritative. **Supersedes** the original `2026-05-24-cloudflare-10x-plan.md` Phase A/B/C/D/E/F. Read this doc; the original is now historical context only.
**Companion docs (still authoritative for their scopes):**
- [2026-05-24-cloudflare-render-blocking-fix.md](./2026-05-24-cloudflare-render-blocking-fix.md) — frontend `<script>` defer/fetchpriority (desktop + mobile)
- [2026-05-24-mobile-handoff.md](./2026-05-24-mobile-handoff.md) — mobile-only items, separate executor
- [2026-05-24-ai-gateway-devils-advocate.md](./2026-05-24-ai-gateway-devils-advocate.md) — Phase B raw DA findings

**5 devil's-advocate research agents** (B, A, C, D, E+F) materially revised the original 10x plan. **Headline:** the "10x" claim was over-optimistic. Honest revised projection: **~2-3x session-weighted desktop average + 6-16x on SSE first-token + meaningful security upgrade (mTLS)**.

---

## 0. Honest revised math

| Path | Original claim | Revised after DA | Why changed |
|---|---|---|---|
| `/api/health`, `/api/auth/config`, `/api/rag/example-queries` (public GETs) | 10x | **10x preserved** | Pure public-routes are still EDGE-CACHE-able on Free |
| `/api/graph` (per-user 3D viz) | 50x on warm | **~1.2-1.5x** (browser-only `private, max-age=N`) | Free plan **ignores `Vary: X-User-Hash`** → per-user edge keying impossible; min edge TTL is 2h |
| `/api/zettels`, `/api/rag/sessions`, `/api/me`, `/api/rag/sandboxes` (per-user list GETs) | 5-10x | **~1.5-2x** (browser-only) | Same reason — no edge benefit on Free |
| `POST /api/zettels/add` (Gemini summarization) | 75x on duplicate URL | **Low at our scale** (10-15 users → rare duplicates) | AI Gateway helps only at scale; cache key includes auth header → key-rotation thrash |
| Entity extraction (internal Gemini) | implicit | **Cache HIT ≈ 0ms** | Deterministic, single pinned key, TTL ≤24h — genuine win |
| RAG chat SSE first-token | 6-16x | **6-16x preserved** | Config Rule `response_body_buffering: none` + Compression Rule + `no-transform` solves the real bottleneck |
| India mobile warm-GET | -100-200ms | **-100-200ms preserved** | 0-RTT + HTTP/3 are default-on or one-toggle |
| Origin security | n/a | **mTLS Authenticated Origin Pulls** | New finding — IP-allowlist alone is bypassable via CF tenant-hopping |

**Realistic session-weighted desktop latency improvement: ~2-3x.** The genuine standout wins are (a) SSE first-token (6-16x), (b) public-route edge cache (10x), (c) entity-extraction cache hits, and (d) security parity via mTLS. **Anyone promising "10x on /api/graph" on Cloudflare Free is lying.**

---

## 1. Priority list (do these in this order)

| P# | Change | Priority | Effort | Risk | Bang/buck |
|---|---|---|---|---|---|
| **P1** | **C — SSE unbreak** (response headers + Config Rule + Compression Rule) | **HIGHEST** | ~1 day | LOW (after DA tightening) | RAG chat first-token 6-16x; user's most-felt friction |
| **P2** | **D.1 — 0-RTT toggle** (one click) | HIGHEST | 5 min | NONE | -100-200ms India mobile warm-GETs |
| **P3** | **D.2 — Verify HTTP/3** + **D.3 — Verify Smart Tiered Cache** (one click each) | HIGHEST | 5 min | NONE | Already-on protocol wins; confirm only |
| **P4** | **D.5-mTLS-subset — Authenticated Origin Pulls** | HIGH | ~2 hours | LOW | Closes the CF tenant-hopping bypass class; zero latency cost |
| **P5** | **Supabase Custom Access Token Hook** (replaces original Phase F) | HIGH | ~3 hours | LOW | Saves 1 Supabase RTT per authenticated page; zero new infra |
| **P6** | **A narrowed — middleware + Cache Rules for PUBLIC routes only** | HIGH | ~1 day | LOW | 10x on /api/health, /api/auth/config, /api/rag/example-queries |
| **P7** | **A.2 narrowed — ETag/304 via `etag-middleware`** on /api/graph, /api/zettels lists | MEDIUM | ~half day | LOW | Browser-only `If-None-Match` saves repeat-poll body bandwidth + CPU |
| **P8** | **B narrowed — AI Gateway for entity extraction only** | MEDIUM | ~1 day | LOW (single pinned key, TTL ≤24h) | Internal cost reduction; user-invisible |
| **P9** | **D.5-rest — DO Cloud Firewall + Caddy DNS-01 + IPv6 lockdown + dead-man's-switch** | MEDIUM | ~1 day | MED — many gotchas | Hide origin IP; tighten attack surface; **not load-bearing for latency** |
| **P10** | **A.4 narrowed — Cache-Tag emission + Purge API** | MEDIUM | ~half day | MED — Free-tier limits | Only if A.3 ships and Cache-Tag header is verified to emit on Free |
| **P11** | **POC: AI Gateway for URL summarization** | LOW | ~1 day spike | MED | Defer; benefits scale-dependent |
| **D.4 — TLS 1.3 minimum** | **SKIP** | — | — | — | CF themselves don't recommend; India Android <7 long-tail risk |
| **E — Worker for /api/graph** | **DEFER to 1k+ DAU** | — | — | — | Per-PoP MISS dominates at 10-15 users |
| **F — Workers KV for profile** | **REPLACED by P5** | — | — | — | Supabase JWT hook is strictly better |
| **Plan upgrade (Pro $25/mo or Business $200/mo)** | **DECISION POINT** | — | — | — | Pro unlocks Snippets + image polish + some SSE behavior; Business unlocks India routing parity (Mumbai/Chennai). See §6. |

---

## 2. Per-change detail — execute in P1→P10 order

### P1 — Phase C revised: SSE unbreak

**What changes (concrete code/config):**

In `website/api/chat_routes.py` (`POST /api/rag/sessions/{id}/messages` + `POST /api/rag/adhoc`) — set on every SSE response:
```python
headers = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",   # no-transform is the documented CF compression bypass
    "X-Accel-Buffering": "no",                   # folk-knowledge, belt-and-suspenders with C.4
    "Connection": "keep-alive",
}
# DO NOT add: Priority: u=1, i  (RFC 9218 is a request header concept, not response — non-standard, middlebox risk)
# DO NOT add: 1024-byte first-token padding (CF buffer threshold is ~100KB, not 1KB — no-op as designed)
return EventSourceResponse(generator(), headers=headers)
```

Verify existing Phase 1B.4 heartbeat cadence in production env is ≤45s (don't change cadence — protected knob).

Cloudflare dashboard:
- **Rules → Configuration Rules** (new rule):
  - Match: `http.request.uri.path matches "^/api/rag/(sessions/.*/messages|adhoc)$" and http.request.method eq "POST"`
  - Action: `response_body_buffering: none`
- **Rules → Compression Rules** (new rule):
  - Match: `http.response.content_type contains "text/event-stream"`
  - Action: Disable Compression

**Pitfalls to avoid:**
1. **Do NOT add `Priority: u=1, i` response header** — RFC 9218 is request-side semantics; setting on origin response is non-standard, no documented CF action, unknown middlebox behavior. Original 10x plan §C.1 was wrong.
2. **Do NOT add 1024-byte first-token padding** — the documented edge buffer threshold is ~100KB; 1KB padding is a no-op. Original 10x plan §C.2 was wrong.
3. **Use `Cache-Control: no-cache, no-transform`**, not just `no-cache`. `no-transform` is the **documented** CF compression bypass (per CF Compression Rules docs). This makes the Compression Rule belt-and-suspenders.
4. **Configuration Rule disables WAF body inspection** on the matched response. Trade-off is acceptable because the LLM-output is from our own Gemini call, but: add a server-side output content filter as defense-in-depth, and document the WAF-skip explicitly in the rule comment.
5. **Configuration Rule body-buffering subsystem is proven-fragile** — Dec 5 2025 CF outage was triggered by a WAF body-buffering change (28% traffic, 25min, 500s). Have a rollback runbook (delete the rule).
6. **Scope the Configuration Rule to POST only** — don't accidentally disable buffering for health probes or other GETs on the same path prefix.
7. **Verify in real Chrome DevTools with `Accept-Encoding: gzip, br, zstd`**, NOT naked `curl -N`. `curl -N` without `--compressed` doesn't send `Accept-Encoding` → false PASS (same trap Mintlify hit). Use `curl --compressed` AND a real browser test.
8. **Confirm Configuration Rule plan availability** in dashboard before relying on it. GA Jan 27 2026 per changelog but plan tier not explicitly stated.

**Verification gate:**
- DevTools Network panel → SSE response shows `cf-cache-status: BYPASS`, first byte within ~500ms on chat-message submit
- Real-browser test with `Accept-Encoding: gzip, br, zstd` — first event arrives within ~500-1500ms (not multi-second)
- No 524 errors during long Gemini synth (heartbeat already covers this — verify cadence)
- WAF dashboard shows no new false-negatives on `/api/rag/*`

**Rollback:** delete the 2 Cloudflare rules + revert the FastAPI header commit.

---

### P2 — Phase D.1 revised: 0-RTT toggle

**What changes:** Dashboard → Speed → Optimization → Protocol Optimization → enable **0-RTT Connection Resumption**.

**Pitfalls to avoid:**
1. Cloudflare auto-restricts 0-RTT to **GET/HEAD/OPTIONS with no query string** (POSTs always rejected by CF itself). No replay attack on state-changing operations — RFC 8470 compliant. Safe as designed.
2. Cookies sent in early data are theoretically replayable, but only for reads on cached responses. No state-change risk for our app.
3. Browser support: all major browsers ≥2018. Older clients silently degrade to 1-RTT. No user-visible breakage.
4. Origin sees `Early-Data: 1` header on 0-RTT requests — FastAPI doesn't act on this by default; fine.

**Verification gate:** SSL Labs scan of `zettelkasten.in` shows TLS 1.3 with early data enabled. Repeat-visit GET from India network shows reduced handshake latency.

**Rollback:** dashboard toggle off.

---

### P3 — Phase D.2 + D.3 revised: HTTP/3 + Smart Tiered Cache verification

**What changes:**
- Dashboard → Network → HTTP/3 → confirm **ON** (default for new zones; verify)
- Dashboard → Caching → Tiered Cache → confirm **Smart Tiered Cache** (not Generic)

**Pitfalls to avoid:**
1. HTTP/3 falls back to HTTP/2 automatically on UDP-blocking networks (corporate Cisco SWG, Zscaler, etc.) — no user-visible breakage but watch for clients reporting Safari 18.1 desktop JS-load random fail bug (Jan 2025).
2. Smart Tiered Cache may misidentify our DigitalOcean Reserved IP as anycast/regional-unicast and pick a wrong upper tier. CF added a "cloud region hint" Apr 2026 ([changelog](https://developers.cloudflare.com/changelog/post/2026-04-17-smart-tiered-cache-for-public-cloud/)) — if `DigitalOcean BLR3` or similar is in the dropdown, set it.
3. If Tiered Cache MISS rate spikes after enabling Smart, fall back to Generic and re-evaluate.
4. Smart Tiered Cache is **incompatible** with Workers `caches.default` — relevant for the deferred P11/Phase E, not for this step.

**Verification gate:** `curl -I --http3 https://zettelkasten.in/` shows `HTTP/3 200`. Cache Analytics dashboard shows Tiered Cache HIT ratio stable or improved over baseline week.

**Rollback:** dashboard toggle (HTTP/3 off → falls back to H/2; Tiered Cache Smart → Generic).

---

### P4 — Phase D.5 mTLS subset: Authenticated Origin Pulls

**What changes (load-bearing security fix):**

Cloudflare dashboard:
- SSL/TLS → Origin Server → **Authenticated Origin Pulls** → enable (zone-level Cloudflare client cert)

Caddy config (`ops/caddy/Caddyfile` or equivalent):
- Add `tls.client_auth.mode require_and_verify` for the production hostname
- Trust Cloudflare's origin CA: download from [CF origin CA cert](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/set-up/zone-level/) and reference as the trusted CA bundle

**Why this is the highest-value security upgrade in Phase D (single most impactful change):**

The original plan §D.5 said "iptables-lockdown to Cloudflare IPv4 ranges = security parity with Tunnel at zero latency cost." That's **half right.** IP allowlist only proves "request came from a CF IP" — but **any** CF customer can DNS-A their zone to our IP and proxy attacks through CF, bypassing our WAF entirely. mTLS cryptographically proves "this came from *our* CF zone."

**Pitfalls to avoid:**
1. **mTLS must be enabled in CF dashboard AND Caddy config simultaneously.** If only one side is on, requests fail.
2. **Test the mTLS chain BEFORE locking down IP at firewall layer.** If mTLS misconfigured + IP lockdown active, you lose ability to debug from outside.
3. **Keep operator panic IP allowlisted** at DO firewall layer for emergency direct access if mTLS breaks.
4. **Document the cert location** in ops runbook — when rotating, both sides must update simultaneously.
5. mTLS does NOT replace IP allowlist; it complements it (defense in depth). Plan for P9 anyway.

**Verification gate:**
- `curl https://zettelkasten.in/` from any non-Cloudflare client succeeds (CF terminates TLS in front)
- `curl --resolve zettelkasten.in:443:$DROPLET_IP https://zettelkasten.in/` directly to origin returns 403 / TLS handshake failure (Caddy refuses non-mTLS clients)
- Real user traffic via CF still works

**Rollback:** disable Origin CA in CF dashboard + remove mTLS lines from Caddy → reload Caddy.

---

### P5 — Supabase Custom Access Token Hook (replaces original Phase F)

**What changes:**

Supabase project → Authentication → Hooks → Custom Access Token Hook → enable.

The hook is a Postgres function that runs at JWT issue/refresh time. It reads from `core.profiles` and injects custom claims into the JWT:
```sql
CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  claims jsonb;
  prof RECORD;
BEGIN
  SELECT display_name, plan_tier, allowlist_member
    INTO prof
    FROM core.profiles
    WHERE user_id = (event->>'user_id')::uuid;

  claims := event->'claims';
  claims := jsonb_set(claims, '{user_metadata,display_name}', to_jsonb(COALESCE(prof.display_name, '')));
  claims := jsonb_set(claims, '{user_metadata,plan_tier}', to_jsonb(COALESCE(prof.plan_tier, 'free')));
  claims := jsonb_set(claims, '{user_metadata,allowlist_member}', to_jsonb(COALESCE(prof.allowlist_member, false)));

  RETURN jsonb_set(event, '{claims}', claims);
END;
$$;

GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook FROM authenticated, anon, public;
```

FastAPI middleware (`website/api/auth.py`): read claims from the verified JWT and skip the Supabase profile lookup on authenticated routes.

**Pitfalls to avoid:**
1. **Stale-on-mutation window:** claims refresh on next JWT issue (typically <1hr by default Supabase refresh interval). User changes display name → other tabs see old name for up to refresh interval. Acceptable for our shape (read-mostly profile, rare changes).
2. **For banned/deleted users**, claims-in-JWT staleness is up to the refresh interval. For abuse cases, also call `supabase.auth.admin.signOut(user_id, scope='global')` to revoke all sessions immediately.
3. **Hook function must be `STABLE`** and **never raise** — a failing hook breaks all auth. Wrap the SELECT in defensive defaults.
4. **Grant + revoke EXEC** carefully — only `supabase_auth_admin` should call the hook function (Supabase enforces this).
5. **Add a hook-test** that issues a test JWT and confirms claims are present.
6. **Document this as a `decision` observation** per CLAUDE.md (the alternative was Workers KV — explicitly rejected).

**Verification gate:**
- New JWT issued post-deploy contains `user_metadata.plan_tier`, `user_metadata.display_name`, `user_metadata.allowlist_member`
- FastAPI route handler reads from `request.state.user` without hitting Supabase
- Profile-change → new JWT (after refresh) contains updated values
- Hook never raises in Supabase logs

**Rollback:** disable hook in Supabase dashboard. FastAPI middleware falls back to direct profile query (keep this code path active during rollout).

---

### P6 — Phase A narrowed: middleware + Cache Rules for PUBLIC routes only

**What changes:**

FastAPI middleware in `website/app.py` (or `website/core/`) sets cache headers per route, allow-list NOT opt-out:
```python
_PUBLIC_CACHE_SPEC = {
    "GET /api/health":              CacheSpec(edge_ttl=7200,  swr=60,  browser=0,   tags=["health-probe"]),
    "GET /api/auth/config":         CacheSpec(edge_ttl=86400, swr=300, browser=0,   tags=["auth-config"]),
    "GET /api/rag/example-queries": CacheSpec(edge_ttl=7200,  swr=60,  browser=0,   tags=["example-queries"]),
}

_PER_USER_BROWSER_SPEC = {
    "GET /api/me":                     CacheSpec(edge_ttl=0, swr=0, browser=300, private=True),
    "GET /api/zettels":                CacheSpec(edge_ttl=0, swr=0, browser=120, private=True),
    "GET /api/zettels/trash":          CacheSpec(edge_ttl=0, swr=0, browser=120, private=True),
    "GET /api/rag/sandboxes":          CacheSpec(edge_ttl=0, swr=0, browser=120, private=True),
    "GET /api/rag/sandboxes/{id}":     CacheSpec(edge_ttl=0, swr=0, browser=120, private=True),
    "GET /api/rag/sessions":           CacheSpec(edge_ttl=0, swr=0, browser=60,  private=True),
    "GET /api/nexus/providers":        CacheSpec(edge_ttl=0, swr=0, browser=300, private=True),
    "GET /api/nexus/runs":             CacheSpec(edge_ttl=0, swr=0, browser=120, private=True),
}

class CloudflareCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # CRITICAL: status gate + content-type gate + defer to handler
        if response.status_code not in (200, 206, 301, 304):
            return response
        if response.headers.get("content-type", "").startswith(("text/event-stream", "multipart/")):
            return response
        if "cache-control" in response.headers:  # handler already set its own
            return response
        key = f"{request.method} {request.url.path}"
        spec = _PUBLIC_CACHE_SPEC.get(key)
        if spec:
            response.headers["Cloudflare-CDN-Cache-Control"] = (
                f"public, max-age={spec.edge_ttl}, stale-while-revalidate={spec.swr}"
            )
            response.headers["Cache-Control"] = f"public, max-age={spec.browser}"
            response.headers["Cache-Tag"] = ",".join(spec.tags)
        else:
            spec = _PER_USER_BROWSER_SPEC.get(key)
            if spec:
                # Browser-only — NO Cloudflare-CDN-Cache-Control (Free plan won't keep per-user separate at edge)
                response.headers["Cache-Control"] = f"private, max-age={spec.browser}"
        return response
```

Cloudflare Cache Rules (5 rules — within Free 10-rule budget; order matters, last match wins):
| # | Match | Action |
|---|---|---|
| 1 | `not_in(http.request.method, {"GET" "HEAD"})` | Bypass cache |
| 2 | `http.request.uri.path matches "^/api/(zettels/add\|rag/sessions/.*/messages\|rag/adhoc)$"` | Bypass cache (defense-in-depth) |
| 3 | `starts_with(http.request.uri.path, "/api/") and not (http.request.uri.path matches "^/api/(health\|auth/config\|rag/example-queries)$")` | Bypass cache (defense-in-depth — only the explicit public routes are eligible) |
| 4 | `http.request.uri.path matches "^/api/(health\|auth/config\|rag/example-queries)$"` | Eligible, respect origin TTL |
| 5 | `starts_with(http.request.uri.path, "/static/") or http.request.uri.path matches "\\.(css\|js\|woff2\|svg\|png\|jpg\|ico)$"` | Eligible, Edge 7d / Browser 1d |

**Pitfalls to avoid:**
1. **Free plan min edge TTL is 2 hours** — `max-age=7200+` is the minimum. Anything shorter is silently floored. Original plan's 30s/60s targets are impossible on Free.
2. **Free plan IGNORES custom `Vary` values** (only `Vary: Accept-Encoding` is honored). Per-user edge caching via `Vary: X-User-Hash` would leak user A's data to user B. **Do NOT use it.** Per-user routes are browser-only `private, max-age=N`.
3. **Status code gate is non-negotiable** — without it, middleware can cache 500s for 5min globally (CF docs: "with Origin Cache Control enabled, CF will ignore HTTP Status code"). Allow only 200/206/301/304.
4. **Content-Type gate is non-negotiable** — never set cache headers on `text/event-stream` or `multipart/` (caches partial SSE stream → users see truncated forever).
5. **Allow-list, not opt-out** — explicit per-route specs only. Catch-all bypass at the rule layer + per-route allow-list at the middleware layer = defense in depth.
6. **Defer to handler-set headers** — `_async_ops.py`'s terminal-only cache headers must NOT be overridden by middleware. Check for existing `cache-control` header before setting one.
7. **Never set `Cache-Control: public` AND `private` together** — pin one strategy per route. Mixing is a footgun (CF caches `public, s-maxage=N` at edge regardless of `private` in same response).
8. **Always Online may silently disable SWR** — check zone setting, document if on.
9. **Audit FastAPI routes for header reflection** (e.g., `X-Forwarded-Host` → absolute URL in response body). Reflected headers → cache poisoning class.
10. **Cache Rules order matters** — last match wins. Rule #4 (public eligible) must come AFTER #3 (catch-all bypass) or #3 will override.
11. **202 Accepted not in default cacheable list** — but if middleware blindly sets `s-maxage`, CF caches it → starves operation-polling. Allow-list (200/206/301/304 only) handles this.

**Verification gate:**
- `curl -I https://zettelkasten.in/api/health` shows `cf-cache-status: HIT` on second request, `Cloudflare-CDN-Cache-Control` header present from origin, **stripped from response delivered to client** (verify it's NOT in browser DevTools)
- `curl -I https://zettelkasten.in/api/me -H 'Authorization: Bearer <token>'` shows `Cache-Control: private, max-age=300` and `cf-cache-status: BYPASS`
- Two concurrent users with different `Authorization` tokens both get their own profile, never cross-leak
- Manual injection of `X-Forwarded-Host: evil.com` does NOT result in cached response with `evil.com` echoed back

**Rollback:** revert middleware commit + delete the 5 Cache Rules in dashboard.

---

### P7 — Phase A.2 narrowed: ETag/304 via `etag-middleware`

**What changes:**

Add `etag-middleware` (alive, last update June 2024) to `ops/requirements.txt`. **Do NOT use `fastapi-etag` — abandoned 12+ months.**

Mount middleware on `/api/graph`, `/api/zettels` (list), `/api/zettels/{id}` (read). For `/api/graph` specifically, use a **weak ETag from a cheap fingerprint** (row count + `max(updated_at)` of user's zettels), NOT body hash — SHA-256 of a 2 MB graph response is ~10 ms cold + GC pressure on the 1-vCPU droplet.

**Pitfalls to avoid:**
1. **`fastapi-etag` is abandoned** — hard NO. PyPI shows no releases in 12+ months. Use `etag-middleware` or hand-roll on Starlette.
2. **`etag-middleware` buffers entire body** to hash — does not work for `StreamingResponse`. Skip streaming routes.
3. **Use weak ETag (`W/"..."`) from cheap fingerprint**, not strong ETag (body hash). Cloudflare auto-converts strong → weak on Brotli/image-opt anyway.
4. **Hashing every `/api/graph` body is expensive** — for 2 MB JSON, SHA-256 is 10 ms cold + GC. Cheap fingerprint = row count of user's zettels + `max(updated_at)`. Update when either changes.
5. **ETag + SWR interaction:** when origin returns same ETag on revalidation, CF's Smart Edge Revalidation accepts 304 and extends cached body freshness. Works correctly.
6. **Don't compute ETag for bodies <80 bytes** — pointless overhead.

**Verification gate:**
- Repeat `GET /api/graph` with `If-None-Match: <previous-etag>` returns 304 with no body, < 50ms
- Mutation to a zettel changes the fingerprint → next GET returns 200 with new ETag

**Rollback:** remove middleware mount; uninstall library.

---

### P8 — Phase B narrowed: AI Gateway for entity extraction only

**What changes:**

In `website/features/api_key_switching/` or wherever entity-extraction Gemini calls live: swap base URL from `https://generativelanguage.googleapis.com/...` to `https://gateway.ai.cloudflare.com/v1/{account}/{gateway-name}/google-ai-studio/...`.

Use a **single pinned Gemini key** for the cached route (do NOT use GeminiKeyPool key rotation here — auth in cache key means rotation = miss).

Set `cf-aig-cache-ttl: 86400` (24h, not 1 week — limits blast radius of bad cached responses since there's no per-entry purge API).

Set `cf-aig-collect-log-payload: false` — DPDP compliance + privacy policy implications.

FastAPI middleware: strip all `cf-aig-*` headers from outbound responses (CLAUDE.md No-Infra-Disclosure rule).

`GeminiKeyPool` stays untouched as the source of truth for URL summarization + RAG chat.

**Pitfalls to avoid:**
1. **Do NOT replace GeminiKeyPool** — `cf-aig-max-attempts` is hard-capped at 5; we traverse up to 20 (10 keys × 2 models). Plus multi-key-same-provider Dynamic Routing chain is undocumented and likely unsupported.
2. **Do NOT route RAG chat SSE through AI Gateway** — `streamGenerateContent` buffer bug confirmed unresolved (Aug 2025, RFC unassigned April 2026).
3. **Cache key includes auth header** — every key rotation invalidates cache. Pin one key for the cached route (the rotation pool is for non-cached calls).
4. **`json.dumps(sort_keys=True)`** mandatory before sending request body — JSON field order breaks cache hits (confirmed CF bug #916379).
5. **Detect empty `candidates[]` / safety-blocked responses and set `cf-aig-skip-cache: true`** — otherwise bad response cached + served to all users for 24h.
6. **Thundering herd**: "simultaneous identical requests may not share cache" per CF docs. Add app-level lock around cacheable Gemini calls if cold-cache concurrent invocations matter.
7. **`GEMINI_DIRECT_FALLBACK=true` env toggle** must be in active code path + tested under fire. AI Gateway took 2.5h global outage June 12 2025 — without hot fallback, our app is down too.
8. **Synthetic 60s ping** to `gateway.ai.cloudflare.com` — fast detection of AI Gateway outages.
9. **Strip `cf-aig-*` headers** from outbound FastAPI responses — CLAUDE.md No-Infra-Disclosure.
10. **`cf-aig-collect-log-payload: false`** — DPDP risk: prompt bodies in CF US-hosted logs is a new data-residency surface.
11. **BYOK `x-goog-api-key` removal has a documented bug** (CF community 834080) — verify in POC that the upstream key strip actually works for Google.

**POC test plan before production cut-over** (12 tests — see [ai-gateway-devils-advocate.md §7](./2026-05-24-ai-gateway-devils-advocate.md#7-poc-test-plan-1-day-spike--before-any-production-commit) for the full list).

**Verification gate:**
- 2 identical entity-extraction calls for the same chunk → second shows `cf-aig-cache-status: HIT`
- Synthetic ping detects AI Gateway down → fallback fires → users unaffected
- `cf-aig-*` headers not present in browser DevTools
- Daily AI Gateway dashboard review during first week — confirm cache hit rate, error rate

**Rollback:** flip base URL back to direct Gemini. Keep code path active.

---

### P9 — Phase D.5 rest: DO Cloud Firewall + Caddy DNS-01 + IPv6 lockdown + dead-man's-switch

**What changes:**

1. **Switch Caddy to DNS-01 via Cloudflare API token** for cert renewal **FIRST**. Without this, locking :443 to CF IPs breaks Let's Encrypt's TLS-ALPN-01 challenge (Caddy default) within 60-90 days.
2. **DigitalOcean Cloud Firewall** (NOT in-droplet iptables) — ingress allowlist for :443 to Cloudflare IPv4 + IPv6 ranges + operator panic IP. SSH (:22) stays open with current ufw policy.
3. **Daily cron** that refreshes the DO firewall via DO API from `https://www.cloudflare.com/ips-v4` + `https://www.cloudflare.com/ips-v6`. Validates fetched list (≥10 CIDRs, valid format) before applying. Atomic swap; last-known-good snapshot preserved on validation failure.
4. **Dead-man's-switch monitor** (healthchecks.io or equivalent) on the refresh cron — alert on missed ping.
5. Lock IPv6 :443 to CF IPv6 ranges too (or disable IPv6 on droplet).

**Pitfalls to avoid:**
1. **Use DigitalOcean cloud firewall**, NOT in-droplet iptables. DO firewall is managed via API outside the droplet — can't self-lockout via bad rule. iptables runs in the droplet — a typo locks you out of the droplet entirely.
2. **Switch Caddy to DNS-01 FIRST.** Caddy's default is TLS-ALPN-01 on :443. Lock :443 to CF IPs → Let's Encrypt can't renew → cert expires in 60-90d → site dark.
3. **CF IP ranges DO change occasionally.** Sept 17 2024 CF accidentally stopped announcing 15 IPv4 prefixes for ~1h. Daily refresh is necessary; weekly is too slow.
4. **Silent cron failure** = total outage weeks later. Dead-man's-switch (healthchecks.io ping on success) is mandatory.
5. **Empty/malformed `ips-v4` fetch** → naive overwrite destroys ipset → site dark. Validate response: ≥10 entries, all valid CIDR format. Atomic swap; keep last-known-good snapshot.
6. **IPv6 scan/bypass.** Attackers scan v6 too. Lock v6 or disable.
7. **Keep operator panic IP allowlisted** for emergency direct access if the system breaks.
8. **CF WARP egress IPs are NOT published.** Operators on WARP get locked out — test from direct IP.
9. **GitHub Actions runners use dynamic Azure IPs** — if any CI step hits the app on :443 (not just SSH), it breaks. Verify no workflow does this.
10. **DigitalOcean monitoring agent is outbound-only** — not affected by ingress lockdown.

**This is the load-bearing security upgrade combined with P4 mTLS.** mTLS proves origin pulls come from our zone; IP allowlist proves they come from a CF IP. Together = defense in depth.

**Verification gate:**
- Origin :443 IP scanned from non-CF host → DROP
- Site reachable via CF as normal
- Caddy cert renews via DNS-01 (verify next renewal window)
- Healthchecks.io dashboard shows green for IP-refresh cron

**Rollback:** widen DO firewall rule to 0.0.0.0/0 for :443 + revert Caddy to TLS-ALPN-01.

---

### P10 — Phase A.4 narrowed: Cache-Tag emission + Purge API (conditional)

**Only if** P6 ships AND `curl -I https://zettelkasten.in/api/health` confirms `Cache-Tag` header is actually emitted on Free (currently unverified):

Add `website/core/cloudflare_purge.py` with bounded-retry queue (NOT fire-and-forget):
```python
import asyncio, httpx

class PurgeQueue:
    def __init__(self, zone_id, api_token, sentry_client):
        self._q = asyncio.Queue(maxsize=1000)
        self._zone = zone_id
        self._token = api_token
        self._sentry = sentry_client
        self._worker = asyncio.create_task(self._drain())

    async def enqueue(self, tags: list[str]):
        try:
            self._q.put_nowait(tags)
        except asyncio.QueueFull:
            self._sentry.capture_message("Purge queue overflow", level="warning")

    async def _drain(self):
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                tags = await self._q.get()
                for attempt in range(3):
                    try:
                        # Batch up to 30 tags per call (CF limit)
                        for batch in (tags[i:i+30] for i in range(0, len(tags), 30)):
                            r = await client.post(
                                f"https://api.cloudflare.com/client/v4/zones/{self._zone}/purge_cache",
                                json={"tags": batch},
                                headers={"Authorization": f"Bearer {self._token}"},
                            )
                            if r.status_code == 429:
                                await asyncio.sleep(15)  # Free is 5 req/min
                                continue
                            r.raise_for_status()
                        break
                    except Exception as e:
                        if attempt == 2:
                            self._sentry.capture_exception(e)
                        await asyncio.sleep(2 ** attempt)
                await asyncio.sleep(13)  # 5 req/min on Free = 12s/req; 13s gives margin
```

**Pitfalls to avoid:**
1. **Cache-Tag header emission on Free is unverified** — test before relying on it. The April 2025 changelog opened all purge METHODS to all plans, but Cache-Tag header EMISSION support on Free is not explicitly documented.
2. **Free Purge API limit: 5 req/min, 25-token bucket.** Fire-and-forget at any scale beyond toy = hits limit instantly. Bounded queue with rate-limiting is mandatory.
3. **Cache-Tag has limits**: 16 KB aggregate per response, ~1000 tags max, 1024 chars per tag, printable ASCII only, no spaces, hyphens OK so UUIDs work.
4. **Purge failures must not be silent** — Sentry alert on persistent failures.
5. **TTL is the source of truth for consistency** — purge is best-effort optimization. Never set TTL based on assumption purge will fire.

**Verification gate:**
- `curl -I /api/health` shows `Cache-Tag` header
- Manual purge via API call → next request shows `cf-cache-status: MISS` then `HIT`
- Queue drains correctly under load test
- Sentry alerts trigger on simulated CF API outage

**Rollback:** stop draining queue; remove Cache-Tag emission.

---

### Skipped: Phase D.4 (TLS 1.3 minimum)

**Do NOT enforce.** Keep Minimum TLS at 1.2.

**Why:** [Cloudflare itself recommends against TLS min > 1.2](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/minimum-tls/) — "likely cause issues with search engine crawlers and some web browsers." India Android <7 device long-tail is real. TLS 1.3 already negotiates for capable clients without forcing min.

---

### Deferred: Phase E (Worker for /api/graph)

**Defer until 1k+ DAU.** Per-PoP MISS dominates at 10-15 users — most requests would be MISS (Worker cache is per-PoP, not global). The existing in-process LRU+SWR in `graph_cache.py` (TTL 30s, SWR 300s, ~60% hit per codebase audit) is doing the job.

Revisit when:
- Daily Active Users > 1000
- `/api/graph` p95 origin latency > 500ms consistently
- Multiple geo cohorts emerge (US + India simultaneous)

Conditions if/when revisited: see DA Phase E+F report §Phase E verdict (8 mandatory conditions).

---

### Replaced: Phase F (Workers KV for user profile)

**Fully replaced by P5 (Supabase Custom Access Token Hook).** Same goal (skip Supabase profile RTT per page), zero new infra, no SPOF, no 60s consistency window, no $50-100/mo at scale, no DPDP exposure, no KV-outage blast radius.

The original Phase F is a documented anti-pattern given Supabase's native solution.

---

## 3. Infrastructure overhead audit (CLAUDE.md production discipline)

| Concern | Impact | Verdict |
|---|---|---|
| Droplet RAM | +0 MB. All P1-P8 are stateless middleware/header/config. No Redis, no Workers, no new daemons. P9 adds 1 cron job (negligible). | ✅ safe |
| `GUNICORN_WORKERS`, `--preload`, `FP32_VERIFY_ENABLED`, `GUNICORN_TIMEOUT`, rerank semaphore, SSE heartbeat cadence, Caddy upstream timeouts, schema-drift gate, `kg_users` allowlist gate | All untouched (protected knobs). | ✅ safe |
| Caddy config | P9 changes cert challenge from TLS-ALPN-01 to DNS-01 (small, well-tested) + adds mTLS (P4). Single reload needed. | ⚠️ requires careful canary |
| DigitalOcean cloud firewall | New configuration. No droplet-side change. | ✅ safe |
| Per-request latency from FastAPI middleware (P6) | ~30-50µs to set 3 headers from a dict lookup | ✅ negligible |
| Cloudflare API token (P5 DNS-01 + P10 Purge) | One-time generation in CF dashboard. Stored as `CLOUDFLARE_API_TOKEN` env var on droplet. **`<private>` tag in any docs**. | ✅ safe |
| Supabase hook function (P5) | One-time SQL migration. STABLE function = consistent across replicas. | ✅ safe |
| AI Gateway (P8) | New external dependency for entity extraction only. `GEMINI_DIRECT_FALLBACK` toggle + synthetic ping = bounded blast radius. | ⚠️ verified with POC |
| Cost | AI Gateway free for our volume; Cloudflare Free plan covers everything else; DO firewall free; Supabase hook free. **$0 monthly delta** for P1-P10 as written. | ✅ safe |
| Cost decision point | Cloudflare Business plan $200/mo for India routing parity — see §6 below. Operator decision. | ✅ flagged |
| bfcache | No new `unload` handlers, no Rocket Loader. Header-only changes neutral or positive. | ✅ safe |

---

## 4. Risk register (consolidated)

Ranked by (likelihood × blast radius). Top 15:

| # | Risk | Likelihood | Blast | Phase | Mitigation |
|---|---|---|---|---|---|
| 1 | DO cloud firewall stale-IP-list outage (cron silent fail) | MED | TOTAL | P9 | Dead-man's-switch + last-known-good snapshot + validate fetch |
| 2 | Caddy cert expiry after :80 lock (TLS-ALPN-01 broken) | HIGH if not addressed | TOTAL in 60-90d | P9 | DNS-01 swap FIRST, verify next renewal cycle |
| 3 | mTLS misconfig + IP lockdown active simultaneously → can't debug | MED | DEBUGGABILITY | P4+P9 | Test mTLS BEFORE IP lockdown; operator panic IP allowlisted |
| 4 | FastAPI middleware caches 500 → 5min global cached outage | MED | PRODUCT | P6 | Status-code gate (200/206/301/304 only) — mandatory |
| 5 | FastAPI middleware caches SSE → partial stream served forever | MED | USER | P6 | Content-Type gate (skip text/event-stream) — mandatory |
| 6 | Cross-tenant data leak if Vary: X-User-Hash silently ignored on Free | HIGH if attempted | USER | A.3 | **DO NOT attempt per-user edge caching on Free.** Browser-only. |
| 7 | AI Gateway outage cascades into entity-extraction failure | LOW-MED | PRODUCT | P8 | `GEMINI_DIRECT_FALLBACK` hot-wired + synthetic 60s ping |
| 8 | AI Gateway caches safety-blocked Gemini response → served to all for 24h | MED | COHORT | P8 | Detect empty `candidates[]` → `cf-aig-skip-cache` |
| 9 | DPDP exposure from prompt bodies in CF US logs (P8) | MED | COMPLIANCE | P8 | `cf-aig-collect-log-payload: false` + DPA + privacy policy update |
| 10 | Configuration Rule body-buffering bug (Dec 5 2025 type) | LOW-MED (recent precedent) | PRODUCT | P1 | Rollback runbook ready; scope to POST only |
| 11 | Cache-Tag header emission on Free unverified — P10 silently no-ops | MED | OBSERVABILITY | P10 | Test with `curl -I` first; defer P10 until verified |
| 12 | Free Purge API rate limit (5/min) drops invalidations under load | MED | COHORT | P10 | Bounded queue + 13s spacing + Sentry alert |
| 13 | Supabase hook function raises → all auth breaks | LOW | TOTAL | P5 | Defensive defaults in hook SQL; hook-test on deploy |
| 14 | Tenant-hopping bypass via another CF customer DNS-A to our IP (without P4 mTLS) | MED | SECURITY | P4 | mTLS Authenticated Origin Pulls — closes the bypass class |
| 15 | India Android <7 / older crawler loses access (if TLS 1.3 min forced) | LOW-MED | USER COHORT | D.4 | **Don't enforce TLS 1.3 min — keep 1.2** |

---

## 5. Free vs Pro/Business plan decision point

| Plan | $/mo | Unlocks for our stack | Verdict |
|---|---|---|---|
| **Free (current)** | $0 | Cache Rules (10), Compression Rules (10), Configuration Rules (limited), Purge API (5/min), Speed Brain, Early Hints, HTTP/3, 0-RTT, AI Gateway core, Workers free tier | **OK for P1-P10 as written.** Per-user edge caching is structurally impossible. |
| **Pro** | $25/mo | Snippets, Polish (image opt), more Cache/Compression Rules, longer log retention | **Not needed** unless image-heavy site (we aren't). Skip. |
| **Business** | $200/mo | **India routing parity** (Jio/Airtel → Mumbai/Chennai instead of Singapore/Amsterdam, -100ms RTT), HTTP/3 prioritization, Cache Reserve eligibility | **Decision point** — only worth it when India MAU > ~25 daily active. **Operator-only call.** |
| **Enterprise** | custom $$$ | Custom cache keys (real per-user edge caching), 300 rules, dedicated support | **Far future** — only at 100k+ DAU |

**Recommendation:** Stay on Free for P1-P10. Re-evaluate Business plan upgrade when India daily-active-users sustained > 25.

---

## 6. Execution order recommendation

Strictly sequential — each phase is independently shippable + revertible. Verification gate between each.

**Week 1 (high impact, low effort):**
- Day 1: P2 + P3 + verify (dashboard toggles only)
- Day 2-3: P1 (SSE unbreak) + verify on real browser
- Day 4: P4 (mTLS Authenticated Origin Pulls) + Caddy config + verify

**Week 2 (medium effort):**
- Day 1-2: P5 (Supabase Custom Access Token Hook) + FastAPI middleware + verify
- Day 3-5: P6 (cache middleware + Cache Rules) + verify with concurrent two-user fixture

**Week 3 (smaller wins + security tightening):**
- Day 1-2: P7 (ETag/304 via etag-middleware) + verify
- Day 3-5: P9 (DO Cloud Firewall + DNS-01 + IPv6 lockdown + dead-man's-switch) + canary

**Week 4 (optional/conditional):**
- Day 1-2: P8 POC (AI Gateway for entity extraction) — 12-test POC
- Day 3: if POC passes, ship P8
- Day 4: verify P10 prerequisite (`Cache-Tag` header on Free) — if confirmed, ship P10

**Defer indefinitely:** Phase E (Worker for /api/graph), Phase D.4 (TLS 1.3 min).

**Operator decisions:**
- D.5 mTLS is **strongly recommended** (closes a real attack class); Phase B URL summarization POC is **optional**.
- Business plan upgrade ($200/mo) is **deferred** until India MAU growth justifies.

---

## 7. Things we are explicitly NOT doing (with rationale)

| Item | Why |
|---|---|
| Replacing `GeminiKeyPool` | `cf-aig-max-attempts` capped at 5; we traverse 20. Multi-key same-provider Dynamic Routing chain undocumented and likely unsupported. |
| AI Gateway for RAG chat SSE | `streamGenerateContent` buffer bug unresolved (April 2026 RFC unassigned). |
| AI Gateway for URL summarization (initial scope) | Low cache hit rate at 10-15 users; revisit at scale via POC. |
| Vectorize migration | 1536-dim cap loses Supabase RLS for `kg_users` tenancy. |
| AutoRAG | Our RAG pipeline is too custom. |
| Workers AI embeddings | Would undo iter-03 BGE int8 RAM work (protected knob). |
| Cache Reserve | Min ~$5/mo + only wins on egress-heavy long-tail. Traffic too low. |
| Argo Smart Routing | $5/mo + $0.10/GB. Single-region single-origin India-heavy stack. |
| Load Balancing | Single origin. |
| Cloudflare Tunnel migration | Adds 5-20ms; worse for SSE; replaced by IP lockdown + mTLS at zero latency cost. |
| China Network | No China users. |
| Python Workers | Pyodide-based, immature, 128MB RAM ceiling. |
| Smart Placement | Worse for cache workloads per CF docs. |
| Snippets | Pro plan required. |
| D1 | Tenant data lives in Supabase v2 schemas. |
| R2 mirror | Future user-uploads only. |
| Browser Rendering | Future Substack-JS-paywall scrape only. |
| Mirage / Auto Minify / Rocket Loader | Deprecated/legacy. |
| Workers KV for user profile | Replaced by Supabase Custom Access Token Hook. |
| Worker for /api/graph | Deferred to 1k+ DAU. |
| Vary: X-User-Hash on Free | Silently ignored → cross-tenant leak. |
| `fastapi-etag` library | Abandoned 12+ months. |
| 1KB SSE first-token padding | Buffer threshold is 100KB; 1KB is a no-op. |
| `Priority: u=1, i` on SSE response | Non-standard for response; CF doesn't act on it; middlebox risk. |
| In-droplet iptables for origin lockdown | Self-lockout risk; use DO Cloud Firewall instead. |
| Minimum TLS 1.3 | CF themselves don't recommend; India Android <7 risk. |
| Per-user `/api/graph` edge caching | Structurally impossible on Free (Vary ignored + 2h min TTL). |

---

## 8. Sources (consolidated; 60+ cited 2022-2026)

Refer to:
- [2026-05-24-cloudflare-10x-plan.md §8](./2026-05-24-cloudflare-10x-plan.md) — original sources
- [2026-05-24-ai-gateway-devils-advocate.md §9](./2026-05-24-ai-gateway-devils-advocate.md) — Phase B DA sources
- Phase A DA report — Free plan limits, Vary ignored, ETag library status, cache poisoning patterns
- Phase C DA report — Configuration Rule GA, Dec 5 2025 outage, RFC 9218 clarification, Mintlify compression writeup
- Phase D DA report — TLS min docs, mTLS bypass class, Caddy DNS-01, DO firewall vs iptables
- Phase E+F DA report — KV outage, Supabase Custom Access Token Hook, Worker cache per-PoP, Smart Placement warning

Critical new sources (not in original 10x plan):
- [CF Authenticated Origin Pulls docs](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/)
- [Javan Rasokat — IP allowlist insufficient](https://javan.de/relying-solely-on-ip-allowlisting-with-cloudflare-is-wrong/)
- [Supabase Custom Access Token Hook docs](https://supabase.com/docs/guides/auth/auth-hooks/custom-access-token-hook)
- [CF Minimum TLS Version docs](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/minimum-tls/)
- [CF Cache Keys — Vary on Free](https://developers.cloudflare.com/cache/how-to/cache-keys/)
- [CF Vary for Images docs](https://developers.cloudflare.com/cache/advanced-configuration/vary-for-images/)
- [CF Workers KV How It Works (60s propagation)](https://developers.cloudflare.com/kv/concepts/how-kv-works/)
- [CF June 12 2025 outage RCA](https://blog.cloudflare.com/cloudflare-service-outage-june-12-2025/)
- [CF Dec 5 2025 outage RCA](https://blog.cloudflare.com/5-december-2025-outage/)
- [CF Async SWR changelog Feb 2026](https://developers.cloudflare.com/changelog/post/2026-02-26-async-stale-while-revalidate/)
- [CF Configuration Rules body-buffering changelog Jan 2026](https://developers.cloudflare.com/changelog/2026-01-27-body-buffering-settings/)
- [Caddy DNS challenge with Cloudflare](https://caddy.community/t/dns-challenge-with-cloudflare/30670)
- [`etag-middleware` PyPI](https://pypi.org/project/etag-middleware/)
- [`fastapi-etag` PyPI (abandoned)](https://pypi.org/project/fastapi-etag/)

---

## 9. Final honest summary

| What the original 10x plan promised | What this revised plan delivers |
|---|---|
| 4-7x session-weighted average | **~2-3x session-weighted average** |
| 50x on /api/graph warm cache | **~1.2-1.5x** (browser-only on Free) |
| 75x on duplicate URL summarization | **Low at our scale**; meaningful only at 1k+ DAU |
| "Bulk win" | **Concentrated win on SSE (6-16x first-token) + entity-extraction cache + India mobile warm-GETs** |
| No mention of security upgrade | **mTLS (P4) is the standout security improvement** |
| Phase B "headline app-level win" | Narrowed to entity extraction; URL summarization POC-deferred |
| Phase E/F as "optional boosters" | E deferred; F replaced by Supabase JWT hook |

**The good news:** the SSE unbreak (P1) genuinely makes RAG chat feel materially faster, the mTLS upgrade (P4) closes a real attack class, and the protocol toggles (P2-P3) cost nothing. **Combined, P1+P2+P3+P4 ship in ~2 days of effort and capture ~70% of the realistic value of this entire plan.** Everything else is marginal-but-worthwhile or deferred-to-scale.

**Single most impactful sequence if you only do 4 things:** P1 → P2 → P3 → P4. Two days of work; the genuine 10x perception lives in SSE first-token + India warm-GETs + security parity.
