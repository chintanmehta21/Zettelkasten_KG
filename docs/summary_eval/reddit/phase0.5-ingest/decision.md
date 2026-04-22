# Reddit Phase 0.5 - decision

## Chain (ordered)

1. Anonymous JSON endpoint `<permalink>.json` with UA rotation. Always primary.
2. `pullpush.io/reddit/search/comment/?link_id=t3_<id>` for removed-comment recovery.
   Triggers when `(num_comments - rendered_count) / num_comments >= 20%`.
3. HTML fallback.
4. On full failure: `extraction_confidence="low"` and the downstream rubric composite should be capped accordingly.

## Acceptance bar (per spec section 7.2)

- All 4 Reddit URLs in `links.txt` return `extraction_confidence >= medium`.
- Both `r/IAmA` heroin URLs should ideally yield `pullpush_fetched > 0`.
- Divergence percentages must be recorded in metadata so the evaluator can score missing or removed comments.

## Benchmark outcome

- `01-anon-json-only`: `success_rate=1.0`, `mean_chars=15483.25`, `total_pullpush_fetched=0`
- `02-anon-json-plus-pullpush`: `success_rate=1.0`, `mean_chars=15483.25`, `total_pullpush_fetched=0`

## Decision

- Keep anonymous JSON as the dominant Reddit ingest strategy.
- Keep pullpush enrichment enabled but strictly conditional.
- Treat `comment_divergence_pct` as the key measurable signal for moderation or missing-comment context, even when pullpush does not recover text.

## Notes

- The benchmark partially meets the acceptance bar: all 4 URLs came back with `extraction_confidence="high"` and divergence metadata is present.
- The expected recovery signal on the two `r/IAmA` threads did not materialize in this environment, so the enrichment path should remain best-effort rather than being promoted or made mandatory.
