# GitHub manifest-fetch — single-call research & A/B verdict (2026-06-09)

**Context.** The summarization-quality build plan's GitHub interface-verification fix (Sol 3 — "interface evidence-ladder") proposed **+2–3 REST calls** per GitHub *repo* zettel to read manifest files (`package.json`, `pyproject.toml`, `setup.cfg`, `Cargo.toml`, `openapi.json`/`openapi.yaml`) and ground CLI/API interface claims, replacing the README-regex must-preserve injection that is the fabrication source. Operator asked: **can all the GitHub-specific reads be ONE API call instead, and which of two finalist mechanisms is best?**

Research method: two parallel web-research subagents (industry-standard/recency; risk/infra/security/scale), recency-weighted (<5 yr), no fabricated numbers, every non-obvious claim cited; cross-checked against this repo's ingestor code. *(The canonical deep-research workflow harness errored on its first StructuredOutput agent; substituted general-purpose research agents.)*

---

## The two finalist solutions — what each does

### Option A — one GraphQL call (`+ token`)
One `POST https://api.github.com/graphql` with aliased blob nodes:
```graphql
{ repository(owner:"o", name:"r") {
    readme:        object(expression:"HEAD:README.md")      { ...on Blob { text byteSize isTruncated } }
    pkg_json:      object(expression:"HEAD:package.json")    { ...on Blob { text isTruncated } }
    pyproject:     object(expression:"HEAD:pyproject.toml")  { ...on Blob { text isTruncated } }
    setup_cfg:     object(expression:"HEAD:setup.cfg")       { ...on Blob { text isTruncated } }
    cargo:         object(expression:"HEAD:Cargo.toml")      { ...on Blob { text isTruncated } }
    openapi_json:  object(expression:"HEAD:openapi.json")    { ...on Blob { text isTruncated } }
    openapi_yaml:  object(expression:"HEAD:openapi.yaml")    { ...on Blob { text isTruncated } } } }
```
- Fetches README + every manifest candidate in **one request**; absent path → that alias is `null`, query stays HTTP 200; binary → `text:null`; large → `isTruncated:true` → REST-raw fallback.
- Cost = **1 rate-limit point** (the official cost formula counts only *connections* = `first`/`last` fields; aliased `object()` reads have none, so it floors at the documented 1-point minimum).
- **Requires a token even for public repos** — GraphQL has no anonymous tier (401 without a token).

### Option B — REST piggyback (no *new* mechanism)
Reuse the root `/contents` directory listing the ingestor **already fetches** to learn which manifests exist at root, then read only those via the existing per-file Contents helper.
- `+1–2` calls per repo (only files that exist; no wasted 404 probes), all under the 1 MB Contents content cap (manifests are tiny).
- Zero new request mechanism, zero new Python dependency — reuses code already in `ingest.py`.

---

## Decisive reframing — the token is needed ANYWAY (orthogonal to A vs B)

This is the single most important finding, and it is a **pre-existing production risk independent of this feature**:

