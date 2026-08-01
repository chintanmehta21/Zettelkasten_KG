# Consolidated hardening plan — 2026-08-01

> **STATUS: EXECUTED.** All three batches complete and deployed.
> Outcomes, including two things that only showed up in production, are
> recorded in §9 at the end of this document.

Source: 6 parallel audits (3 code, 3 web-research) after the 2026-07-31 fail-dark outage.
Two agents died on session limits (deploy/rollback standards; ML-model memory sidecar) —
their ground is ~80% covered by the synthetic-fixtures and readiness streams. Gaps flagged in §7.

**Every recommendation below costs ~0 MB steady-state RSS on the droplet.** Anything that
didn't was rejected outright (§6).

---

## 0. P0 — SECURITY, operator action required

Three **real Gemini API keys printed in plaintext** into workflow logs on a **public** repo.

| Fact | Value |
|---|---|
| Cause | GH masks the whole `GEMINI_API_KEYS` string, not its comma-split parts. `test_key_pool.py` patches settings but not the env var, so real keys load and pytest's assertion diff prints them. |
| Exposure | Every weekly `live-tests` run since 2026-05-31 — ~13 public runs, 2 months. |
| Repo visibility | **public** — logs world-readable. |

1. **Rotate all 3 keys** (aistudio.google.com) — operator only; I don't handle key material.
2. Update `GEMINI_API_KEYS` secret + droplet `/etc/secrets/api_env`.
3. Delete affected run logs (I can execute on your word — irreversible, so held).
4. Check Gemini billing for anomalous usage over the window.
5. Code fix: `monkeypatch.delenv("GEMINI_API_KEYS"/"GEMINI_API_KEY")` in 3 tests — **safe autonomous**.

---

## 1. The through-line

Every severe finding is one defect class: **a gate that can abort after the point of no return, or that
silently reports success when it did not run.**

- `deploy.sh:239` `docker rm`s the serving container; the Caddy flip is at `:480`. Three exits in between.
- The smoke gate skipped for weeks (missing creds → `exit 0`), which is why two rotted fixtures were invisible.
- All 4 Postman suites pass while skipping every authenticated request.
- A weekly CI suite was red for 2 months with no alert.

Industry consensus (K8s admission webhooks default `failurePolicy: Fail`; Nagios exit-3 UNKNOWN):
**a verification gate that cannot run must block, never wave through.**

---

## 2. Tier 1 — Deploy fail-dark family

| # | Issue | Evidence | Fix | Approval |
|---|---|---|---|---|
| 1.1 | `exit 87` (cgroup) / `exit 88` (stage2) abort with nothing serving; they fire **before** the smoke gate I fixed, so `restore_previous_color` is never reached | `deploy.sh:266,282` vs rm at `:239` | call `restore_previous_color` before each | **approval** (changes abort semantics) |
| 1.2 | `exit 90` (caddy-smoke) — post-flip, lesser severity | `deploy.sh:545` | same treatment | approval |
| 1.3 | **Preflight before the point of no return** — assert creds/tools with `: "${VAR:?}"` at top of script, before `docker stop` | industry std (12-factor, Google shell guide) | ~10 lines at `deploy.sh` top | **approval** |
| 1.4 | `rollback.sh` starts old colour with `:latest` = the new suspect image. Since `docker rm` already ran, compose *must* create fresh → pulls new image | `rollback.sh:30-32`, `docker-compose.blue.yml:3`, CI pushes both tags | persist `$ROOT/LAST_GOOD_SHA` after caddy-smoke passes; rollback exports `IMAGE_TAG` from it; fall back to `docker inspect` of the running container, then `:latest` with a loud warning. Drop the `\|\| true` masking pull failures | **approval** |
| 1.5 | Failed container's logs destroyed by `docker rm` — blocked root-causing the 04:08 failure | my own fix's flaw | capture `docker logs` → `$ROOT/logs/failed-*.log` before rm (**written, uncommitted**) | safe |
| 1.6 | Tri-state gate: UNKNOWN(3) ≠ PASS | Nagios guidelines | exit 3 on "couldn't run"; never 0 | approval |
| 1.7 | Stale/false comments: `:264-265` claims "Caddy still on previous color" and "--force-recreate will replace it" — both untrue post-sequential-rewrite | `deploy.sh:264-265` | correct them | safe |

