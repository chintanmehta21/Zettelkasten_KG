# Add Zettel async fast-ack — deferred follow-up

**Status:** Deferred out of PR #25 (operator decision 2026-05-18). PR #25 scope = engine-routing verification + old-engine purge only. This is NOT yet implemented.

## Problem

`/api/zettels/add` is fully synchronous in production: every UI caller hardcodes
`mode: 'sync'` (`home.js`, `user_zettels.js`, `mobile/summarizer.js`, `static/app.js`)
and the gate env `ADD_ZETTEL_IN_MEMORY_ASYNC` is unset. The browser holds one open
HTTP connection for the entire ingest → summarize → dense-verify → persist, serialized
behind `_SUMMARIZE_SEMAPHORE = asyncio.Semaphore(2)`. Perceived latency for Strong/Pro
multi-hop content is tens of seconds, masked only by the Caddy 240s read-timeout and
the frontend loader animation.

A fast-ack path (instant `202` + `status_url` poll, `_AUTO_ACCEPT_AFTER_SECONDS = 8.0`,
`GET /api/operations/{id}`, frontend `pollAccepted()`) is already built but dormant.

## Why it cannot just be flipped on

Production runs `GUNICORN_WORKERS=2` + `--preload` with no worker-level sticky routing
(Caddy proxies one container port; the 2 worker processes accept connections
non-deterministically). All async-path state — `_OPERATIONS`, `_OPERATION_TASKS`,
`_IN_FLIGHT`, `_IDEMPOTENCY_CACHE`, `_RATE_STORE` — is module-level in-process dicts
(`zettels_routes.py:55-58`), not shared across workers.

Consequence: a `202` issued by worker A stores the operation in A's dict; the browser's
poll has ~50% chance of landing on worker B → `_operation_get` returns `None` →
spurious `404` for a Zettel that actually succeeded. Hence the `IN_MEMORY` env name.

Secondary risks: worker recycle (`--max-requests`) orphans in-flight tasks (operation
stuck `accepted` until 15-min TTL); per-worker idempotency cache widens the
double-LLM-spend window to the 15-min TTL; `_MAX_OPERATION_RECORDS = 128` LRU eviction
404s slow pollers under burst (tight vs the 10k+ scale target); the
`run.py:53` capacity math (2×(2 sem + 8 queue) = 20) is reasoned around the synchronous
hold model and must be re-derived for an accept-and-poll model.

## Required for a production-correct implementation (own iteration)

1. Cross-worker shared store for operations + idempotency (Postgres operations table
   keyed by `client_action_id`, or Redis), with TTL + bounded size, replacing the
   in-process `_OPERATIONS` / `_IDEMPOTENCY_CACHE`.
2. Worker-recycle safety: persist task state so a recycled worker's orphaned operation
   resolves (resume, or mark failed deterministically) instead of hanging at `accepted`.
3. Re-derive the concurrency/queue budget for accept-and-poll; confirm it does not
   require touching the protected `Semaphore(2)` knob.
4. Frontend: switch callers to `mode: 'auto'`, verify `pollAccepted()` backoff + the
   202→200/failed transitions and error surfacing.
5. Test coverage: multi-worker poll-routing correctness, worker-recycle mid-task,
   idempotent retry across workers, burst eviction, concurrency under `Semaphore(2)`.

Until (1)–(5) ship, synchronous `mode: 'sync'` remains the correct production behavior.
