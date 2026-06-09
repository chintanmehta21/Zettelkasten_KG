# Graph-Loading Industry Research — Backend Delivery + Frontend Rendering

**Date:** 2026-06-04
**Author:** Claude Code (assistant-authored research; not an implementation plan — no code changed)
**Scope:** End-to-end "ideal load" for `/knowledge-graph` — backend graph-data API + frontend rendering.
**Method:** 6 web-research angles (Sonnet) → per-angle adversarial verification (refute + our-stack risk) → cross-checked against our actual code. Recency filter 2021–2026. Verdicts: **adopt / adopt-with-mods / reject** for a **2 GB / 1 vCPU / 2-worker** droplet, ~10–15 users scaling to 10k.

> **Reading note.** Every recommendation below was passed through an adversarial verifier that hunted counter-evidence and stack-specific side-effects. Where the verifier overturned or qualified a claim, it is marked **⚠ corrected**. Where our code already does the thing, it is marked **✅ already in place** so we don't redo it.

---

## 0. TL;DR — Priority Shortlist (minor-mods, in current stack)

Ranked by **(perceived-load impact) ÷ (risk + infra)**. All zero-new-infra.

| # | Change | Effort | Risk | Why it wins |
|---|--------|--------|------|-------------|
| 1 | **Wire weak-ETag + `Cache-Control: private, max-age=30, stale-while-revalidate=300` onto `/api/graph`** | ~½ day | Very low | Infra already exists (`if_none_match`); turns repeat-visit + duplicate fetches into cheap `304`s. `private` is **mandatory** (CDN leak otherwise). |
| 2 | **Kill the 2–3 duplicate `/api/graph` fetches** (vanilla dedup; `loadUserOwnedIds` shares the `view=my` fetch) | ~½ day | Very low | Pure client; removes 1–2 full graph builds per logged-in visit. |
| 3 | **`asyncio.to_thread` the cold build + `Semaphore(1)`/worker around igraph** | ~1 day | Low–med | Fixes the real bug: cold build freezes the worker (availability, not just speed). Semaphore prevents CPU thrash + igraph RNG races. |
| 4 | **Parallelize / collapse the 3–4 sequential DB round-trips** (wrap sync calls in `to_thread` + `gather(return_exceptions=True)`, or one Postgres RPC) | 1–2 days | Med | Cold build latency drops ~proportionally to round-trip count. |
| 5 | **Server-precompute node positions (igraph FR-3D only) → inject `fx/fy/fz`, set client `warmup/cooldownTicks=0`** | 2–3 days | Med (UX appearance) | Eliminates the ~2.5s client settle. **Needs operator eyeball** (changes the "alive settle" look). |

Lower tier (build when a user crosses ~500–1500 nodes): skeleton screen on the build window; personal-subgraph-first progressive reveal; LOD/focal-node subsetting as a scale gate.

---

## PART A — BACKEND / API DELIVERY

### A1. Payload delivery: full vs paginated vs viewport/LOD vs streaming

**Industry standard (2021–2026).** Single full JSON payload is the norm for **small/medium** graphs; Neo4j Bloom hard-caps at **10k nodes**; Linkurious Ogma / Datadog Service Map / Grafana topology use **server-side LOD / focal-node + top-K-by-centrality subsetting** above that; **cursor pagination (Stripe, GitHub, Relay spec)** is for *lists*, not graph topology; **streaming (NDJSON/SSE)** is used by Neo4j's 3D WebGL demo for very large sets.

