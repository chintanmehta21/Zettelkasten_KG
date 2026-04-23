# Newsletter Phase 0.5 - decision

## Chain
1. Keep the existing body extractor and paywall fallback chain as the base path.
2. Layer site-specific DOM extraction on top for Substack, Beehiiv, Medium, and Ghost-style custom-domain newsletter pages.
3. Extract `preheader` from explicit meta tags first, then body-prefix fallback.
4. Extract CTA anchors with regex filtering and boilerplate suppression.
5. Detect conclusions from both sentence prefixes and takeaways/action-item list headers near the body tail.
6. Run a cached newsletter-specific stance classifier keyed by URL.
7. Route branded newsletter custom domains to the newsletter summarizer so `/api/v2/summarize` returns newsletter payloads instead of the generic web schema.

## Benchmark outcome
- `01-trafilatura-baseline`: mean chars `9183`, signal coverage `3/3`
- `02-site-specific-plus-structural`: mean chars `9713`, signal coverage `3/3`

## Per-URL outcome from `02-site-specific-plus-structural`
- Platformer: `site=ghost`, `publication_identity=Platformer`, `cta_count=3`, `stance=neutral`
- Synthesis Spotlight: `site=beehiiv`, `publication_identity=Synthesis Spotlight`, `cta_count=1`, `stance=neutral`
- beehiiv Product Updates: `site=beehiiv`, `publication_identity=Product Updates`, `cta_count=5`, `stance=neutral`

## Acceptance status
- All 3 benchmark URLs returned `extraction_confidence=high`.
- All 3 URLs now populate `publication_identity` in ingest metadata.
- All 3 URLs surface structural coverage through at least one of preheader or CTA.
- Live `/api/v2/summarize` on Platformer now returns newsletter-shaped `detailed_summary` with `publication_identity`, `stance`, and `conclusions_or_recommendations`.

## Follow-up
- Add more branded custom domains as they appear in real user traffic instead of assuming all newsletters stay on provider-owned hosts.