Also: consider dropping the `:latest` push entirely (`deploy-droplet.yml:105`) — nothing consumes it,
and it is what makes 1.4 possible.

---

## 3. Tier 2 — Cold-start / citation suppression

**Corrected diagnosis.** Not warm-up, not cache poisoning. Timing refutes a warm-up model
(passes at 61s/63s/64s; the failing run probed at 52s then kept failing at 103s and 144s).

Leading mechanism: the **answer critic fails closed** — it catches every exception and returns
`"unsupported"` → `unsupported_no_retry` → `_SUPPRESS_CITATIONS_ON_REFUSAL` returns `[]`.
Retrieval was probably healthy; citations were deliberately stripped. A transient Gemini failure
on the last of ~6 generative calls produces exactly this signature.

| # | Fix | Where | Approval |
|---|---|---|---|
| 2.1 | Don't suppress citations when the verdict came from a critic **outage** rather than a judgement — add `and not details.get("critic_error")` to the guard | `orchestrator.py:1417` | approval (RAG behaviour) |
| 2.2 | Log a WARNING when synth drops the `[id=…]` tag and `used_candidates` is cleared — currently entirely silent | `orchestrator.py:1120` | safe |
| 2.3 | Capture `turn.critic_notes` + `mem-trace` in the smoke failure output — makes the next occurrence self-diagnosing | `deploy.sh` smoke block | safe |
| 2.4 | Warm **all** workers: `/api/health/warm` is one request, `GUNICORN_WORKERS=2` | `deploy.sh:368` → loop 4–6× | safe |
| 2.5 | `/api/health/warm` warms only the ONNX session — not embeddings, pools, RPC, or PostgREST. Add those, or stop claiming it does | `routes.py:373-407` | approval |
| 2.6 | **Contract-shaped smoke assertion** — assert 200 + JSON shape + `citations \| length > 0`, not a specific row's title. Deleting any row can no longer break the deploy | `deploy.sh` | **approval** — supersedes the fixture-identity assert |
| 2.7 | `/api/readyz` + `_ready` flag, PID in body; deploy gate requires ≥2 distinct ready PIDs. Keep `/api/health` shallow | new route | approval |
| 2.8 | `_build_runtime` memoizes `workspace_id=None` on a cold blip for the process lifetime | `service.py:87-90` | approval |

**2.6 is the highest-leverage item in this section** — it fixes the *class* (fixture rot breaking
deploys), not the instance.

---

## 4. Tier 3 — Live tests: 228 of 248 are ONE bug

Seven unit-test files call `os.environ.setdefault("SUPABASE_V2_URL", "https://ci-stub.supabase.co")`
at **module level**. pytest imports every module at collection, process-wide, never reverted.
`_v2_env` prefers `SUPABASE_V2_*` over the real `SUPABASE_URL`, and `get_v2_client` is
`lru_cache`d with **no `cache_clear` anywhere in the repo**. One poisoned client, whole session.
`ci-stub.supabase.co` → `NXDOMAIN` → `[Errno -2] Name or service not known`.

Introduced by commit `64baeafd` (Mon 2026-05-25); next Sunday cron was 2026-05-31 — exact onset.
It also explains why my second secret fix moved nothing: the stub outranked the real values.

