eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - GitHub iter-08 (extension)

## brief_summary (/25)
The extension did not solve the core held-out blocker because the `psf/requests` shape still falls through to schema fallback. On the two non-fallback repos in this extension set, the brief remains generally usable. On the failing repo, the brief is structurally unusable and drags the aggregate down immediately.

`brief.user_facing_purpose`: 4/6.

`brief.architecture_high_level`: 3/5.

`brief.languages_and_frameworks`: 4/4.

`brief.usage_pattern`: 2/4.

`brief.public_surface`: 2/4.

`brief.no_maturity_fabrication`: 2/2.

Subtotal: 17/25.

## detailed_summary (/45)
The non-fallback repos still show acceptable detailed behavior, but the extension cannot be considered successful because one repo shape is still structurally failing rather than merely under-scoring. The extension therefore improves little in the dimension that matters most for release confidence.

`detailed.features_bullets`: 6/8.

`detailed.architecture_modules`: 6/8.

`detailed.interfaces_exact`: 5/8.

`detailed.operational`: 3/6.

`detailed.limitations_docs`: 3/5.

`detailed.benchmarks_tests_examples`: 2/5.

`detailed.bullets_focused`: 4/5.

Subtotal: 29/45.

## tags (/15)
Tags remain fine on the repos that preserve structure, but the fallback case still zeroes the value of the extension as a whole.

`tags.count_7_to_10`: 2/2.

`tags.domain_tag`: 3/3.

`tags.languages`: 3/3.

`tags.technical_concepts`: 2/3.

`tags.no_unsupported_claims`: 4/4.

Subtotal: 14/15.

## label (/15)
Canonical labels are mostly fine, but the extension still cannot be treated as healthy because one repo shape remains schema-fragile.

`label.owner_slash_repo`: 9/10.

`label.no_extra_descriptors`: 5/5.

Subtotal: 14/15.

## Anti-patterns explicit check
- `production_ready_claim_no_evidence`: not the primary issue.
- `invented_public_interface`: not the primary issue.
- `label_not_owner_repo`: not the primary issue.
- Structural blocker persists: `schema_failure` on `psf/requests`.

## Editorialization check (global rule)
Editorialization is not the main concern here.
Count: 0

## FineSurE dimension estimates (subjective)
- faithfulness (0-1): 0.82
- completeness (0-1): 0.63
- conciseness (0-1): 0.78

## G-Eval dimension estimates (0-5 each)
- coherence: 3.8
- consistency: 4.0
- fluency: 3.9
- relevance: 3.9

## Composite computation
base = 0.60 * 60 + 0.20 * 0.82 * 100 + 0.10 * 0.63 * 100 + 0.10 * 3.9 * 20
cap_applied = pessimistic aggregate dominated by schema failure
composite = 66.7

## Most impactful improvement for iter-09
The only remaining honest value in iter-09 is measurement: confirm whether the GitHub source should be closed as degraded after the extension path. The evidence so far suggests yes, because the failure is structural and repo-shape-specific rather than a minor wording gap.

estimated_composite: 66.7
