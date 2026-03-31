# Lead Review - Planning Phase

## Summary
Straightforward gap-fill plan with 2 independent implementation tasks + 1 verification task. No architectural changes needed — the existing code matches the spec well.

## Improvement Suggestions
1. The `kg_graph_view` should use `jsonb_build_object`/`jsonb_agg` (not json_*) for better Supabase compatibility
2. Tasks 1 and 2 are independent and should run in parallel via subagents

## Recommendations for Execution
- Mock the supabase client using `unittest.mock.MagicMock` with chained return values
- Use `@patch.dict(os.environ, ...)` for client.py env var tests
- Match existing test file naming: `tests/test_supabase_kg.py`

## Parallel Task Groups
- Group A (independent): [Task 1: schema view, Task 2: unit tests]
- Group B (depends on A): [Task 3: run full test suite]
