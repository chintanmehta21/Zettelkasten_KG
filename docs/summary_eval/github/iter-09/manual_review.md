eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - GitHub iter-09 (extension final, held-out)

## brief_summary (/25)
The final held-out GitHub run still does not clear the acceptance bar because the source remains structurally inconsistent across repository shapes. `fastapi/fastapi` is excellent, `encode/httpx` is acceptable, `psf/requests` recovered compared with the earlier collapse, but `pydantic/pydantic` remains soft and `tiangolo/typer` now collapses hard enough to sink the held-out mean. This means the source is not failing everywhere; it is failing unpredictably on certain repo forms, which is even more important to document honestly.

`brief.user_facing_purpose`: 4/6.

`brief.architecture_high_level`: 3/5.

`brief.languages_and_frameworks`: 4/4.

`brief.usage_pattern`: 2/4.

`brief.public_surface`: 2/4.

`brief.no_maturity_fabrication`: 2/2.

Subtotal: 17/25.

## detailed_summary (/45)
The detailed layer is still strong on some held-out repos but not robust enough as a source-wide contract. The final held-out set proves that the GitHub summarizer can produce high-quality outputs for certain repositories, but cannot yet reliably avoid structural or faithfulness collapse across all repo shapes in the held-out pool.

`detailed.features_bullets`: 5/8.

`detailed.architecture_modules`: 5/8.

`detailed.interfaces_exact`: 4/8.

`detailed.operational`: 3/6.

`detailed.limitations_docs`: 3/5.

`detailed.benchmarks_tests_examples`: 2/5.

`detailed.bullets_focused`: 4/5.

Subtotal: 26/45.

## tags (/15)
Tagging is not the main issue. When structure holds, tags are mostly useful; when structure degrades, tags degrade with it.

`tags.count_7_to_10`: 2/2.

`tags.domain_tag`: 3/3.

`tags.languages`: 2/3.

`tags.technical_concepts`: 2/3.

`tags.no_unsupported_claims`: 4/4.

Subtotal: 13/15.

## label (/15)
Canonical labels are mostly preserved even in weak runs, so the remaining blocker is not label formatting.

`label.owner_slash_repo`: 9/10.

`label.no_extra_descriptors`: 5/5.

Subtotal: 14/15.

## Anti-patterns explicit check
- `production_ready_claim_no_evidence`: not the dominant issue.
- `invented_public_interface`: contributes risk on weaker held-out repos but is not the only failure mode.
- `label_not_owner_repo`: not the dominant issue.
- Final blocker is held-out instability across repo shapes, especially the `tiangolo/typer` collapse.

## Editorialization check (global rule)
Editorialization is not the key failure mode here.
Count: 0

## FineSurE dimension estimates (subjective)
- faithfulness (0-1): 0.72
- completeness (0-1): 0.64
- conciseness (0-1): 0.77

## G-Eval dimension estimates (0-5 each)
- coherence: 3.7
- consistency: 3.9
- fluency: 3.8
- relevance: 3.8

## Composite computation
base = 0.60 * 70 + 0.20 * 0.72 * 100 + 0.10 * 0.64 * 100 + 0.10 * 3.8 * 20
cap_applied = pessimistic held-out result dominated by repo-shape instability
composite = 70.0

## Most impactful improvement for the next loop
If GitHub were to be revisited in a future plan, the work should move away from brief formatting polish and toward repo-shape-aware structured extraction, especially for CLI-first and older-library repositories. The current source should be closed as degraded rather than stretched further in this loop.

estimated_composite: 70.0
