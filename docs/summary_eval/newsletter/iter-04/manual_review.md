eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - Newsletter iter-04 (cross-URL probe, URLs #1 and #2)

## URL 1 (Platformer, branded)
- The output is a schema-fallback-like collapse: boilerplate `ID/Title/Tags` text leaked into brief and sections, stance regressed to neutral, and CTA boilerplate was promoted into structured fields.
- Branded behavior degraded: label includes Platformer, but summary quality fails core brief/detailed criteria.
- Rubric read: brief ~8/25, detailed ~10/45, tags ~6/15, label ~9/15. Anti-pattern risk: `stance_mismatch` likely for this URL.

## URL 2 (Organic Synthesis @ Beehiiv, non-branded)
- Strong extraction and structuring; detailed methodology and synthesis sections are rich and source-grounded.
- Type/intent tagging is good (`research-summary`), stance neutral fits source tone, and no obvious footer pollution.
- Remaining weakness: `conclusions_or_recommendations` stays empty and actionability is under-expressed.
- Rubric read: brief ~22/25, detailed ~40/45, tags ~15/15, label ~13/15.

## Cross-URL diagnosis
- This is a generalization failure, not a single-criterion miss: branded URL #1 regressed into fallback/boilerplate mode while non-branded URL #2 remained high.
- Most likely root cause is prompt contamination path for one archetype plus insufficient fallback guardrails against metadata-template leakage (`**ID:**`, `**Title:**`, hash-tag blocks).

## Anti-patterns explicit check
- `stance_mismatch`: yes for URL #1 likely.
- `invented_number`: no clear evidence.
- `branded_source_missing_publication`: no.

## Composite computation (aggregate estimate)
- URL #1 estimate: ~33
- URL #2 estimate: ~87
- Mean estimate: ~60
- cap_applied likely on URL #1 only.

## Most impactful improvement for iter-05
Add strict sanitizer/validator that rejects newsletter payloads containing metadata-template leakage (`**ID:**`, `**Title:**`, markdown heading artifacts, inline hash-tag bundles), then force one regeneration pass; preserve existing high-quality behavior for non-branded Beehiiv path.

estimated_composite: 60.0
