status: continue_pessimistic

computed_composite: 62.97

## URL: https://github.com/fastapi/fastapi

### Lowest components
- brief.no_maturity_fabrication: 2.0/2
- tags.count_7_to_10: 2.0/2
- tags.domain_tag: 3.0/3

## URL: https://github.com/encode/httpx

### Lowest components
- detailed.benchmarks_tests_examples: 0.0/5
- brief.no_maturity_fabrication: 2.0/2
- tags.count_7_to_10: 2.0/2

### Missed criteria
- detailed.interfaces_exact
- detailed.benchmarks_tests_examples

## URL: https://github.com/psf/requests

### Lowest components
- brief_summary: 0.0/25
- detailed_summary: 0.0/45
- tags: 0.0/15

### Missed criteria
- brief.user_facing_purpose
- brief.architecture_high_level
- brief.languages_and_frameworks
- brief.usage_pattern
- brief.public_surface
- brief.no_maturity_fabrication
- schema_failure
- detailed.features_bullets
- detailed.architecture_modules
- detailed.interfaces_exact
- detailed.operational
- detailed.limitations_docs

### Caps applied
- hallucination_cap: 60

### Anti-patterns
- schema_failure

### ⚠️ HALT / REVERT RECOMMENDED
- composite regressed by -24.2 (>3.0 threshold)
- Consider reverting iter-05 edits: ops/scripts/eval_loop.py, ops/scripts/lib/phases.py, ops/scripts/push_iter_summaries.py, tests/unit/summarization_engine/summarization/test_youtube_schema.py, website/features/summarization_engine/evaluator/prompts.py, website/features/summarization_engine/summarization/youtube/prompts.py, website/features/summarization_engine/summarization/youtube/schema.py
