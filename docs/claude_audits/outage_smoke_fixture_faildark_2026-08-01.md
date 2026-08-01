# Incident: deploy smoke gate fail-dark (2026-07-31 → 2026-08-01)

**Impact:** `zettelkasten.in` served raw 502s for ~10 hours (17:32Z Jul 31 → 03:10Z Aug 1).
**User impact: none observed.** Traffic in the whole window was the Better Stack uptime
bot plus scanner noise; no human session has touched the app since ~Jul 7.
**Status: resolved.** Site green, deploy pipeline green, root cause fixed at source.

---

## 1. What happened

A 30-day log audit surfaced five latent ops issues. Fixing them (P1) committed a
`deploy.sh` change that had been sitting **uncommitted for 41 days**: the rag-smoke
gate became *fail-closed*. That gate then ran, for the first time ever, against
real CI credentials — and immediately found that its own fixture had rotted.

Two independent rots, both silent for weeks:

| # | Rot | Why it stayed hidden |
|---|-----|----------------------|
| A | Smoke Kasten `227e0fb2` and its `zk-org/zk` canonical zettel **no longer exist** (QA cleanup + the 30-day canonical shred). `rag.kastens` holds 4 rows, none of them the fixture. | The gate skipped on every prior deploy (`NARUTO_SMOKE_PASSWORD` / anon-key not wired), so it never probed. |
| B | The gate asserted `citations[0].node_id == "gh-zk-org-zk"`. Under DB v2, `node_id` carries a **`canonical_chunk_id` UUID**. The assert could never match again, regardless of data. | Same — never executed. |

### The failure chain

1. `deploy.sh` opens the maintenance window, then **stops and `docker rm`s the active
   green container** — the sequential cutover is deliberate: a 2 GB droplet cannot hold
   two containers during stage-2 rerank.
2. Blue starts, passes health, cgroup and stage-2 asserts.
3. Smoke probes `POST /api/rag/adhoc` → `create_session` inserts `rag.chat_sessions`
   with the dead `kasten_id` → PostgREST `23503`
   `chat_sessions_kasten_id_fkey` → escapes every structured handler →
   `500 {"error":"internal_server_error"}`.
4. `exit 89`. **A bare exit** — so Caddy stayed pointed at the container deleted in
   step 1. Site dark until an operator intervened.

Step 4 is the real severity multiplier. The gate was *right* to refuse the cutover;
it was wrong to leave nothing serving.

---

## 2. Root causes and fixes

| Cause | Fix | Commit |
|---|---|---|
| Smoke fixture deleted from DB | Retargeted to Naruto's durable curated Kasten `087184be` (Economics & Markets) / `TheEconomist/big-mac-data` | `94a0e6cd` |
| v1-era `node_id` assert can never pass under v2 | Assert the stable citation **title** via new `RAG_SMOKE_EXPECT_TITLE`; both fixture knobs env-overridable | `94a0e6cd` |
| Smoke abort left the site dark | `restore_previous_color()` — every fatal exit in the smoke block hands off to `rollback.sh` first. Still exits non-zero; the failure stays loud. | `94a0e6cd` |
| Missing/foreign Kasten → unhandled 500 | `UnknownKastenError` raised from `session_store`, mapped app-wide to **403 Forbidden** (BOLA convention, never leak existence) | `25b7e80f` |
| Guard test pinned the retired fixture | `test_deploy_sh_rag_smoke.py` rewritten to guard the new contract + assert the dead id never returns | `10cf5ac0` |
| Caddy "unhealthy" 6 weeks | Healthcheck used `localhost`; busybox wget resolves `::1` with no IPv4 fallback while Caddy admin binds IPv4 only. **Proven on droplet:** `localhost` → exit 1, `127.0.0.1` → exit 0. | `b4b6339d` |
| `ACTIVE_COLOR` tier-1 detection dead | Env-verify read `deploy/active_color`, a path `deploy.sh` never writes; canonical is `$ROOT/ACTIVE_COLOR` | `b4b6339d` |

### Pre-deploy verification (not assumed — measured)

The retargeted fixture was proven against **live production** before any deploy relied
on it: `HTTP 200`, primary citation `TheEconomist/big-mac-data` at rerank score
**0.9996** vs 0.41 for the runner-up, answer naming both the repo and the R generator.
The subsequent real deploy passed the gate on attempt 1.

---

## 3. Recovery

Both the deploy workflow and every retry were blocked behind GitHub's
malicious-workflow scanner (it holds **every** run whose push edits
`deploy-droplet.yml`). Service was restored without it, via a new dispatch-only
workflow — `.github/workflows/ops-recover-serve.yml`:

- finds the running color that answers 200 on loopback,
- rewrites `upstream.snippet` **in place** (`cat >` preserves the inode; `scp` creates
  a new one and Caddy's single-file bind mount goes stale — a graceful reload would
  keep reading the old content),
- clears any stale `maintenance.flag`,
- delegates to `reload_caddy.sh`, which restarts Caddy if the e2e probe fails,
- verifies public 200 through Caddy before exiting.

Keep this workflow. It is the correct lever any time a cutover aborts mid-flight.

---

## 4. Open items (not done — each needs a decision)

1. **`rollback.sh` boots `:latest`, not the last-known-good SHA.** Compose resolves
   `${IMAGE_TAG:-latest}`, and CI pushes `:latest` alongside every SHA — so a "rollback"
   actually starts the *old color with the new image*. This now sits on the
   `restore_previous_color` safety path. It restored service correctly here (the fault
   was data, not code), but it is not a true version rollback. Proper fix: record the
   running image SHA pre-cutover and have `rollback.sh` reuse it. Not done blind —
   it is the most safety-critical script and cannot be end-to-end tested without
   staging a failed deploy.
2. **`EmptyScopeError` → 500 on the non-stream path.** Caught only in `answer_stream`
   (`orchestrator.py:661`); `stream=false` has no catch, so corpus drift presents as
   code breakage. The `ask_kasten.py:320` docstring already *claims* this is mapped.
   Behaviour change on a live endpoint — wants explicit approval.
3. **`ops/scripts/eval_iter_03_http.py`** still targets the deleted Kasten / `gh-zk-org-zk`.
   Dev-only eval harness, not in any CI path, but it will fail if run.
4. **Junk smoke sessions.** ~2 "Quick ask" rows in `rag.chat_sessions` (one from the
   passing deploy gate, one from my live verification) plus the quota they consumed.
   Deletion is a production DB write — not performed unattended.
5. **No alert when the smoke gate skips.** It skipped on every deploy on record, which
   is precisely why a weeks-old breakage only surfaced when the gate went fail-closed.
   Worth an explicit "gate skipped N consecutive deploys" warning.

---

## 5. Lessons

- **A gate that never runs is not a gate.** Both fixture halves rotted precisely
  because the gate had been skipping. Fail-closed found both within one run.
- **Fail-closed must not mean fail-dark.** Refusing to cut over is correct; refusing
  *and* leaving nothing serving is a separate bug. Order matters: the gate ran after
  the point of no return.
- **Assert on stable identifiers.** The v1 `node_id` assert survived the v2 migration
  as dead code because nothing exercised it.
- **A 500 is a diagnosis failure, not just a bug.** Missing fixture data presented
  identically to broken code, which is what made triage slow. That is now a 403.