| # | Action | Fixes | Approval |
|---|---|---|---|
| 3.1 | Add `SUPABASE_V2_URL/_ANON_KEY/_SERVICE_ROLE_KEY` to `live-tests.yml` → `setdefault` no-ops | **228** | safe (3 lines) |
| 3.2 | Re-point stale entitlement monkeypatches (`consume_entitlement` no longer exists) | **35 errors** | safe |
| 3.3 | `delenv` Gemini keys in key-pool tests | 3 + §0 | safe |
| 3.4 | `_ensure_workspace` mint real auth user (profile FK violation) | 4 | safe |
| 3.5 | Autouse `reset_for_tests()` for concurrency tests (module-global depth leaks) | 3 | safe — **don't touch semaphore/queue_max** |
| 3.6 | Avatar tests → `core.profiles.avatar_url` (migration 78 moved it) | 3 | safe |
| 3.7 | Zoro assertion → `_zoro_user_id()` | 2 | safe |
| 3.8 | `example.com` fixture yields 112 chars → below thin-extraction floor | 1 | safe |
| 3.9 | `test_pricing_unmodified` — guard asserts `pricing_subscriptions == 0` against a live prod DB with 23 real subscribers | 3 | **OPERATOR-LOCKED — report only** |
| 3.10 | Delete the 21 module-level `setdefault` lines (dead in CI, landmine in live-tests) | — | safe, separate commit |

**Expectation-setting:** once 228 tests reach live Supabase for the first time since May, expect a
fresh unknown set of genuine failures. Today's log says nothing about their real health. Those
fixtures also mint/delete real users in the **production** project.

**Then** apply the burn-down: baseline → `xfail(strict=True)` ratchet (XPASS fails, so the list
self-cleans) → cap → expiry. Do **not** add `pytest-quarantine` (abandoned, v2.0.0 2019, py≤3.8).
Do **not** add global `--reruns` — this is deterministic breakage, not flakiness, and reruns
multiply paid Gemini calls.

---

## 5. Tier 4 — Silently-green gates and latent issues

| # | Issue | Impact | Approval |
|---|---|---|---|
| 4.1 | **All 4 Postman suites no-op** — `POSTMAN_AUTH_TOKEN_USER_A/B` absent; collection skips via a *passing* assertion; Newman exits 0. Includes every cross-tenant BOLA denial test | security coverage is fiction | approval |
| 4.2 | Scheduled-CI alerting: red for 2 months, nobody notified | root enabler of everything | safe (auto-issue + dedupe) |
| 4.3 | Dead-man's-switch — a *dropped* scheduled run is indistinguishable from a passing one. Public repo ⇒ **scheduled workflows auto-disable after 60 days of inactivity**; runs are attributed to whoever last edited the cron | silent total stoppage | safe (Healthchecks.io free tier, 0 RSS) |
| 4.4 | `check_calibration_drift` red every Sunday — `check_corpus_drift.py:81` raises `NotImplementedError`; downstream script targets tables dropped in Phase 6 | dead workflow read as "drift detected" | approval |
| 4.5 | `cleanup-test-fixtures`, `read_droplet_state`, `check_calibration_drift` declare no `environment: production` → env-scoped secrets arrive empty | nightly cleanup may be no-op | approval |
| 4.6 | `WEBSHARE_API_TOKEN` vs real `WEBSHARE_API_KEY` | diagnostic permanently false | safe |
| 4.7 | Caddy healthcheck fix **inert 3 ways**: `docker run` block skipped (`init=true`), `docker-compose.caddy.yml` not synced, and nothing ever runs that compose file | caddy shows unhealthy forever | approval (needs container recreate) |
| 4.8 | `/api/health` raw-502s for **2–5 min (worst ~13)** per deploy — routed before the maintenance matcher | false downtime pages | split: move warm-up loops after the flip (safe); monitor threshold (operator) |
| 4.9 | `EmptyScopeError` → 500 on non-stream path; `ask_kasten.py:320` docstring falsely claims it's mapped; **quota is charged before the 500** | corpus drift looks like code breakage | safe (422 + `empty_scope`) |
| 4.10 | Allowlist gate queries `kg_users` — dropped in Phase 6. Harmless only because it defaults off | enabling it aborts every deploy | safe (comment/disarm) |
| 4.11 | `eval_iter_03_http.py` targets the dead kasten; swallows all exceptions → emits `gold_at_1: 0` indistinguishable from total collapse | dev tool lies | safe |
| 4.12 | `docs/runbooks/gh_secrets.md` + `new_envs.txt.bak` still prescribe `DROPLET_SSH_PORT` | re-infects the log-masking bug | safe |
| 4.13 | Protect the smoke fixture: `BEFORE DELETE` trigger with `RAISE EXCEPTION` (immune to `service_role`; RLS is **not** — service key bypasses it, and it fails silently) | fixture rot can't recur | approval (DB change) |