- **Full payload — VERDICT: adopt as-is to ~8k total nodes+edges/user.** Our payload at `limit=5000` is ~0.5–3 MB compressed = safe zone today. The bottleneck is the *blocking build*, not bytes. *Caveat:* the oft-cited "9–27× RAM-on-parse" figure is a 2020 source; **⚠ corrected** to "directional, not a hard threshold" (V8 ≥7.6 rewrote the `JSON.parse` fast-path).
- **Cursor pagination — VERDICT: reject for `/api/graph`, adopt for `/api/zettels` lists.** Paginating topology breaks edges whose endpoint is on an unfetched page.
- **Server-side LOD / focal-node subsetting — VERDICT: adopt-with-mods, as a SCALE GATE.** Serve full graph ≤ ~2k nodes; above that return a `focal_node_id` + `depth` + top-K-by-PageRank neighbourhood. **Prerequisite: the `to_thread` fix (A3) first**, else more igraph calls = more event-loop freeze. Not needed at current scale; build the threshold now.
- **Streaming (NDJSON/SSE) — VERDICT: DEFER for our stack. ⚠ corrected (downgraded).** Verifier found **Cloudflare buffers chunked/streaming responses** until ~full/threshold — so the "nodes render first" benefit is likely *neutralized* behind our CDN, while adding cache-key fragmentation + lost middleware compression. Only revisit if CF buffering is confirmed off (`X-Accel-Buffering: no` validated on the zone).

*Citations:* Neo4j Bloom 10k limit (community, 2022); Linkurious Ogma vs Cytoscape (2024); Stripe pagination (2024); Relay connections spec; Neo4j 3D WebGL incremental demo (2021); FastAPI `StreamingResponse` NDJSON (2024).

### A2. Where to compute expensive analytics (PageRank / Louvain / betweenness)

**Industry standard.** Precompute-on-write / materialized: Neo4j GDS `write`/`mutate` modes, Gephi, Cambridge Intelligence, TigerGraph all store scores as node properties and the viz reads properties — **never** runs the algorithm per request. Per-request exact betweenness (O(V·E)) is used by *no one* at scale.

