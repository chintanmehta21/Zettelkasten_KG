# Nexus Execution Plan

## Objective

Close Nexus schema/frontend/docs drift so current runtime behavior is correctly represented and operable.

## File-Level Task Breakdown

1. `supabase/website/nexus/schema.sql`
- Update table definitions so `user_id` references `public.kg_users(id)`.
- Expand ingest run status check to include `partial_success`.
- Add/normalize artifact fields used by runtime (`run_id`, `status`, `error_message`, `node_id`).
- Keep `ingest_run_id` as temporary compatibility alias.
- Add migration-safe `ALTER TABLE ... IF NOT EXISTS` and data backfill from `ingest_run_id -> run_id`.
- Recreate outdated FK/check constraints to match current behavior.
- Ensure indexes exist for run/status lookup paths.

2. `ops/requirements.txt`
- Add `cryptography>=43.0` for Fernet token encryption/decryption support.

3. `website/experimental_features/nexus/js/nexus.js`
- Update connect redirect URL extraction to include `authorization_url`/`authorizationUrl`.
- Replace disconnect placeholder with real API action:
  - `POST /api/nexus/disconnect/{provider}`
  - refresh provider/runs state after disconnect
  - user-facing success/error toasts

4. `website/experimental_features/nexus/IMPLEMENTATION_SPEC.md`
- Document exact runtime contracts, schema requirements, migration notes, and frontend/API expectations.

5. `website/experimental_features/nexus/EXECUTION_PLAN.md`
- Capture this concrete implementation sequence and validation checklist.

## Verification Checklist

1. Static syntax checks
- `node --check website/experimental_features/nexus/js/nexus.js`
- `python -m compileall website/api/nexus.py website/experimental_features/nexus/service`

2. Dependency sanity
- Confirm `cryptography` appears in `ops/requirements.txt`.

3. Contract sanity (quick grep/inspection)
- Confirm frontend redirect aliases include `authorization_url`.
- Confirm disconnect handler calls `/api/nexus/disconnect/{provider}`.
- Confirm SQL includes:
  - `partial_success` in run status check
  - artifact `status/error_message/node_id/run_id`
  - `user_id` FKs targeting `public.kg_users(id)`

## Rollout Notes

- Apply schema SQL in Supabase SQL editor as a single migration.
- Because constraints are added with compatibility in mind, existing data can be migrated incrementally while new writes follow canonical fields immediately.