---

## 6. Rejected — with reasons

| Rejected | Why |
|---|---|
| Prometheus + Alertmanager on droplet | 100–250 MB resident |
| Checkly Agent / Datadog private location | vendor minimums 2 vCPU / 4 GB |
| TorchServe / Triton / KServe / Seldon | control-plane shaped; non-starter at 2 GB |
| Argo Rollouts / Flagger / Spinnaker | require k8s |
| `pg_prewarm` | vectors are on Supabase's box, not ours; advice assumes you own Postgres |
| Pact / PactFlow | consumer-driven contracts need a participating provider; Google won't verify our pacts |
| Supabase branching / Neon | paid; local CLI stack covers the same surface free |
| Testcontainers-Postgres as the only DB surface | **false confidence** — no PostgREST/GoTrue/`service_role`; our PGRST200 FK-hint bug would have passed green |
| `pytest-quarantine` | abandoned 2019, py≤3.8 |
| Global `--reruns` | multiplies paid Gemini calls for a non-flaky problem |
| ORT arena tuning | measure first; the cited 625→415 MB case is a different workload |

---

## 7. Honest gaps

- Two agents died on session limits: deploy/rollback **standards** research and the ML-memory-sidecar
  question. Item 1.4's design is from the code audit + first principles, not from surveyed industry practice.
- The 04:08 failure could not be root-caused — its container logs were destroyed. §2 is the *leading*
  mechanism with a decisive tell (`critic_notes`), not a confirmed one. Item 2.3 makes the next
  occurrence self-diagnosing.
- Subagent "ruled out" claims were themselves wrong at least once (cache poisoning was dismissed by
  reasoning that ignored the container having been replaced).
- Unverified: commercial flake-service pricing; Supabase Cron behaviour on restore/pause;
  private-repo scheduled-workflow disable behaviour.

---

## 8. Recommended execution order

**Now (operator):** rotate keys (§0.1–2).

**Batch A — safe autonomous, no deploy needed:** 3.1–3.8, 3.10, 4.2, 4.6, 4.11, 4.12, plus §0.5.
Unblocks 270 test failures and restores CI alerting. Zero production risk.

**Batch B — one deploy window, needs approval:** 1.1–1.7, 2.2–2.4, 2.6, 4.9, 4.10.
This closes the fail-dark class and makes the smoke gate rot-proof. Single cutover.

**Batch C — deliberate, individually approved:** 2.1, 2.5, 2.7, 2.8, 4.1, 4.4, 4.5, 4.7, 4.8, 4.13.

**Never autonomous:** 3.9 and anything touching pricing semantics.


---

## 9. Execution outcome (appended 2026-08-01, after the work shipped)

### Shipped
| Batch | Items | Result |
|---|---|---|
| A | 13/13 | live-tests unpoisoned (228 failures + 35 errors), P0 key-leak closed, scheduled-CI alerting + dead-man's canary |
| B | 12/12 | every fail-dark exit closed, preflight, LAST_GOOD_SHA rollback, contract-shaped smoke |
| C | 10/10 | critic-outage citations, EmptyScope 422, warm data path, `/api/readyz`, Postman fail-loud, workflow env scoping |

### Two things only production revealed

**1. The cold-start flake was warm-up insufficiency, and the fix is measurable.**
Deploy `b7f257d1` reproduced it live with the new instrumentation:
`attempt 1 → NO_CITATIONS`, `attempt 2 → HTTP 000000 PARSE_FAIL`,
`attempt 3 → OK` (~3.5 min after boot). The next deploy, with the DB warm-up
shipped, passed on **attempt 1**. That also finally rules out the
poisoned-cache theory: the same container recovered without a restart, which a
process-lifetime `lru_cache` could never do.

