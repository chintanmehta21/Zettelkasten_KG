eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - Newsletter iter-06 (held-out validation)

## Aggregate
- Held-out mean is 81.54 with min faithfulness 0.80, below the Plan 9 acceptance gate.
- Three URLs are production-grade or near-production-grade; two are capped to 60 and define the extension target.

## Per-URL notes
- Platformer: schema route is healthy and label is branded, but evaluator flags invented-number risk. Stance is skeptical and source fit is otherwise strong.
- Organic Synthesis: high faithfulness and detailed quality, but label/publication handling is capped by `branded_source_missing_publication`; this is likely a rubric/source-classification mismatch because the digest has an identifiable publication-like title.
- beehiiv Email Boosts: evaluator flags invented-number and branded-source issues; likely product/update style needs stronger source-grounded number filtering and beehiiv label/publication consistency.
- Pragmatic Engineer product-minded engineer: capped at 60, likely because label omits publication identity and source-specific stance fields are less explicit in prompt excerpt.
- beehiiv MCP: strong run with optimistic stance, branded label, and no schema fallback.

## Thresholds
- Held-out mean >= 88: no.
- Min faithfulness >= 0.95: no.
- Extension required: yes.

## Extension target
Iter-08 should add source-grounded number/date validation and a publication-identity normalizer for newsletter labels, especially Beehiiv/Pragmatic Engineer/technical digest sources.

estimated_composite: 82.0
