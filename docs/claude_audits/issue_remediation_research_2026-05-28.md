# Remediation Research — 6 Production Issues
**Date:** 2026-05-28 · **Stack:** FastAPI / Python 3.12 / DO 2GB-1vCPU / Caddy 2 / Supabase v2 / Gemini · **Method:** 6 parallel websearch subagents, sources weighted 2023–2026

---

## 1. Reddit OAuth missing on droplet → **HIGH**

**Recommended:** Reddit **OAuth2 script-app, password grant** with a dedicated bot account.

| Aspect | Value |
|---|---|
| Tier | Free (≤100 QPM averaged over 10 min) |
| Token TTL | 1 hour bearer; refresh with re-POST to `/api/v1/access_token` |
| Cost | $0 until >100 QPM, then $0.24 / 1k calls (far below cap) |
| Headroom | 100 QPM = 144k calls/day. At 10k users × 5 Reddit URLs/day = 50k calls/day — well within. Bottleneck is Gemini, not Reddit. |

**Setup (copy-paste sequence, all values wrapped in `<private>` when in chat):**
1. Create dedicated Reddit account `zettelkasten-bot`; verify email; wait ~24 h to age the account.
2. `https://www.reddit.com/prefs/apps` → "create another app..." → **script** → name `zettelkasten-ingest` → redirect `http://localhost:8080`.
3. Capture: `client_id` (14-char under app name), `client_secret`, bot `username`, bot `password`.
4. Append to `/etc/secrets/api_env` on droplet (already mounted both colors): `REDDIT_CLIENT_ID=…`, `REDDIT_CLIENT_SECRET=…`, `REDDIT_USERNAME=…`, `REDDIT_PASSWORD=…`, `REDDIT_USER_AGENT=zettelkasten.in:v1.0 (by /u/<bot>)` (custom UA required — Reddit 429s generic UAs).
5. Restart inactive color, smoke-test one `/r/` URL via `/api/zettels/add`, then `deploy.sh` cutover.
6. Confirm `RedditIngestor` now hits `oauth.reddit.com` (not `www.reddit.com/.json`).

**Side-effects:** RAM ≈ +1–2 MB · latency +200–400 ms once/hour for token refresh · blast radius if leaked = bot can post/vote as itself + exhaust 100 QPM budget (no financial exposure — free tier).

**Don't pursue:** Pushshift (dead post-2023), PullPush (historical-only/unreliable), redlib self-host (markup breaks weekly).

**Sources:** Reddit OAuth2 wiki · PRAW 7.7.1 docs · Reddit pricing 2024-25 · PainOnSocial rate-limits guide 2026.

---

## 2. JWT `InvalidAlgorithmError` silent downgrade → **CRITICAL-leaning HIGH** *(security + UX)*

**Verdict: REJECT with 401, do not silently downgrade.** Silent downgrade-to-anonymous is textbook OWASP API2:2023 anti-pattern — masks attacks, hides misconfig (current symptom), and turns "I am Alice" into "I am no one" without telling Alice. The 3-day-old change must be reverted.

**Root cause hypothesis (high confidence):** Supabase flipped new projects to **asymmetric JWT keys on 2025-05-01** (default RS256, optional ES256/Ed25519). Existing HS256 projects begin issuing asymmetric tokens after operator clicks "Migrate JWT secret" in the dashboard. Our `_decode_token` is almost certainly still pinned to `algorithms=["HS256"]`; a user with a rotated session token signed with ES256/RS256 via JWKS `kid` raises `InvalidAlgorithmError`.

**Config knobs (no code yet):**
| Knob | Value |
|---|---|
| Auth path return | `401 + WWW-Authenticate: Bearer error="invalid_token"` |
| `SUPABASE_JWKS_URL` | `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` |
| `algorithms` allow-list | **Explicit set during migration:** `["ES256","RS256","HS256"]`. Drop HS256 once legacy key revoked. |
| `PyJWKClient` | `cache_keys=True, lifespan=600, max_cached_keys=16` (matches Supabase Edge 10-min cache) |
| Keep `SUPABASE_JWT_SECRET` env | Until dashboard shows "Previously used → Revoked" |
| Log on failure | Include `kid`, `alg`, `iss` — **never** token body |

