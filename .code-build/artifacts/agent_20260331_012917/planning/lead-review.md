# Lead Review - Planning Phase

## Summary
The planning phase produced a 9-task implementation plan with full TDD coverage for Supabase Auth with Google OAuth. The spec covers all 8 components from the design (C1-C8), and the plan maps every requirement to concrete tasks with exact code.

## Improvement Suggestions
1. **Tasks 1, 2, 5, and 6 are fully independent** — they should all run in parallel in the first wave to maximize speed.
2. **Task 3 depends only on Task 2** (env template), and Task 4 depends on Task 3. These form the critical backend path.
3. **PyJWT installation** should happen at the start of Task 3 (before tests can import `jwt`). Add `PyJWT>=2.8.0` to `ops/requirements.txt` as part of Task 2.
4. **The `_get_supabase()` refactor in Task 4** changes function signature — existing `test_website.py` tests that mock or call `_get_supabase()` may need minor updates to pass `user_id_override`.
5. **Performance**: The `/api/auth/config` endpoint could benefit from caching since the values never change at runtime. A simple module-level dict cache would eliminate repeated `os.environ.get()` calls.

## Recommendations for Execution
- Start with Tasks 1+2+5+6 in parallel (Group A+C), then Task 3, then Task 4, then Tasks 7+8, then Task 9.
- After Task 4, run the full existing test suite (`pytest tests/test_website.py`) to catch any regressions from the `_get_supabase()` signature change.
- The manual post-implementation steps (Google Cloud Console, Supabase Dashboard) should be presented to the user as a checklist after all code tasks complete.

## Parallel Task Groups
- Group A (independent): [Task 1, Task 2, Task 5, Task 6]
- Group B (depends on A): [Task 3]
- Group C (depends on B): [Task 4]
- Group D (depends on C): [Task 7, Task 8]
- Group E (depends on D): [Task 9]
