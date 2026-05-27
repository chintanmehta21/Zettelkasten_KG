# User Statistics Module — Research & Proposal (Statistics tab on /profile)

**Date**: 2026-05-26
**Author**: Research synthesis from 7 parallel subagents (one per Statistics tab section)
**Scope**: Research-only. Proposes stats + DB feasibility for the future "Statistics" tab on the My Profile page. No code, no schema changes applied.

---

## Executive summary

7 dedicated subagents — one per section — each researched 5-12 reference apps (Spotify Wrapped, GitHub, Strava, Goodreads, Letterboxd, Duolingo, Notion, Roam Research, Obsidian, Readwise, Pocket, Pinterest, Trello, WakaTime, LinkedIn, Last.fm, Apple Screen Time, ChatGPT, Perplexity, Connected Papers, Gephi-style SNA tooling) and verified DB feasibility against the actual `supabase/website/_v2/*.sql` migrations. Total proposed: **100 stats across 7 sections**.

**Headline findings**:
- **~70 stats are EASY/MEDIUM today** (existing schema + indexes cover them).
- **~30 stats need 1-2 schema additions** (most impactful: a `core.profiles.timezone` column, a single new partial index on `rag.chat_messages`, and 2-3 materialized views).
- **API design**: A single `GET /api/profile/stats` endpoint returning `{ general, zettel, kasten, domain, activity, network, retrieval }` is feasible at p95 < 800ms with the tiered caching strategy below.
- **Ship sequence**: A "v1" with ~40 cheap stats can ship without ANY schema change; "v1.5" adds a `timezone` column + one index for ~20 more; "v2" adds the recommended MVs for the remaining heavy stats.

---

## Cross-cutting infrastructure recommendations

### Single endpoint shape

```
GET /api/profile/stats
Response: {
  meta: { workspace_id, profile_id, computed_at, cache_tier },
  general:   { ... 6-9 headline numbers ... },
  zettel:    { ... source mix, top items, density ... },
  kasten:    { ... totals, top-5, empty, cross-filed ... },
  domain:    { ... top topics, cloud, emerging, concentration ... },
  activity:  { ... streaks, peak hour, week-over-week, biggest day ... },
  network:   { ... graph size, hubs, orphans, edge mix, communities ... },
  retrieval: { ... questions asked, top retrieved, verdict mix, gaps ... }
}
```

### Tiered caching strategy (combined across sections)

| Tier | Stats | TTL | Invalidation |
|------|-------|-----|--------------|
| **Live (no cache)** | General #1/4/9, Activity #1/8, Retrieval #13 | none | every request |
| **5-min app-level LRU** | General #6/7/8/13, Zettel #1/2/3/6/14/15, Kasten #1/4/5/7, Activity #3/4/9/14, Retrieval #1/7/11 | 300s | none |
| **15-min Redis cache** | Domain #1/2/3/6/7/11/14, Activity #5/13, Retrieval #4/5/10 | 900s | on Add Zettel or chat send |
| **1-hour cache** | General #3/12, Zettel #4/5/12/13, Kasten #11/14/15 | 3600s | on workspace mutation |
| **24-hour MV refresh (pg_cron)** | General #10, Domain #15, Activity (MV-backed), Retrieval rollups | nightly | scheduled |
| **Nightly precompute (Python+NetworkX)** | Network #5/8/11/12/13 | nightly | scheduled |

ETag derived from `max(workspace_zettels.updated_at, chat_messages.created_at, kg_edges.created_at)` for client cache hits when nothing changed.

### Schema additions ranked by ROI

