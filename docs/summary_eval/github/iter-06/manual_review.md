eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - GitHub iter-06 (held-out validation)

## brief_summary (/25)
Across the held-out set, the brief layer is generally serviceable on `fastapi/fastapi`, `encode/httpx`, `pydantic/pydantic`, and `tiangolo/typer`, but it is not yet robust enough to survive every repository shape. The catastrophic miss is `psf/requests`, where schema fallback zeroes the brief entirely and therefore dominates the held-out mean. On the non-fallback repos, purpose, stack, and public surfaces are mostly present, though still sometimes phrased more generically than ideal.

`brief.user_facing_purpose`: 4/6.

`brief.architecture_high_level`: 4/5.

`brief.languages_and_frameworks`: 4/4.

`brief.usage_pattern`: 3/4.

`brief.public_surface`: 3/4.

`brief.no_maturity_fabrication`: 2/2.

Subtotal: 20/25.

## detailed_summary (/45)
The held-out detailed summaries remain the strongest layer when the schema route succeeds. They preserve features, architecture, interfaces, and operational signals reasonably well across multiple repositories. The blocker is not normal detailed-summary weakness; it is schema robustness on one held-out repo, which causes a complete structured collapse and forces the pessimistic held-out result.

`detailed.features_bullets`: 7/8.

`detailed.architecture_modules`: 7/8.

`detailed.interfaces_exact`: 6/8.

`detailed.operational`: 4/6.

`detailed.limitations_docs`: 4/5.

`detailed.benchmarks_tests_examples`: 3/5.

`detailed.bullets_focused`: 4/5.

Subtotal: 35/45.

## tags (/15)
Held-out tag behavior is generally solid on the repos that keep the structured path. The schema-fallback repo collapses this entirely, which reinforces that the acceptance miss is being driven by structural failure rather than incremental tag quality.

`tags.count_7_to_10`: 2/2.

`tags.domain_tag`: 3/3.

`tags.languages`: 3/3.

`tags.technical_concepts`: 3/3.

`tags.no_unsupported_claims`: 4/4.

Subtotal: 15/15.

## label (/15)
Canonical `owner/repo` labeling is good on the held-out repos that preserve structure, but the schema-fallback case means the held-out set still cannot be treated as production-grade.

`label.owner_slash_repo`: 9/10.

`label.no_extra_descriptors`: 5/5.

Subtotal: 14/15.

## Anti-patterns explicit check
- `production_ready_claim_no_evidence` (auto_cap=60): not the main issue in this held-out run.
- `invented_public_interface` (auto_cap=60): not the main issue in this held-out run.
- `label_not_owner_repo` (auto_cap=75): not the dominant failure.
- Structural blocker observed: `schema_failure` on `psf/requests`, which effectively acts as the held-out killer here.

## Editorialization check (global rule)
Editorialization is not the primary problem in this held-out set.
Count: 0

## FineSurE dimension estimates (subjective)
- faithfulness (0-1): 0.89
- completeness (0-1): 0.74
- conciseness (0-1): 0.81

## G-Eval dimension estimates (0-5 each)
- coherence: 4.0
- consistency: 4.4
- fluency: 4.1
- relevance: 4.2

## Composite computation
base = 0.60 * 84 + 0.20 * 0.89 * 100 + 0.10 * 0.74 * 100 + 0.10 * 4.175 * 20
cap_applied = pessimistic held-out result dominated by schema failure on one URL
composite = 75.8

## Most impactful improvement for iter-08
The next change should be a narrow GitHub schema-hardening pass aimed specifically at the held-out repo shape that produced schema failure, not a broad prompt rewrite. The held-out aggregate already shows that four repositories are acceptable-ish; the extension work should target `psf/requests`-style payload generation so one malformed structured response cannot zero an otherwise decent held-out batch.

estimated_composite: 75.8
