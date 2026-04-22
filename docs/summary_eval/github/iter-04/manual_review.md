eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - GitHub iter-04 (cross-URL probe, URLs #1 and #2)

## brief_summary (/25)
Across both repositories, the brief has improved in structure but still shows the same recurring weakness: sentence clipping under compression. On `fastapi/fastapi`, the purpose and stack are recognizable, but the opening sentence is still too architecture-first and the public-surface line is generic rather than exact. On `encode/httpx`, the same template shape generalizes reasonably well, which is encouraging, but it still reads like a compressed formatter output rather than a polished repo summary.

`brief.user_facing_purpose`: 5/6. Both briefs broadly state what the repos do, though not always with the cleanest user-facing framing.

`brief.architecture_high_level`: 4/5. Architecture is present and useful, but often clipped.

`brief.languages_and_frameworks`: 4/4. Language and core frameworks are captured.

`brief.usage_pattern`: 2/4. Workflow/install information is still weaker than it should be.

`brief.public_surface`: 3/4. Public surfaces are partially captured, but the phrasing is still more generic than exact in the brief layer.

`brief.no_maturity_fabrication`: 2/2. No unsupported maturity inflation appears in the brief.

Subtotal: 20/25.

## detailed_summary (/45)
The detailed summaries generalize much better than the briefs. The core features, architecture, interfaces, and project-health signals remain the strongest part of the GitHub summarizer across both URLs. Exact names are usually preserved, and the cross-repo behavior is far steadier here than in the brief section.

`detailed.features_bullets`: 8/8.

`detailed.architecture_modules`: 7/8.

`detailed.interfaces_exact`: 7/8.

`detailed.operational`: 4/6.

`detailed.limitations_docs`: 4/5.

`detailed.benchmarks_tests_examples`: 4/5.

`detailed.bullets_focused`: 4/5.

Subtotal: 38/45.

## tags (/15)
The tag behavior generalized well across both repos. Count, language, domain, and technical-concept coverage are all strong, and the reserved-tag logic is doing the right thing.

`tags.count_7_to_10`: 2/2.

`tags.domain_tag`: 3/3.

`tags.languages`: 3/3.

`tags.technical_concepts`: 3/3.

`tags.no_unsupported_claims`: 4/4.

Subtotal: 15/15.

## label (/15)
Canonical `owner/repo` labeling generalized correctly across both URLs and no extra descriptors leaked in.

`label.owner_slash_repo`: 10/10.

`label.no_extra_descriptors`: 5/5.

Subtotal: 15/15.

## Anti-patterns explicit check
- `production_ready_claim_no_evidence` (auto_cap=60): no clear trigger in this probe set.
- `invented_public_interface` (auto_cap=60): no clear trigger.
- `label_not_owner_repo` (auto_cap=75): no.

## Editorialization check (global rule)
I do not see three or more unsupported judgment/framing additions.
Count: 0

## FineSurE dimension estimates (subjective)
- faithfulness (0-1): 0.95
- completeness (0-1): 0.87
- conciseness (0-1): 0.85

## G-Eval dimension estimates (0-5 each)
- coherence: 4.2
- consistency: 4.7
- fluency: 4.1
- relevance: 4.5

## Composite computation
base = 0.60 * 88 + 0.20 * 0.95 * 100 + 0.10 * 0.87 * 100 + 0.10 * 4.375 * 20
cap_applied = none
composite = 88.5

## Most impactful improvement for iter-05
The probe suggests the GitHub fixes generalize well in detailed sections and tags, but the brief layer still underperforms across repositories in the same way. The next broadening pass should be narrowly focused on brief sentence quality and exact public-surface phrasing, not on labels or tags again.

estimated_composite: 88.5