| # | Addition | Cost | Unlocks |
|---|----------|------|---------|
| 1 | Partial idx `rag.chat_messages (workspace_id, created_at) WHERE role='user'` | 30s migration | All Retrieval stats <50ms |
| 2 | `core.profiles.timezone text DEFAULT 'UTC'` | 1-line migration + frontend tz capture | All Activity stats become correct for non-UTC users |
| 3 | `content.workspace_tag_stats` materialized view, pg_cron refresh 15min | ~80 lines SQL | Domain section stays <200ms at 10k scale |
| 4 | `kg.kg_workspace_metrics_mv` materialized view + Python worker (NetworkX) | Bigger lift (background job) | Network components/bridges/diameter/communities |
| 5 | Backfill `core.usage_events` from zettels/chats/kastens + AFTER INSERT triggers | Medium (data migration) | Unified action stream collapses 4-table UNIONs to one index scan |
| 6 | `idx_kg_edges_workspace_created` on `kg.kg_edges (workspace_id, created_at DESC)` | 30s migration | Network #14 (newest edge) <50ms |
| 7 | `content.retrieval_citation_rollup` table + AFTER INSERT trigger on chat_messages | Medium | Retrieval #4/5/10 stay <50ms at 10k chats |
| 8 | `pipelines.search_events` log table | Medium (instrumentation in search/KG-click paths) | True cross-surface retrieval stats |
| 9 | `query_class` column on `rag.chat_messages` | 1-line column + rewriter wiring | "Question types I ask most" stat |
| 10 | `content.workspace_topic_clusters` (semantic clusters via HDBSCAN) | Big (offline embedding job) | Domain #15 "audio aura"-style stat |

### Ship sequence

- **v1 (zero schema change)** — ships ~40 stats. Covers General (all 13), Zettel (12 of 15), Kasten (all 15), Activity (10 of 14 in UTC), Network (cheap 9 of 15), Retrieval (10 of 13 with current indexes — may be slow at scale).
- **v1.5 (+items 1-2)** — adds Retrieval performance + Activity timezone correctness. ~50 stats total.
- **v2 (+items 3-4)** — adds Domain MV + Network heavy metrics. ~80 stats total.
- **v2.5 (+items 5-10)** — adds the long-tail (semantic clusters, query-type, cross-surface retrieval). All 100.

### Privacy rule (Retrieval section only)

