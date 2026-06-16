# Community Graph + Personal Graph — Design Proposal (research-backed, adversarially verified)

**Date:** 2026-06-15
**Author:** Claude Code (design research; NOT yet approved; no code written)
**Trigger:** `/knowledge-graph` Global/Personal toggle "broken." Root cause investigated first (below), then 5-angle deep-research on the proper design (search → adversarial verify, 10 agents).

---

# ▶ REV 3 — privacy MODEL FLIP: all-public + per-zettel opt-OUT (operator decision 2026-06-16)

> **This supersedes Rev 2's opt-in model.** Operator chose, with the privacy implication stated explicitly: the community (Global) graph shows **ALL users' zettels by default**, auto-updating as users add more; each user can **mark any zettel private** to hide it from Global; a clear **signup/first-use notice** tells users their captures are public and shown with their name. This is **opt-OUT**, not opt-in. Rationale (operator-accepted): it's a knowledge-sharing app over **summaries of public URLs**, a populated community graph is the product goal, the user base is tiny/early, and GDPR applicability is uncertain (India/non-EU per the research). The notice + per-zettel opt-out + erasure are the privacy mitigations *in lieu of* privacy-by-default.

## R3.1 What flips vs Rev 2

| Rev 2 (opt-in) | Rev 3 (opt-out) — AUTHORITATIVE |
|---|---|
| `is_published boolean DEFAULT false` (default hidden) | **`is_private boolean NOT NULL DEFAULT false`** (default **public**) on `content.workspace_zettels` + optional `made_private_at timestamptz`. **No backfill needed** — the existing ~80 zettels become public via the column default. Drop `is_published`/`published_at`/`attribution` columns from the plan. |
| Per-publish consent modal + `publish_consent_events` | **Signup/first-use NOTICE** ("Your saved zettels are public and shown with your display name. Mark any private to hide it.") is the consent basis. Keep a light append-only **`content.zettel_privacy_events`** audit (actor, workspace_zettel_id, action `make_private`/`make_public`, created_at). |
| Community predicate `WHERE is_published = true` | **`WHERE is_private = false`** everywhere (RPC, RLS policy, wrapper, regression gate). |
| RLS policy `... USING (is_published = true)` for `community_reader` | **`... USING (is_private = false)`** — fail-closed now protects the *marked-private* subset (a forgotten predicate still hides private rows). |
| Publish toggle (default OFF) + "Public" badge | **"Make private" toggle** per zettel (default = public/shown) + a teal **"Private"** badge on hidden ones + undo toast. |
| `view=global` file-store fallback when empty | **Retire the file-store** from the live global path — Global = the real all-public community graph (there is real data). Keep `graph.json` only as a seed/last-resort, not the normal path. |
| `view=my` Optional-user → empty | **`view=my` hard-401** on missing/expired auth (operator approved 2026-06-16). Verify the Part A `zk_fetch` 401→refresh→banner pipeline + `loadUserOwnedIds` handle it; regression-test Part A. |

