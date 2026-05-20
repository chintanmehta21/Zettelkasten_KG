# Final Summarization Pipeline + API Fixes

**Branch:** `exec/final-summarization-pipeline-api-fixes`
**Created:** 2026-05-20
**Status:** SCAFFOLD — operator will share concrete change list next.

## Context

Investigation report for the 4-5 min Add Zettel hang (YouTube `fmOPM1cSrY4` ingestion
on `zettelkasten.in`) identified a structural mismatch between three independent
timers introduced by the async-ops redesign shipped 2026-05-20 (PR #32 + 8 follow-ups):

- inline fast-ack 20 s (`_AUTO_ACCEPT_AFTER_SECONDS` in `website/api/zettels_routes.py`)
- frontend poll budget 180 s (`POLL_BUDGET_MS` in `website/static/js/add_zettel_api.js`)
- stuck-running reaper 5 min (`supabase/website/_v2/57_stuck_running_reaper.sql`)

Plus a doubled-pipeline race (`work` + `_run` both call `_run_add_zettel`), a `mode:"sync"`
field declared in the request model but ignored by the route, and silent swallowing of
`ops_finalize` PostgREST errors.

## Scope (to be filled in by operator)

Operator will share the consolidated fix report; this branch will execute it.

Placeholder sections — each will be replaced with a discrete commit:

- [ ] F1: collapse to single pipeline path
- [ ] F2: `mode:"sync"` — implement or delete
- [ ] F3: align poll budget with reaper threshold
- [ ] F4: retry `ops_finalize` on transient failure
- [ ] F5: graceful UI on poll-budget exhaustion
- [ ] F6: wire `Idempotency-Key` from JS client
- [ ] F7: (optional) SSE push completion
- [ ] F8: delete dead module-level dicts in `zettels_routes.py`
- [ ] F9: integration test — pipeline runs exactly once per accept

## Guardrails (CLAUDE.md)

- No protected-knob changes (`GUNICORN_WORKERS=2`, `--preload`, `GUNICORN_TIMEOUT=180`,
  rerank semaphore, SSE heartbeat wrapper).
- All migrations: pre-DROP audit + co-apply + manifest update.
- Tests cover concurrency / race conditions explicitly (per Production Change Discipline).
- Rebase & Merge (never squash) when shipping to master.
- Verify ALL touched modules end-to-end before claiming complete.
