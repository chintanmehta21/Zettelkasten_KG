# Reddit Phase 0.5 - decision

## Chain (ordered)

1. Anonymous JSON endpoint `<permalink>.json` with UA rotation. Always primary.
2. `pullpush.io/reddit/search/comment/?link_id=<id>` for removed-comment recovery.
   Triggers when `(num_comments - rendered_count) / num_comments >= 20%`.
3. HTML fallback.
4. On full failure: `extraction_confidence="low"` and the downstream rubric composite should be capped accordingly.

## Acceptance bar (per spec section 7.2)

- All 4 Reddit URLs in `links.txt` return `extraction_confidence >= medium`.
- Both `r/IAmA` heroin URLs should ideally yield `pullpush_fetched > 0`.
- Divergence percentages must be recorded in metadata so the evaluator can score missing or removed comments.

## Benchmark outcome

- `01-anon-json-only`: `success_rate=1.0`, `mean_chars=15483.25`, `total_pullpush_fetched=0`
- `02-anon-json-plus-pullpush`: `success_rate=1.0`, `mean_chars=23651.25`, `total_pullpush_fetched=94`

## Decision

- Keep anonymous JSON as the dominant Reddit ingest strategy.
- Keep pullpush enrichment enabled but strictly conditional.
- Treat `comment_divergence_pct` as the trigger signal for archive recovery and as evaluator-visible moderation context.

## Notes

- The benchmark now fully supports the intended phase-0.5 path: all 4 URLs came back with `extraction_confidence="high"` and divergence metadata is present.
- Both `r/IAmA` heroin threads recovered archived comments successfully, so conditional pullpush enrichment is justified as the second-stage Reddit ingest path.
