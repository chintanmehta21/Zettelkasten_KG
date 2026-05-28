# Production Issue Sweep — 2026-05-28

Surgical batch fixes after a two-round devil's-advocate sweep. Original 6-fix
plan trimmed to 3 surgical changes; each backed by real evidence (3-day droplet
log + actual `auth.py` source state). No protected-knob changes, no DB DROPs,
no infra changes.

## In-scope (2)

| # | Phase | Touches | Why kept |
|---|---|---|---|
| P0 | JWKS alg allowlist: add `EdDSA` + `PS256` (Supabase optional algs since 2025-05-01) | `website/api/auth.py` (1-line set literal) + 1 test | Latent footgun if Supabase rotates to EdDSA/PS256; cost ≈ 0 |
| P3 | Heartbeat: first-WARN-then-suppress dedup (no backoff cadence) | `website/core/heartbeat.py` (~5 lines) + 1 test | Cheap; prevents future log pollution; observability hygiene |

## Out of scope (4 — dropped/deferred)

| # | Original phase | Verdict | Reason |
|---|---|---|---|
| ~~P1~~ | Reddit OAuth env keys + runbook | **DROP** | Code verification revealed: neither live `RedditIngestor` nor `backfill_chunks.py` actually use OAuth — they just check the vars and warn. Setting the env vars is functionally a no-op. CLAUDE.md doc is inaccurate. Today's 8/8 Reddit success on the re-run via public-JSON path proves current behavior works at our scale. |
| ~~P2~~ | KG edge_drop pg_trgm + NIL placeholder | **DEFER** | 1× in 3 days; real behavior change deserves dedicated iteration |
| ~~P4~~ | Worktree `.git` file parse | **DROP** | Zero prod impact; copy-`api_env` workaround works |
| ~~P5~~ | Topup script Pydantic `model_validate` | **DROP** | Non-prod eval script; fail-loud could break ingest mid-batch |

## Discipline

- Each phase: failing test → minimal fix → green → commit.
- Don't touch `get_optional_user` downgrade behavior — it's by design for anon-tolerant endpoints (`/api/graph`, etc.).
- Don't touch any knob in CLAUDE.md "Critical Infra Decision Guardrails".

Source: `docs/claude_audits/issue_remediation_research_2026-05-28.md` (sibling thirsty-dirac worktree).