## R3.2 Unchanged from Rev 2 (still authoritative)
- D3/D4 the privacy GATE is still the **app-layer predicate + the `community_reader` non-BYPASSRLS role + the SECURITY-DEFINER RPC owned by it + RLS** — only the predicate flips to `is_private = false`. service_role still BYPASSRLS; `community_reader` is the fail-closed boundary.
- D5 strip `user_id` from the payload; opaque node ids not derived from user_id — BUT public zettels **do** show the owner's `display_name` (attribution is the chosen model). Anonymous-contribution mode is **deferred**.
- D6/D7 caching (`view=global` public + drop `Authorization` + no `Set-Cookie` + `Vary: Accept-Encoding` only; `view=my` private,no-store), D8 SWR+single-flight+version-counter, D9 precomputed `kg.community_*` (no user_id, SELECT revoked) at scale, D10 MV CONCURRENTLY→staging-swap ladder, D11 Leiden(modularity), D12 edge top-K, D13 Cloudflare purge-on-change. (Purge/version-bump now fire on **make-private/make-public**, not publish/unpublish.)
- The N≥5 cell-suppression note (R2.2 #10) still applies to any *non-consensual aggregate* (e.g. per-URL contributor counts) — fine to expose `contributor_count` for public zettels since they're public by the chosen model, but suppress at N<5 for anything that could de-anonymize a private holder. (No private data is aggregated, so this is mostly moot under opt-out.)

## R3.3 New requirement
- **Signup/first-use public-content NOTICE** (the consent surface) — a clear, dismissible notice that saved zettels are public + attributed + how to mark private. Teal, no purple. This replaces the per-publish consent modal.

---

# ▶ REV 2 — research-integrated & operator-approved (2026-06-16)

> **NOTE: REV 2's opt-in model is SUPERSEDED by REV 3 above (opt-out). Rev 2 is retained for the decision table D3–D13 detail + citations, but the opt-in/`is_published`/default-OFF/consent-modal parts are replaced by Rev 3.**

> Part A (session keep-alive + toggle) **shipped** (PR #157, master `7a920f38`). This Rev 2 folds in the **13-agent deep-research** (full cited report: `community_graph_partb_research_2026-06-16.md`) and the operator's 2026-06-16 approval to **adopt all necessary changes incl. the least-privilege public-read DB role**. **Where Rev 2 and the original Rev-1 text below disagree, Rev 2 wins.** Implementation is driven by `docs/superpowers/plans/2026-06-16-community-graph-partb.md`.

## R2.1 Final decision table (post adversarial verification)

| # | Decision | Status | Note |
|---|---|---|---|
| D1 | `is_published` (default `false`) on **`content.workspace_zettels`** (per-user overlay), NOT on shared `canonical_zettels` | **CONFIRMED** | strongest call — avoids silent over-share via `UNIQUE(normalized_url)` |
| D2 | Explicit **named** publish (`display_name`), default private | **CONFIRMED** | Obsidian/Are.na/GitHub norm; no k-anonymity for named |
| D3 | App-layer `WHERE is_published=true` is the **PRIMARY** privacy gate | **CONFIRMED** | correct *because* service_role bypasses RLS |
| D4 | Secondary gate = RLS + `security_invoker` view | **MODIFIED → least-privilege role (APPROVED)** | RLS is **inert** on the service_role/BYPASSRLS path → serve `view=global` through a **separate non-BYPASSRLS, SELECT-only role** so a forgotten filter **fails closed at the DB**. Mirror existing `supabase/website/_v2/79_stats_reader_role.sql`. |
| D5 | `view=global` takes **no** caller `user_id`; strip `user_id` from payload; opaque node ids **not derived from user_id** | **CONFIRMED + sharpen** | add a guard that rejects/logs any `user_id` on global |
| D6 | `view=global` → `public, s-maxage=300, swr` + Cloudflare Cache Rule + **drop `Authorization` client-side** | **CONFIRMED + add** | also emit **zero `Set-Cookie`** on the public response (CF → BYPASS otherwise); `Vary: Accept-Encoding` only |
| D7 | `view=my` → `private, no-store`, hard-401, ~~`Vary: Authorization`~~ | **MODIFIED** | **DROP `Vary: Authorization`** — Cloudflare ignores all `Vary` except `Accept-Encoding`; relying on it can leak a private response to anon |
| D8 | Storage Tier 1 = live query + 5-min cache | **MODIFIED** | → **stale-while-revalidate + single-flight**, refresh thread started **post-fork** (gunicorn pre-fork bug); per-worker caches aren't shared → add a **version-counter** row for coherency |
| D9 | Precomputed `kg.community_*` (no `user_id`, `SELECT` revoked from anon/authenticated) | **CONFIRMED** | the no-PII published surface |
| D10 | Rebuild via staging-table swap | **MODIFIED** | insert **`REFRESH MATERIALIZED VIEW CONCURRENTLY`** as Tier 2 (the "empty-graph window" objection to MV is **factually wrong** — only `DELETE+INSERT`/non-concurrent `REFRESH` do that). Staging-swap (Tier 3) `RENAME` takes `AccessExclusiveLock` → `lock_timeout`+retry, one-txn, **re-apply REVOKE + re-point view** each swap; prefer stable view name + `CREATE OR REPLACE VIEW` |
| D11 | Clustering via igraph `community_multilevel()` (Louvain) | **MODIFIED** | use **Leiden** with **`objective_function="modularity", n_iterations=-1`** (igraph's Leiden defaults to CPM/res=1.0 → fragmented). Run **out-of-DB** in the Python batch (pg_cron can't call igraph) |
| D12 | Shared-tag co-occurrence edges | **MODIFIED/ADD** | cap **per-node top-K (~10–20) + tag-frequency ceiling**; avoid a single global weight threshold; disparity filter (Serrano 2009) as upgrade |
| D13 | CDN revocation via short `max-age` | **MODIFIED** | Cloudflare purge is **free for all plans since 2025-04-01** → fire async **purge-by-URL on unpublish** atop `s-maxage`+SWR |

## R2.2 New scope — gaps the original design omitted (all low/zero-infra, now IN-scope)

1. **Consent-audit table** `content.publish_consent_events` (actor, workspace_zettel_id, action publish/unpublish, consent_version, attribution_mode, created_at) — append-only (GDPR Art. 7(1)).
2. **Least-privilege public-read DB role** (D4) — non-BYPASSRLS, SELECT-only, scoped to the published surface. *(Approved infra decision 2026-06-16.)*
3. **Forced-predicate repository wrapper** — single code path that always applies the published filter.
4. **Published↔unpublished edge invariant** — both endpoints must be published; tested at API **and** DB.
5. **Moderation pipeline** — report → `content_reports` → review queue → single unpublish lever + statement-of-reasons (DSA Art. 16/17 bind even micro/small).
6. **Legal** — ToS license grant ("user retains ownership + non-exclusive operating license", Are.na/GitHub model; **reject CC BY-SA**) + AUP + Privacy Policy + **DMCA agent (~$6)**.
7. **Per-user publish rate-limit** (ride pricing entitlements) + new-account first-publish hold; track by account not IP.
8. **Erasure path for precompute tiers** + append-only erasure audit log (tombstone ⇒ actual removal).
9. **Cross-worker cache version-counter** + TTL backstop (poll at scale; `LISTEN/NOTIFY` doesn't scale to 10k+).
10. **N≥5 cell suppression** for any non-consensual public aggregate (e.g. per-URL "published by N users").
11. **Cloudflare hardening** — no `Set-Cookie` on global; web-cache-deception path-confusion guard.
12. **CI regression gate** — `view=global` can never return `is_published=false` rows under service_role.

## R2.3 Corrected phasing (scale-proof, not over-built for ~15 users)

- **Phase 0 — schema + privacy/consent floor:** `is_published` on `workspace_zettels` (default OFF) + `publish_consent_events` + the **least-privilege public-read role** + forced-predicate wrapper + the `view=global` CI regression gate. *Must exist before anything is publishable.*
- **Phase 1 — serving + minimal publish UX (MVP public graph):** live `SELECT … WHERE is_published` + SWR + single-flight (post-fork) · `view=global` (`public, s-maxage`, `Vary: Accept-Encoding`, no `Set-Cookie`, drop `Authorization`) + `view=my` (`private, no-store`, hard-401) · Cloudflare Cache Rule (key = path/`view`) · per-item publish toggle (default OFF) + first-publish consent modal + undo toast + teal "Public" badge · Personal/Community switch.
- **Phase 2 — moderation + legal:** report → `content_reports` → queue → unpublish lever (+ ack/statement emails) · ToS/AUP/Privacy/DMCA · rate-limit + new-account hold · wire unpublish → Cloudflare purge + version-counter bump.
- **Phase 3 — clustering + discovery:** out-of-DB Python batch — igraph **Leiden(modularity) + PageRank** (one graph load, write back) · per-node top-K + tag-frequency edge capping · discovery = chronological "Recently published" + curated featured + scoped search + cluster entry points.
- **Phase 4 — precompute tier, on MEASURED triggers only:** MV CONCURRENTLY first; staging-swap/rollup only if forced. Trigger = uncached p95 / cron-vs-interval / WAL share — **never user count**.

**Deferred (each a standalone decision when triggered):** free classifier triage (OpenAI Moderation, fail-open) · shadow-ban · trusted-flagger/DSA portal · anonymous-contribution mode (stylometry caveat) · CC-export. Engagement-ranked "trending" → likely never (anti-algorithm is the feature).

## R2.4 Residual uncertainties (carry into build)
- **GDPR applicability** to an India-based, non-EU-targeting, ~15-user app is genuinely uncertain (Art. 3(2) targeting test) — controls above are justified as best-practice + scale-future-proofing; get a real legal read before relying on "out of scope."
- **Cloudflare Free-plan async SWR** is non-uniform per open reports → `curl`-verify `cf-cache-status` on the zone.
- **MV CONCURRENTLY** autovacuum/bloat tax on a 2 GB Supabase instance is real but unquantified → measure at Phase 4.

---

## 0. Root cause (already investigated, on the live site)

The graph **API is healthy**. What broke:
1. **Session silently dies on `/knowledge-graph`.** The page never loads the Supabase auth client (`auth-core.js`) — confirmed live: `window.supabase` undefined, `hasAuthCore:false`, scripts list has no auth-core. The client (with `autoRefreshToken:true`) is the *only* thing that refreshes the access token. So the token expires after ~1h (observed expired ~2.8h), every `view=my` call degrades to anonymous (`jwt-dropped-to-anon`), Personal → 0. The `refresh_token` is sitting in localStorage unused.
2. **"Global" toggle never sends `view=global`** — `loadGraphData()` omits the param, server infers `my` for authed users → "Global" shows the *personal* graph.
3. **There is no real community graph today.** "Global" = a curated 29-node `graph.json` demo seed (`source:file-store`). User zettels live in Supabase v2 (`source:v2`), per-workspace, and are **not** in it. (User's mental model "Global has everyone's zettels" does not match reality.)

---

## 1. The single most important finding (privacy)

**Our app queries Supabase via the `service_role` client (`get_v2_client()`), which has `BYPASSRLS`.** Therefore **RLS is NOT the privacy gate for the API path** — it is bypassed. The verified consequence:

> The **application-layer `WHERE <published> = true` filter is the PRIMARY and load-bearing privacy gate.** RLS + a `security_invoker` view are *secondary* defense-in-depth only. Any bug/injection that drops the app-layer filter leaks every private zettel.

Corollaries (all from the adversarial passes):
- Tables created via SQL migration have **RLS disabled by default** → adding policies is inert unless `ENABLE ROW LEVEL SECURITY` is run. Verify it; but don't *rely* on it given service_role.
- `kg.*` community tables must have **SELECT revoked from `anon`/`authenticated`** or Supabase PostgREST auto-exposes them publicly (advisor 0016). Never expose a materialized view to those roles.

---

## 2. Corrected core architecture (the key fix vs the naive design)

**Naive design (from first-pass findings): put `is_public` on `content.canonical_zettels`.** ❌ **Rejected by the adversarial pass** — `canonical_zettels` is **shared across users** (dedup by `UNIQUE(normalized_url)`, PR #25). If `is_public` lived there, a user saving a URL another user already published would inherit `is_public=true` **without consent** (silent over-share). Also a single SQL row can't represent per-user consent.

**Corrected design: the publish/opt-in flag is PER-USER, on `content.workspace_zettels`** (the per-(user,canonical) overlay row), default off. A canonical entity is "in the community graph" iff **≥ 1 user's workspace_zettel for it is published** (and see k-anonymity below). This also yields `contributor_count` for free.

```
content.workspace_zettels   (per-user overlay — EXISTS)
  + ADD COLUMN is_published BOOLEAN NOT NULL DEFAULT false   -- per-user opt-in, the consent record
  + ADD COLUMN published_at TIMESTAMPTZ                       -- internal audit ONLY, never in any API
  + ADD COLUMN attribution  TEXT DEFAULT 'named'             -- 'named' | 'anonymous'
content.canonical_zettels   (shared, deduped — EXISTS, UNCHANGED; no is_public here)
```

This single correction resolves the consent-collision **and** the `graph.json` seed problem: seed/demo nodes become a "system" workspace's published rows; a user saving the same URL gets their *own* `workspace_zettels` row with `is_published=false` — the shared canonical is reused but the consent flag is per-workspace. ✓

---

## 3. PART A — Immediate fix (restores Personal + toggle; small; independent of the community build)

Ship this first — it makes the toggle work "every time" for the *existing* Personal/Global(file-store) behavior, regardless of the bigger feature.

| Fix | What | Verified caveat |
|-----|------|-----------------|
| **A1. Load `auth-core.js` on `/knowledge-graph`** | One `<script>` so the Supabase client's `autoRefreshToken` timer runs → token never silently expires. The removal-with-the-shared-header was the bug. | **Must add a singleton guard** in auth-core.js (`if (window.__supabase) return window.__supabase`) — "Multiple GoTrueClient instances" is undefined behavior (auth-js #725). **And avoid `await` inside `onAuthStateChange`** — documented P0 Navigator-Locks deadlock (supabase-js #2013, open Jan 2026). |
| **A2. 401-retry shim** (secondary) | In the KG fetch wrapper: on `JWT expired`/anon-downgrade, `refreshSession()` once and retry. Belt-and-suspenders for the ~1s expiry race. | Not the primary mechanism (A1 is); a noticeable hiccup if used as primary. |
| **A3. Global toggle sends `view=global`** | `loadGraphData()` must set `view=global` explicitly (not rely on server inference). | Trivial; confirmed via live asset. |
| **A4. Auth-expiry UX** | On `SIGNED_OUT` (refresh token dead), show inline "Session expired — sign in" in the Personal panel; keep Global visible. No empty-graph confusion, no hard redirect. | Industry standard (Notion/Linear/Vercel). |

Part A is ~a day, vanilla-JS + a cache-bust, through the normal review→merge→deploy→verify (this time **including a logged-in `view=my` check + the toggle**, which my earlier verification missed).

---

## 4. PART B — The community graph (phased; the real feature)

### B1. Opt-in model — **operator decision needed** (see §6)
Two consensual models (both industry-standard; pick one as the default):
- **Explicit named publish (recommended):** per-zettel "Publish to community" toggle (`is_published` on `workspace_zettels`), shown with the author's `display_name`. Matches Obsidian Publish / Notion "Share to web" / Are.na. **Works at small scale (k=1 is fine — the user consented to attribution).** No k-anonymity gymnastics.
- **Anonymous aggregate:** community node appears only when **`contributor_count ≥ 3`** (k-anonymity) and never shows an author. Privacy-max, but at 10–15 users **almost nothing qualifies** (needs 3 users sharing the *same* URL) → an empty community graph. Better suited to 1k+ users.

> Adversarial flag: with named attribution at scale, `display_name` + a uniquely-shared URL is a re-identification vector — fine for opt-in *public* content (they consented), but never auto-attribute non-published data.

### B2. Privacy guardrails (non-negotiable, all verified)
1. **App-layer `WHERE is_published=true` is the gate** (service_role bypasses RLS). Add `ENABLE ROW LEVEL SECURITY` + a `security_invoker` view as secondary layers; never rely on them alone.
2. **`view=global` query NEVER accepts a caller `user_id`** — hardcoded predicate. **Strip `user_id`** from the payload; emit `display_name` only for `attribution='named'` published rows. Use random/opaque node ids.
3. **`view=my` MUST hard-401** on missing/expired auth via `Depends(require_auth)` — never `Optional[user]` silent-fallthrough (that's today's bug). Keep `Cache-Control: private, no-store` + weak ETag (shipped) + add `Vary: Authorization`.
4. **Un-publish revocation must be bounded.** A zettel set back to private must leave the community graph + CDN within an SLA: shorten cache TTL on revoke, or Cloudflare cache-purge, or Postgres `LISTEN/NOTIFY` to invalidate the per-worker in-process cache (2 Gunicorn workers each cache independently → a revoke on worker A leaves worker B stale up to TTL).
5. `kg.community_*` tables: **REVOKE SELECT from anon/authenticated** (PostgREST auto-exposure).

### B3. Aggregation + storage (start simple → precompute later)
- **Now (10–15 users):** `view=global` = a live `SELECT … JOIN where is_published=true` + an **in-process cache (5-min TTL)**; igraph analytics (`community_multilevel()` — NOT `community_louvain()`, which AttributeErrors) computed on the cached result, also cached. No new infra.
- **Scale path (tens of thousands of public nodes):** precomputed `kg.community_nodes` / `kg.community_edges` (no `user_id` column), rebuilt by **pg_cron via a staging-table swap** (`build into staging → ALTER … RENAME`) — NOT `DELETE+INSERT` (causes an empty-graph window every refresh) and NOT `pg_ivm` (can't do the co-occurrence joins/aggregates) and NOT Apache AGE (not on Supabase). Dedup is free via the existing `UNIQUE(normalized_url)`.
- **Retire `graph.json`** from the live path → seed those demo nodes as a system workspace's published rows.

### B4. Serving + caching
- `view=global`: `Cache-Control: public, max-age=300` + **Cloudflare Cache Rules** (2024 GA, query-aware) — NOT the 2021 `CDN-Cache-Control` header dance, NOT a Caddy path rule (can't match `?view=`). **Do not send `Authorization` on global requests** (Cloudflare BYPASSes cache when `Authorization` is present) — omit it in the JS client for `view=global`. Strong ETag from `MAX(updated_at WHERE is_published)`.
- `view=my`: unchanged (`private, no-store`, weak ETag, hard-401, `Vary: Authorization`).
- **CDN cache key must include `view`** or a public response could be served for a private request (and vice-versa).

---

## 5. Adversarial corrections that changed the design (don't lose these)
1. **Opt-in flag must be on `workspace_zettels` (per-user), not `canonical_zettels` (shared)** — else silent over-share via URL dedup.
2. **service_role bypasses RLS** → app-layer filter is the real gate; RLS is secondary; verify `ENABLE RLS` + REVOKE on kg.*.
3. **k-anonymity (contributor_count ≥ 3) for anonymous mode**; named-publish needs explicit consent + attribution.
4. **Postgres MVs have no RLS** + `REFRESH CONCURRENTLY` isn't free on 2GB/1vCPU → use a plain table + staging swap, and don't expose it to anon/authenticated.
5. **`community_multilevel()`** not `community_louvain()`.
6. **Singleton GoTrueClient guard + no-async-in-`onAuthStateChange`** (deadlock) when adding auth-core to KG.
7. **No `Authorization` on `view=global`** (Cloudflare BYPASS) + Cloudflare **Cache Rules** for query-aware caching.
8. **Un-publish revocation window** (per-worker cache + CDN) is a real privacy gap to bound.
9. Drop the unverifiable perf numbers (igraph "<200ms", MV "<100ms"); cache is mandatory regardless.

---

## 6. Decisions needed before building (operator)
1. **Publish model:** explicit named-publish (recommended; works now) vs anonymous k-anonymity (privacy-max; needs scale). Or both modes.
2. **Ship Part A now** (session fix + toggle + auth-expiry UX) as a fast standalone PR, *before* the community build? (Recommended — restores Personal reliably today.)
3. **Phasing of Part B:** schema + opt-in toggle + `view=global` live query first; precompute tables deferred to a scale trigger?

## 7. Phasing (proposed)
- **Phase 0 (now):** Part A (session keep-alive + toggle + auth-expiry UX). Restores reliability.
- **Phase 1:** schema (`is_published`/`attribution`/`published_at` on workspace_zettels) + per-zettel publish toggle UI + `ENABLE RLS`/REVOKE/`security_invoker` view.
- **Phase 2:** `view=global` = live query + in-process cache + igraph (`community_multilevel`) + app-layer filter (primary gate) + cache divergence (public + Cache Rules; no Authorization) + retire graph.json (seed migration).
- **Phase 3 (scale trigger):** precomputed `kg.community_*` via pg_cron staging-swap; un-publish purge (NOTIFY/CF purge); k-anonymity if anonymous mode.

## Citations (selected, 2021–2026)
Obsidian Publish / Logseq / Notion / Are.na / Wikidata / GitHub dependency graph (community-vs-personal patterns); OWASP API1:2023 BOLA; Supabase RLS docs + security advisors 0016/0010; pganalyze + Knock "security_invoker views"; Postgres `REFRESH MATERIALIZED VIEW CONCURRENTLY` docs; pg_ivm limitations; Supabase Cron; Cloudflare cache-control + Cache Rules + Authorization-BYPASS; supabase-js #2013 (Navigator Locks deadlock) + auth-js #725 (multiple GoTrueClient); GDPR Art. 25 privacy-by-default; k-anonymity in social graphs. (Full URLs in the research transcript.)