Some retrieval stats (verbatim user-query text in #8) must remain **profile-private-only** and be opt-in if a public-profile feature ever ships. Aggregate stats are safe; query content is not. Flagged in the Retrieval section below.

---

## Section 1 — General Overview (13 stats)

> *Headline ribbon at the top. Spotify-Wrapped/Strava-year-in-review style.*

1. **Total Zettels Captured** — lifetime count of non-deleted `workspace_zettels`. EASY · <50ms · big number.
2. **Member Since (days in vault)** — days since `core.profiles.created_at`. EASY · <50ms · big number + sub-label.
3. **Total Words Captured** — `SUM(canonical_chunks.token_count) * 0.75` for chunks the user references. MEDIUM · 50-200ms · big number + book-equivalent caption ("≈ 250-page book").
4. **Zettels Last 30 Days + delta** — count vs prior 30-day window; sparkline by week. EASY · <50ms · number + arrow + sparkline.
5. **Total Kastens** — `count(rag.kastens)` for user's workspaces. EASY · <50ms · big number.
6. **Knowledge Graph Size** — `(count(kg_nodes), count(kg_edges))` paired. EASY · <50ms · `412 ideas · 1,847 links`.
7. **Source Diversity** — `count(DISTINCT canonical_zettels.source_type)`, max 13. EASY · <50ms · `9 / 13 sources` with mini dots.
8. **Tagged Coverage %** — `% workspace_zettels WHERE cardinality(user_tags) > 0`. EASY · <50ms · donut.
9. **Last Zettel Added** — `max(created_at)` rendered relative. EASY · <50ms · "3h ago".
10. **Personal Best Day** — single date with max zettels. MEDIUM · 50-200ms · "23 zettels on Apr 8" (MV candidate).
11. **Plan Tier + Quota Bar** — from `billing.pricing_subscriptions`. EASY · <50ms · badge + thin progress bar.
12. **Words per Zettel** — derived from #3 / #1, zero DB hit. EASY · 0ms · "avg ~520 words/zettel".
13. **Pinned + Note-Augmented** — `count FILTER (WHERE pinned)`, `count FILTER (WHERE user_note IS NOT NULL)`. EASY · <50ms · "12 pinned · 47 with notes".

**Top 5**: #1 Total Zettels · #6 KG Size · #4 30-Day Recency · #3 Words+book-equivalent · #11 Plan/Quota.

---

## Section 2 — Zettel-level (15 stats)

> *Unit of analysis: the individual zettel. Source mix, density, freshness, top items.*

1. **Source-type distribution** — top 5 of 13 source types + "other". EASY · <50ms · stacked horizontal bar.
2. **Top source (single)** — #1 source_type with count + %. EASY · <50ms · big number + icon.
3. **Average summary length** — `AVG(length(ai_summary))` + min/max. EASY · <50ms · big number + range chip.
4. **RAG chunk density** — avg/median `count(canonical_chunks)` per zettel. MEDIUM · 50-200ms · big number + median.
5. **Top 5 chunk-densest zettels** — ranked list of "substantial" captures. MEDIUM · 50-200ms · list with badges.
6. **Average user tags per zettel** — `AVG(cardinality(user_tags))` (user_tags only, not derived). EASY · <50ms · big number.
7. **Oldest zettel ("First capture")** — earliest created_at + title + age. EASY · <50ms · card.
8. **Newest zettel ("Latest capture")** — most recent + relative time. EASY · <50ms · card.
9. **Freshness profile** — 5 buckets `<7d / 7-30d / 30-90d / 90-365d / >365d`. EASY · <50ms · 5-stop bar.
10. **Pinned count + share** — `count(*) FILTER (WHERE pinned)`. EASY · <50ms · big number + %.
11. **Capture surface mix (added_via)** — telegram/website/share/migration. EASY · <50ms · 4-segment bar.
12. **% with publication date + median publish-to-capture gap** — `publication_date` provenance. EASY-MEDIUM · 50-200ms · % + "typically X days after publication".
13. **Multi-Kasten zettels %** — `% of zettels in ≥1 kasten` via `rag.kasten_zettels`. MEDIUM · 50-200ms · donut.
14. **Source diversity score** — `count(DISTINCT source_type)` framed as `9 / 13 sources used`. EASY · <50ms · progress.
15. **Avg canonical body length + compression ratio** — `AVG(length(body_md))` paired with #3 → "compresses 14× on average". EASY · <50ms · chip.

**Top 5**: #1 Source distribution · #7+#8 Oldest/Newest pair · #4 Chunk density · #9 Freshness profile · #5 Top chunk-densest.

---

## Section 3 — Kasten-level (15 stats)

> *Unit of analysis: a Kasten (user-created collection grouping zettels).*

1. **Total Kastens** — `count(*) FROM rag.kastens WHERE workspace_id=$1`. EASY · <50ms · big number + 30d delta.
2. **Total Kasten Memberships** — sum of `kasten_zettels` rows (zettel-in-multi counts thrice). EASY · <50ms · big + "avg X Kastens/zettel".
3. **Avg/Median zettels per Kasten** — paired tiles. MEDIUM · 50-200ms · two numbers side-by-side.
4. **Largest Kasten** — top-1 by non-deleted zettel count, with name+icon+color. EASY · 50-200ms · hero card.
5. **Top 5 Kastens** — ranked list with bars + percentages. EASY · 50-200ms · 5-row horizontal bars.
6. **Size distribution buckets** — histogram `0 / 1-5 / 6-20 / 21-50 / 51-200 / 200+`. MEDIUM · 50-200ms · 6-bar histogram.
7. **Empty Kastens** — Kastens with zero non-deleted zettels. EASY · 50-200ms · number + "Review them →" CTA.
8. **Singleton Kastens** — Kastens with exactly 1 zettel. EASY · 50-200ms · stat tile.
9. **Oldest Kasten** — earliest `created_at` + age. EASY · <50ms · card.
10. **Most recently active Kasten** — uses `max(kz.added_at)`, NOT `k.updated_at` (which moves on metadata edits). EASY · 50-200ms · card.
11. **Shared Kastens (in/out)** — outgoing shares + incoming via `rag.kasten_members`. MEDIUM · 50-200ms · two paired tiles.
12. **Customization rate** — % with non-null icon or color. EASY · <50ms · ring progress.
13. **Description coverage %** — % with non-empty description (GitHub-style). EASY · <50ms · % tile.
14. **Cross-filed zettels** — count in ≥2 Kastens (this app's many-to-many model uniquely allows this — Obsidian/Notion can't). MEDIUM · 200-500ms · big number + share.
15. **Auto-organized vs Manual share** — `added_via` breakdown across `manual / bulk_* / graph_pick / migration`. EASY · 50-200ms · stacked bar.

**Top 5**: #4 Largest Kasten · #5 Top 5 list · #1 Total · #7 Empty (most actionable) · #14 Cross-filed (this app's differentiator).

---

## Section 4 — Domain / Topic-level (15 stats)

> *Unit of analysis: a tag/topic. All tag stats are `unnest(user_tags)` over `workspace_zettels`. `derived_tags` is system-only — never surfaced.*

1. **Top 10 topics** — `unnest(user_tags) GROUP BY tag ORDER BY count DESC LIMIT 10`. EASY · 50-200ms · horizontal bars.
2. **Topic diversity (unique tag count)** — `count(DISTINCT tag)`. EASY · 50-200ms · big number.
3. **Topic concentration (HHI)** — Herfindahl index over tag-share. EASY · 50-200ms · gauge + label band (Polymath / Specialist).
4. **Emerging topics (last 30d)** — tags whose recent share materially exceeds lifetime. MEDIUM · 200-500ms · trending list + sparkline.
5. **Declining topics (last 90d)** — mirror of #4 with inequality flipped. MEDIUM · 200-500ms · paired list.
6. **Longest-running topic** — tag with greatest `(max-min) created_at` span, ≥3 zettels. EASY · 50-200ms · hero callout.
7. **Topic cloud (top 40)** — weighted by `log(1+count)`. EASY · 50-200ms · word cloud (teal-only, no purple).
8. **Mono-tag vs Multi-tag ratio** — `% with 1 / 2-3 / 4-6 / 7+ tags`. EASY · <50ms · stacked bar.
9. **Top 5 topic co-occurrence pairs** — self-join on shared zettel id, `a.tag < b.tag`. MEDIUM · 200-500ms · pair-chip list.
10. **Topic × source-type affinity** — for top 5 tags, source breakdown ("rust via GitHub, philosophy via YouTube"). MEDIUM · 200-500ms · mini stacked bars or 5×5 heatmap.
11. **Single-use tags ("Long Tail")** — tags appearing on exactly 1 zettel — consolidation prompt. EASY · 50-200ms · big number.
12. **Top-3 topic recency** — days since each of top-3 tags was last touched. EASY · <50ms · 3-row mini-list with age badges.
13. **First-topic anniversary** — earliest tag with ≥2 zettels — "you started thinking about X on Y date". EASY · 50-200ms · hero card.
14. **Tag saturation curve** — "your top 10 cover X% of all tagged zettels". EASY · 50-200ms · big sentence + sparkline.
15. **Semantic cluster count** *(optional)* — HDBSCAN over zettel-level embedding centroids. HARD · requires offline precompute table.

**Top 5**: #1 Top topics · #7 Topic cloud · #4 Emerging · #3 Concentration (shareable) · #9 Co-occurrence pairs (PKM-native).

**Critical caching note**: At 10k zettels with median ~6 user_tags = 60k post-unnest rows. **A `content.workspace_tag_stats` MV refreshed every 15 min via pg_cron is strongly recommended** — without it the 12+ stats × independent unnest scans blow the 800ms p95 budget. Anti-pattern: do NOT add a `kg_tags` dictionary table — the GIN index on `user_tags text[]` already serves lookups and migration 73's normalization is sufficient.

---

## Section 5 — Activity / Engagement (14 stats)

> *Unit of analysis: a TIMESTAMP. Source = UNION of zettel-created, chat-sent, kasten-created. Already-shipped 26-week heatmap is #0; this list adds 14 more.*

1. **Current streak** — consecutive user-local days with ≥1 action. MEDIUM · 50-200ms · big number + flame.
2. **Longest streak** — max consecutive run (free with #1's CTE). MEDIUM · bundled · big + date range.
3. **Peak hour of day** — most-active hour (rolling 90d). EASY · <50ms · 24-bar histogram + caption.
4. **Peak day of week** — Mon-Sun bar, modal day highlighted. EASY · <50ms · 7-bar histogram (bundled with #3).
5. **Active days** — 30d + lifetime distinct dates + rate. EASY · 50-200ms · "13/30 + 187 lifetime".
6. **Biggest day** — single date with most actions + count. EASY · 50-200ms · "47 actions on Apr 18".
7. **Longest gap** — max consecutive zero-activity stretch (honest mirror to #2). MEDIUM · bundled · big + range.
8. **This week vs last week** — capture count + delta + arrow. EASY · <50ms · big + arrow + sparkline.
9. **30-day sparkline** — daily counts zero-filled via generate_series. EASY · <50ms · inline SVG.
10. **First capture** — `min(created_at)` + "joined N days ago". EASY · <50ms · big number.
11. **Avg daily captures on active days** — depth-when-engaged metric. EASY · <50ms · "4.2/active day".
12. **Time-of-day bucket split** — Morning/Afternoon/Evening/Night %. EASY · <50ms · 4-segment bar with persona label ("Night Owl 62%").
13. **Chat-vs-Capture mix (30d)** — ratio of input mode vs query mode. EASY · 50-200ms · two paired numbers.
14. **7-day rolling average + 7d/30d/90d deltas** — smoothed velocity. MEDIUM · 50-200ms · big number + 3 delta chips.

**Top 5**: #1 Current Streak · #8 Week-over-week · #3 Peak hour · #2 Longest streak (free with #1) · #6 Biggest day.

**Critical infrastructure note (timezone)**: `core.profiles` has NO timezone column. Server-side date-bucketing without it produces wrong streaks for non-UTC users (e.g. IST late-night captures split across UTC days). **Strong recommendation**: add `core.profiles.timezone text DEFAULT 'UTC'`, capture from browser via `Intl.DateTimeFormat().resolvedOptions().timeZone` on first visit, use `SET LOCAL timezone=...` in the stats RPC. Workaround if not done: pass per-request from browser as RPC param.

**Unified action log**: `core.usage_events` exists (partitioned, indexed) but is currently only billing-events. Backfilling it from zettels/chats/kastens via AFTER INSERT triggers collapses streak math into one indexed scan.

---

## Section 6 — Knowledge Graph / Network (15 stats)

> *Unit of analysis: graph structure. KG nodes are ENTITIES/TOPICS (not zettels). Edges are undirected, typed, weighted (workspace_strength drives rendering).*

1. **Total graph size** — `(count(kg_nodes), count(kg_edges))` for workspace. EASY · <50ms · two big numbers.
2. **Avg connections per node (mean degree)** — `2*|E|/|V|`. EASY · <50ms · big number + caption.
3. **Top 10 hub nodes** — degree-sorted, click → 3D KG viz. EASY · 50-200ms · ranked list with bars.
4. **Orphan nodes** — count + top-5 examples of zero-edge nodes. EASY · <50ms · big + collapsible list + re-engage CTA.
5. **Connected components** — count + size of largest (BFS in Python from pre-fetched adjacency at small scale; MV at >2k nodes). MEDIUM · 50-200ms · "1 giant (84%) + 6 smaller".
6. **Graph density** — `2*|E|/(|V|*(|V|-1))` (derived from #1, free). EASY · <50ms · % with sparseness label.
7. **Degree distribution histogram** — buckets `0 / 1 / 2-3 / 4-7 / 8-15 / 16+`. MEDIUM · 50-200ms · 6-bar.
8. **Bridge edges** — edges whose removal disconnects (Tarjan, Python NetworkX precompute). HARD · cached <50ms · big number + top-3 pair list.
9. **Edge strength distribution** — `workspace_strength` buckets `≥0.7 strong / 0.4-0.7 medium / <0.4 weak` (matches rendered thickness). EASY · <50ms · 3-segment bar.
10. **Relation type mix** — donut over `shared_tag / mentions / cites / co_occurs / authored_by / published_in`. EASY · <50ms · 6-segment donut.
11. **Average path length** — APSP via NetworkX, nightly MV mandatory. HARD · cached <50ms · "any two ideas ~3 hops apart".
12. **Graph diameter** — max shortest-path (cached). HARD · cached <50ms · "the two most-distant ideas are 6 hops apart".
13. **Modularity / community count** — Louvain, nightly MV; also store `community_id` in `kg_nodes.metadata` for 3D-viz coloring. HARD · cached <50ms · "7 communities, modularity 0.42".
14. **Newest edge / most recent connection** — last added edge + week growth. EASY · <50ms (needs new index) · one-line + week delta.
15. **Personal vs Global tag coverage** — `count(DISTINCT user_tags)` vs `count(kg_nodes)`. EASY · <50ms · two stacked counts + ratio insight.

**Top 5**: #1 Graph size · #3 Top hubs (engagement gold) · #4 Orphans (actionable) · #9 Edge strength mix · #13 Modularity / communities.

**Critical infrastructure note**: Stats #5/8/11/12/13 are O(V²) or worse and **must be precomputed**. Recommended:
- New MV `kg.kg_workspace_metrics_mv (workspace_id PK, computed_at, component_count, largest_component_size, bridge_count, bridges_top jsonb, avg_path_length, diameter, community_count, modularity, degree_histogram jsonb)`.
- pg_cron nightly refresh at 02:00 UTC via Python worker that reads `kg_edges`, runs NetworkX, writes via service-role upsert.
- Surface `computed_at` to UI: "Updated 6 hours ago" so freshness is visible.
- New idx `kg.kg_edges (workspace_id, created_at DESC)` for #14.

---

## Section 7 — Retrieval / Discovery / RAG (13 stats)

> *Unit of analysis: a user query. Sources = `rag.chat_messages` (role='user'), `rag.retrieval_feedback_events`. KG view + search bar aren't separately logged today — they piggyback on chat.*

1. **Total questions asked** — `count(chat_messages WHERE role='user')` all-time. EASY · <50ms (with new partial idx) · big + monthly delta.
2. **Questions this week (sparkline)** — 14-day daily count. EASY · <50ms · 14-bar sparkline.
3. **Average conversation depth** — avg user turns per session. EASY · 50-200ms · big + histogram.
4. **Top 10 most-retrieved zettels** — citations expansion + join. MEDIUM · 200-500ms (faster with rollup table) · ranked list.
5. **Most-cited source type** — % of citations by source_type. MEDIUM · 200-500ms · donut.
6. **Question streak (current + longest)** — gaps-and-islands over distinct days with ≥1 user message. MEDIUM · 50-200ms · two numbers + flame.
7. **Answer quality mix (verdict)** — `% supported / retried_supported / partial / unsupported`. EASY · <50ms · 4-segment bar.
8. **Knowledge gaps (top 5 unsupported queries)** — verbatim user questions whose paired reply was `unsupported`. MEDIUM · 50-200ms · list with "Capture on this" CTA. **PRIVACY: profile-private-only; opt-in if public-profile feature ever ships.**
9. **CTR on retrieved results** — `clicks / impressions` from `retrieval_feedback_events`. EASY · <50ms · % + 30-day sparkline.
10. **"Go-to" topics — top user-tags you keep asking about** — different from "topics you have"; this is "topics you RE-CONSULT". MEDIUM · 200-500ms · teal-saturation tag cloud.
11. **Avg answer latency (30d)** — `avg(latency_ms)` for assistant messages. EASY · <50ms · big + 30d sparkline.
12. **Conversation heatmap (hour × dow)** — 7×24 grid, teal. Mirror of capture heatmap but for retrieval. EASY · 50-200ms · same component, different data.
13. **Last query + active Kasten** — `max(user message)` + Kasten name + resume link. EASY · <50ms · one-line.

**Top 5**: #4 Top 10 most-retrieved (Spotify-top-tracks moment) · #7 Verdict mix · #8 Knowledge gaps (actionable) · #1 Total questions · #10 Go-to topics.

**Critical infrastructure note**: Existing `idx_chat_messages_session` is session-keyed; almost every retrieval stat filters on `(workspace_id, role, created_at)`. **HIGH PRIORITY**: add partial idx `rag.chat_messages (workspace_id, created_at) WHERE role='user'` — ~30 sec migration, unlocks <50ms latency for Stats 1/2/3/6/11/12.

At scale (>10k chat messages/workspace), Stats 4/5/10 should be backed by a `content.retrieval_citation_rollup (workspace_id, canonical_zettel_id, citation_count, last_cited_at)` table maintained by AFTER INSERT trigger on chat_messages.

---

## Combined "MVP" recommendation (~25 stats, zero schema change)

If the user wants the absolute leanest first ship — one card per "top pick" across sections, all EASY-tier, zero schema changes:

| Section | MVP stats |
|---------|-----------|
| General Overview | #1 Total Zettels · #4 30-day recency · #6 KG size · #9 Last added · #11 Plan+quota |
| Zettel | #1 Source mix · #7+#8 First+Latest pair · #10 Pinned · #9 Freshness buckets |
| Kasten | #1 Total · #4 Largest · #5 Top-5 · #7 Empty (with CTA) |
| Domain | #1 Top topics · #7 Topic cloud · #2 Topic diversity |
| Activity | #1 Current streak (UTC fallback) · #8 Week-over-week · #3 Peak hour |
| Network | #1 Graph size · #4 Orphans · #3 Top hubs · #9 Edge strength mix |
| Retrieval | #1 Total questions · #7 Verdict mix · #13 Last query |

That's **~25 stats**, all p95 < 200ms each (combined ~600ms in one API call with parallel CTEs), zero schema changes, ships in a single PR.

---

## What was deliberately NOT proposed

- **Cross-tenant leaderboards** ("you rank 47th globally") — privacy nightmare + the app deliberately scopes everything by workspace.
- **3rd-party-fetched stats** ("your top YouTube channel by subscriber count") — violates the DB-only constraint.
- **User-survey stats** ("how do you feel about your Zettelkasten?") — no manual input loop.
- **Anything requiring `global_strength`** from `kg_edges` — leaks cross-workspace signal.
- **`derived_tags` rollups in Domain section** — system-only per migration 72; never user-surfaced.
- **A `kg_tags` dictionary table** — explicitly rejected as anti-pattern; GIN index on `user_tags text[]` + `normalize_user_tags` migration already serve the lookup pattern at scale.

---

## Files referenced during research

- `supabase/website/_v2/01_core_schema.sql` — profiles, workspaces, workspace_members
- `supabase/website/_v2/02_content_schema.sql` — canonical_zettels, workspace_zettels, canonical_chunks
- `supabase/website/_v2/03_kg_schema.sql` — kg_nodes, kg_edges, chunk_node_mentions
- `supabase/website/_v2/04_rag_schema.sql` — kastens, kasten_zettels, chat_sessions, chat_messages
- `supabase/website/_v2/06_billing_schema.sql` — pricing_subscriptions
- `supabase/website/_v2/13_v2_kasten_rpcs.sql` — kasten member RPCs + indexes
- `supabase/website/_v2/29_kasten_sharing_rls.sql` — kasten_members sharing surface
- `supabase/website/_v2/35_retrieval_signal_views.sql` — kg_edge_viz_weights MV pattern
- `supabase/website/_v2/36_signal_views_pgcron.sql` — pg_cron MV refresh pattern
- `supabase/website/_v2/38_extensible_attrs.sql` — workspace_zettels attribute columns
- `supabase/website/_v2/42_kg_edge_two_level_strength.sql` — workspace_strength buckets (D-KG-3)
- `supabase/website/_v2/45_document_source_type.sql` — source_type enum
- `supabase/website/_v2/66_workspace_zettels_partial_indexes.sql` — idx_workspace_zettels_workspace_created
- `supabase/website/_v2/67_canonical_shred_grace_30d.sql` — soft-delete behavior
- `supabase/website/_v2/72_workspace_zettels_derived_tags.sql` — user_tags vs derived_tags split
- `supabase/website/_v2/73_normalize_user_tags.sql` — tag NFKC normalization
- `website/features/rag_pipeline/ingest/kg_population.py` — kg_node type='zettel' confirmation
- `website/features/user_profile/` — target frontend directory