- GitHub REST rate limits (live docs, verbatim): **unauthenticated = 60 requests/hour, per originating IP**; **authenticated = 5,000/hour**. [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- Our ingestor makes **~6–10 REST calls per repo ingest** (repo metadata, readme, languages, issues, commits, root `/contents` listing, per-doc fetches, `fetch_all_signals`), from **one droplet IP**, and **`GITHUB_TOKEN` is absent from `ops/.env.example`** → it is almost certainly running **anonymously today**.
- Anonymous capacity ≈ **6–10 repo ingests per hour total, shared across all users** from that IP. Adding manifest reads (either option) shrinks it further. The 10k-user target is categorically impossible at 60/hr.
- GitHub explicitly nudged authentication for reliability in its 2025-05-08 changelog (*"use authentication for enhanced consistency and reliability"*; the new anonymous number was **not** published — docs still say 60/hr, treated as current). [changelog](https://github.blog/changelog/2025-05-08-updated-rate-limits-for-unauthenticated-requests/)
- GraphQL (Option A) has **no anonymous access** at all → 401 without a token. [GraphQL rate limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)

**⇒ A token is effectively mandatory regardless of A/B.** The lowest-blast-radius credential: a **fine-grained PAT with zero permissions / public-repo read** — it reads public `/contents` without any Contents permission, gets the full 5,000/hr authenticated quota, expires (1–366 days; cannot be non-expiring), and is auto-revoked by secret-scanning if leaked. Storage adds **zero** new infra (repo already mounts secrets at `/etc/secrets/api_env` and via `--env-file`). [fine-grained PAT public read](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens), [introducing FG-PATs](https://github.blog/security/application-security/introducing-fine-grained-personal-access-tokens-for-github/)

Once the token is accepted as a given, **Option A's "requires a token" downside disappears — but so does its main differentiator over a *token-authenticated* Option B.**

---

## Comparison (assuming a token is provisioned either way)

| Axis | Option A — GraphQL | Option B — REST piggyback |
|---|---|---|
| Round-trips / ingest for manifests | **1** | N+1 (root listing already fetched + 1 per present manifest; +1–2 typical) |
| Rate-limit points / ingest | ~1 (separate GraphQL bucket) | ≤ ~12 total (REST bucket) — far under 5,000/hr |
| New code / dependency | New GraphQL query + `...on Blob` + `errors[]` parsing | **None** — reuses `/contents` listing + existing helper |
| Failure granularity | **All-or-nothing** per repo | **Per-file** — skip one manifest, still ship summary |
| Token lapses | **Hard 401, feature fully dark** (no fallback) | Degrades to anon 60/hr; manifest read silently skipped |
| Rate-limit signaling | Primary breach = HTTP **200 + `errors[]`** (breaks generic retry) | Standard **403/429 + `Retry-After` + `x-ratelimit-*`** |
| Maintenance | Hand-maintained query under GitHub's **quarterly breaking-change** cadence (≥3 mo notice) | `/contents` is the most stable, ubiquitous endpoint |
| Nesting (`openapi.*`, Cargo workspaces) | Needs exact paths (can't glob) | Root listing misses nested; same limitation |
| Droplet CPU/RAM | Negligible | Negligible |

The only axis where A wins is round-trips/points-per-ingest — **negligible at our volume** (manifest reads are a rounding error against the ~10 calls/ingest we already make, and 5,000/hr ≈ 500 ingests/hr of headroom). Every reliability/maintenance/failure axis favors B.

---

## Industry precedent (recency-weighted)

- **Backstage** (CNCF) reads known files from arbitrary repos using **Option A's exact** `object(expression:"HEAD:…") { ...on Blob { text } }` pattern as its default — **but authenticates by design** (GitHub App). The token requirement is a non-issue *for it*; that's the hinge. Strongest apples-to-apples precedent, and it favors A only because Backstage already authenticates. (Project source, current.)
- **Renovate / Dependabot** *clone* repos (they need the whole tree and write PRs back) — wrong tool for "read 3 known files." Both run **mixed** REST+GraphQL integrations.
- **GitHub official:** *"You don't need to exclusively use one API over the other,"* and a Dec-2025 accepted community answer describes exactly the REST-metadata + GraphQL-batch split. Mixing REST+GraphQL is **endorsed, not an anti-pattern**. [REST vs GraphQL](https://docs.github.com/en/rest/about-the-rest-api/comparing-githubs-rest-api-and-graphql-api), [community #182555](https://github.com/orgs/community/discussions/182555)
- **Modern default is nuanced:** GraphQL batching when minimizing round-trips *and a token is in hand*; REST per-file remains the blessed pragmatic choice at low volume.

---

## Code grounding (this repo — verified)

- `source_ingest/github/ingest.py:68-70` — token-ready: sets `Authorization: Bearer {token}` when `_github_token(config)` resolves (`GITHUB_TOKEN` env, then `gh auth token`).
- `ingest.py:471-475` — **already fetches the root `/contents` listing** → Option B's "reuse" premise is verified, not hypothetical.
- `ingest.py:479-484` — already builds a `lower→actual` map of top-level filenames (manifest presence is detectable for free).
- `ingest.py:527-553` — `_fetch_file_contents()` helper already exists (Contents API + base64 decode); Option B reuses it directly.
- `summarization_engine/config.yaml:55` — `github_token_env: "GITHUB_TOKEN"`; `:67` `architecture_overview_enabled: true` (a paid-Gemini call already runs per repo).
- `ops/.env.example` — **no `GITHUB_TOKEN`** → droplet anonymous today.
- `ingest.py:86-96` — issue/PR/commit/blob URLs short-circuit before the manifest stage → manifest reads fire **only for repo-type GitHub zettels, forward-only** (answers "all zettels / all future?" → no).

---

## VERDICT

**Option B (REST piggyback on the root `/contents` listing we already fetch) + provision a zero-permission fine-grained `GITHUB_TOKEN` on the droplet.**

Rationale: the token is mandatory for scale and graceful operation *regardless* of the mechanism (the ingestor is already at risk at 60/hr/IP anonymous today). Given the token, Option A's sole advantage — one call vs N+1 — is negligible at our volume, while Option B reuses existing code, fails gracefully per-file, degrades to anonymous rather than going dark if the token lapses, and avoids GraphQL's quarterly breaking-change surface, `errors[]` partial-failure parsing, and HTTP-200-with-error rate-limit signaling. Reserve the GraphQL aliased-blob pattern (and/or a GitHub App) for if/when file-read volume explodes or the service goes multi-tenant — at which point the Backstage-style REST-metadata + GraphQL-batched-blobs split is the textbook upgrade.

**Honest answer to "can it be a single call?"** Technically yes (GraphQL). But "one call" is the wrong optimization target here — "authenticated + graceful + minimal-new-code" is, and that is Option B. The single-call saving is illusory value at our scale.

**Nesting note:** root-level manifests (`package.json` `bin`, `pyproject.toml [project.scripts]`, `setup.cfg` console_scripts, `Cargo.toml [[bin]]`) — the high-value interface signals — are covered free by the listing we already fetch. `openapi.*` is frequently nested and is a weaker signal; treat it as best-effort (an optional single recursive Trees call can resolve nested paths later if needed).

---

## Approval-gated next actions (NOT yet taken)

1. **Provision `GITHUB_TOKEN`** (a 0-permission fine-grained PAT, public-repo read, with expiry) as a droplet secret — a new infra/secret step and operator action. Also fixes the **pre-existing** 60/hr anonymous production risk for the whole GitHub ingestor.
2. **Update the build plan's Wave-2 GitHub phase**: Sol 3 → Option B (`+1–2` calls), gated on the token, instead of the "+2–3 calls" placeholder.

## Citations
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api (60/hr IP vs 5,000/hr auth; secondary limits; 403/429 + Retry-After + x-ratelimit-*)
- https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api (1-point minimum; cost formula counts connections; no anonymous access)
- https://docs.github.com/en/rest/about-the-rest-api/comparing-githubs-rest-api-and-graphql-api ("you don't need to exclusively use one API"; GraphQL replaces multiple REST calls)
- https://docs.github.com/en/graphql/overview/breaking-changes (quarterly breaking-change cadence, ≥3 months notice)
- https://docs.github.com/en/rest/repos/contents (1 MB / 1–100 MB raw / >100 MB unsupported; base64)
- https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens (public resources readable without Contents permission)
- https://github.blog/security/application-security/introducing-fine-grained-personal-access-tokens-for-github/ (prefer FG-PAT; least privilege; expiry)
- https://github.blog/changelog/2025-05-08-updated-rate-limits-for-unauthenticated-requests/ (auth nudge; new anon number unpublished)
- https://github.com/orgs/community/discussions/182555 (Dec-2025: REST for single resources, GraphQL to minimize calls)
- Backstage `plugins/catalog-backend-module-github/src/lib/github.ts` via https://github.com/backstage/backstage (Option-A pattern in production, App-authenticated)
- https://gist.github.com/MichaelCurrin/6777b91e6374cdb5662b64b8249070ea (aliased-blob multi-file recipe; ~1–2 points)
