# Researched issue register — 2026-08-05

Every verdict below rests on dedicated web research (industry standard, sources
<5 years old where available, pragmatically scoped to our stack, with
side-effects verified). Nothing here has been applied. Companion documents:
`youtube_ingest_failure_2026-08-02.md` (the incident), `open_issues_2026-08-02.md`
(the operator's original register).

Status key: `[ ]` open · `[~]` blocked on operator decision · `[x]` done

---

## P0 — security

### [~] 1. Three leaked Gemini API keys, still live

**Verified fact, not a recollection:** the `GEMINI_API_KEYS` production secret was
last updated **2026-05-27**. The leak window ran **2026-05-31 → 2026-08-01**
(~13 weekly `live-tests` runs on a **public** repo). The secret has not been
touched since before the window closed, so **the leaked keys are the current
production keys.**

Mechanism (already closed in code): GitHub masks a secret's whole string but
never its comma-split components, so a pytest assertion diff that split
`"k1,k2,k3"` rendered each key unmasked.

**Operator-only. I do not handle key material.**

**Assume compromised.** Every measured study puts time-to-first-use at 1–11
minutes (Unit 42 honeypot: real attacker at ~4–5 min; Meli et al. NDSS 2019:
median 20 s to *discoverable*). Our window is ~2 months. There is no
evidence-supported grace period. LLM keys have the worst abuse economics of any
credential class — Sysdig measured LLMjacking victim costs at **>$46,000/day**.

**Deleting the logs does not undo exposure, and doing it FIRST destroys your own
forensics.** Preserve the log archive privately before deleting anything. Note
the exposure is narrower than a committed secret — public Actions logs require a
logged-in GitHub account, and GH Archive never carried them (`WorkflowRunEvent`
is webhook-only, not on the public firehose). But bulk harvesting is routine:
the GHALogs dataset on Zenodo publishes **142.3 GB of raw Actions log text from
25,000 public repos**. Also scrub check-run annotations, job summaries, and any
bot PR comments — all survive log deletion, and bot comments *do* land in GH
Archive permanently.

**Aggravating:** `Google Gemini API Key` appears **not** to be a secret-scanning
*partner* pattern, so there was likely **no provider notification and no
auto-revoke** — unlike an AWS key, which gets quarantined in ~2 min.

**Rotation is not swap-in-place.** Create-before-delete: mint 3 new keys → add
alongside the old (pool holds 6) → deploy → verify → drain → revoke. Two
Gemini-specific traps:
- **Deletion propagation lags ~16–23 min** (Aikido, May 2026; Google closed it
  "won't fix"). A single 403 is not proof of revocation — retest after ~30 min.
- **A key minted in Cloud Console without an API restriction is now rejected
  outright** (post-2026-06-19). Rotation runbooks written before mid-2026 cause
  an instant outage. Mint in AI Studio, which produces restricted auth keys.

Forensics expectation: **you will probably not be able to prove non-abuse.**
Data Access audit logs for `generativelanguage.googleapis.com` are off by default
and not retroactive; there is no per-key metric or billing attribution. Document
the window as unreconcilable rather than clean. Set a project spend cap now — it
is the only hard blast-radius limiter.

### [ ] 1b. NEW — Standard `AIza` keys stop working in September 2026

Independent of the leak, and a **hard production outage timer ~1 month out.**
Google is retiring standard keys for the Gemini API. Enforcement gates already
fired **2026-05-07** (unrestricted dormant keys) and **2026-06-19** (unrestricted
standard keys rejected). **September 2026: the Gemini API rejects Standard keys
entirely.**

This makes the rotation and the migration the *same task* — rotate directly onto
**auth keys** (service-account-bound, restricted to the Generative Language API,
with fast-acting leaked-key enforcement) rather than rotating onto standard keys
that die within weeks.

### [ ] 1c. NEW — the key-pool's quota rationale may be false

**Gemini rate limits and billing are per *project*, not per key.** If all pool
keys live in one Google Cloud project, the key-first traversal on 429 —
`key1→key2→key3` before downgrading model tier — buys **zero extra quota**.

That traversal order is a CLAUDE.md-protected decision (`GeminiKeyPool` key-first
vs model-first). If the premise is wrong, the protected decision is protecting
nothing, and 429 handling should downgrade tier immediately instead of burning
latency cycling keys.

**Verify before acting:** are the 3 keys in one project or three? Operator can
check; I cannot without key access. Do **not** change the traversal order on the
strength of this alone — confirm the project topology first.

---

## P1 — correctness / durability

### [ ] 2. Migration 85 is written and tested but NOT applied

Adds `attempts`/`max_attempts`/`heartbeat_at` to `core.operations`, the
`core.operation_steps` journal, 5 RPCs, and repoints the reaper to requeue
instead of fail.

**Research verdicts:**

| Question | Verdict |
|---|---|
| `ADD COLUMN ... NOT NULL DEFAULT 0/3` | **Metadata-only since PG 11** — constant (non-volatile) defaults skip the rewrite. No table rewrite here. |
| Plain `CREATE INDEX` (non-concurrent) | **Correct as written.** Takes `SHARE` — blocks writes, **not** reads (widely mis-stated as `ACCESS EXCLUSIVE`, including by Braintree/PayPal's much-cited post; the PG docs are unambiguous). On a table capped in the low thousands by a 24 h TTL, the build is milliseconds. |
| `CONCURRENTLY` instead? | **No.** Indexes on a table created in the *same* migration never need it, and the Supabase CLI wraps migrations in a pipeline where `CONCURRENTLY` hard-fails with `SQLSTATE 25001`. It would also force the whole file non-transactional — losing all-or-nothing semantics for the `ALTER`/`CREATE TABLE`/`CREATE FUNCTION` statements to buy nothing. |
| `CREATE OR REPLACE FUNCTION` under live traffic | Safe. Takes no table lock; in-flight calls finish on the old definition; no half-replaced state (single MVCC tuple update). Risk is only *concurrent* DDL on the same function (`XX000 tuple concurrently updated`) — serialize deploys. |
| `cron.schedule` upsert | Genuinely idempotent since pg_cron 1.3, preserves `jobid`, no gap. **Trap: the conflict key is `(jobname, username)`, not `jobname`.** Scheduling as a different role creates a *second* job and silently doubles execution. |
| Deploy ordering | This migration is **purely additive** — old code that knows nothing about the new columns/RPCs keeps working. So **migrate first, then deploy** (the expand-phase rule). Deploy-then-migrate is only correct for the contract/destructive phase. |
| Rollback | Modern consensus is **roll forward**. GitLab: *"a roll-forward strategy is used instead of rolling back migrations."* Our `.down.sql` exists and correctly restores a working reaper, but a `DROP COLUMN` down-migration restores the column, never the data. |

**Change to make before applying:** add `SET lock_timeout = '3s';` at the top.
`ADD COLUMN` still takes `ACCESS EXCLUSIVE` briefly, and Postgres's lock queue is
**FIFO with no queue-jumping** — our instant migration queueing behind one slow
query would stall *every* subsequent query on that table. Fail fast and retry
instead of piling up.

**Also verify before applying:** Supabase's `postgres` role has no
`statement_timeout` set, so it inherits the **2-minute** global default. Not a
risk at our table size, but the migration must run over a **direct/session
connection (port 5432)** — transaction mode (6543) cannot hold the session state
migrations need and `SET statement_timeout` does not work there at all. Our
`SUPABASE_V2_DATABASE_URL` is already on 5432. ✅

Post-apply: regenerate `expected_schema.json` or the v2 drift check goes red.

### [ ] 3. `ops_claim_next` exists but nothing calls it

The reaper requeues orphaned work correctly; no worker picks it up.

**Verdict: wire it — as a slow, jittered orphan sweeper folded into the EXISTING
poller, not a second dispatcher and not a separate container.** A second Python
process is the one option our 2 GB budget genuinely cannot absorb.

Researched parameters:

| Knob | Value | Why |
|---|---|---|
| Placement | one extra branch in the existing poller loop | one task, one cancel path; two independent timers is the failure mode |
| Cadence | 30 s base, **±33 % jitter** | ~0.05 qps; jitter breaks the 2 workers' lockstep |
| Backoff | → 120 s after 10 empty sweeps | steady state is empty |
| LISTEN/NOTIFY | **No** — poll only | would cost 2 permanently-idle dedicated backends for a rare fallback path |
| Per-worker job concurrency | **1** (hard semaphore) | caps in-flight LLM jobs at 2 = worker count = vCPU reality |
| Startup sweep | yes, delayed `random.uniform(15, 45)` s | keeps it off the cold-start ONNX window |

**Non-negotiable constraint:** the orphan threshold must exceed the graceful
drain window or **blue/green cutover becomes a duplicate-execution generator**.
Our 10 min vs 180 s drain matches Solid Queue's 60 s/5 min safety ratio. ✅

**Highest-risk item:** every CPU-bound step in the job body (ONNX, tokenization,
heavy parsing) must go through `asyncio.to_thread` or a bounded executor. On
1 vCPU, a sync call inside a job coroutine stalls *all* HTTP on that worker, and
it will present as a capacity problem rather than a code problem.

**Credible alternative worth knowing:** pg_cron + `pg_net` can push from the DB
(the reaper pokes an internal endpoint) instead of the app polling — zero
in-process loop. Costs a public inbound trigger + auth surface.

---

## P2 — operational

### [ ] 4. Caddy `(unhealthy)` for 25 h+ while serving fine

**Diagnosis:** BusyBox `wget` resolves `localhost` → `::1` first with no IPv4
fallback; Caddy's admin binds `127.0.0.1` only. Well-documented bug class
(maildev#407, ExcaliDash#61, bunqueue#7). **Second latent bug:** `--spider` sends
**HEAD**, and admin `/config/` is a GET handler — so it may stay red even after
the IP fix.

**Is it harmful?** On plain Compose, health status is **inert** — restart policies
fire only on process *exit*; there is no code path from `unhealthy` to `restart`.
The 25 h uptime is itself proof no health-consumer exists. The harm is that the
signal is pinned false and cannot distinguish "fine" from "wedged."

**Is fixing it risky?** (the question I asked specifically) **No restart loop is
mechanically possible.** The only real cost is that healthchecks cannot be updated
in place, so applying it recreates the container → ~1–5 s of edge downtime.
**Do not bundle autoheal or any health-triggered automation into the same
change** — coupling a newly-honest signal to an automated action is how an inert
cosmetic bug becomes an outage.

Recommended (option A, minimal): `wget -q -O /dev/null http://127.0.0.1:2019/reverse_proxy/upstreams`,
`interval 30s / timeout 5s / retries 3 / start_period 30s`. `/config/` is also the
heaviest admin endpoint — it serializes the entire config on every check.

### [ ] 5. Deploy cascade: "reload fails → restart → rollback"

**This cascade is self-inflicted and the fix is to delete a step.** Caddy's reload
is transactional: it provisions and validates the new config alongside the running
one and only swaps on success — *"if the new config fails for any reason, the old
config is rolled back into place without downtime."* **A failed reload is a no-op.
Restarting Caddy afterwards is strictly harmful and never necessary.**

Correct decision table:

| Failure point | Action |
|---|---|
| `caddy validate` fails | abort; touch nothing |
| `caddy reload` non-zero | abort; **do not restart, do not roll back** |
| Pre-flip health-wait fails | abort; old color never lost traffic |
| **Post-flip verification fails** | **the only real rollback trigger** — reload back to old color |

**Testable hypothesis that would unify #4 and #5:** if `caddy reload` is invoked
against `localhost:2019`, it hits the *same* `::1` trap as the healthcheck —
making these one bug, not two.

---

## P3 — test-suite integrity

### [ ] 6. Postman suites: dispatch-only, and were green while executing nothing

**Verdict: the credential design is the root cause, and the obvious fix is wrong.**

- Static JWT in a secret cannot work — 1 h expiry.
- **Service-role key must NOT be the test principal.** It bypasses RLS entirely,
  so a cross-tenant *denial* test run with it gets **allowed** — the assertion
  inverts and passes trivially. This would be a net security loss *and* a
  worthless test.
- **Correct:** seed two test users in different tenants; mint fresh JWTs per run
  with `signInWithPassword()`; store only passwords as Environment secrets.

**Placement (OWASP API1:2023 is explicit — *"Do not deploy changes that make the
tests fail"*, which a dispatch-only suite structurally cannot satisfy):**

| Suite | Where |
|---|---|
| Cross-tenant BOLA/BFLA (port to pytest+httpx, reuse `mint_test_user_with_workspaces`) | **required PR check**, ephemeral local stack |
| 4 Newman contract suites | scheduled nightly + post-deploy smoke |
| `workflow_dispatch` | manual re-run only, never sole trigger |

**Guaranteeing it can never pass while executing nothing** — Newman has no
`--fail-on-skip`, and `pm.execution.skipRequest()` is invisible to reporting
(confirmed by Postman staff, unanswered since 2024). Four fail-closed layers:
1. preflight on credentials (shipped ✅)
2. replace `pm.test('SKIPPED', () => pm.expect(true).to.equal(true))` with a `throw`
3. **execution floor** — `--reporters json`, assert `run.stats.requests.total`
   and `assertions.total` meet committed minimums (the load-bearing one)
4. tripwire assertion that must appear as executed+passed in the report

### [ ] 7. pytest has the same vacuous-pass hole

Exit code 5 covers *collection* emptiness only. **A suite where everything is
collected then skipped at runtime exits 0.** Needs a passed-count / skip-ratio
guard at session finish, not just the collection guard.

And at the CI layer: **GitHub reports a skipped job as Success**, so a required
check can pass by not running. Needs an `if: always()` aggregator reading
`needs.*.result`.

### [x] 8. Known-failure ratchet — already correct on the load-bearing property

The one mechanism with genuine cross-ecosystem consensus (pytest `xfail_strict`,
LLVM lit, DejaGnu, Rust `known-bug`, PHPStan, Psalm, ESLint, betterer) is:
**an entry that starts passing must FAIL the build.** Our ratchet does this —
`strict = "flaky" not in trailing` defaults entries to `strict=True`. ✅

Gaps worth knowing (all "build it yourself" — **nothing off-the-shelf ships a
quarantine TTL or a budget cap**):
- No mandatory bug ID / owner per entry. Chromium lint-enforces this; Kubernetes
  requires a `lifecycle/frozen` tracking issue so the debt cannot be auto-closed.
  This is the enforcement with the best real-world track record.
- Consider a CI check that entry count strictly decreased vs the merge base.
- Chromium's `StaleTestExpectations` is a formally segregated graveyard — proof
  the rot problem is real even at their discipline level.

### [~] 9. `pricing_subscriptions count == 0` (now 26)

**Wrong under every authority found** — an absolute row count on a shared live
table can only ever fail. Correct fix in priority order: **(a) scope to the run's
own tenant** (mandatory if tests run in parallel — delta assertions are documented
as insufficient under parallelism), (b) delta assertion, (c) delete it if it
isn't testing the change.

Operator-locked per CLAUDE.md pricing authority.

### [~] 10. Golden-md5 on the `consume_entitlement` RPC body

Weak control: it asserts **text, not behaviour**, and lives in the same commit as
the change it guards, so it's rubber-stampable. Also brittle — `prosrc` preserves
whitespace that `pg_dump` normalizes, and PG14+ `BEGIN ATOMIC` bodies are parsed
at definition time and re-rendered on output.

Replacement: **pgTAP behavioural tests** (signature, `SECURITY DEFINER`,
`search_path`, grants, plus real input/output cases including quota-exhausted) +
**CODEOWNERS on the migration dir** (the actual anti-unauthorized-change control)
+ drift detection via `supabase db diff`.

---

## Cross-cutting: memory (steps 0–4, shipped in this branch)

Step 0 measurement result: **swap is COLD.** `workingset_refault_anon` moved
+8 pages in 12.5 min; `oom_kill` 0→0. The 692 MB of swap is parked, not thrashing.
Caveat: the box was idle, so this is the idle floor — the two OOM kills on the
*previous* container instance happened under real conditions. Steps 2–4 are
therefore prophylaxis against the loaded case, **not** a fix for active thrashing.

Honest accounting:
- **Step 2 was already done** in iter-03 (`intra_op=1`, `inter_op=1`, arena off,
  mem_pattern off). No new saving; tests added to pin it against regression.
- **Step 3 yields tens of MB, not hundreds** — `gc.freeze()` removes only the
  GC-scan source of COW breakage; `Py_INCREF` still dirties headers, and our
  resident bulk is ONNX weights the Python GC never touches.
- **`memory.high` deliberately NOT set.** With the working set already at
  `memory.max`, it would buy a permanent reclaim treadmill. Meta moved off it as
  a primary control. Revisit only after 2–4 create measurable headroom.
- **jemalloc deliberately NOT adopted.** Strongest published numbers (50–67 %)
  but they come from fragmentation-dominated workloads; ours is model-dominated,
  and `LD_PRELOAD` carries real conflict risk with ORT's prebuilt binaries.

---

## Recommended order

1. **Rotate the Gemini keys** (#1) — operator, today, before anything else.
2. Apply migration 85 with `lock_timeout` (#2) — additive, migrate-then-deploy.
3. Wire the orphan sweeper (#3) — completes the durability story.
4. Caddy healthcheck + delete the restart-on-failed-reload step (#4, #5) — fold
   into an already-scheduled deploy so the container recreate is paid once.
5. Contract-test auth + execution floors (#6, #7).
6. Test-hygiene items (#9, #10) — operator-locked, need sign-off.
