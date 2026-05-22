# Postman Coverage Map

| Priority | Requirement from reports | Implemented coverage |
| --- | --- | --- |
| P1 | URL Add Zettel returns durable LRO contract: `202`, `Location`, `Retry-After`, status URL | `P1 Landing button fires POST /api/zettels/add`, `P1 Home button fires authenticated POST /api/zettels/add`, `P1 Zettels page button fires POST /api/zettels/add` |
| P1 | Website buttons use the correct endpoint | Same three surface requests assert `/api/zettels/add` and use the same payload shape as `website/static/js/add_zettel_api.js` |
| P1 | Poll `/api/operations/{id}` until terminal or explicit budget | `P1 Poll home operation until terminal or budget` |
| P1 | Response schema includes operation, summary, persistence, quality, and error structure | Add requests, operation polling, validation failures |
| P1 | Auth/user scoping and BOLA resistance | `P1 User A list contains only scoped zettels`, `P1 User B cannot read User A operation payload` |
| P1 | Supabase writes land in v2 content tables | `P1 Supabase workspace row exists for persisted zettel`, `P1 Supabase canonical row is scoped`, `P2 Supabase chunks or enrichment state is visible` |
| P1 | Operation terminal payload preserves response summary | `P1 Supabase operation response keeps full payload` |
| P1 | No duplicate/incorrect writes | User list duplicate ID assertion plus single-row Supabase checks |
| P1 | Invalid URLs and SSRF candidates fail cleanly | `P1 Invalid URL is rejected`, `P1 Private URL SSRF candidate is blocked` |
| P1 | Unauthenticated user zettel list is rejected | `P1 Unauthenticated zettel list is rejected` |
| P1 | Avoid `"Untitled"` regression in list output | User A list asserts titles do not equal `Untitled` |
| P2 | `/api/v2/summarize` timeout-prone path remains tested | `P2 /api/v2/summarize returns response schema` |
| P2 | Batch API and misleading stream endpoint are visible in tests | `P2 /api/v2/batch validates batch contract`, `P2 /api/v2/batch/stream exposes SSE contract` |
| P2 | Document upload old architecture has coverage | `P2 Document upload endpoint rejects empty file cleanly` |
| P2 | Timing capture without flaky hard limits | Collection-level latency event capture plus `summarize-newman-report.mjs` |
| P2 | CI/manual GitHub Actions execution | `.github/workflows/postman-summarization.yml` |
| P3 | Structured run artifacts | Workflow writes `docs/postman_results/YYYY-MM-DD/HHMMSS-run-<run_id>/` and uploads the same tree |
| P3 | Runbook for local, CI, staging/prod-like environments | `tests/postman/README.md` |

## Not Applied As Code Changes In This Module

- Poll budget/reaper changes, `title_ready`, operations-store fail-closed semantics, document LRO migration, and YouTube tier timeout fixes are production behavior changes. This PR creates the Postman module that detects those gaps; it does not alter production API behavior.
- Live droplet checks for YouTube cookies, migration 62 deployment, FK/schema-cache state, and operation payload rows require runtime credentials and are represented as workflow/runbook verification steps rather than committed secrets.