**Side-effects:** JWKS cold-cache fetch ~50–250 ms (cached 10 min thereafter, ~0 ms) · JWKS rotation handled transparently if `PyJWKClient` re-fetches on unknown `kid` · **blast radius wide** if `algorithms` list misconfigured: too-narrow = mass logout (recoverable in minutes via env), **too-wide combining HS256 + asymmetric with shared key var = CVE-2022-29217 mass auth bypass** — far worse than mass logout.

**Security caveats (mandatory):**
- Never feed a JWKS public key to an HS256 verifier (algorithm-confusion attack).
- Use PyJWT ≥ 2.4.0 (current stable 2.13.0) — fixes CVE-2022-29217.
- Mitigate `PyJWKClient` DoS (GHSA-fhv5-28vv-h8m8) by `max_cached_keys` + `kid` shape sanity check before `get_signing_key_from_jwt`.
- Pin `iss` (`https://<ref>.supabase.co/auth/v1`) **and** `aud` (`authenticated`) — alg is one check of several.

**Sources:** Supabase JWT signing keys docs 2025 · Supabase asymmetric-keys discussion #29289 · OWASP API2:2023 · PyJWT 2.13.0 docs · CVE-2022-29217 · GHSA-fhv5-28vv-h8m8 · Objectgraph migration walkthrough 2025.

---

## 3. Heartbeat `httpx.ConnectError` loop → **LOW-MED** *(log noise; risks masking real signals)*

**Verdict: keep outbound push pattern, fix the target, quiet the logger.** Outbound push is the right pattern for blue/green cutover death detection — an external inbound probe can't distinguish "blue is dead" from "Caddy routed correctly to green".

| Question | Recommendation |
|---|---|
| Provider | **healthchecks.io** (free 20 checks, canonical 2024–26). Cronitor close peer. |
| Direction | Outbound push (current) + inbound `/api/health` external monitor as a complement (not a replacement) — they answer different questions. |
| Loop error handling | **First failure → WARNING; suppress until state changes** (recovery → INFO; every Nth=12 failure → re-WARN). Tiny in-memory counter, no lib. |
| Circuit-break | After K=5 consecutive failures: **back off cadence** 300s → 900s → 1800s capped (with jitter). Don't stop — must auto-resume on target recovery. |
| Cadence + grace | **60 s ping / 300 s grace.** Current 300 s ping is too coarse for cutover-window detection. healthchecks.io default `1d/1h` is for cron, not liveness. |

**Detect the dead target (no URL leak in logs):**
- On boot: do one ping; on failure log WARNING with **hostname only** (no path/UUID) + hint "verify HEARTBEAT_PING_URL".
- Operator-only test: `docker exec <color> curl -v https://hc-ping.com` isolates "egress working" from "URL wrong".
- Never log the full URL — healthchecks.io URLs embed a UUID.

**Side-effects:** ~99% log-volume reduction · CPU <0.01% · RAM ~200 KB (re-use single `httpx.AsyncClient` — do NOT create-per-ping) · false-positive rate drops because grace tolerates 4 missed beats.

**Sources:** healthchecks.io configuring-checks docs · Better Stack 2026 cron-monitor comparison · Squadcast push-vs-pull comparison · OneUptime exp-backoff-with-jitter 2025-01.

---

## 4. KG edge_drop 26% → **HIGH** *(silent data quality loss; user-visible on `/knowledge-graph`)*

**Quick fix (1 day, captures ~80% of dropped edges):**
1. Add **pg_trgm fuzzy match + type filter** as resolution stage 3 (pg_trgm built-in, GIN-indexable, zero extra calls).
2. Change silent **drop → NIL placeholder node** (`type='unresolved'`, edge preserved, `needs_review=true`). Zero recall lost. Backfillable later when more evidence arrives.
3. Log every NIL promotion → operator dashboard. Replaces "silent drop" with observable backlog.

