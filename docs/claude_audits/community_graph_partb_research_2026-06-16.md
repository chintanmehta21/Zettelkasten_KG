<!-- Deep-research deliverable: 13-agent search -> adversarial-verify -> synthesize (run wf_7da8660c-115), 2026-06-16. Assistant-authored audit; pairs with community_graph_design_2026-06-15.md. -->

# Part B: Community Knowledge Graph (Public, Opt-In) + Personal Graph — Final Implementation-Grade Research Report

**Audience:** Senior engineer building Part B on the existing stack (FastAPI async + Supabase Postgres via PostgREST/asyncpg + vanilla-JS `3d-force-graph` + ONE DigitalOcean droplet 2 GB/1 vCPU + Caddy + Cloudflare). **Scale mandate:** ~15 users today, must reach 10k+ without rework.

**Critical infra fact this whole report turns on:** the app talks to Supabase via the **`service_role` client, which has `BYPASSRLS`**. RLS does not execute on the API path. Every privacy decision below is shaped by that single fact.

---

## 1. Executive Summary — The Recommended Complete Solution

1. **Publish flag placement (CONFIRMED).** Put `is_published` (default `false`) on the per-user overlay row `content.workspace_zettels`, **never** on the deduped `content.canonical_zettels`. A flag on the canonical row would let User A's consent silently control User B the moment a second user saves the same `normalized_url`. This is the single strongest, fully-upheld decision in the design. ([Transcend GDPR consent](https://transcend.io/blog/gdpr-consent-requirements))

