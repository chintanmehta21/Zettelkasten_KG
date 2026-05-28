# Production Issue Sweep — 2026-05-28

Surgical batch fixes for 6 production / diagnostic issues surfaced during the
Naruto top-up audit. Each phase is one focused commit with tests.

| # | Phase | Severity | Touches |
|---|---|:---:|---|
| P0 | JWT reject-with-401 + JWKS multi-alg validator | CRITICAL | `website/api/auth.py`, settings, tests |
| P1 | Reddit OAuth env keys + droplet rollout note | HIGH | `ops/.env.example`, runbook doc |
| P2 | KG edge_drop: pg_trgm fuzzy + NIL placeholder (quick fix) | HIGH | `website/api/routes.py` graph build, migration |
| P3 | Heartbeat: first-WARN-then-suppress + exp backoff | LOW-MED | `website/core/heartbeat.py`, tests |
| P4 | Worktree path discovery: `.git` file parse | LOW | `website/features/api_key_switching/key_pool.py`, tests |
| P5 | Topup script: Pydantic `model_validate` + fail-loud | LOW | `docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py` |

Each phase: failing test first → minimal fix → green → commit. No protected-knob
changes. No DB DROPs. No infra changes.

Source: `docs/claude_audits/issue_remediation_research_2026-05-28.md` (in the
sibling thirsty-dirac worktree).