**Industry consensus (ReFinED, BLINK, NASTyLinker, Senzing 2024–25): never silently drop.** Either NIL-promote or queue.

**Full resolution chain (for principled 1–2 week fix):**
| Stage | Method | Cost | Catches |
|---|---|---|---|
| 1 | Exact normalized-string match | ~0 ms | ~40–50% |
| 2 | Alias / synonym lookup (existing) | ~0 ms | brings to current ~74% |
| 3 | **pg_trgm fuzzy + type filter** | 5–20 ms | +10–15% |
| 4 | **pgvector ANN** on title+aliases embedding, cosine ≥ 0.83, top-K=5, type-constrained | 20–50 ms | +5–10% |
| 5 | **LLM verify** (Gemini Flash-Lite, batch ≤10 unresolved/ingest) | 200–400 ms · ~$0.0001/ingest | +3–5% |
| 6 | **NIL placeholder + needs_review** | ~0 ms | guarantees preservation |

**Embedding-fallback params:** `gemini-embedding-001` (768-dim, MRL-truncate to 384) · threshold 0.83 auto-link, 0.75–0.83 → LLM verify, <0.75 → NIL · HNSW `m=16, ef_construction=200` on 384-dim vectors · embed **only titles + aliases** (small corpus, index <200 MB even at 100k nodes).

**Side-effects (2 GB droplet realism):**
- **Zero in-app RAM cost** — pgvector index lives on Supabase Postgres, not droplet. Protects iter-03 BGE int8 budget.
- 5–20 extra embed calls per ingest (free-tier covers; paid ≈ $0.00015/ingest).
- pgvector HNSW p99 ≈ 5–15 ms at 100k nodes (network-bound, not droplet RAM).

**Sources:** ReFinED 2022 · NASTyLinker arXiv 2023 · Senzing ER-Knowledge-Graphs 2024 · Elastic Labs entity-resolution-LLM 2024-25 · MDPI Multi-Agent RAG ER 2025 · Gemini Embedding for RAG 2025 · pgvector IVFFlat vs HNSW (dev.to 2024 + AWS Database Blog 2024).

---

## 5. Bug X — `candidate_api_env_paths` misses `.claude/worktrees/` → **LOW** *(dev ergonomics; zero prod impact)*

**Recommended fix: hybrid — pathlib-first parse of the worktree's `.git` file, subprocess fallback.**

**Why:** `.git` inside a linked worktree already encodes the path back to the main checkout (single-line text: `gitdir: <path>/.git/worktrees/<name>`). Pure pathlib parse handles every convention because git itself wrote the pointer. Subprocess fallback (`git -C <start> rev-parse --git-common-dir`) is canonical but costs ~10–40 ms and adds a hard `git` binary dep — keep as labelled fallback only.

**Logic (described in words, not code):**
1. Walk `Path(__file__).parents` looking for `.git` directory (main checkout — done) or `.git` file (linked worktree).
2. If `.git` is a file, read its single line. Strip `gitdir:` prefix, resolve relative to file parent, then `.parent.parent.parent` (strips `worktrees/<name>/` and `.git/`). That's the main checkout root.
3. On failure (malformed / bare repo / submodule edge), `git rev-parse --git-common-dir`. Cache via `@lru_cache`.
4. Look for `api_env` at `<main>/api_env`, then `<main>/.env`, then `/etc/secrets/api_env`, then `GEMINI_API_KEYS` env var. **First hit wins.**

**Worktree layouts handled defensively:**
| Layout | Mechanism |
|---|---|
| `<repo>/.worktrees/<name>` (traditional) | `.git` file parse |
| `<repo>/.claude/worktrees/<name>` (Claude Code default 2025) | `.git` file parse |
| Sibling `../<repo>-<feature>/` | `.git` file parse |
| Custom hook paths | `.git` file parse |
| JetBrains / VS Code multi-root | N/A (not git constructs) |
| Codespaces / devcontainers | Single checkout — step 1 returns |
| Bare repo / submodule | Subprocess fallback |

