# Runbook — move live tests off production onto an isolated Supabase project

**Status:** repo side is DONE and inert. The remaining steps are operator-only
(they need Supabase console/CLI auth, which CI does not have).

## Why

`live-tests.yml` runs `pytest --live`, which **mutates whatever database it
points at**: it mints real auth users (`e2e-<hex>@test.com`), workspaces and
content rows. It currently points at **production**.

Measured 2026-08-04: **1392 of 1520** non-deleted `content.workspace_zettels`
(92%) were leaked fixtures, because the nightly purge had failed for five days.
That is survivable while the data is private — it stops being survivable the
moment a **public** community graph aggregates the same table, because those
fixtures become publicly visible content.

The industry answer is to isolate at the **environment boundary**, not to filter
test rows out at read time:

- Stripe binds credentials to a sandbox — "Stripe uses the API keys linked to a
  sandbox to authenticate API requests directed at the corresponding sandbox
  environment" ([Stripe][1]). Isolation is by credential, not by a flag or a
  naming convention.
- Supabase branching gives "a separate environment with its own Supabase
  instance and API credentials", and branches deliberately start with **no**
  production data — "This is meant to better protect your sensitive production
  data" ([Supabase][2]).

We explicitly did **not** take the alternative of adding an
`email ~ '^e2e-...'` exclusion to the public RPC: that pushes a test-shaped
regex onto a hot production read path, puts PII in query plans, and leaves the
underlying problem (test data in prod) in place.

## What is already done (no action needed)

- `live-tests.yml` reads `SUPABASE_TEST_*` **with fallback** to the production
  secrets: `${{ secrets.SUPABASE_TEST_URL || secrets.SUPABASE_URL }}`. Until the
  test secrets exist, behaviour is byte-for-byte unchanged.
- A step applies `supabase/website/_v2` migrations to the test project before
  the suite runs. **Guarded on `SUPABASE_TEST_DATABASE_URL` being non-empty**, so
  it can never run against production.
- A run with no `SUPABASE_TEST_*` secrets emits a GitHub **warning annotation**
  saying it is about to mutate production.

## Operator steps

### 1. Create the isolated project

Either is fine; pick one.

- **Supabase branching** (preferred if the plan includes it): create a
  **persistent** branch — the weekly cron needs stable credentials, so a
  per-PR preview branch that disappears on merge will not do.
- **A second Supabase project** named e.g. `zettelkasten-test`: works on any
  plan and has no branching prerequisites.

### 2. Set these repository secrets

Set them in the **`production` GitHub Environment** (that is where
`live-tests.yml` resolves secrets from — a repo-level secret will read as an
empty string and silently fall back to prod).

| Secret | Where to find it |
|---|---|
| `SUPABASE_TEST_URL` | Project Settings → API → Project URL |
| `SUPABASE_TEST_ANON_KEY` | Project Settings → API → `anon` key |
| `SUPABASE_TEST_SERVICE_ROLE_KEY` | Project Settings → API → `service_role` key |
| `SUPABASE_TEST_JWT_SECRET` | Project Settings → API → JWT Secret |
| `SUPABASE_TEST_DATABASE_URL` | Settings → Database → Connection string (**direct, port 5432 — NOT the 6543 pooler**; `asyncpg_pool` rejects 6543) |
| `SUPABASE_TEST_PROJECT_REF` | The project ref in the dashboard URL |

### 3. Dispatch and verify

```bash
gh workflow run live-tests.yml --repo chintanmehta21/Zettelkasten_KG --ref master
```

Verify, in order:

1. The "Warn if live tests are about to mutate PRODUCTION" step is **skipped**
   (if it ran, the secrets are not visible to the job — check the Environment).
2. "Apply _v2 migrations to the test project" **ran** and succeeded.
3. After the run, **production** has no new fixtures:

```sql
SELECT COUNT(*) FROM auth.users WHERE email ~ '^e2e-[0-9a-f]{6,12}@test\.com$';
```

Run that against **prod** — it should stop growing after each weekly run.

## Known caveats

- **A fresh project has no data.** 52 of the v2 integration test files mint
  their own users via `mint_user`, so they are fine. Tests that assert against
  pre-existing production rows are not — e.g.
  `test_pricing_unmodified.py::test_pricing_subscriptions_unchanged_count`
  asserts an absolute row count on a shared live table. Those are already in
  `tests/known_failures.txt`; expect their failure *mode* to change, and
  rescope them to the test's own minted rows.
- **Branching does not replay our migrations.** Supabase auto-applies
  `supabase/migrations`, which is **empty** here — the real schema lives in
  `supabase/website/_v2` behind `apply_migrations.py`. That is why CI applies
  them explicitly. If you rebuild the branch, the next run re-applies them.
- **The nightly purge still matters** and still points at production; keep it.
  It is the safety net for fixtures created before this cutover, and for any
  operator run that still targets prod.

[1]: https://stripe.dev/blog/avoiding-test-mode-tangles-with-stripe-sandboxes
[2]: https://supabase.com/docs/guides/deployment/branching