- **Precompute-on-write + cache — VERDICT: adopt.** Move scores into a `kg_node_analytics` (pagerank/community/betweenness/`computed_at`) table written by a background task; `/api/graph` reads columns. ✅ *Partial:* we **already** memoize analytics by content hash ([routes.py:183](../../website/api/routes.py)) so identical topology isn't recomputed — this is a lighter version of the same idea.
- **Approximate/sampled betweenness — VERDICT: adopt-with-mods, deferred.** Build an exact/approximate switch at `node_count>500`. **⚠ corrected:** igraph has **no** built-in `k`-sampling (issue #8 open since 2013); `betweenness(vertices=…)` still computes full all-pairs — it only filters output. Real approximate path = manual pivot-accumulation (~50 lines) or NetworkX `betweenness_centrality(G, k=N)`. At <500 nodes/user, exact igraph is fine; defer.
- **Scheduled refresh (APScheduler) — VERDICT: adopt-with-mods, later. ⚠ corrected.** APScheduler **4.0 is pre-release** (pin `>=3.10,<4`); the advisory-lock dedup across 2 workers is a community hack — the *supported* multi-process dedup is an APScheduler **SQLAlchemy job store on the existing Supabase Postgres**. Or simpler: fire-on-write `to_thread` refresh. Don't add Celery/Redis.
- **Compute-on-read per request — VERDICT: reject** for betweenness/PageRank/Louvain (keep only sub-ms degree inline).

*Citations:* Neo4j GDS running-algos + betweenness write mode (2026); Technori materialized-views tradeoffs (Jan 2026); NetworkX betweenness `k`; igraph issue #8; Cambridge Intelligence SNA (2024); APScheduler FAQ / discussion #1088.

### A3. Async hygiene: get blocking DB + CPU off the event loop; parallelize DB

**Industry standard.** FastAPI/Starlette/anyio canon: wrap every blocking call in `await asyncio.to_thread(...)` / `run_in_executor`; **CPU parallelism needs `ProcessPoolExecutor`**, not threads; fan out independent I/O with `asyncio.gather`; collapse round-trips with PostgREST resource embedding or an RPC.

- **`to_thread` the build + analytics — VERDICT: adopt (the immediate availability fix).** Today `_v2_assemble_graph` + `_enrich_graph_with_analytics` run **synchronously on the event loop** ([view_graph.py:318/363](../../website/api/module_runners/view_graph.py) call them directly, no `to_thread`) → a cold build freezes the worker. **⚠ key correction across angles:** whether **python-igraph releases the GIL** is *unverified / build-dependent* (needs `IGRAPH_ENABLE_TLS=ON`; the RNG is never thread-safe). So frame the win precisely: `to_thread` reliably restores **event-loop liveness** (worker serves other requests during a build) — it does **not** guarantee concurrent CPU throughput, and on 1 vCPU that's moot anyway. **Mandatory companion: a `Semaphore(1)` per worker around the igraph step** (mirrors our existing rerank-semaphore pattern) to (a) prevent CPU thrash from concurrent builds and (b) avoid igraph RNG data races. Pass an immutable snapshot, not a shared `Graph`.
- **`asyncio.gather` for the 3–4 serial DB calls — VERDICT: adopt-with-mods.** Our PostgREST client is **synchronous**, so this is `gather(*[to_thread(call) for call in …])`, not native async. **⚠ corrected:** use **`return_exceptions=True`** — default `gather` discards completed siblings on first error (pays network, throws data away → retry amplification). Add an `asyncio.Semaphore` cap; Supabase pooler is **Supavisor** (not PgBouncer), transaction-mode, port 6543.
- **Single Postgres RPC / FK embedding — VERDICT: adopt-with-mods (best long-term collapse).** One `POST /rpc/get_graph` = one round-trip, server-side join. **⚠ corrected:** PostgREST FK embedding **silently fails on UNION views** — audit every table (our public/anon graph mirror may union sources) before relying on it.
- **`ProcessPoolExecutor` — VERDICT: reject.** Fork + gunicorn pre-fork = documented deadlock (CPython #105464; 3.14 changed the default away from fork), **and** +30–50 MB/subprocess risks OOM on 2 GB, **and** zero CPU gain on 1 vCPU.
- **External task queue (Celery/RQ/Arq) — VERDICT: defer to 10k+** (needs Redis + worker RAM).
- **⚠ corrected (thread-pool isolation):** anyio's default 40-token pool is **shared** with sync deps — a slow build can starve HTTP handlers. Use a **dedicated `CapacityLimiter`** for the analytics path + an `anyio.fail_after` timeout.

*Citations:* FastAPI async docs; anyio threads docs; Sentry run_in_executor (2023); PostgREST v12/v14 embedding + issue #1587; Supabase Supavisor announcement (2023); CPython #105464; SuperFastPython `gather` exceptions.

### A4. HTTP delivery + cache architecture

**Industry standard.** ETag/`If-None-Match` 304 (GitHub, Wikimedia, Stripe); `Cache-Control` + `stale-while-revalidate`; compression at the **edge/proxy**, not in-app; payload trimming via sparse fieldsets; in-process cache until multi-node, then Redis.

- **ETag + 304 on `/api/graph` — VERDICT: adopt (highest ROI / lowest effort).** ✅ Infra exists: `if_none_match` weak-compare ([functional_gates], used at [routes.py:557](../../website/api/routes.py)) — but `/api/graph` ([routes.py:1318](../../website/api/routes.py)) returns a **plain dict, no ETag/Cache-Control**. Wire it: ETag = cheap version key (newest-zettel `updated_at` or `graph_hash` we already compute), cached alongside the payload (don't recompute per request). **Weak ETag is required** behind Cloudflare (it weakens strong ETags on compression — our PR #133 precedent).
- **`Cache-Control: private, max-age=30, stale-while-revalidate=300` — VERDICT: adopt.** Mirrors our in-process 30s+300s SWR at the browser. **⚠ corrected — `private` is non-negotiable:** without it a shared CDN can serve user A's graph to user B (Railway/Next.js 2024 incident). Our `/api/me` already sets `private, no-store` — same discipline.
- **Compression — VERDICT: ✅ already in place (verify redundancy).** Caddy does `encode zstd gzip` ([Caddyfile:13](../../ops/caddy/Caddyfile)). **⚠ finding:** we *also* run in-process `BrotliMiddleware`/`GZipMiddleware` ([app.py:465](../../website/app.py)). On 1 vCPU, compressing inside the Python worker steals event-loop CPU; the verifier's standing advice is "compress at the proxy." **Action: measure whether the Python middleware is redundant given Caddy (+Cloudflare edge); if so, drop it** so compression stays off the GIL. (Both run on the same box, so this is a liveness optimization, not a raw-CPU one — verify before removing.)
- **Edge-caching personalized graph — VERDICT: reject (keep origin-only).** ✅ `private` already prevents it. **⚠ corrected:** CF Free/Pro enforce a **2-hour minimum edge TTL** — `s-maxage=60` is impossible there; and CF custom cache keys are **no longer Enterprise-only** (now via Cache Rules on all tiers) but irrelevant for private data.
- **Payload shrinking — field trimming VERDICT: adopt** (sparse fields; we already `_trim_graph_response`). **Integer IDs / MessagePack / Protobuf — VERDICT: reject for our scale. ⚠ corrected:** post-gzip, integer-ID and MessagePack savings are negligible (gzip already exploits JSON redundancy); Protobuf/FlatBuffers add schema+codegen for ROI erased by gzip.
- **In-process vs Redis — VERDICT: in-process is correct now; Redis deferred.** ✅ Our cache is `asyncio.Lock` + `OrderedDict` ([graph_cache.py](../../website/api/graph_cache.py)) — so the verifier's "`cachetools.LRUCache` not thread-safe" risk **does not apply** to us. Per-worker incoherence (worker B serves ≤30s stale after a write on A) is acceptable at our scale; **consider shortening the 300s SWR to ~60s** to bound cross-worker staleness. Add Redis only at ~50+ concurrent / 3rd worker / multi-droplet.

*Citations:* Wikimedia conditional requests; MDN `Cache-Control`; Cloudflare ETag + default-cache + edge-TTL docs; lemire.me gzip vs zstd (2021); Railway CDN incident (2024); peterbe.com msgpack-vs-gzip; "don't jump to Redis in FastAPI" (Medium).

---

## PART B — FRONTEND / RENDERING

### B1. Rendering large node-link graphs (precomputed layout, LOD, instancing)

**Industry standard.** "Ship coordinates, not a simulation": Graphistry/Gephi/KeyLines precompute positions server-side and the browser only renders (WebGL). `warmupTicks`/`cooldownTicks` is the cheap pre-settle. Library ceilings: **3d-force-graph ~2–4k smooth** (sluggish ~8k; <500 with live sim on mobile); Sigma.js v2 100k+; Cosmograph 1M+ (GPU).

- **Server-precompute positions (igraph FR-3D) + inject `fx/fy/fz`, client `warmup/cooldownTicks=0` — VERDICT: adopt-with-mods (biggest perceived-load win).** Kills the ~2.5s settle. **⚠ corrected — FR-3D only, never Kamada-Kawai** (O(V²); igraph caps KK at ~100 nodes — it would run for *minutes* on 2k). FR-3D ~50–200 ms at <500 nodes, inside the cached+`to_thread`+semaphore build. **Operator decision flagged:** this replaces the animated settle with an instant static layout and may change the look (we deliberately keep an "alive" feel — particles always on). Keep a brief gentle reheat if the static load feels dead. Don't ship without an eyeball.
- **`warmupTicks`/`cooldownTicks` — VERDICT: ✅ already in place.** [app.js:927](../../website/features/knowledge_graph/js/app.js) sets `warmupTicks(100)`, `cooldownTime(2500)`, `d3AlphaDecay(0.025)`, `d3AlphaMin(0.01)`, `useWebWorker:true`. The remaining lever is B1's precompute, not more tick-tuning. **⚠ mobile caveat:** cap warmup ticks (≈`min(50, nodes/10)`) — 100 synchronous ticks can freeze a low-end phone before first paint.
- **Library migration (Sigma.js v2) — VERDICT: reject now, revisit only >~1500 nodes/user on mobile.** Cosmograph/cosmos.gl — reject (GPU/WebGL2 overkill until ~50k).
- **`to_thread` + `gather` (restated here) — adopt;** see A3 for the corrections (GIL unverified; semaphore mandatory; snapshot the Graph).

*Citations:* Graphistry architecture; 3d-force-graph + d3-force-3d READMEs; igraph layout docs (KK ≤100); PkgPulse 2026 + PMC 2025 library benchmarks; Nightingale "million-node" article.

### B2. Fetch hygiene + perceived performance

**Industry standard.** Client request-dedup + SWR (TanStack Query / SWR in React); skeleton screens for 2–10s waits; ego-subgraph-first (Obsidian Local Graph, Roam, Kumu); one combined endpoint over N fetches.

- **Dedup the 2–3 `/api/graph` fetches — VERDICT: adopt (vanilla, not React).** **⚠ critical stack correction:** our frontend is **vanilla JS** ([app.js](../../website/features/knowledge_graph/js/app.js) IIFE + `zkFetch`) — **TanStack Query/SWR do not apply** (React libs, need a bundler). Equivalent = a ~10-line module-level in-flight-promise cache keyed by `(view,min_strength)`. **Concrete free win:** when `currentView==='my'`, `loadUserOwnedIds()` ([app.js:499](../../website/features/knowledge_graph/js/app.js)) fetches the *same* `/api/graph?view=my` that `loadGraphData()` fetches — share one response instead of two.
- **Browser SWR / instant-revisit paint — VERDICT: adopt via headers (A4).** The `Cache-Control` header (A4) gives the browser instant repaint on revisit with no JS library. **⚠ reject `localStorage` cross-session persistence** of the graph: race where the key is `['graph', undefined]` before auth resolves → user A's graph shown to user B on shared device. If ever added, gate on confirmed auth + use `sessionStorage`.
- **Skeleton screen on the build window — VERDICT: adopt-with-mods.** Use a `<div>`/CSS non-specific "node cluster" placeholder (not a canvas — avoids extra WebGL contexts; not a precise node replica — avoids false layout expectation). **⚠ corrected:** the headline skeleton study (Mejtoft 2018) actually reported **no statistically significant** speed win and that spinner users found first-visit targets faster — so treat skeleton as a polish item, pair with "Building your graph…".
- **Personal-subgraph-first progressive reveal — VERDICT: adopt-with-mods, when users hit 500+ nodes.** Render top-N (PageRank) personal subgraph in <200ms, hot-merge the rest via `graphData()`. **⚠ corrected:** mitigate node-jump with `nodeId`-stable updates + reheat only on first render (not a globally low alpha). The new endpoint **must** sit behind our existing schema-drift + `kg_users` allowlist gates (protected knobs) — "no new infra" ≠ "no auth work".

*Citations:* TanStack Query vs SWR (PkgPulse 2026); Mejtoft 2018 (ResearchGate — note significance caveat); NNGroup skeleton screens (2022); Obsidian Local Graph; web.dev stale-while-revalidate; 3d-force-graph `graphData()` hot-update.

---

## PART C — Bigger options: explicit keep/reject for 2 GB / 1 vCPU (→10k)

| Option | Verdict | Rationale |
|--------|---------|-----------|
| **Redis (shared cache)** | **Reject now / adopt at ~50+ concurrent or 3rd worker** | In-proc `asyncio.Lock` cache is correct for 2 workers/15 users; ~80 MB at 200 users fits 2 GB. Adds a service + RAM for cross-worker coherence we don't need yet. |
| **Graph DB (Neo4j/AGE)** | **Reject** | Postgres + igraph is sufficient; Neo4j = RAM-heavy new service + migration. The GDS advantage (precomputed scores) is captured by A2's precompute-on-write in Postgres. |
| **GraphQL** | **Reject** | One graph endpoint, already-unified payload; GraphQL adds schema/codegen with no delivery benefit here. (Relay pagination only relevant to list endpoints.) |
| **Dedicated precompute service / Celery+Redis** | **Reject now / 10k+** | APScheduler-3.x (SQLAlchemy job store) or fire-on-write `to_thread` covers refresh with zero new infra. |
| **CDN-edge compute (CF Workers)** | **Reject** | Per-user private data can't be edge-cached; CF Free 2-hr min TTL; Workers $5+/mo. Negligible value vs origin + `private`. |
| **`ProcessPoolExecutor`** | **Reject** | Fork+gunicorn deadlock (CPython #105464) + OOM risk on 2 GB + no CPU gain on 1 vCPU. |
| **Binary wire formats (Protobuf/FlatBuffers/MessagePack)** | **Reject** | Gains erased by gzip; schema/codegen + browser-parse cost not worth it at our scale. |
| **NDJSON/SSE streaming** | **Defer (stack-specific)** | Cloudflare buffers chunked responses → progressive-render benefit likely neutralized; revisit only if buffering confirmed off. |

---

## PART D — ✅ Already in place (do NOT redo)

- Proxy compression: Caddy `encode zstd gzip` ([Caddyfile:13](../../ops/caddy/Caddyfile)).
- Weak-ETag gate exists (`if_none_match`, [routes.py:34](../../website/api/routes.py)) — used on `/api/avatars`, **not yet on `/api/graph`**.
- Cache: `asyncio.Lock` + `OrderedDict`, 30s TTL + 300s SWR + single-flight coalescing + full-invalidate on mutation ([graph_cache.py](../../website/api/graph_cache.py)) — already thread-safe; already the SWR pattern.
- Analytics memoized by content hash ([routes.py:183](../../website/api/routes.py)).
- Frontend: WebWorker layout, `warmupTicks(100)`/`cooldownTime(2500)`/`d3AlphaMin(0.01)`, shared sphere geometry, shallow-clone (F8), per-sprite `onBeforeRender` (no 60 Hz O(N) loop) ([app.js:927](../../website/features/knowledge_graph/js/app.js)).
- Wire-boundary summary parsing + field trimming (`_trim_graph_response`, `_normalize_summary_for_wire`).

---

## PART E — Adversarial corrections that changed a verdict (read these)

1. **igraph GIL release is unverified** → frame `to_thread` as an *event-loop-liveness* fix, not a throughput fix; add a **`Semaphore(1)`** + Graph snapshot (RNG not thread-safe).
2. **`asyncio.gather` default discards siblings on first error** → use `return_exceptions=True`.
3. **Cloudflare buffers streaming responses** → NDJSON/SSE downgraded to *defer*.
4. **Kamada-Kawai is O(V²)** → server layout must be **FR-3D only**.
5. **`private` is mandatory** on `/api/graph` cache headers → else CDN cross-user leak.
6. **CF Free 2-hr min edge TTL** → public `s-maxage=60` is impossible there.
7. **Our frontend is vanilla JS, cache is `asyncio.Lock`** → TanStack/SWR and the `cachetools` thread-safety risk both **N/A**; redundant in-process `BrotliMiddleware` is the real frontend-adjacent finding.

---

## PART F — Suggested sequence (NOT yet approved — research only)

1. ETag + `private` SWR headers on `/api/graph` (reuses existing gate). *(low risk)*
2. Vanilla fetch-dedup + share the `view=my` fetch. *(low risk)*
3. `to_thread` + `Semaphore(1)` around the build/igraph; snapshot the Graph. *(availability fix)*
4. Parallelize/collapse DB round-trips (`gather(return_exceptions=True)` or one RPC; audit UNION views first).
5. Server-precompute FR-3D positions → `fx/fy/fz`, client ticks→0. **(operator UX sign-off required)**
6. Scale gates (build, don't enable): LOD/focal-node subset; skeleton; personal-subgraph-first; `analytics` materialized columns + APScheduler-3.x refresh.

**Open decisions needing operator approval before any code:** (a) precomputed static layout vs the current animated settle (look-and-feel); (b) dropping in-process compression in favor of Caddy/Cloudflare; (c) shortening SWR 300s→60s; (d) whether scale-gate work (LOD/progressive/materialized analytics) is in-scope now or deferred.

---

# FOLLOW-UP: Decisions on the 5 open questions (research round 2, 2026-06-04)

Second deep-research pass (4 angles → adversarial verify) to resolve the open decisions above. Each verdict cross-checked against our actual code.

## Decision table

| # | Question | **Decision** | One-line why |
|---|----------|--------------|--------------|
| Q1+Q3 | In-process Brotli vs Caddy/CF compression | **Drop in-process** (`BrotliMiddleware`/`GZipMiddleware`); keep Caddy `encode zstd gzip` + Cloudflare edge Brotli | In-process compression burns event-loop CPU on 1 vCPU for no gain; Caddy skips already-encoded bodies (no double-compress); `brotli-asgi` is unmaintained (~Oct 2023). |
| Q2 | Static precompute vs animated settle | **Client-side hybrid now** (tune existing settle); **defer** server-side precompute | The team wants "alive"; the problem is the *chaotic 2.5s*, not animation. Tuning `warmupTicks`/`cooldownTime` gives "alive but fast" with zero backend change. Server precompute has real blockers (below). |
| Q4 | SWR 300s → 60s? | **Keep 300s** | 300s is the graceful-degradation buffer for background-refresh failure on CPU-bound local recompute; shortening adds fragility without fixing the root cause (per-worker caches). |
| Q5a | Server-side LOD/focal subset | **Defer** | WebGL render zone is fine to ~3k nodes; our personal graphs are 30–200 nodes. |
| Q5b | Personal-subgraph-first reveal | **Defer impl — seam already exists** | We already have per-user `view=my`, auth, per-user cache. Only the two-phase reveal + top-N subset is deferred. |
| Q5c | Materialized analytics + scheduler | **Defer — cheap guard already exists** | Analytics already content-hash-memoized + `computed_at` in meta; only DB-column persistence is deferred. |

## The keystone change (everything points here)
Wiring **`Cache-Control: private, max-age=30, stale-while-revalidate=300` + weak-ETag onto `/api/graph`** (rec #1 from round 1) is now load-bearing for three of these decisions:
- **Q4:** Cloudflare shipped **async SWR on 2026-02-26** — it now *acts* on the directive at the edge. Without `private`, CF would edge-cache and serve one user's per-user graph to another (BOLA/data leak). `private` keeps `/api/graph` origin-only and our in-process cache the enforcer.
- **Q2 (if server precompute is ever adopted):** prevents CF caching stale node coordinates after a write.
- **Q5:** the ETag/version is the natural freshness key.

## Q1 + Q3 — Compression (DROP in-process)
- **Our code:** Caddy already `encode zstd gzip` ([Caddyfile:13](../../ops/caddy/Caddyfile)); redundant in-process `BrotliMiddleware` (fallback `GZipMiddleware`) at [app.py:465](../../website/app.py).
- **No client ratio regression** (corrects the verifier's "main regression"): **Cloudflare applies edge Brotli to end clients regardless of origin encoding**, so dropping origin `brotli-asgi` does not degrade what clients receive; the origin→Caddy hop is loopback (free) and the Caddy→CF hop uses zstd/gzip (comparable). The verifier's brotli-loss concern only applies if Cloudflare is bypassed (direct-to-origin), which is test-only.
- **⚠ Pre-ship verification (the one real risk):** the **SSE heartbeat path** (Phase 1B.4, a protected knob). Confirm Caddy `encode` does not buffer/break `text/event-stream` (Caddy flushes SSE and generally skips it, but verify on our config) before removing in-process compression. Keep the existing weak-ETag gate (already tolerates CF weakening — PR #133).
- **Citations:** Caddy `encode.go` Content-Encoding passthrough (v2.11.x); Cloudflare content-compression + ETag docs (2024); FastAPI #11972 (middleware CPU); `brotli-asgi` repo (last push ~Oct 2023).

## Q2 — Layout (client-side hybrid now; defer server precompute)
- **Our code:** [app.js:927](../../website/features/knowledge_graph/js/app.js) already sets `useWebWorker:true`, `warmupTicks(100)`, `cooldownTime(2500)`, `d3AlphaDecay(0.025)`. So the verifier's "no built-in worker → warmup blocks main thread" concern is **likely already mitigated** (verify our `3d-force-graph` version honors `useWebWorker`). The client-side hybrid is literally retuning these 3 numbers: raise warmup ticks (more off-screen pre-settle), cut `cooldownTime` to ~1–1.2s gentle drift, keep particles.
- **Why not server-side precompute now (deferred):** real blockers for our stack — (1) **Python has no `d3-force-3d`**: precomputing server-side needs either a **Node.js subprocess** (new droplet runtime dependency, not installed) or **igraph FR-3D** (works in Python but produces a *different* visual layout than d3-force — appearance change); (2) **stale-position regression** across 2 per-worker caches (new node snaps to origin then repels — visually worse); (3) **CF could cache stale coords** without `private`/`no-store`; (4) the 300-tick compute would sit in the cold-build path (mitigated only by the round-1 `to_thread`+`Semaphore` fix).
- **⚠ Operator approval:** the client-side settle retune is a **visible UI change** → needs your eyeball (UI-pref discipline). Never adopt the "instant static" variant (`cooldownTicks=0`) — it kills the alive feel you want and the link-particle bootstrap.
- **Citations:** d3-force `simulation.stop()`+`tick(N)` precompute; 3d-force-graph `warmupTicks`/`cooldownTime` API + issue #27; AVI 2024 (animation ↑ perceived appeal); `d3-force-3d` repo (3D forces are a separate package).

## Q4 — SWR window (KEEP 300s)
- **Corrected rationale:** Cloudflare **async SWR shipped 2026-02-26** ([CF changelog](https://developers.cloudflare.com/changelog/post/2026-02-26-async-stale-while-revalidate/)) — the round-1 premise "in-process cache is the only enforcer" is now false *if* `/api/graph` is ever made cacheable. Keeping `private` (keystone above) makes it moot for per-user graphs; 300s remains the right *origin* buffer so a failed/slow background refresh (CPU-bound igraph) degrades gracefully instead of forcing a synchronous cold fetch.
- **Don't "fix" cross-worker staleness with Caddy sticky sessions:** `lb_policy cookie` **breaks our blue/green cutover** (sticky cookie keeps routing to the old color → 502 mid-deploy). The right fix *when scale demands it* is lightweight shared invalidation (small Redis ~15 MB, or a Unix-socket fan-out signal). At 10–15 users the 30s fresh TTL + soft HTTP/2 affinity make cross-worker landing rare.
- **Citations:** RFC 9111/5861; web.dev SWR; Fastly serving-stale (short SWR + long stale-if-error); CF async-SWR changelog (2026); Caddy `lb_policy cookie` open issues (#6393/#6110, blue/green caveat).

## Q5 — Scale-gate (defer all three; instrument now)
- **Already built (corrects the research's assumptions):** per-user cache keying + `view=my` scoping + auth (`get_optional_user`) already exist ([view_graph.py](../../website/api/module_runners/view_graph.py), [graph_cache.py](../../website/api/graph_cache.py)) → the personal-subgraph **seam and its auth-gate are done**; analytics are already content-hash-memoized with `computed_at` in `meta` ([routes.py:183](../../website/api/routes.py)) → the cheap freshness guard largely exists.
- **Build now = instrumentation only** (3 cheap log lines), then defer implementations until a metric fires:

| Feature | Decision | Flip metric (watch) |
|---|---|---|
| (a) LOD / focal subset | Defer | **client-side** transferred `/api/graph` bytes > ~500 KB (measure *after* Cloudflare, not origin) OR client settle > 5s |
| (b) Personal-subgraph reveal | Defer impl (seam exists) | max per-user node count > ~500 OR p95 graph load > 2s |
| (c) Materialized analytics columns | Defer (guard exists) | in-process analytics wall-time > 1s p95 — **lower the shared-graph trigger to ~500–1,000 nodes** (2 per-worker caches double cold-compute on 1 vCPU) |

- **Citations:** Fowler YAGNI (seam-vs-capability); PMC 2025 web graph-viz benchmark (≥30fps to ~5–7k WebGL nodes; ~3k turning point) — but note the verifier's correction: that benchmark is *render* fps, while d3-force-3d *simulation* convergence degrades earlier (~500–1k nodes at 3–5 edges/node), and it's client CPU, not our server.

## Net: one keystone + one retune + instrumentation; everything else deferred
1. **Wire `private` + weak-ETag + SWR header on `/api/graph`** (unblocks Q4 safety, enables Q5 metrics, prerequisite for any Q2 precompute). *Keystone.*
2. **Drop in-process compression** (Q1/Q3) — after verifying the SSE path.
3. **Retune the client settle** (Q2) — operator eyeball required.
4. **Add the 3 flip-metric log lines** (Q5) — pure observability, no behavior change.
5. **Keep SWR at 300s** (Q4) — no change.

All zero-new-infra. Bigger options (server precompute, LOD, materialized columns, Redis, sticky sessions) remain deferred behind the named metrics.
