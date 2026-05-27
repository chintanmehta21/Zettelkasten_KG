# Statistics-Tab Architecture — Industry-Standard Research (2024-2026)

**Date**: 2026-05-26
**Author**: Synthesis from 4 parallel websearch-heavy subagents (~80 sources surveyed, all 2021+)
**Companion doc**: `docs/claude_audits/user_stats_research_2026-05-26.md` (the 100-stat catalog)

**Status**: Research-only. Establishes the load architecture. No code, no schema changes applied.

---

## TL;DR — the verdict shifts the original framing

The original framing was "single API call, all calculations on-the-fly, 30-60s loading buffer acceptable". After surveying ~80 sources across 4 dedicated research streams, the dominant 2024-2026 industry pattern is **NOT on-the-fly computation**. It is:

> **Precompute heavy stats into materialized views / denormalized rollup rows (refreshed off-peak by `pg_cron` / batch jobs), then serve via a single BFF endpoint that does cheap key-lookups + progressive streaming (NDJSON / SSE) with SWR caching on the client.**

**The 30-60s budget should be your REFRESH-JOB compute budget, NOT the user's wait time.** Every credible 2024-2026 UX source (Nielsen Norman, Vercel, LogRocket, Smashing-adjacent) places the user wait tolerance at:
- **<400 ms** for shell + skeleton paint
- **<2 s** for headline stats (5-10 most important)
- **<10 s** for the long tail (with progress feedback past that)
- **Mobile users abandon 2× faster than desktop** (53% mobile vs ~22% desktop at 10s)

A monolithic 30-60s blocking load is outside the acceptable band even with progress feedback. The streaming + SWR pattern converts that compute time into a "filling in" experience that feels live — without lying to users about wait length.

---

## Section 1 — How major SaaS apps actually do this (first-party evidence)

**Convergent pattern: batch-precompute + serve-from-key-lookup. The live endpoint NEVER aggregates at request time.**

