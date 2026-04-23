eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - Newsletter iter-05 (joint tune, URLs #1/#2/#3)

## URL 1 (Platformer, branded)
- Major recovery from iter-04: schema fallback resolved, branded label present, stance preserved, and evidence/conclusion quality is strong.
- Residual issue is slight uncertainty language (`likely via Platformer`) where publication identity should be asserted directly for a clearly branded source.
- Estimated rubric: brief 23/25, detailed 41/45, tags 14/15, label 14/15.

## URL 2 (Organic Synthesis digest, non-branded)
- High factual density and good sectioning for methodology/total synthesis content.
- Compactness is weaker in detailed bullets (some are overly long), and publication identity remains generic.
- Estimated rubric: brief 23/25, detailed 39/45, tags 15/15, label 12/15.

## URL 3 (beehiiv product/newsletter growth)
- Strong coverage of thesis and practical framing; stance/intent handling looks appropriate.
- Minor risk: label and tags are slightly product-marketing-centric and could over-compress nuance if source contains caveats.
- Estimated rubric: brief 22/25, detailed 38/45, tags 14/15, label 14/15.

## Anti-patterns explicit check
- `stance_mismatch`: no clear hit in this loop.
- `invented_number`: no obvious invented numbers observed.
- `branded_source_missing_publication`: no hit on URL 1; URL 2/3 are non-branded.

## Aggregate view
- Mean quality is now near acceptance for training URLs, but still below strict loop-5 gate (all three >=88) because URL 2/3 remain just under ceiling on detailed specificity/label precision.

## Most impactful improvement for iter-06+
Target concise-but-specific detailed bullets for long technical digests and tighten publication-identity confidence handling (avoid hedged phrasing for clearly branded sources).

estimated_composite: 87.0
