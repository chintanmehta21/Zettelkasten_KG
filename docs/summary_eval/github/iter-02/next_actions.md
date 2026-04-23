status: continue

computed_composite: 83.00

## URL: single

### Lowest components
- label: 10.0/15
- tags: 13.0/15
- brief_summary: 22.0/25

### Missed criteria
- brief.no_maturity_fabrication
- detailed.limitations_docs
- tags.no_unsupported_claims
- label.no_extra_descriptors

### ⚠️ HALT / REVERT RECOMMENDED
- composite regressed by -17.0 (>3.0 threshold)
- Consider reverting iter-02 edits: ops/scripts/eval_loop.py, ops/scripts/lib/phases.py, ops/scripts/push_iter_summaries.py, tests/unit/summarization_engine/summarization/test_youtube_schema.py, website/features/summarization_engine/evaluator/prompts.py, website/features/summarization_engine/summarization/youtube/prompts.py, website/features/summarization_engine/summarization/youtube/schema.py
