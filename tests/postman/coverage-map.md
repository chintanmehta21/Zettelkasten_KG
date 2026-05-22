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
| P1 | `/api/v2/summarize` is on the async-ops contract (202 + status_url) | `P2 /api/v2/summarize returns response schema` asserts 202 accepted envelope + URL-safe `operation_id` |
| P1 | Document upload is on the async-ops contract (202 + status_url) | `P2 Document upload endpoint rejects empty file cleanly` asserts 202/422 + accepted envelope |
| P1 | `title_ready` / `enrichment_status` readiness signal on list items | `P1 User A list contains only scoped zettels` asserts both fields and their consistency |
| P2 | Batch contract validated; fake-SSE stream endpoint removed (ADR-4) | `P2 /api/v2/batch validates batch contract`, `P2 /api/v2/batch/stream is removed (ADR-4)` asserts 404 |
| P2 | Timing capture without flaky hard limits | Collection-level latency event capture plus `summarize-newman-report.mjs` |
| P2 | CI/manual GitHub Actions execution | `.github/workflows/postman-summarization.yml` |
| P3 | Structured run artifacts | Workflow writes `docs/postman_results/YYYY-MM-DD/HHMMSS-run-<run_id>/` and uploads the same tree |
| P3 | Runbook for local, CI, staging/prod-like environments | `tests/postman/README.md` |

## Status

- The production behaviour the original Postman scaffold was built to *detect* — poll budget/reaper alignment, `title_ready`, operations-store fail-closed 503, the document + `/api/v2/summarize` async-ops migration, the fake-SSE `/api/v2/batch/stream` removal, and the YouTube per-tier timeout — is now implemented on branch `exec/summary-api-async-fixes-a1`. This collection and coverage map were updated to assert the new contract instead of the legacy one.
- Live droplet checks for YouTube cookies, migration 62 deployment, FK/schema-cache state, and operation payload rows require runtime credentials and are represented as workflow/runbook verification steps rather than committed secrets.
