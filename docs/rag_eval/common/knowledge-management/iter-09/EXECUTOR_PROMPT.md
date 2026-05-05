Take over iter-09 RAG-eval recovery for the Zettelkasten project at
`C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault`. Implement
`docs/rag_eval/common/knowledge-management/iter-09/PLAN.md` strictly phase-by-phase,
task-by-task, in the order written. Before EACH phase, read the matching `RES-N`
section in `docs/rag_eval/common/knowledge-management/iter-09/RESEARCH.md` for
rationale, edge cases, and "Cons NOT to take" — these capture every dead end
already explored.

Discipline (non-negotiable):

- TDD per task: write failing test → run to confirm fail → minimal implementation
  → run to confirm pass → commit. One commit per task.
- Commit subject ≤10 words. Use `feat:` / `fix:` / `chore:` / `ci:` / `ops:` /
  `refactor:` / `docs:` / `test:` prefixes per `CLAUDE.md`. NO `Co-Authored-By`
  trailers, NO AI-tool names anywhere in commits.
- Honor `CLAUDE.md` "Critical Infra Decision Guardrails": never touch
  `GUNICORN_WORKERS`, `--preload`, `FP32_VERIFY_ENABLED`, `GUNICORN_TIMEOUT`,
  `RAG_QUEUE_MAX`, the rerank semaphore, SSE heartbeat, Caddy timeouts, the
  schema-drift gate, the `kg_users` allowlist, or teal/amber colour rules.
  Phase 4 is the ONE exception (already chat-approved).
- Apply Supabase migrations via the existing `apply_iter08_migrations.py` pattern
  (idempotent, BEGIN/COMMIT-wrapped). They do not auto-deploy.
- Phase 5 tasks are investigation-only — no code without explicit user approval.
  q5 500 stays HOLD until logs are pulled in Phase 0 / Task 1.
- Phase 6 items are explicitly deferred to iter-10. Do NOT implement them in
  iter-09 even if iter-09 tests pass quickly.

Stop and ask the user before: any beyond-plan decision, any guarded-knob touch
beyond Phase 4, any speculative q5 fix, any test failure that would require
scope expansion, or any commit that would push to remote. Do NOT push until
ALL phases land AND `pytest -q` shows 542+ passing tests AND the local NDCG
hotfix `ee31c85` is included.

When in doubt: `RESEARCH.md` first, then ask.