| Company | Architecture | Refresh cadence | Source |
|---------|-------------|-----------------|--------|
| **Spotify Wrapped** | Apache Beam (Scio) batch jobs on Dataflow → one Bigtable row per user, column family per data story → key-lookup at serve | Annually, precomputed weeks/months ahead | [Spotify Unwrapped engineering blog, 2020](https://engineering.atspotify.com/2020/02/spotify-unwrapped-how-we-brought-you-a-decade-of-data) + [Load Testing 2022, 2023](https://engineering.atspotify.com/2023/03/load-testing-for-2022-wrapped) |
| **LinkedIn analytics** | Kafka stream + Hadoop batch → Apache Pinot columnar OLAP → user queries in tens of ms | Near-real-time (Pinot ingests >1B records/day) | [LinkedIn Engineering / Pinot](https://engineering.linkedin.com/analytics/real-time-analytics-massive-scale-pinot) |
| **Discord Insights** | 30+ PB BigQuery warehouse → Spark-precomputed tables → exported to ScyllaDB for user-facing query path | Daily/hourly batch | [Discord blog: Insights from Trillions of Data Points](https://discord.com/blog/how-discord-creates-insights-from-trillions-of-data-points) |
| **Strava Year in Sport / leaderboards** | Cassandra denormalized rows + Redis ephemeral cache; transforms ride writes via background pipeline | "Up to 24-hour delay" — disclosed publicly to users | [Strava Engineering Medium](https://medium.com/strava-engineering/rebuilding-the-segment-leaderboards-infrastructure-part-3-design-of-the-new-system-39fdcf0d5eb4) |
| **Notion analytics** | Postgres → Debezium CDC → Kafka → Hudi → S3 data lake → Spark transforms. Analytics NEVER reads from live Postgres. | Continuous CDC, batch transforms | [Notion blog: Data Lake](https://www.notion.com/blog/building-and-scaling-notions-data-lake) |
| **Stripe Dashboard vs Sigma** | Tiered: fast pre-aggregated dashboard (live) + Sigma SQL-over-warehouse (slow/flexible). Explicit two-speed UX. | Dashboard: pre-rolled; Sigma: ad-hoc | [Stripe Sigma](https://stripe.com/sigma) |
| **GitHub contribution graph** | Inferred (no engineering post): pre-aggregated (user, day) table, hourly refresh per docs | Hourly (per enterprise docs) | [GitHub Profile contributions reference](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference) |

**Convergent practices across all of them**:
1. Heavy aggregation NEVER happens on the request path
2. One denormalized row per user, many columns/cells (Bigtable shape)
3. Refresh cadence is whatever business needs — daily, hourly, never realtime unless required (LinkedIn-style)
4. **Single aggregating endpoint (BFF/GraphQL)** — not N small REST endpoints. Decathlon adopted BFF company-wide 2024 [InfoQ](https://www.infoq.com/news/2024/03/decathlon-backend-for-frontend/)
5. Load-test the **read path** before launch (Spotify Wrapped thundering-herd is read-path concern, not pipeline concern)

**Outlier worth noting**: LinkedIn's Pinot path is the only one doing genuine near-real-time aggregation — and even there it's a columnar OLAP engine doing pre-indexed lookups, not OLTP joins.

---

## Section 2 — Postgres-specific patterns (our actual stack)

**Decision matrix**:

| Pattern | When it wins | Failure threshold | Cost |
|---------|-------------|-------------------|------|
| **Live on-the-fly aggregation** | Stat query <100ms with proper indexes; tables <1-5M rows; user-scoped filter prunes to thousands of rows | Query >budget OR starves OLTP CPU/IO at peak. "One complex analytics query scanning millions of rows can bring your entire application to a halt." ([Tinybird](https://www.tinybird.co/blog/outgrowing-postgres-how-to-run-olap-workloads-on-postgres)) | Lowest |
| **Materialized View + pg_cron (CONCURRENTLY)** | Multi-table joins, expensive aggregates, 5-60min staleness OK; reads >> writes | Refresh time > refresh interval; lock contention under heavy MV-graph dependencies | Medium |
| **Incremental rollup table (AFTER-INSERT trigger / pg_ivm)** | Counters that must be live (`total_zettels` to-the-second); writes < hundreds/sec/key | MVCC bloat on hot keys; VACUUM falling behind | Medium-high |
| **Separate OLAP engine (ClickHouse, Tinybird, Pinot)** | Sustained 10k+ qps writes, multi-billion rows | Operational complexity, ETL lag | High |
| **Read replica for analytics** | Analytics unavoidable on OLTP, dashboards <1 qps; budget allows | Replication lag during MV refresh | Medium |

**Postgres-specific best practices (with citations)**:
1. **`REFRESH MATERIALIZED VIEW CONCURRENTLY`** — non-concurrent takes AccessExclusiveLock, blocks all readers. CONCURRENTLY requires UNIQUE index but allows reads against stale snapshot until atomic swap. [Postgres docs](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html)
2. **Stagger MV refreshes** — same base tables touched simultaneously = lock contention + pool exhaustion. [dev.to/divyansh_gupta](https://dev.to/divyansh_gupta/optimizing-materialized-view-refresh-to-minimize-locks-in-postgresql-4f76)
3. **Literal denormalization in MVs** — store labels in MV itself, not FK ids needing runtime join. [Sachin Satpute/Medium](https://sachinsatpute.medium.com/faster-dashboards-with-postgresql-materialized-views-and-literal-denormalization-ea1f47a86841)
4. **`statement_timeout = 30-60s` global default**; per-session override for known long jobs. [Crunchy Data](https://www.crunchydata.com/blog/control-runaway-postgres-queries-with-statement-timeout)
5. **Always enable `pg_stat_statements`** — only practical way to find slow queries in prod. Supabase enables by default.
6. **CTEs in PG 12+ inline by default** when referenced once. Use `WITH foo AS NOT MATERIALIZED (...)` to force inline, `MATERIALIZED` only when wanting optimization fence. Pre-12 behavior was opposite. [Haki Benita](https://hakibenita.com/be-careful-with-cte-in-postgre-sql)
7. **Covering / INCLUDE indexes** enable index-only scans for COUNT(*) etc.
8. **`pg_cron` limits** — Supabase caps 32 concurrent jobs, ≤8 recommended, <10 min each. [Supabase Cron docs](https://supabase.com/docs/guides/cron)
9. **Separate analytics pool in PgBouncer** — analytics needs session mode (prepared statements, temp tables), OLTP runs transaction mode.
10. **`pg_ivm` for incremental MVs** — installs base-table triggers, applies deltas within same transaction. Compatible PG 13-18. [sraoss/pg_ivm](https://github.com/sraoss/pg_ivm)

**Real case studies**:
- **Sid Ngeth, Oct 2025**: dashboard query rewritten as pg_cron-refreshed MV → multi-second → sub-millisecond, **9000× speedup**. Lesson: MV-ize the slow ones, not all. [sngeth.com](https://sngeth.com/rails/performance/postgresql/2025/10/03/materialized-views-performance-case-study/)
- **American Red Cross osm-stats #56**: started with MVs, refresh got too expensive → migrated to incremental rollup tables with cursor-based upserts. Textbook MV→rollup migration trigger.
- **Notion**: Postgres sharded 480 ways → analytics impossible on OLTP → Fivetran to Snowflake. Lesson: when OLTP shards for writes, analytics needs separate store.
- **Figma DBProxy**: sampled `pg_stat_activity` at 10ms intervals to attribute load by table. `pg_stat_statements` + `pg_stat_activity` is universal at every scale.
- **Airbnb Minerva / StarRocks**: 12k metrics + 4k dimensions; OLTP entirely outgrown for analytics. (Not relevant to us until we're 1000× larger.)

---

## Section 3 — Loading UX (the 30-60s budget verdict)

**Tolerance numbers**:
- **3s**: 53% mobile / ~40% desktop abandon (Google data, 2024 reaffirmed)
- **10s**: Nielsen's hard ceiling for attention. ~22% abandon at 10s, 43% frustrated. [NN/G Response Time Limits](https://www.nngroup.com/articles/response-times-3-important-limits/)
- **TTFB 40-90 ms, full paint <400 ms**: best-practice 2024 RSC/streaming dashboards
- **Mobile 2× faster abandonment than desktop**: ~4s mobile = ~7s desktop tolerance
- **Animated progress = 3× longer wait tolerance** before bail. Feedback makes wait feel 11-15% faster ([NN/G Progress Indicators](https://www.nngroup.com/articles/progress-indicators/))

**Pattern catalog** (winners in 2024-2026):
- **Static shell + Suspense streaming** — render shell+skeletons immediately, stream each widget when data resolves. Vercel/Next.js App Router, GitHub Insights.
- **Partial Pre-Rendering (PPR)** — static parts pre-rendered at build, dynamic holes streamed in single HTTP request. Next.js 15. [Vercel](https://vercel.com/blog/partial-prerendering-with-next-js-creating-a-new-default-rendering-model)
- **NDJSON / chunked HTTP streaming** — server emits one JSON per stat as computed. Reported first-paint 900ms → 120ms in published case studies. [apidog](https://apidog.com/blog/ndjson/), [Ardan Labs](https://www.ardanlabs.com/blog/2024/11/scalable-json-streaming-with--http-and-go.html)
- **SSE (Server-Sent Events)** — one-way push, auto-reconnect. Stripe Billing real-time analytics uses this. [Stripe Dev Blog](https://stripe.dev/blog/how-we-built-it-real-time-analytics-for-stripe-billing)
- **Skeleton screens** — layout-shaped placeholders. LinkedIn / Instagram / Facebook / Google use these. Cut abandonment up to **30%** in studies.
- **Stale-while-revalidate (SWR)** — return cached instantly, revalidate in background. [Vercel SWR](https://swr.vercel.app/docs/revalidation), [DebugBear](https://www.debugbear.com/docs/stale-while-revalidate)
- **Async + email/notification** — "Your Wrapped is ready" pattern. For genuine minute-long compute, not routine dashboards.

**Skeleton vs spinner verdict (2024-2026)**:
- Skeletons = default for any content load >1s in a known layout
- Spinners scoped to "short, ambiguous-layout" interactions (button press, save)
- A spinner past ~2s reads as "broken" — Productboard, Boldist, NN/G converge on this
- SWR + skeleton-on-cache-miss = winning combo

**Streaming feasibility for our stack**: FastAPI has first-class `StreamingResponse`. NDJSON over `Transfer-Encoding: chunked` is the lightest option. Concrete shape:
```
GET /api/profile/stats/stream
→ {"id":"total_zettels","value":1247}\n
  {"id":"top_tags","value":[...]}\n
  ...
```
Emit highest-value stats first. Client renders each into target skeleton slot. Heartbeat every 15s to defeat Cloudflare/Caddy idle timeout (you already have this pattern from iter-12 per CLAUDE.md).

---

## Section 4 — Safety on the 2 GB / 1 vCPU droplet

**Top 3 risks for our exact setup**:

1. **Connection pool starvation** — 25-100 aggregations held in Supavisor slots for 30-60s; concurrent stats requests multiply this. At free-tier ~15-20 effective DB connections, 3 simultaneous profile loads wipe the pool. Medium-high likelihood.
2. **Droplet OOM-kill** — gunicorn preload + BGE int8 + Caddy already ~1.0-1.3 GB. Residual ~500-700 MB headroom is below Percona's safe-threshold for high-concurrency Postgres clients. Medium-high likelihood.
3. **Shared-buffer / OS-cache pollution** — heavy seq-scans evict hot OLTP pages; every subsequent OLTP query goes to disk for minutes. Postgres planner does NOT protect OLTP working set. High likelihood.

**Real postmortems with this exact pattern**:
- **RevenueCat Aurora 10→14**, Nov 2022 → 5-hour outage; missing `ANALYZE` post-upgrade → planner seq-scans on hot tables.
- **Medium postmortem, June 2023** → 3.5h outage; ORM pool set to 150 instead of 300; 2× spike exhausted pool; 80% users got HTTP 500 for ~3h.
- **Shopify Reports & Analytics** → 9.7h incident; replica lag → wrong revenue numbers shown to customers for hours.
- **"I debugged 147 slow queries"** → in ~40% of cases the root cause was app-side N+1, not DB. 47 API calls per dashboard. Count round-trips FIRST.

**Concrete numbers for our 2GB / 1vCPU / 2-gunicorn-worker droplet**:

| Setting | Recommended | Rationale |
|---------|-------------|-----------|
| `statement_timeout` (stats_reader role) | **45 s** (60 s client-side hard cap) | Operator budget; Supabase max 60s for non-direct |
| `idle_in_transaction_session_timeout` (stats_reader) | **60 s** | Prevents vacuum-horizon freeze |
| `work_mem` per session (stats_reader) | **32 MB** (override max 64 MB via SET LOCAL) | Default 4 MB too low for aggregation; 64 MB × 5 nodes × 5 conns = 1.6 GB worst case |
| Max concurrent stats requests **per gunicorn worker** | **1** (semaphore) | With 2 workers = 2 total system-wide |
| Max concurrent stats requests **total** | **2** | Prevents R1+R2 stacking |
| Connection-pool slots reserved for stats | **2 of ~15-20** | Leaves 13-18 for OLTP/RAG |
| Result-set size cap per aggregation | **10k rows** server-side LIMIT | Beyond = downsample or materialize |
| Swapfile on droplet (BEFORE enabling tab) | **1 GB**, `vm.swappiness=10` | Single most cost-effective OOM prevention |
| Background-job threshold | Any aggregation projected >5s p95 → move off request thread | FastAPI thread should not be doing 30s work synchronously |

**Mandatory safeguards before enabling tab in prod** (NON-NEGOTIABLE per safety agent):

1. Dedicated `stats_reader` Postgres role with read-only grants, `statement_timeout=45s`, `idle_in_transaction_session_timeout=60s`.
2. Semaphore + bounded queue on stats endpoint (max 1 concurrent per worker, queue size 4, 503 above).
3. EXPLAIN-and-bound every aggregation in staging; reject any plan with seq-scan over >100k rows or estimate >10× actual.
4. `ANALYZE` all touched tables in pre-deploy step.
5. **1 GB swapfile added to droplet pre-launch**.
6. **NO pgvector / halfvec queries** in the stats tab. Each HNSW traversal is 2.7-5.7s and pulls into RAM.

**Without those safeguards: NOT SAFE.** The combination of (a) preloaded gunicorn at ~1.0-1.3 GB resident, (b) 2 GB hard ceiling, (c) shared OLTP/OLAP Postgres, (d) unbounded "25-100 queries per page load" is exactly the failure mode the EDB workshop, Springtail blog, and Medium postmortem all warn about.

---

## Recommended architecture (the synthesis)

### Layer 1 — Compute (off the request path)

- **Per-user materialized views** for expensive stats, one row per user, denormalized labels. Refresh `CONCURRENTLY` every 15-60 min via `pg_cron`. UNIQUE index on `(workspace_id)` mandatory.
- **`core.usage_events` backfill + AFTER-INSERT triggers** for live counters that must be to-the-second (total zettels, current streak).
- Refresh schedules staggered so different MVs don't pile on same base tables.

### Layer 2 — Read path (the BFF)

- Single endpoint `GET /api/profile/stats` (or `.../stream`).
- Routes for cheap key-lookups against MV + live counters from rollup table.
- Wraps in `stats_reader` role connection with hard timeout.
- Returns a single JSON if all stats <2s OR an NDJSON stream if any exceed 2s.

### Layer 3 — Client UX

- Render shell + skeletons in <400 ms (no data dependency).
- Stream "headline bundle" (5-10 most-important stats) in <2s.
- Continue streaming heavier 50-90 stats over 10-30s, each fills its skeleton in place. No global blocking spinner.
- Any aggregation truly >10s → localized progress indicator + cancel on its tile; rest stays interactive.
- **SWR per user**: cache full result keyed by `(user_id, last_refresh_ts)`. First load is the only slow one; revisits instant with background refresh.
- "Last updated 2m ago • refreshing…" affordance so users understand SWR.

### Layer 4 — Safety guardrails (non-negotiable)

- Dedicated `stats_reader` role, `statement_timeout=45s`.
- Semaphore (1 concurrent per worker, 2 total, queue 4, 503 backpressure).
- 1 GB droplet swapfile.
- `ANALYZE` pre-deploy.
- No pgvector/halfvec in stats path.
- `pg_stat_statements` watched weekly.

### Revised budget framing

| Layer | Budget |
|-------|--------|
| MV refresh job (pg_cron) | **30-60 s** ← THIS is where the operator's accepted budget belongs |
| User wait — shell + skeleton | **<400 ms** |
| User wait — headline stats streamed | **<2 s** |
| User wait — full tab loaded | **<10 s** with progressive fill |
| Subsequent visit (SWR cache hit) | **<200 ms** |

---

## Risks of NOT doing this

| Risk | What breaks |
|------|-------------|
| Skip MV layer, run live aggregations | Connection pool starvation at ~3 concurrent users; cache pollution slowing OLTP for minutes after each load |
| Skip safety guardrails | OOM-kill on droplet (preload + 2GB ceiling = no margin), silent statement_timeout failures, vacuum-horizon freeze |
| Skip progressive streaming | 53% mobile users abandon at 3s; 22% all users at 10s; "computing your stats…" past 10s reads as broken |
| Skip SWR client cache | Every page revisit pays the cold-start cost; thundering-herd on MV refresh |
| Include pgvector queries | Each one is 2.7-5.7s; multiplies HNSW RAM cost; one rogue query starves rest |
| 1 endpoint with no semaphore | A single user with bad luck (multi-tab + fast refresh) starves pool for all other users |

---

## Recommended ship sequence

### Phase 0 — Safety prep (1 PR, day 1)
- Create `stats_reader` Postgres role with timeouts.
- Add 1 GB droplet swapfile.
- Add semaphore + bounded queue on `/api/profile/stats` endpoint (even before the endpoint does anything).

### Phase 1 — MVP cheap stats (1 PR, day 2-3)
- ~25 cheapest stats (the MVP-25 list from companion audit), all live queries scoped by workspace_id.
- Single endpoint, single JSON response, in-process 60s cache keyed by user_id.
- Skeleton-first shell, fade to data.
- ANALYZE pre-deploy. `pg_stat_statements` baseline captured.

### Phase 2 — Materialized views (1-2 PRs, week 2)
- `content.workspace_zettel_stats_mv` for Zettel-section heavy stats
- `content.workspace_tag_stats_mv` for Domain section (15-min pg_cron refresh)
- `core.profile_overview_mv` for General section
- All `CONCURRENTLY` with UNIQUE index
- Stats endpoint switches MV-backed stats from live to MV-lookup
- Add SWR client cache with `(user_id, mv_refresh_ts)` ETag

### Phase 3 — Streaming + progressive disclosure (1 PR, week 3)
- Switch endpoint to NDJSON `StreamingResponse`
- Client renders progressively into skeleton slots
- Headline bundle emitted first, heavier later
- 15s heartbeat to defeat Caddy idle timeout

### Phase 4 — Heavy KG metrics (week 4+, only when needed)
- `kg.kg_workspace_metrics_mv` populated by nightly Python (NetworkX) worker
- Adds component count, bridges, diameter, modularity stats
- Surface `computed_at` to UI

### Phase 5 — Defer until 100+ active users
- Read replica for analytics
- PgBouncer split-pool
- Background job pattern for any aggregation projected >5s p95

---

## What WAS NOT validated and would need follow-up

- **Vercel, Linear, Reddit, Twitter/X, Supabase Dashboard internal architecture** — no first-party engineering posts found. Don't cite their patterns as evidence.
- **Stripe Dashboard live tier (vs Sigma)** — known to be pre-aggregated but exact architecture undocumented.
- **GitHub contribution graph implementation** — inferred from API behavior (hourly refresh), not first-party post.
- **Linear Insights backend** — public docs describe per-dashboard refresh tuning but no architecture posts.

If we need stronger evidence on any of these, the next research cut would be: targeted queries against engineering.github.com, linear.app/blog, vercel.com/blog filtered to 2023+, plus engineering Twitter accounts for product launches.

---

## Sources surveyed (~80 total)

Full per-agent citation list available in agent outputs; cross-cutting highlights:

**Industry pattern**:
- [Spotify Unwrapped engineering blog](https://engineering.atspotify.com/2020/02/spotify-unwrapped-how-we-brought-you-a-decade-of-data)
- [Spotify Load Testing for 2022 Wrapped](https://engineering.atspotify.com/2023/03/load-testing-for-2022-wrapped)
- [LinkedIn Engineering: Pinot](https://engineering.linkedin.com/analytics/real-time-analytics-massive-scale-pinot)
- [Discord: Insights from Trillions](https://discord.com/blog/how-discord-creates-insights-from-trillions-of-data-points)
- [Strava Segment Leaderboards rebuild](https://medium.com/strava-engineering/rebuilding-the-segment-leaderboards-infrastructure-part-3-design-of-the-new-system-39fdcf0d5eb4)
- [Notion Data Lake](https://www.notion.com/blog/building-and-scaling-notions-data-lake)
- [InfoQ: Decathlon BFF Pattern](https://www.infoq.com/news/2024/03/decathlon-backend-for-frontend/)

**Postgres patterns**:
- [TigerData: Real-Time Analytics in Postgres](https://www.tigerdata.com/learn/real-time-analytics-in-postgres)
- [Tinybird: Outgrowing Postgres](https://www.tinybird.co/blog/outgrowing-postgres-how-to-run-olap-workloads-on-postgres)
- [Crunchy Data: Control Runaway Postgres Queries](https://www.crunchydata.com/blog/control-runaway-postgres-queries-with-statement-timeout)
- [Sid Ngeth: 9000× MV speedup, Oct 2025](https://sngeth.com/rails/performance/postgresql/2025/10/03/materialized-views-performance-case-study/)
- [American Red Cross osm-stats MV→rollup migration](https://github.com/AmericanRedCross/osm-stats/issues/56)
- [Supabase Cron docs](https://supabase.com/docs/guides/cron)
- [pg_ivm: Incremental MVs](https://github.com/sraoss/pg_ivm)

**UX research**:
- [NN/G Response Time Limits](https://www.nngroup.com/articles/response-times-3-important-limits/)
- [NN/G Progress Indicators](https://www.nngroup.com/articles/progress-indicators/)
- [Vercel Partial Prerendering](https://vercel.com/blog/partial-prerendering-with-next-js-creating-a-new-default-rendering-model)
- [SitePoint RSC Streaming](https://www.sitepoint.com/react-server-components-streaming-performance-2026/)
- [Stripe Billing real-time analytics](https://stripe.dev/blog/how-we-built-it-real-time-analytics-for-stripe-billing)
- [Vercel SWR](https://swr.vercel.app/docs/revalidation)

**Safety / postmortems**:
- [Springtail: OLAP meets OLTP](https://www.springtail.io/blog/long-running-queries-postgresql)
- [RevenueCat Aurora 10→14 outage / EDB](https://www.enterprisedb.com/blog/lets-workshop-an-unplanned-postgres-outage)
- [Medium pool exhaustion postmortem](https://medium.com/@ngungabn03/postmortem-database-connection-pool-exhaustion-causing-service-outage-9afd33a45311)
- [Supabase Timeouts](https://supabase.com/docs/guides/database/postgres/timeouts)
- [Supabase Read Replicas](https://supabase.com/docs/guides/platform/manage-your-usage/read-replicas)
- [Percona OOM Killer](https://www.percona.com/blog/out-of-memory-killer-or-savior/)
- [CYBERTEC: idle_in_transaction_session_timeout](https://www.cybertec-postgresql.com/en/idle_in_transaction_session_timeout-terminating-idle-transactions-in-postgresql/)