**Side-effects:** zero subprocess on happy path · ~10–40 ms once on fallback (cached) · `GEMINI_API_KEYS` env-var override is highest precedence → CI/prod skip filesystem walk entirely (matches 12-factor).

**Note:** [obra/superpowers #521](https://github.com/obra/superpowers/issues/521) (2025) — Claude Code env-file propagation into worktrees is an actively-tracked ecosystem pain point. Our `api_env` copy workaround tracks the broader trend.

**Sources:** git-rev-parse `--git-common-dir` docs · git-worktree docs · Claude Code worktrees docs 2025 · MindStudio worktree pattern 2025 · 12-Factor Config · Computing Arts env-vars-12factor 2026.

---

## 6. Bug Y — topup script `workspace_zettel_id` always null → **LOW** *(eval pipeline observability gap)*

**Recommended:** **Import the pipeline's response Pydantic model** and call `Model.model_validate(result)` inside `try/except ValidationError`. On success, attribute-access the field. On failure, log full `ValidationError.errors()` (paths + actual shape) and mark eval row `extraction_failed=true`.

| Concern | Recommendation |
|---|---|
| Coupling | **Tight (import the model).** Same-repo callers should accept tight coupling — duck-typed extractors are for cross-service consumers. Pydantic v2 `ValidationError` gives structured all-fields-at-once diagnostics a `dict.get` ladder cannot. |
| Failure mode | **Fail loud.** Eval/diagnostic scripts must never silently no-op on shape drift — exactly what produced 39 null reports. Raise (or at minimum log ERROR with stack + record id + actual keys) and increment `extraction_failure_count`. |
| Verify hard-fail | When `workspace_zettel_id is None` and upstream run **was** marked succeeded, hard-fail the verify step (not silently no-op). |
| Contract guard | Add tiny pytest contract test in `tests/contract/` calling `run_add_zettel_pipeline` against recorded fixture, asserting response model parses + extractor returns non-None id. Run in CI so next refactor breaks the test, not the eval. |

**Side-effects:** trivial import-time coupling (same repo) · runtime ~µs at <1k eval scale · false-confidence risk currently HIGH and is exactly the bug — switching to model-based extraction eliminates the class.

**Sources:** Pydantic V2 validation-errors docs · index.dev "avoid silent failures" 2024 · swenotes tight-coupling guide 2025-09 · totalshiftleft schema-first contract testing 2026 · intellinotebook contract-testing-with-pytest.

---

## Cross-cutting observations

1. **The Supabase 2025-05-01 JWT key migration is the most likely root cause of Issue #2**, not random InvalidAlgorithmError noise. This should be the #1 production fix — touches security, data trust, and matches a known external timeline.
2. **Bug X is an ecosystem-wide pain point** (open superpowers issue #521). Our pragmatic copy-`api_env` workaround mirrors what other Claude Code users are doing.
3. **All 6 recommendations preserve the protected-knobs list** (GUNICORN_WORKERS=2, --preload, FP32_VERIFY_ENABLED, GUNICORN_TIMEOUT, rerank semaphore, SSE heartbeat, Caddy transport timeouts, schema-drift gate, kg_users allowlist, Kasten teal/amber surfaces). No protected knob is touched by any of the proposed fixes.
4. **Zero added in-app RAM cost** across all 6 fixes combined. Closest is heartbeat httpx.AsyncClient at ~200 KB (already exists). KG embeddings live on Supabase Postgres, not the droplet.

## Priority ordering for fix execution

| Rank | Issue | Why first |
|---|---|---|
| **P0** | JWT (#2) | Security + UX + likely affecting real users right now via Supabase rotation |
| **P1** | Reddit OAuth (#1) | Affects all Reddit ingests; long-standing; trivial setup |
| **P2** | KG edge_drop (#4) — quick fix only (pg_trgm + NIL) | Silent data loss on user-visible graph; principled fix is later iter |
| **P3** | Heartbeat (#3) | Log noise masks future triage |
| **P4** | Bug X (#5) | Dev ergonomics |
| **P5** | Bug Y (#6) | Eval observability |