**2. `cancel-in-progress` is a fail-dark path no in-script guard can close.**
Pushing while a deploy was mid-cutover cancelled it after the active container
had been removed. deploy.sh's EXIT trap cleared the maintenance flag on the way
out, so users got raw 502s rather than the graceful 503, and
`restore_previous_color` never ran — an external SIGHUP bypasses every gate.
`ops-recover-serve.yml` restored service in ~2 minutes, and its log validated
two designed behaviours for real: the colour swap preserved the protected
transport block, and a graceful reload was **not** sufficient — only the restart
fallback re-bound the stale single-file mount.

**Operating rule now in force:** check
`gh run list --workflow=deploy-droplet.yml --limit 1` before every push to
master; if a deploy is in flight, batch commits and wait.

### Still open
- **P0 key rotation** — operator only; the three leaked Gemini keys must be
  rotated regardless of the code fix that stopped the leak.
- **live-tests** — the 25-minute cap only ever "fit" because a third of the
  suite died instantly on DNS. Raised to 60. The first full-length run is the
  first true signal since 2026-05-31, and per the audit a fresh set of genuine
  failures should be expected.
- **§7 gaps** unchanged: two research agents died on session limits, and the
  04:08Z container logs were destroyed before capture existed.


---

## 10. Live-test burn-down (appended after execution)

| Measurement | failed | passed | errors |
|---|---|---|---|
| Baseline (2026-05-31 → 2026-08-01, unnoticed) | 248 | 5128 | 35 |
| After the fixes below | **43** | **5393** | **0** |

### What each fix actually bought

| Fix | Failures cleared | Note |
|---|---|---|
| `SUPABASE_V2_*` in `live-tests.yml` + guarded `tests/env_stub.py` | ~228 | The `ci-stub.supabase.co` module-level `setdefault` poisoning |
| Shared `bypass_entitlements()` helper | 52 (all 35 errors) | Nine modules patched symbols Phase 9 / the D2 strangler-fig had moved |
| `kg` seed param `int` → `str(i)` | 9 | `$2::text` makes asyncpg infer TEXT; proven against the live DB inside a rolled-back transaction |
| `_usage_weight_bonus` kwarg `user_id` → `workspace_id` | 6 | A deliberate correctness rename the test never followed |
| Avatar reads → `core.profiles.avatar_url` | 2 | Migration 78 moved the source of truth and cleared the `auth.users` copy |
| Anonymous identity derived, not hard-coded | 2 | Tests asserted the *fallback sentinel*, i.e. the failure path, as the contract |
| Restored instrumented ordering patches | 2 | CI caught my own over-broad refactor — those tests observe call order, so a generic no-op erased the marker |

### The ~14 that remain — all need a decision, not more code

| Cluster | Count | Why it is not an autonomous fix |
|---|---|---|
| Pricing / entitlements | 4 | **Operator-locked.** `pricing_subscriptions` drifted 0 → 26 against a live prod DB with real subscribers; free-tier day cap not enforced; order-create gate returns 502. Touching any of it requires explicit sign-off. |
| Naruto avatar pin | 1 | Migration 78 pins `avatar_01`; prod holds `avatar_41`. The pin is a one-time backfill and the avatar picker can legitimately change it — so the failure is TRUE. Re-pin prod data, relax to shape-match, or enforce with a trigger. |
| RAG queue-503 | 2 | CI cannot build the RAG runtime, so the test gets the *wrong* 503 (`RAG runtime is not available`). An environment problem, diagnosable only from inside CI. |
| Graph seeding / XSS node count / URL-dedup semantics | ~7 | Need confirmation of intended behaviour before the expectation is rewritten (notably: does URL-dedup now win over content-hash? PR #25 suggests yes). |

### Process fix that came out of this

`ops/scripts/check_deploy_clear.sh`. I pushed during a live cutover **twice**; the second time my own inline check printed `IN FLIGHT` and then `(none=safe)` and exited 0 — a guard whose failure looked like its success, which is the exact defect class this whole plan was about. The script exits non-zero when a deploy is running and exits 2 (UNKNOWN) if it cannot read status at all.

Use it as a gate, never by eye:

```bash
ops/scripts/check_deploy_clear.sh && git push origin master
```
