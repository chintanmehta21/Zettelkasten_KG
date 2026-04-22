eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - GitHub iter-05 (joint tune, URLs #1-#3)

## brief_summary (/25)
Across the three training URLs, the GitHub brief is now much closer to the rubric contract than in earlier loops. Purpose, stack, and public surfaces are usually present, and the usage sentence survives more consistently. The remaining weakness is that the brief still sounds repaired rather than naturally authored, and some public-surface phrasing is broader than the exact interface-level ideal.

`brief.user_facing_purpose`: 5/6.

`brief.architecture_high_level`: 4/5.

`brief.languages_and_frameworks`: 4/4.

`brief.usage_pattern`: 3/4.

`brief.public_surface`: 3/4.

`brief.no_maturity_fabrication`: 2/2.

Subtotal: 21/25.

## detailed_summary (/45)
The detailed summaries are now the most reliable part of the GitHub source. Feature bullets, architecture, operational cues, interfaces, and project-health signals all generalize well across the training set. The only consistent gap is that some repo-specific public surfaces are still summarized a little too generically instead of always being named with the sharpest possible exactness.

`detailed.features_bullets`: 8/8.

`detailed.architecture_modules`: 7/8.

`detailed.interfaces_exact`: 7/8.

`detailed.operational`: 5/6.

`detailed.limitations_docs`: 4/5.

`detailed.benchmarks_tests_examples`: 4/5.

`detailed.bullets_focused`: 4/5.

Subtotal: 39/45.

## tags (/15)
The tags now generalize strongly across the GitHub training set. They stay in range, carry language and domain information, and preserve useful technical concepts without drifting into unsupported maturity claims.

`tags.count_7_to_10`: 2/2.

`tags.domain_tag`: 3/3.

`tags.languages`: 3/3.

`tags.technical_concepts`: 3/3.

`tags.no_unsupported_claims`: 4/4.

Subtotal: 15/15.

## label (/15)
Canonical `owner/repo` labeling is now stable across the joint set and no extra descriptors are leaking back in.

`label.owner_slash_repo`: 10/10.

`label.no_extra_descriptors`: 5/5.

Subtotal: 15/15.

## Anti-patterns explicit check
- `production_ready_claim_no_evidence` (auto_cap=60): not clearly triggered.
- `invented_public_interface` (auto_cap=60): not clearly triggered.
- `label_not_owner_repo` (auto_cap=75): not triggered.

## Editorialization check (global rule)
The summaries remain descriptive and source-grounded.
Count: 0

## FineSurE dimension estimates (subjective)
- faithfulness (0-1): 0.96
- completeness (0-1): 0.90
- conciseness (0-1): 0.87

## G-Eval dimension estimates (0-5 each)
- coherence: 4.3
- consistency: 4.7
- fluency: 4.2
- relevance: 4.6

## Composite computation
base = 0.60 * 90 + 0.20 * 0.96 * 100 + 0.10 * 0.90 * 100 + 0.10 * 4.45 * 20
cap_applied = none
composite = 91.1

## Most impactful improvement for iter-06
The GitHub training set now looks strong enough that the next meaningful signal is held-out behavior rather than more local polishing. If another content change becomes necessary after the held-out run, it should be narrowly about exact public-surface wording in the brief, not about tags or labels.

estimated_composite: 91.1
