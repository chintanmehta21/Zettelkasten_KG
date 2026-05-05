Implement `docs/rag_eval/common/knowledge-management/iter-11/PLAN.md` strictly phase-by-phase, task-by-task, in the order written. Before EACH phase, read the matching `Class A/B/C/D/F/E1/E2` section in `docs/rag_eval/common/knowledge-management/iter-11/RESEARCH.md` for rationale, edge cases, and "Cons NOT to take" — they capture every dead end already explored.

Mandatory pre-flight reading (Phase 0 / Task 1): iter-10 `scores.md`, `PLAN.md`, `RESEARCH.md`; iter-09 `iter09_failure_deepdive.md` (note: its auto-title-Gemini claim is wrong — see iter-10 RES-7 correction); root `CLAUDE.md` Critical Infra Decision Guardrails.

Discipline (non-negotiable):
- TDD per task: failing test → confirm fail → minimal impl → confirm pass → commit. One commit per task.
- Commit subject ≤ 10 words, conventional prefixes per CLAUDE.md (feat/fix/chore/ci/ops/refactor/docs/test). NO Co-Authored-By, NO AI-tool names.
- Honor CLAUDE.md guardrails. Class F has explicit operator approval for an ADDITIVE per-class offset above the LOOKUP-default `_PARTIAL_NO_RETRY_FLOOR=0.5` literal (NOT lowering the literal). Hard-clamp to ≥ 0.3.
- Phase 0 / Task 2 q10 scout decision GATES the Class C implementation choice. If the scout reveals a metadata-extraction gap, ship Class C per-entity loop AND patch the metadata extractor; document in RESEARCH.md.
- Class B requires a new fixture in `tests/unit/rag/integration/test_class_x_source_matrix.py`.
- Class E2 is investigative; runs DevTools `EventSource` smoke before deciding whether to keep `p_user` honest or modify the Playwright harness. Document the verdict in RESEARCH.md.
- iter-11 `scores.md` follows the canonical iter-09/iter-10 template — NO fix recommendations, NO root-cause tables. Those go in chat or RESEARCH.md.

Stop and ask the user before: any beyond-plan decision, any guarded-knob touch outside Class F, any test failure requiring scope expansion, or any commit that would push to remote BEFORE Task 10. Do NOT push until ALL phases land AND `pytest -q` passes.

Success criteria: composite ≥ 85, gold@1_unconditional ≥ 0.85, gold@1_within_budget ≥ 0.85 (post-E1 N/A treatment), zero worker OOMs.

When in doubt: RESEARCH.md first, then ask.

Dashboard-only mode on UNTIL FINAL DEPLOY UNLESS YOU NEED A DECISION CLARIFICATION. DO NOT MAKE DECISIONS YOURSELF.
