# Post-PR-113 Closing Gaps — Tracking

**Created:** 2026-05-26
**Branch:** `claude/post-113-closing-gaps`
**Base PR being closed-out:** [#113 fix(security): strip Content-Encoding on response rebuild](https://github.com/chintanmehta21/Zettelkasten_KG/pull/113) (merged 2026-05-26 14:02 UTC)
**Predecessor PRs in the SSRF / hotfix chain:** #109, #111, #113

## Purpose

PR #113's body explicitly enumerates three follow-up scopes that were intentionally NOT bundled into the hotfix because they widen the blast radius. This PR closes those gaps.

Every item below must be **re-verified in the current tree** before a fix is written — the line numbers in PR #113 were captured at hotfix-time and code has shifted since. Per CLAUDE.md research discipline: punch-list items are hypotheses, not facts.

---

## Scope A — Broad-except audit (from PR #113 body)

Each is a `except Exception:` (or equivalent) that silently degrades. Narrow to the actually-expected exception classes; log + raise on anything else.

- [ ] `website/features/source_ingest/github/api_client.py` — 5 silent fail-open sites (PR #113 cited lines 56, 63, 71, 88, 97; reverify before patching)
- [ ] `website/features/source_ingest/utils.py:71` — trafilatura import + extract both swallowed as one
- [ ] `website/features/source_ingest/twitter/*` — two-layer silent fan-out (PR #113 didn't name files; audit the whole `twitter/` subtree)
- [ ] `website/features/summarization_engine/core/orchestrator.py:47` — `_is_youtube_url` urlparse catch could mis-route YT links
- [ ] `website/features/async_backpressure.py:55` — should explicitly narrow even though `CancelledError` is `BaseException`-derived

**Per-site rubric:**
1. Identify the precise exception classes the call site can raise (read the libs, don't guess).
2. Narrow the except clause to those classes only.
3. Log unexpected exceptions at WARNING with `type(exc).__name__`.
4. Add a unit test that injects an unexpected exception and asserts it surfaces (not swallowed).

## Scope B — Redirect / safe_request test gaps (from PR #113 body)

The test gaps that made the gzip/brotli regression invisible to CI. All four must land with assertions on **decoded** body bytes via `httpx.MockTransport` (not respx) so the decoder pipeline is faithfully exercised.

- [ ] POST method preservation on 307/308 redirects (verify `safe_request` keeps POST, doesn't downgrade to GET)
- [ ] Cookie scrubbing on cross-host redirect — code path exists in `safe_request`, untested
- [ ] Chunked body without Content-Length (transfer-encoding: chunked)
- [ ] Empty body / 204 No Content
- [ ] Location header with fragment / query / unusual percent-encoding

## Scope C — Pure-ASGI middleware conversion (from PR #113 body)

Industry consensus per [encode/starlette#1438](https://github.com/encode/starlette/issues/1438), [#1715](https://github.com/encode/starlette/issues/1715): `BaseHTTPMiddleware` is fundamentally racy against the response body pump. PR #113 worked around the `_post_response_release` symptom with a 50 ms `call_later` defer; the proper fix is pure-ASGI.

Convert all 5 `@app.middleware("http")` decorators in `website/app.py` to pure-ASGI implementations. The PR #113 Agent-3 test matrix must pass:
- [ ] SSE streaming endpoint (no body-pump corruption)
- [ ] HEAD requests (no body emitted)
- [ ] 401 responses (auth middleware short-circuits cleanly)
- [ ] Cookie idempotency (Set-Cookie not duplicated by middleware reentry)
- [ ] `MemoryPressureError` propagation (Phase 1A backpressure preserved)
- [ ] Middleware ordering assertion (explicit test that the chain runs in the documented order)

**Risk note:** This touches the Phase 1A memory-release knob and the SSE heartbeat wrapper — both are HARD-RULE protected per CLAUDE.md. Operator approval required before the conversion is merged; the PR body must call out the diff in release semantics and confirm zero regression vs. PR #113's `call_later` defer.

---

## Commit cadence

One commit per scope item (or per file, if a scope item spans multiple files). Subject ≤10 words per CLAUDE.md, prefixes: `fix(security):` for the narrowings, `test:` for the redirect test backfill, `refactor:` for the ASGI conversion.

## Verification gate before each merge

- `pytest tests/ -m "not live"` clean
- `ruff check .` clean
- For Scope C only: live deploy on droplet + 30-min log tail showing zero `LocalProtocolError`, zero `DecodingError`, zero middleware-chain ordering surprises.

## Out of scope for this PR

- Phase 9 pricing enforcement (separate plan exists)
- Anything not enumerated above
- New decisions per CLAUDE.md "beyond-plan = approval first"
