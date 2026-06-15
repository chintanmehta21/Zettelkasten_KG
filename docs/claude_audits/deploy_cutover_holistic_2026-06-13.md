# Deploy-cutover 502 — holistic solution (deep-research synthesis)

**Date:** 2026-06-13 · **Scope locked by operator:** stay 2 GB (no upsize) · graceful ~30 s 503 acceptable (never raw 502s) · reranker externalization in-scope to *evaluate*.
**Inputs:** deep-research run `wf_35784d9a-74a` (105 agents, 23 sources, 25 claims verified → 18 confirmed / 7 killed) + current-system read + the cascade-reranker migration spec.

---

## Headline verdict

For **this exact box** (single 2 GB / 1 vCPU VM, 1 GB swap, Caddy 2, in-process int8 ONNX reranker that peaks ~+684 MB), the holistic solution is **reliability + graceful window *within the in-process int8 architecture*** — **not** re-externalizing the reranker:

1. **Reliability** — stop trusting `caddy reload`/`/load` exit codes; verify the cutover actually re-bound by reading back the live config (or swap surgically via the admin API). *(PR #145's A — an end-to-end serving probe — is a valid, simpler form of exactly this.)*
2. **Graceful window** — keep the RAM-forced sequential stop-old→start-new, but serve a graceful **503** during it. **The mechanism must be validated empirically** — the research could **not** confirm the file-matcher / `handle_errors` → 503 path for a backend-DOWN case.
3. **Do NOT externalize the reranker** — it reverses the deliberate, approved TEI→int8 migration (below). This is the key correction to the generic research recommendation.

---

## The cross-check that overrides the research's #1 idea

The research recommended externalizing the reranker to a shared TEI/Infinity CPU sidecar so both colors stay light → standard blue/green within 2 GB, and noted "this system previously ran BGE-in-TEI." **It did — and migrated off it on purpose.** Per `docs/superpowers/specs/2026-04-13-cascade-reranker-migration-design.md` (Approved, 2026-04-13):

| Metric | TEI sidecar (old) | In-process int8 (current) |
|---|---|---|
| Total RAM | **2.8 GB** (2048 MB reranker + 768 MB app) | **~1 GB** |
| Deploy latency | ~10 min | ~2 min |
| Rerank latency | ~300 ms (HTTP) | ~40-60 ms (in-process) |
| Containers | 2 + health-chain | 1 |

Re-externalizing re-adds the sidecar's RAM (the win is only that it stops *doubling* during overlap — but sidecar ~0.7-1.1 GB + two slim colors + Caddy + OS still ≈ 2.5-2.9 GB > 2 GB), re-adds ~300 ms latency with sidecar/app contending for the **single** vCPU, and re-adds deploy complexity. **Verdict: not viable on 2 GB; it regresses the exact metrics the migration fixed.** The research's own caveat ("RAM-fit not measured for this box") is answered by our history: it didn't fit — that's why we left.

Corollary: **lazy/deferred model load doesn't enable a safe overlap either** — the +684 MB is the *inference* peak (stage-2 temp tensors), not the load. Two colors both reranking during a drain still OOM. So true two-instance overlap is off the table on 2 GB regardless. The sequential window is inherent.

---

## What the research confirms — and whether it applies here

| Finding (confidence) | Applies to us? | Action | Source |
|---|---|---|---|
| **Caddy intentionally no-ops byte-identical reloads** (logs "config is unchanged" + exit 0, applies nothing); maintainer-confirmed | Partially — we *do* change the snippet, but the lesson "never trust the exit code; verify re-bind" is dead-on | Verify the cutover by reading back the live config / e2e serving probe | [caddy#6948](https://github.com/caddyserver/caddy/issues/6948), [admin API](https://caddyserver.com/docs/api), [caddy#7258](https://github.com/caddyserver/caddy/pull/7258) |
| **Surgical admin-API upstream swap** — `PATCH /id/<tag>/.../upstreams/0/dial` + read back `GET /config/`; atomic, no snippet rewrite | Yes — the robust end-state cutover mechanism | Optional upgrade from snippet-rewrite+reload (future) | [admin API](https://caddyserver.com/docs/api) |
| **`lb_try_duration` (~5 s) + `lb_retries`** hold clients instead of 502 — needs **both** upstreams declared | Limited — holds only ~5 s; can't bridge our ~35 s sequential window (and old color is *stopped*, not a live alternate) | Not our window mechanism; would only matter if we had a <5 s overlap (we can't) | [reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) |
| **Health-gated start-new→drain-old** (kamal-proxy/Dokku/ECS): route to new only after health, then SIGTERM-drain old | No — presupposes both instances running during drain = the +684 MB we can't absorb | N/A until reranker is externalized (which we're rejecting) | [kamal-proxy](https://github.com/basecamp/kamal-proxy/blob/main/README.md), [Dokku](https://dokku.com/docs/deployment/zero-downtime-deploys/) |
| **Verify proxy re-bound end-to-end**; Caddy 2.11.1 `health_port` regression → 503-storm, fixed 2.11.2 | Yes — confirm Caddy version before using active health checks / `health_port` | Pin/confirm Caddy ≥ 2.11.2 if adopting active health checks | [caddy#7524](https://github.com/caddyserver/caddy/issues/7524), [caddy#7533](https://github.com/caddyserver/caddy/pull/7533) |

### Killed / unsettled — do NOT rely on
- **`handle_errors` converting a backend-down 502 → graceful 503** in the reverse_proxy path — **refuted/split (1-2).** Our graceful-503 must be validated empirically, not assumed.
- **The nginx-style file-flag → 503 idiom as "industry standard"** — refuted (0-3). (Our PR #145 C is a *pre-proxy* file-matcher gate, which is a *different* mechanism than handle_errors-on-502 — but it's still in the "validate empirically" bucket.)
- **`POST /load` is atomic-self-verifying** — refuted (0-3). Still must read back.
- **"Caddy retries only GET"** — unverified (1-2). So whether a hold-and-retry would protect the non-idempotent `POST /api/zettels/add` is **unknown** — don't rely on it for ingestion.

---

## Recommended holistic design (this box)

**Tier 0 — Reliability (do it).** Cutover verified by actual serving / config read-back, never by a reload exit code.
- Now: PR #145 **A** (e2e `https://…/api/health == 200` probe) already does this — sound.
- Later (optional hardening): surgical admin-API `PATCH …/upstreams/0/dial` + `GET /config/` read-back instead of snippet-rewrite+reload.

**Tier 1 — Graceful window (do it, the accepted bar).** Serve a graceful 503 during the inherent ~35 s sequential window. Mechanism **must be empirically confirmed**:
- Candidate A: PR #145 **C** pre-proxy `@maintenance` file-gate (with the C1 `root /data` fix) — confirm on the merge-deploy access log that it actually emits 503 (not 502).
- Candidate B (more robust if A doesn't fire): a tiny **always-up "maintenance" container as a second upstream**, so Caddy always has a live backend to serve the 503 page when the app color is down — sidesteps the unsettled handle_errors/file-matcher question entirely.

**Tier 2 — Externalize reranker / true blue/green: REJECTED for 2 GB.** Reverses the approved int8 migration; doesn't fit; regresses latency + deploy time.

**Shrink the window (cheap wins, optional):** trim the pre-flip warm phases (multi-route SSR warm, smoke retries) that run *inside* the window, and speed cold-start — these reduce the 503 duration without changing architecture.

---

## Open items to resolve before/with implementation
1. **Empirically confirm the graceful-503 mechanism** (Candidate A vs B) on a deploy — the research left this unsettled.
2. **Confirm the droplet's Caddy version** (≥ 2.11.2) if we ever adopt active health checks / `health_port`.
3. (Only if Tier-2 were ever reconsidered) measure sidecar+colors RSS and rerank latency on 1 vCPU — but our migration history already argues against it.

---

## Impact on PR #145
- **A (reload_caddy.sh e2e readiness):** keep — research-validated direction.
- **C (maintenance window):** the C1 `root /data` fix is still the right correctness fix *if* we keep the file-gate; but its effectiveness is exactly the "validate empirically" open item — or switch to the always-up maintenance-upstream (Candidate B).
- **Reranker:** unchanged — externalization rejected.
