Implement `docs/rag_eval/common/knowledge-management/iter-10/PLAN.md` strictly phase-by-phase, task-by-task, in the order written. Before EACH phase, read the matching `RES-N` section in `docs/rag_eval/common/knowledge-management/iter-10/RESEARCH.md` for rationale, edge cases, and "Cons NOT to take" — these capture every dead end already explored.

Mandatory pre-flight reading (Phase 0 / Task 3): iter-09's `RESEARCH.md`, `iter09_failure_deepdive.md`, `prior_attempts_knowledge_base.md`, `iter10_solutions_research.md`, `iter10_followup_research.md`, `guardrails_review.md`. Plus root `CLAUDE.md` Critical Infra Decision Guardrails section.

Discipline (non-negotiable):
- TDD per task: failing test → confirm fail → minimal impl → confirm pass → commit. One commit per task.
- Commit subject ≤10 words, conventional prefixes per CLAUDE.md (feat/fix/chore/ci/ops/refactor/docs/test). NO Co-Authored-By, NO AI-tool names.
- Honor CLAUDE.md guardrails: do NOT touch GUNICORN_WORKERS, --preload, FP32_VERIFY_ENABLED, GUNICORN_TIMEOUT (verified 240s prod), RAG_QUEUE_MAX, rerank semaphore, SSE heartbeat, Caddy timeouts, schema-drift gate, kg_users allowlist, teal/amber rule, threshold floors (`_PARTIAL_NO_RETRY_FLOOR`, `_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR`, `_RETRY_TOP_SCORE_FLOOR`).
- Apply Supabase migrations via the existing idempotent BEGIN/COMMIT-wrapped pattern. They do not auto-deploy.
- Phase 0 / Task 2 scout decision GATES Task 10. If scout shows q6/q7 pool already had gold, SKIP Task 10 and document the decision.
- Phase 0 / Task 1 is a 2-LOC docs commit; do not change `run.py:38` value.
- Items 6+7 (admission middleware refactor, mid-flight latency abort) are explicitly DEFERRED to iter-11. Do NOT implement them in iter-10.

Stop and ask the user before: any beyond-plan decision, any guarded-knob touch, any test failure that requires scope expansion, or any commit that would push to remote BEFORE Task 19. Do NOT push until ALL phases land AND `pytest -q` passes (542+ baseline + iter-10 new tests; the 4 pre-existing unrelated failures may persist).

Success criteria: composite ≥85, gold@1_unconditional ≥0.85, gold@1_within_budget ≥0.85, burst 503 rate ≥0.08, zero 502 from upstream-down, zero worker OOMs during eval — ALL three thresholds, not stack-rank.

When in doubt: `RESEARCH.md` first, then ask.