2. **Consent model: explicit, named, opt-in, default-OFF, with a consent audit record (MODIFY — add the audit table).** Named pseudonymous attribution via `display_name` is correct; do **not** gate it with k-anonymity. Add a ~5-column append-only `publish_consent_events` table (ISO/IEC TS 27560-*inspired*, not literal) to satisfy GDPR Art. 7(1) demonstrability — this is the biggest consent gap in the current design. ([gdpr-info Art. 7](https://gdpr-info.eu/art-7-gdpr/))

3. **Privacy enforcement (MODIFY — the secondary gate is currently inert).** The app-layer `WHERE is_published = true` is correctly the *primary* gate, but RLS + `security_invoker` view provide **zero** protection on the `service_role`/`BYPASSRLS` path — they are dormant exactly where it matters. The decisive upgrade: **serve the global path through a separate, non-`BYPASSRLS`, SELECT-only DB role** whose grants cover only the published surface, so a forgotten filter **fails closed at the DB**. ([Postgres RLS docs §5.9](https://www.postgresql.org/docs/current/ddl-rowsecurity.html), [pganalyze BYPASSRLS](https://pganalyze.com/blog/5mins-postgres-row-level-security-bypassrls-security-invoker-views-leakproof-functions))

4. **Forced-predicate query layer (MODIFY — add it).** Funnel ALL community reads through one repository method that always applies the published filter (Django-manager / `django-scopes` pattern). The #1 documented failure of app-layer isolation is a forgotten `WHERE`. ([django-scopes](https://github.com/raphaelm/django-scopes))

5. **No `user_id` in the public payload + opaque node IDs (CONFIRMED, with one sharpening).** Strip `user_id`; node IDs must be opaque (UUID/salted hash) and **must not be derived from `user_id`** (else the ID itself fingerprints). Promote the **published↔unpublished edge filter to a hard, tested invariant** — opt-in consent excuses *node attribution* but not *structural leakage* of private notes via edges/degree. ([OWASP API1:2023](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/))

6. **Serving/caching (MODIFY — `Vary` is a trap on Cloudflare).** `view=global` → `Cache-Control: public, s-maxage=300, stale-while-revalidate` + `Vary: Accept-Encoding` only, with `Authorization` **dropped client-side**. `view=my` → `Cache-Control: private, no-store` + hard-401. **Remove `Vary: Authorization`** — Cloudflare ignores all `Vary` except `Accept-Encoding`; relying on it can leak one user's private graph to anonymous requests. Public response must emit **zero `Set-Cookie`** (with Origin Cache Control on, a stray `Set-Cookie` silently forces BYPASS). ([Cloudflare cache-control](https://developers.cloudflare.com/cache/concepts/cache-control/))

7. **Storage tier ladder (MODIFY — insert MV CONCURRENTLY; the design's "empty-graph window" premise for it is factually wrong).** Tier 1 (now): live `SELECT … WHERE is_published` + stale-while-revalidate in-process cache. Tier 2 (next): **`REFRESH MATERIALIZED VIEW CONCURRENTLY`** via pg_cron — it does NOT cause an empty-graph window (only `DELETE+INSERT` and plain non-concurrent `REFRESH` do). Tier 3 (scale): staging-swap / rollup tables. The current design jumps straight to staging-swap; MV CONCURRENTLY is less code for identical no-empty-window semantics. ([Postgres REFRESH MV](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html))

8. **Staging-swap, if/when used (MODIFY — not free).** `ALTER TABLE … RENAME` takes `AccessExclusiveLock`; it queues behind in-flight reads and then **blocks all subsequent reads** (lock-queue stall on 1 vCPU). Mandate `SET lock_timeout` (~2 s) + retry, do both renames in one transaction, and **re-apply `REVOKE SELECT` + re-point the `security_invoker` view** after every swap (renames don't follow dependents). Prefer a **stable view name + `CREATE OR REPLACE VIEW` repoint**. ([xata lock-queue](https://xata.io/blog/migrations-and-exclusive-locks))

9. **Clustering (MODIFY — Leiden, but NOT with defaults).** Use `igraph.community_leiden(objective_function="modularity", n_iterations=-1)` — **not** `community_multilevel` (Louvain, leaves up to 16% of clusters disconnected). Critical correction: igraph's Leiden **defaults to CPM/resolution=1.0, which the maintainers say "almost guarantees" bad/fragmented clusters** — "just swap the method name" is wrong; you must pass `objective_function="modularity"`. Run igraph (Leiden + PageRank, one graph load) **out-of-process** on a schedule. ([igraph CPM-default warning](https://github.com/igraph/rigraph/issues/529), [Traag 2019 Leiden](https://www.nature.com/articles/s41598-019-41695-z))

10. **Edge-explosion control (CONFIRMED-and-add).** A naive all-pairs-sharing-a-tag join is combinatorial (one tag with N items → N²/2 edges). Cap with **per-node top-K (K≈10–20) + a tag-frequency ceiling**; **avoid a single global weight threshold** (it deletes the long-tail low-degree nodes you want). Disparity filter (Serrano 2009) is the documented upgrade. ([MS "Trimming the Hairball"](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/12/TrimmingTheHairball.pdf), [Serrano 2009 PNAS](https://www.pnas.org/doi/10.1073/pnas.0808904106))

11. **Revocation/erasure (MODIFY — wire active purge; treat nodes as identifiable).** Unpublish must (a) flip the flag, (b) **fire a Cloudflare purge-by-URL** (now free for all plans since 2025-04-01; propagation sub-second), and (c) exclude the note from the next precompute rebuild. Community nodes carry `display_name` + URL → they are **identifiable personal data**: erasure must *remove*, not hide. Cross-worker cache coherency: use a Postgres version-counter (poll at scale; `LISTEN/NOTIFY` is fine now but **does not scale** to the 10k+ write target due to a global commit lock). ([Cloudflare instant-purge-for-all](https://blog.cloudflare.com/instant-purge-for-all/), [Recall.ai LISTEN/NOTIFY](https://www.recall.ai/blog/postgres-listen-notify-does-not-scale))

12. **Moderation/UX (CONFIRMED — reactive, Are.na-style).** Ship reactive T&S (report button → review queue → single unpublish lever), zero ML infra at launch. ONE report pipeline satisfies both EU DSA notice-and-action *and* DMCA. Publish UX = per-item toggle (default OFF) + first-publish consent modal + undo toast. License = "user retains ownership + non-exclusive operating license" (Are.na/GitHub model); **reject CC BY-SA** on AI-summaries of third-party URLs. Register a DMCA agent (~$6). ([Are.na ToS](https://www.are.na/terms), [GitHub AUP](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies))

13. **GAPS the current design omits entirely:** consent audit record, ToS/license grant + AUP + Privacy Policy + DMCA agent, report→queue→unpublish moderation pipeline, the least-privilege public-read DB role, per-user publish rate limit, erasure audit log, and the published↔unpublished edge invariant. All are low/zero-infra.

14. **One legal-scope caveat carried throughout:** GDPR applicability is **conditional**, not automatic. An India-based, non-EU-targeting, 15-user app is plausibly outside GDPR's material scope (Art. 3(2) targeting test; "mere EU accessibility is not enough"). Treat the GDPR-grade controls as **best practice + scale-future-proofing**, not unconditional legal mandate. ([EDPB Guidelines 3/2018](https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_3_2018_territorial_scope_after_public_consultation_en_1.pdf))

---

## 2. Area-by-Area Findings (final verdicts after adversarial corrections)

### 2.1 Consent / Publish

**FINAL VERDICT: ADOPT the per-overlay, explicit, named, default-OFF model; ADD a consent audit record, a withdrawal-as-easy-as-publish path, and three non-code load-bearing items (consent micro-copy, ToS license grant, regression test).**

**Pragmatic approach for our infra.** Keep `is_published` on `content.workspace_zettels`. When you later add "publish my whole Kasten," implement it as a **fan-out that sets the per-item flag on each row**, never a workspace-level boolean — preserves per-item granularity + audit while giving bulk ergonomics. Add a tiny append-only table:

```
content.publish_consent_events (
  id, actor_user_id, workspace_zettel_id,
  action,            -- 'publish' | 'unpublish'
  consent_version,   -- ToS/consent-copy version string
  attribution_mode,  -- 'named' (today) | 'anon' (deferred)
  created_at
)
```

Append-only so withdrawal never erases the proof consent *was* given before withdrawal (Art. 7(3): withdrawal doesn't affect prior lawfulness). This is ~5 columns, one table, zero new infra. Named pseudonymous `display_name` is the correct, sufficient identifier — **do not require legal names, do not gate with k-anonymity** (consent makes k-anonymity moot for named publish; an N≥3 gate would render a 15-user graph empty).

**What major corps do.** Obsidian Publish is the north star: per-note `publish: true`, default unpublished, explicit publish AND explicit unpublish. Notion is the *warning*: public pages can be duplicated into other workspaces and **persist outside the owner's control after unpublish** — disclose this in consent copy. Stack Overflow makes attribution a *license term* (CC BY-SA), which is why you need an explicit ToS grant. Reddit/Discord/GitHub = persistent pseudonym (the dominant UGC norm); Facebook real-name is the outlier you do not copy.

**Adversarial corrections incorporated.**
- **Dropped** the CaixaBank citation (its €6M fine was Art. 6 + Arts. 13/14; Art. 25 was only an *aggravating factor*, not the violated article).
- **Dropped/re-scoped** EDPB Opinion 08/2024 (it covers "consent or pay" for behavioural ads by *large* platforms — wrong authority for granular publishing consent).
- **Relabeled** the consent table "27560-*inspired*" (the real standard is JSON-LD/DPV consent receipts, heavier than 5 columns).
- **Marked** "Notion withdrawal doesn't retract copies" as a logical *inference* (Notion confirms duplication + independent control, but doesn't state post-unpublish persistence verbatim).
- **Strengthened** (not softened) the anonymity warning: if you ever build an anonymous mode, 2026 stylometry + LLM authorship-attribution de-anonymizes free text *at scale* — k-anonymity over tag facets does **not** defend the note's free text.

**Side-effects + infra cost.** One small append-only table; trivial write on each toggle. No new services.

**Citations.** [Transcend GDPR consent](https://transcend.io/blog/gdpr-consent-requirements) · [gdpr-info Art. 7](https://gdpr-info.eu/art-7-gdpr/) · [noyb Art. 7(3)](https://noyb.eu/en/your-right-withdraw-your-consent-article-73) · [Obsidian Publish docs](https://help.obsidian.md/Obsidian+Publish/Publish+and+unpublish+notes) · [Notion duplicate public pages](https://www.notion.com/help/duplicate-public-pages) · [SO CC BY-SA (arXiv 1707.00452)](https://arxiv.org/pdf/1707.00452) · [W3C DPVCG 27560 guide](https://www.w3.org/community/reports/dpvcg/CG-FINAL-guide-27560-20240801/) · [EDPB territorial scope 3/2018](https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_3_2018_territorial_scope_after_public_consultation_en_1.pdf) · [GDPRhub CaixaBank (correction)](https://gdprhub.eu/index.php?title=AEPD_-_PS-00477-2019) · [Simmons EDPB 08/2024 (correction)](https://www.simmons-simmons.com/en/publications/clvpeiyzw00s0ua8c0jyqml42/key-points-from-edpb-opinion-08-2024-on-consent-or-pay-models)

---

### 2.2 Privacy Enforcement under RLS-Bypass + BOLA / k-anonymity

**FINAL VERDICT: ADOPT-WITH-MODS. The ordering (app-filter primary) is correct *because* `service_role` bypasses RLS — but the secondary RLS/`security_invoker` layer is INERT on the API path and must be made real via a least-privilege role.**

**Pragmatic approach for our infra.** Five-layer defense, in priority order:

1. **Primary — forced-predicate wrapper.** One repository method that always applies `is_published = true` (or reads only the published-surface tables). Kills the forgotten-filter failure mode.
2. **Secondary that actually bites — least-privilege role.** Run `view=global` through a **non-`BYPASSRLS`, SELECT-only role** granted only the published surface (ideally the precomputed `kg.community_*` tables, `SELECT REVOKED from anon/authenticated`). A missing predicate now **fails closed**, and your RLS/`security_invoker` finally executes. This is the highest-leverage upgrade. *(Practical tension: Supabase's `service_role` IS `BYPASSRLS` by design and is the app's current connection — this mod means standing up and routing a second DB role/connection for global reads. Real work, low cost, surface as an explicit decision per repo guardrails.)*
3. **Tertiary — structural.** Precomputed `kg.community_*` with **no `user_id` column**; opaque node IDs not derived from `user_id`. Apply `security_barrier = true` to the *live* `security_invoker` view over `workspace_zettels` (benchmark it — docs warn it "may perform far worse"; it's largely unnecessary on the no-PII precomputed table since there's nothing to leak).
4. **Quaternary — edge/CDN.** Drop `Authorization` on global; hard-401 on private (see §2.4).
5. **Continuous — CI deploy gate.** Row-level isolation tests run **as the public-read role**: assert an unpublished node never appears in `view=global` (API *and* DB layers), and `view=my` returns 401 without auth and never another user's nodes. OWASP: "Do not deploy changes that make the tests fail."

**BOLA discipline (CONFIRMED).** `view=global` takes **no** `user_id` (no object reference to break); `view=my` derives tenant **only from the token**, strips any client-supplied `user_id`. This split is itself the strongest BOLA control.

**k-anonymity (ADOPT-WITH-MODS, low priority).** Do **not** gate individual published nodes (consent makes it unnecessary and UX-harmful). **Do** apply a **minimum cell size N≥5** (suppress 1–4) to any *non-consensual aggregate* you ever surface — especially a per-URL "published by N users" count, which fingerprints directly at N=1 given `UNIQUE(normalized_url)`.

**What major corps do.** Google **Zanzibar** is the canonical large-scale object-authz answer (one consistent authorizer for every endpoint) — you don't need it at 10k; the forced-predicate wrapper is the same principle at the right altitude. The Supabase/Postgres community (MakerKit, Bytebase, pganalyze) treats **RLS as the security floor and "don't run the app on a `BYPASSRLS` role" as the real consensus** — your least-privilege-role mod is the *convergence* of the app-primary and RLS-primary camps. Apple/Google use differential privacy for *non-consensual telemetry* — **reject DP here** (you want fidelity + attribution, not noise).

**Adversarial corrections incorporated.**
- **Dropped** the "k=50 is what Google enforces" claim: Privacy Sandbox's real value was k=10 (planned k=50 never shipped), and **Protected Audience was officially retired Oct 2025**. Re-anchor N≥5 to statistical-disclosure-control small-cell practice.
- **Softened** "app-layer-primary is industry consensus" → the real consensus is "avoid `BYPASSRLS` on the app path."
- **Flagged** `security_barrier`'s performance cost.
- **Promoted** the published↔unpublished edge filter from a parenthetical to a hard, tested invariant.

**Side-effects + infra cost.** New DB role + grants + a second connection routing; one wrapper method; CI test additions. Zero new services.

**Citations.** [Postgres RLS §5.9 (BYPASSRLS always bypasses)](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) · [Supabase service_role bypasses RLS](https://supabase.com/docs/guides/troubleshooting/why-is-my-service-role-key-client-getting-rls-errors-or-not-returning-data-7_1K9z) · [pganalyze BYPASSRLS/security_invoker/leakproof](https://pganalyze.com/blog/5mins-postgres-row-level-security-bypassrls-security-invoker-views-leakproof-functions) · [Bytebase RLS footguns](https://www.bytebase.com/blog/postgres-row-level-security-footguns/) · [MakerKit RLS best practices](https://makerkit.dev/blog/tutorials/supabase-rls-best-practices) · [Postgres security_barrier perf](https://www.postgresql.org/docs/current/rules-privileges.html) · [OWASP API1:2023 BOLA](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/) · [django-scopes](https://github.com/raphaelm/django-scopes) · [CDT: Privacy Sandbox is dead (correction)](https://cdt.org/insights/googles-privacy-sandbox-is-dead-the-fight-for-real-online-privacy-continues/)

---

### 2.3 Aggregation / Storage at Scale

**FINAL VERDICT: ADOPT-WITH-MODS. Phased ladder is right; insert MV CONCURRENTLY as Tier 2; use Leiden-with-modularity; cap edges per-node; switch tiers on measured triggers, not user count.**

**The load-bearing correction.** The design rejects `REFRESH MATERIALIZED VIEW CONCURRENTLY` partly on an "empty-graph window" premise — **that premise is factually wrong**. Per Postgres docs, CONCURRENTLY builds new contents in a temp area and applies only the diff "without locking out concurrent selects." The empty/outage window applies to **`DELETE+INSERT`** (correctly rejected) and to **plain non-concurrent `REFRESH`** (takes an exclusive lock that blocks readers). So MV CONCURRENTLY is a valid no-empty-window option the design wrongly excluded.

**Pragmatic three-tier ladder for our infra:**

| Tier | Mechanism | Switch when… |
|---|---|---|
| **1 — Live + SWR cache** (now) | `SELECT … WHERE is_published` + stale-while-revalidate + single-flight | uncached recompute p95 approaches ~⅓ of latency budget, or recompute contends with request traffic on the 1 vCPU |
| **2 — MV refreshed CONCURRENTLY** (next) | pg_cron `REFRESH … CONCURRENTLY` (needs UNIQUE index); igraph Leiden+PageRank batch writes back | CONCURRENTLY's WAL/CPU/autovacuum-blocking cost gets heavy, or you need incremental (only-new-zettels) edge computation |
| **3 — Staging-swap / rollup tables** (scale) | `kg.community_nodes/_edges` (no `user_id`, SELECT revoked); build-into-staging → swap; incremental `ON CONFLICT` | terminal tier on a single Postgres |

**`pg_ivm` — REJECT** (two independent disqualifiers): not installable on managed Supabase (C extension, not in the approved set), and "not recommended for production" / blocks writes until the IMMV updates. **Trigger-based whole-graph rebuild — REJECT** (same write-blocking failure mode; triggers OK only for O(1) counters).

**Clustering — Leiden, run out-of-DB.** pg_cron schedules SQL only; **igraph runs in the Python app process, not in pg_cron**. Real pipeline: pg_cron → trigger app-side recompute → `SELECT` published edge list → igraph **Leiden + PageRank in one graph load** → write `cluster_id`/`pagerank` back. Drive `3d-force-graph` node size from stored `pagerank`.

**Edge-explosion control.** Per-node top-K (K≈10–20) via `ROW_NUMBER() OVER (PARTITION BY node ORDER BY weight DESC)` + tag-frequency ceiling (down-weight `1/log(tag_freq)`). **Avoid a single global weight threshold** (biases against low-degree nodes). Disparity filter (Serrano 2009) is the documented upgrade.

**What major corps do.** Citus/Azure frames it as materialized-views-vs-rollup-tables (rollups win only under genuine write-scale). Figma/Notion (via pganalyze) escalate **on a measured metric, not headcount**. GitLab schedules MV refreshes via cron. Neo4j GDS / TigerGraph precompute-and-store centrality in batch.

**Adversarial corrections incorporated.**
- **CRITICAL — Leiden defaults are a trap:** igraph `community_leiden` defaults to `objective_function='CPM', resolution_parameter=1.0`, which maintainers say "almost guarantees" fragmented/singleton clusters — *worse* than Louvain. Must call `community_leiden(objective_function="modularity", n_iterations=-1)`. (Neo4j GDS Leiden defaults to modularity — which is why "swap the name" works there but breaks in igraph.)
- **Struck the fabricated GraphRAG citation** (arXiv 2602.23372 is "Democratizing GraphRAG," and its 28% figure is CPU-only PPR cost reduction, not "hub pruning reduces query time 16–28%"). Cite edge-capping only from the Microsoft Hairball + Serrano sources.
- **MV CONCURRENTLY costs** more than implied on 2 GB/1 vCPU: slower than plain refresh, more WAL, long transaction **blocks autovacuum → MV bloat**. Budget vacuum tuning; expect Tier 2→3 sooner.
- **Staging-swap RENAME** caveats (lock_timeout + retry; dependent view/grant handling) — see §2.6.
- **SWR/single-flight Gunicorn bug:** background refresh threads started pre-fork die in workers — start them post-fork/lazily. Per-worker caches aren't shared → single-flight only dedupes *within* a worker (N workers = up to N concurrent recomputes); for cross-worker coalescing without Redis, use a Postgres advisory lock or accept the N-fold cost.
- **pg_cron limits:** max ~32 concurrent jobs (each holds a connection); keep the rebuild singular and well under interval (≥ ~3× observed refresh time).

**Side-effects + infra cost.** pg_cron is already on Supabase. MV CONCURRENTLY's extra WAL + autovacuum interaction is the main cost. Staging-swap needs ~2× transient table storage (cheap). igraph CPU is negligible at sub-10k nodes; schedule off-peak. **Topology note:** pg_cron + MV refresh run on **Supabase's managed Postgres, not the droplet** — but **igraph runs in the droplet's Python process** (the real memory-pressure point alongside BGE/rerank), so cap graph size / run off-peak.

**Citations.** [Postgres REFRESH MV (CONCURRENTLY semantics)](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html) · [Citus materialized-views-vs-rollup-tables](https://www.citusdata.com/blog/2018/10/31/materialized-views-vs-rollup-tables/) · [Supabase Cron](https://supabase.com/blog/supabase-cron) · [pg_ivm not on Supabase](https://github.com/orgs/supabase/discussions/16389) · [Traag 2019 Leiden](https://www.nature.com/articles/s41598-019-41695-z) · [igraph CPM-default warning](https://github.com/igraph/rigraph/issues/529) · [Neo4j GDS Leiden = modularity](https://neo4j.com/docs/graph-data-science/current/algorithms/leiden/) · [MS Trimming the Hairball](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/12/TrimmingTheHairball.pdf) · [Serrano 2009 PNAS](https://www.pnas.org/doi/10.1073/pnas.0808904106) · [Democratizing GraphRAG (citation correction)](https://arxiv.org/abs/2602.23372) · [CONCURRENTLY blocks autovacuum](https://www.postgresql.org/message-id/918deb54-9d01-4a9c-abd3-d8412c9e6c80%40gmx.de)

---

### 2.4 Serving / Caching / CDN

**FINAL VERDICT: ADOPT-WITH-MODS. Skeleton correct; the keystone correction is that Cloudflare ignores `Vary` — remove `Vary: Authorization` as a privacy control.**

**Pragmatic header design for our infra:**

| Response | `Cache-Control` | `Vary` | Other |
|---|---|---|---|
| `view=global` | `public, max-age=60, s-maxage=300, stale-while-revalidate=600` | `Accept-Encoding` **only** | drop `Authorization` (client-side), **no `Set-Cookie`**, reject/ignore+log any `user_id` |
| `view=my` | `private, no-store` | — (do not rely on `Vary: Authorization`) | hard-401 on missing auth |

**Cloudflare Cache Rule for the global path:** match → *Eligible for cache*; **Cache Key → Query String → "No query parameters except `view`"**; **Edge TTL → Respect origin**; **Browser TTL → Override → 60 s**; **Serve stale while revalidating → ON**.

**Drop `Authorization` at the *client*, not via a Transform Rule.** Cloudflare bypasses cache when `Authorization` is present *by default*; the clean fix is for the frontend to simply omit the header (and session cookie) on the public-graph `fetch()`. (Note the precise rule: with Origin Cache Control enabled, content *can* still cache with `Authorization` present **if** `public`/`s-maxage`/`must-revalidate` is set — but relying on that is fragile; header-drop is mandatory, not optional.) Avoids the documented "HTTP Request Header Modification → BYPASS" gotcha; verify `cf-cache-status: HIT` with `curl`.

**ETags — weak-compare or skip.** Cloudflare converts strong ETags → weak on recompression; the repo already fixed this (`functional_gates/etag.py::if_none_match`, PR #133, "Cloudflare Weakens ETags"). For `view=global`, `s-maxage` + SWR carry the load — ETags optional. For `no-store` `view=my`, ETags are pointless.

**Web cache deception (elevate).** The 2024 ChatGPT account-takeover was WCD via path-confusion / static-extension. Ensure the global endpoint can't be reached as `…graph.css` / `;.css` and still return cacheable JSON. This is one more reason **sibling paths** (`/api/community-graph` vs `/api/my-graph`) are marginally safer than `?view=` (a reversible simplification worth considering).

**What major corps do.** Stack Overflow: don't cache for logged-in users; cache key = anonymous×mobile×compression (≈ your model; flag the 2019 source as dated). GitHub: user responses `private` + ETag conditional requests (304 doesn't count against rate limit). Google Cloud CDN: with `Authorization`, caches only `public`/`must-revalidate`/`s-maxage` (same RFC rule). Fastly: prefer `private` over `Vary: Authorization`. **Counter-evidence to internalize:** AWS CloudFront and Fastly *do* honor `Vary`/header-keyed caches — so "don't use `Vary`" is **Cloudflare-specific**, not universal; document this so a future CDN migration doesn't inherit a false assumption.

**Adversarial corrections incorporated.**
- **CRITICAL:** remove `Vary: Authorization` from `view=my` (Cloudflare ignores it → can serve a private response to anon requests). Private safety rests on `private, no-store` + the auth-bypass + a Cache Rule keyed on path/host — never `Vary`.
- **Strengthened Set-Cookie warning:** with Origin Cache Control on, Cloudflare does **not** strip `Set-Cookie` — it preserves it and returns BYPASS, silently disabling caching. Public handler must emit zero `Set-Cookie` (or add a Cache Response Rule to strip it).
- **Fix RFC 9111 section numbers** if cited: must-revalidate §5.2.2.2, public §5.2.2.9, s-maxage §5.2.2.10 (the brief's §5.2.2.7/§5.2.2.5 were wrong).
- **SWR on Free is non-uniform** (open report of `REVALIDATED` vs `UPDATING`); verify `cf-cache-status` with `curl` on the actual zone.

**Side-effects + infra cost.** Zero new services. One Cloudflare Cache Rule; frontend header/cookie omission; existing weak-ETag helper.

**Citations.** [Cloudflare cache-control (Vary ignored; Authorization; Origin Cache Control)](https://developers.cloudflare.com/cache/concepts/cache-control/) · [Cloudflare Cache Rules settings](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/) · [Cloudflare ETag strong→weak](https://developers.cloudflare.com/cache/reference/etag-headers/) · [Cloudflare default cache behavior (no HTML/JSON)](https://developers.cloudflare.com/cache/about/default-cache-behavior) · [Cloudflare Set-Cookie → BYPASS](https://developers.cloudflare.com/cache/troubleshooting/dynamic-content-and-login-issues/) · [RFC 9111 §3.5](https://www.rfc-editor.org/rfc/rfc9111.html) · [Nick Craver SO caching (2019, dated)](https://nickcraver.com/blog/2019/08/06/stack-overflow-how-we-do-app-caching/) · [Google Cloud CDN caching](https://docs.cloud.google.com/cdn/docs/caching) · [Fastly Vary best practices](https://www.fastly.com/blog/best-practices-using-vary-header) · [AWS CloudFront header caching (counter-evidence)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/header-caching.html) · [PortSwigger Gotta cache 'em all (WCD)](https://portswigger.net/research/gotta-cache-em-all)

---

### 2.5 Revocation / Erasure

**FINAL VERDICT: ADOPT-WITH-MODS. Active invalidation + TTL backstop; wire a Cloudflare purge on unpublish; treat community nodes as identifiable personal data (erase, don't hide); no Redis.**

**Two-tier SLA.**
- **Unpublish (UX):** gone from the community graph + caches in **≤60 s typical, ≤5 min worst case**.
- **Erasure (legal, if GDPR applies):** legally **≤1 month**, engineered to **minutes** via the same cascade + an on-demand precompute rebuild. Backups handled via ICO "put beyond use."

**Cross-worker cache bust (cheapest correct).** Use a **generation/version-counter** row `kg.community_cache_version` + a 60–120 s TTL fallback (mandatory backstop). On any publish/unpublish/delete: `UPDATE … version = version + 1`. The version-counter beats per-key invalidation because the community graph is a *single aggregate object* and "unpublish one node ⇒ edges vanish" can't be expressed per-key.

- **Now:** `LISTEN/NOTIFY` to push the version bump is fine at current write volume.
- **At scale (the 10k+ mandate):** **`NOTIFY` does not scale** — it takes a database-wide `AccessExclusiveLock` serializing the commit phase of every NOTIFY-issuing transaction (fix only lands in PG 19, GA ~Sept 2026). The **rework-free escape hatch**: have workers **poll the version int row** once per TTL window (one tiny indexed read), which also avoids pinning a 24/7 listener connection and is PgBouncer-transaction-pool compatible (`LISTEN` is not). **No Redis** — unjustified RAM/ops on the 2 GB droplet.

**CDN purge (design correction).** Cloudflare made **all purge methods free for all plans on 2025-04-01** — the design's "short max-age only" can be upgraded. On unpublish/delete, fire a **best-effort async purge-by-URL** (Free limit is generous — **800 URLs/second**, not the brief's "1,000/min"; P50 ≈ 234 ms). Keep `s-maxage` + SWR as the passive backstop so correctness holds even if a purge call fails. Tag-purge's Free limit is tight (5/min, burst 25) — only reach for it if you later cache many per-cluster URLs.

**Erasure semantics (treat nodes as identifiable).** Community nodes carry `display_name` + source URL → **identifiable personal data**; erasure must **remove**, not hide. The live-query Tier-1 design is GDPR-safest (aggregate derived on read; flip flag ⇒ next rebuild drops it). Precompute tiers are a *second copy* needing an explicit erasure path: on an erasure request, **trigger an immediate out-of-band rebuild** rather than waiting for pg_cron. Keep an **append-only erasure/unpublish audit log**. **Tombstone caution:** a retained-but-flagged identifiable row is **not** GDPR-erased — use tombstones to *trigger* removal, not as the end-state. Anonymize-instead-of-delete is **not** available unless you strip attribution to the "all means reasonably likely" identifiability bar.

**What major corps do.** Meta (TAO) uses **active invalidation, not TTL** (TTL-only is "out of scope"), hitting 10 nines within a 5-min settling window via per-entry version fields — exactly the "event-bounded staleness + TTL safety net" pattern. Google Cloud CDN / Varnish bypass on `Authorization` (Cloudflare does **not** by default — the project's actual CDN is the exception, reinforcing §2.4).

**Adversarial corrections incorporated.**
- **Re-anchor legal citations:** replace 2012-era ICO citation with the **current ICO right-to-erasure page** (note: under review post Data (Use and Access) Act 2025); add **EDPB CEF 2025 erasure report (Feb 2026)** and **CJEU C-413/23 P EDPS v SRB (Sept 2025)** as live authorities for "aggregation ≠ anonymisation" and the relative-identifiability test.
- **Re-frame `LISTEN/NOTIFY`** as fine-now / not-scale-proof (global commit lock) with the polling escape hatch.
- **Fix the purge-by-URL number** (800/s, not 1,000/min).
- **Staging-swap `AccessExclusiveLock`** + re-apply grants/view after every rebuild (see §2.6).

**Side-effects + infra cost.** One version row; 2 extra listener connections now (or polling later); async best-effort purge calls. No new services.

**Citations.** [Recall.ai LISTEN/NOTIFY doesn't scale](https://www.recall.ai/blog/postgres-listen-notify-does-not-scale) · [Postgres NOTIFY docs](https://www.postgresql.org/docs/current/sql-notify.html) · [Meta cache made consistent](https://engineering.fb.com/2022/06/08/core-infra/cache-made-consistent/) · [Cloudflare instant-purge-for-all (2025)](https://blog.cloudflare.com/instant-purge-for-all/) · [Cloudflare purge availability/limits](https://developers.cloudflare.com/cache/how-to/purge-cache/) · [ICO right to erasure (current)](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/) · [EDPB CEF 2025 erasure report](https://www.edpb.europa.eu/system/files/2026-02/edpb_cef-report_2025_right-to-erasure_en.pdf) · [GDPR Recital 26](https://gdpr-info.eu/recitals/no-26/) · [Cache stampede prevention](https://oneuptime.com/blog/post/2026-01-30-cache-stampede-prevention/view)

---

### 2.6 Moderation / UX (+ the shared staging-swap mechanics)

**FINAL VERDICT: ADOPT (reactive T&S, Are.na model). Strategic recommendations all upheld; corrections are engineering-precision (fail-closed DB gate, wire cache purge, bound the lock, drop Perspective-at-scale).**

**Pragmatic launch posture for our infra.** Reactive, not proactive — copy Are.na (no proactive monitoring, remove on report/discovery, zero-tolerance CSAM). **Build ONE pipeline** that satisfies both EU DSA notice-and-action *and* DMCA: a "Report" control on every public node → `content_reports` table (DSA-shaped fields: reason, URL, good-faith statement) → internal review list → **single "unpublish node" admin lever** (same lever for spam, illegal content, DMCA) → acknowledgement + statement-of-reasons email.

**Publish UX (CONFIRMED).** Per-item toggle, default OFF + **first-publish consent modal** (names: public, attributed to your `display_name`, others can view, you can unpublish) + **undo toast** thereafter (NN/G: friction for first serious action, undo over repeated confirms). Persistent per-node "Public" badge in **teal** (amber is reserved for `/knowledge-graph` per repo UI rules). Top-level **Personal / Community** segmented control mapping to `view=my` / `view=global`.

**Discoverability (CONFIRMED).** Anti-algorithm by design (Are.na): **chronological "Recently published" + human-curated featured + scoped search** over the published-only / no-`user_id` surface. "Trending" = a simple explainable `COUNT(...) GROUP BY tag` over published rows (trivial SQL), never engagement-ranking (dodges gaming/brigading). Cluster/topic entry points ride the existing Leiden clustering. **No new services.**

**License (CONFIRMED).** "User retains ownership + grants a non-exclusive, worldwide, royalty-free operating/display license" (Are.na/GitHub model). **Reject CC BY-SA** at launch — applying share-alike to AI-summaries of third-party URLs over-commits and is legally murky. AUP = trimmed GitHub category list. Register a **DMCA Designated Agent (~$6 e-filing**, renew every 3 years).

**Rate limits.** Cap the publish-to-community toggle **per-user** (ride existing pricing entitlements) + **Cloudflare edge rate-limit** for coarse IP abuse. Track abuse by **account, not IP**. New-account first-publish hold (one cheap rule).

**Legal scope precision.** DSA notice-and-action (Art. 16) + statement-of-reasons (Art. 17) bind **all** hosting services including micro/small; only the *online-platform-specific* obligations (Arts. 20–28) are exempted for micro/small. Nuance: you must **give** the user a statement of reasons (Art. 17) but need **not** upload it to the EU Transparency DB (Art. 24(5) exempt) — don't over-build.

**Shared storage mechanics — staging-swap (corrections that also serve §2.3/§2.4/§2.5).** When/if you adopt the staging-swap: `ALTER TABLE … RENAME` takes `AccessExclusiveLock`, queues behind in-flight reads, then **blocks all subsequent reads** (lock-queue stall on 1 vCPU). Mitigations are **mandatory**: `SET lock_timeout` (~2 s) + retry; both renames in one transaction; **prefer a stable view name + `CREATE OR REPLACE VIEW` repoint** over renaming the queried relation; and **re-apply `REVOKE SELECT FROM anon, authenticated` + re-bind the `security_invoker` view after every rebuild** (renames/swaps don't follow dependents — otherwise the privacy gate silently reopens).

**Adversarial corrections incorporated.**
- **Privacy/serving (most important):** do not leave the app-layer filter as the sole/primary gate — serve global through a **non-`BYPASSRLS` role** / pre-baked `community_*` table with SELECT revoked, so a missing filter **fails closed** (consistent with §2.2).
- **Perspective API is dead as a scale path** (Google stopped accepting quota increases after Feb 2026; ~1 QPS default) — use it only as a dev/triage toy; **OpenAI Moderation** (free) is the deferred production classifier, but it's a **synchronous external call on the publish hot path** that must **fail-open to the human queue**, never block publish.
- **Classifiers are weak** (no major tool >~50% on adversarial/implicit content) — triage signal only, never sole auto-remover. The "85/15 auto/human" figure is one vendor anecdote; the DSA Transparency DB real spread is ~60.7% fully / 31.5% partial / 7.7% none.
- **Cloudflare purge is sub-second**, not a takedown-SLA threat — the real risk is *forgetting* to purge; **wire unpublish → purge** (consistent with §2.5).
- `community_multilevel()` is **undirected-only** (fine for tag co-occurrence) — and superseded by Leiden anyway (§2.3).
- **Are.na sourcing:** "no ads / aligned incentives" is Are.na's own claim; "no algorithm / chronological Explore" is third-party characterization — attribute accordingly.

**Side-effects + infra cost.** `content_reports` table + admin unpublish action + report form/emails. Optional later: free classifier triage (external API dependency). ToS/AUP/Privacy/DMCA are docs + a $6 filing. No new services.

**Citations.** [Are.na ToS](https://www.are.na/terms) · [Are.na About (no-ads claim)](https://www.are.na/about) · [GitHub AUP](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies) · [GitHub licensing a repository](https://docs.github.com/articles/licensing-a-repository) · [NN/G confirmation dialogs](https://www.nngroup.com/articles/confirmation-dialog/) · [U.S. Copyright Office §512](https://www.copyright.gov/512/) · [Copyright Office $6 DMCA agent](https://www.proskauer.com/alert/copyright-office-establishes-new-electronic-dmca-agent-registration) · [DSA Art. 16](https://www.eu-digital-services-act.com/Digital_Services_Act_Article_16.html) · [DSA Art. 19 micro/small exemption](https://www.cms-digitallaws.com/en/dsa/article-19/) · [Perspective API limits (quota dead)](https://developers.perspectiveapi.com/s/about-the-api-limits-and-errors) · [OpenAI Moderation](https://platform.openai.com/docs/guides/moderation) · [Haize: moderation APIs are weak](https://blog.haizelabs.com/posts/content-moderation-apis-are-bad/) · [DSA Transparency DB analysis](https://arxiv.org/pdf/2312.04431) · [Stack Overflow CC BY-SA](https://stackoverflow.blog/cc-by-sa/) · [xata lock-queue / RENAME](https://xata.io/blog/migrations-and-exclusive-locks)

---

## 3. Cross-Check vs the Current Proposed Design

| # | Design decision | Verdict | Reason (from research) |
|---|---|---|---|
| D1 | `is_published` on `workspace_zettels` (per-user overlay), default OFF — NOT on deduped `canonical_zettels` | **CONFIRMED** | A flag on the canonical row lets User A's consent control User B on URL collision (over-share). Per-(user,canonical) is the granular, per-data-subject unit. *Strongest decision in the design.* |
| D2 | Explicit named publish; author `display_name` shown; consented attribution; default private | **CONFIRMED** | Matches Obsidian/Are.na/GitHub pseudonymous-attribution norm; satisfies "informed + unambiguous." |
| D3 | App-layer `WHERE is_published = true` is the PRIMARY gate | **CONFIRMED** | Correct *because* `service_role` bypasses RLS — the query predicate is necessarily primary. |
| D4 | RLS + `security_invoker` view as SECONDARY defense-in-depth | **MODIFY** | **Inert on the `service_role`/`BYPASSRLS` path** — provides zero runtime defense there. Make it real by routing `view=global` through a **non-`BYPASSRLS`, SELECT-only role**; then RLS/`security_invoker` actually execute and a missing filter fails closed. |
| D5 | `view=global` never takes a caller `user_id`; strip `user_id` from payload | **CONFIRMED** (enforce in code) | Textbook OWASP BOLA: no object reference to break. Add a guard that *rejects/ignores+logs* any `user_id` on the global path. |
| D6 | `view=global` → `Cache-Control: public` + Cloudflare Cache Rules (query-aware) + drop `Authorization` | **CONFIRMED** | Cloudflare bypasses on `Authorization`; dropping it (client-side) is the clean path to cache hits. Add `Vary: Accept-Encoding` and **no `Set-Cookie`**. |
| D7 | `view=my` → private, no-store, **`Vary: Authorization`**, hard-401 | **MODIFY** | `private, no-store` + hard-401 are correct. **Drop `Vary: Authorization`** — Cloudflare ignores all `Vary` except `Accept-Encoding`; relying on it risks serving a private response to anon requests. |
| D8 | Storage Tier 1: live `SELECT … WHERE is_published` + 5-min in-process cache | **MODIFY** | Right direction, but make it **stale-while-revalidate + single-flight** (plain 5-min TTL → stampede cliff on 1 vCPU) and start the refresh **post-fork** (Gunicorn pre-fork thread bug); per-worker caches aren't shared — add a version-counter for coherency. |
| D9 | Storage at scale: precomputed `kg.community_nodes/edges`, no `user_id`, SELECT revoked from anon/authenticated | **CONFIRMED** | Correct structural enforcement of the no-PII published surface. |
| D10 | Rebuild via **staging-table swap (build → ALTER RENAME)**, NOT DELETE+INSERT, NOT pg_ivm | **MODIFY** | DELETE+INSERT rejection ✔; pg_ivm rejection ✔ (not on Supabase). **But insert MV CONCURRENTLY as Tier 2** (the "empty-graph window" objection to it is factually wrong) — it's less code for identical semantics. If staging-swap is used (Tier 3), `ALTER RENAME` takes `AccessExclusiveLock` and stalls reads → **mandate `lock_timeout`+retry, one-txn, re-apply grants + re-point view**. |
| D11 | Clustering via igraph **`community_multilevel()`** (Louvain) | **MODIFY** | Use **Leiden** (`community_leiden`) — Louvain leaves up to 16% of clusters disconnected (visible UX bug). **Critical:** Leiden in igraph defaults to CPM/res=1.0 (fragmented) — **must pass `objective_function="modularity", n_iterations=-1`**. Run **out-of-DB** in the Python batch (pg_cron can't call igraph). |
| D12 | (Implied) shared-tag co-occurrence edges | **MODIFY/ADD** | Naive all-pairs is combinatorial. Add **per-node top-K + tag-frequency ceiling**; **avoid a single global weight threshold**; disparity filter as upgrade. |
| D13 | CDN revocation = (implied) short max-age | **MODIFY** | Cloudflare purge is **free for all plans since 2025-04-01** — add a best-effort async **purge-by-URL on unpublish** (sub-second) on top of `s-maxage` + SWR. |

---

## 4. Gaps — What a Complete Solution Still Needs (omitted by the current design)

1. **Consent audit record** — append-only `publish_consent_events` (actor, action, consent_version, attribution_mode, timestamp). Art. 7(1) demonstrability. *Biggest consent gap.* (§2.1)
2. **Least-privilege public-read DB role** — non-`BYPASSRLS`, SELECT-only, scoped to the published surface, so a forgotten filter fails closed. *Biggest privacy gap.* (§2.2) — surface as an explicit decision per repo guardrails.
3. **Forced-predicate repository wrapper** — single code path that always applies the published filter. (§2.2)
4. **Published↔unpublished edge invariant** — both endpoints must be published; tested at API + DB. Closes the structural-leak vector consent doesn't cover. (§2.2)
5. **Moderation pipeline** — report button → `content_reports` → review queue → single unpublish lever + acknowledgement/statement-of-reasons emails. Legally load-bearing (DSA Art. 16/17 bind even micro/small). (§2.6)
6. **Legal docs** — ToS (license grant + AUP + repeat-infringer + "remove anything" reservation) + Privacy Policy + **DMCA Designated Agent (~$6)**. (§2.6)
7. **Per-user publish rate limit** (ride pricing entitlements) + Cloudflare edge limit + new-account first-publish hold. Account-not-IP. (§2.6)
8. **Erasure path for precompute tiers** — on-demand out-of-band rebuild + append-only erasure audit log; tombstone ⇒ actual removal, not end-state. (§2.5)
9. **Cross-worker cache coherency** — version-counter row + TTL backstop; poll at scale (not `LISTEN/NOTIFY`). (§2.5)
10. **N≥5 cell suppression** for any non-consensual public aggregate (esp. per-URL "published by N users"). (§2.2)
11. **Cloudflare hardening** — no `Set-Cookie` on global; WCD path-confusion guard (no cacheable JSON via `.css`/`;.css` suffix); `curl`-verify `cf-cache-status` and SWR behavior on the Free plan. (§2.4)
12. **Regression test** asserting `view=global` can never return `is_published=false` rows under `service_role`/`BYPASSRLS`, wired as a CI deploy gate. (§2.1/§2.2)

---

## 5. Phasing — Pragmatic Build Order (scale-proof, not over-built for 15 users)

**Phase 0 — Schema + consent foundation (ship first).**
`is_published` on `workspace_zettels` (default OFF) · `publish_consent_events` audit table · the **least-privilege public-read role + grants** · forced-predicate repository method · the `view=global` regression test (CI gate). *Rationale: the privacy/consent floor must exist before anything is publishable; the role + wrapper are cheap and make every later feature fail-closed.*

**Phase 1 — Serving + minimal publish UX (MVP public graph).**
Live `SELECT … WHERE is_published` + **stale-while-revalidate + single-flight** (post-fork init) · `view=global` (`public, s-maxage`, `Vary: Accept-Encoding`, no `Set-Cookie`, drop `Authorization` client-side) + `view=my` (`private, no-store`, hard-401) · Cloudflare Cache Rule (key = path/`view` only; SWR on) · per-item publish toggle (default OFF) + first-publish consent modal + undo toast + teal "Public" badge · Personal/Community view switch. *Rationale: end-to-end public graph with correct caching and consent at near-zero infra; defer all precompute.*

**Phase 2 — Moderation + legal (gate before meaningful public exposure).**
Report button → `content_reports` → review list → single unpublish lever (+ ack/statement-of-reasons emails) · ToS + AUP + Privacy Policy + DMCA agent · per-user publish rate limit + Cloudflare edge limit + new-account first-publish hold · **wire unpublish → Cloudflare purge-by-URL** + version-counter cache bust. *Rationale: legally load-bearing the moment strangers can see/contribute; the report→unpublish pipeline is the whole launch moderation surface.*

**Phase 3 — Clustering + discovery (quality layer).**
Out-of-DB Python batch (scheduled): igraph **Leiden (`objective_function="modularity"`) + PageRank**, one graph load, write `cluster_id`/`pagerank` back · **per-node top-K + tag-frequency ceiling** edge capping · discovery = chronological "Recently published" + human-curated featured + scoped search + cluster entry points. *Rationale: makes the graph usable/explorable; still runs against the live published surface — no precompute tables yet.*

**Phase 4 — Precompute tier, on MEASURED triggers only (defer until metrics demand).**
**Tier 2 first: MV refreshed CONCURRENTLY** via pg_cron (UNIQUE index; interval ≥ ~3× refresh; watch WAL + autovacuum bloat). Only graduate to **Tier 3 staging-swap / rollup** when CONCURRENTLY's cost or incremental-compute need forces it — and then with `lock_timeout`+retry, one-txn swap, re-applied grants + re-pointed view. Switch trigger = uncached p95 / cron-duration-vs-interval / WAL share, **never user count**. *Rationale: avoids writing/testing custom swap machinery until a real metric (not headcount) hits a wall — the explicit "don't over-build for 15 users" guard.*

**Explicitly deferred (each a standalone decision when triggered):** free classifier triage queue (OpenAI Moderation, fail-open) · shadow-ban for confirmed spammers · trusted-flagger weighting + DSA complaint portal (only if you outgrow the micro/small exemption) · anonymous-contribution mode (with the stylometry caveat) · CC-licensed reuse/export (v2). Engagement-ranked "trending": **likely never** (anti-algorithm is a feature and is abuse-resistant).

---

### Residual uncertainties (flagged, not resolved)
- **GDPR applicability** to an India-based, non-EU-targeting, 15-user app is genuinely uncertain (Art. 3(2) targeting test). All GDPR-grade controls above are justified as best-practice + scale-future-proofing regardless; get a real legal read before relying on the "out of scope" position.
- **Cloudflare Free-plan async SWR** behavior is non-uniform per open reports — `curl`-verify on the actual zone before depending on it.
- **MV CONCURRENTLY's** autovacuum/bloat tax on a 2 GB Supabase instance is real but unquantified for this workload — measure at Phase 4 rather than assuming the Tier 2→3 trigger is far off.