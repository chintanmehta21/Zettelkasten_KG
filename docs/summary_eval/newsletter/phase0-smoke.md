# Newsletter Phase 0.5 smoke - 2026-04-22

## URL
- `https://www.platformer.news/substack-nazi-push-notification/`

## Exit criteria
- [x] `POST /api/v2/summarize` returns a newsletter-shaped payload
- [x] `summary.detailed_summary.publication_identity` is non-empty
- [x] `summary.detailed_summary.stance` is one of the 5 newsletter enum values
- [x] `summary.detailed_summary.conclusions_or_recommendations` is present
- [x] Branded source `mini_title` includes the publication name

## Result snapshot
- HTTP status: `200`
- `mini_title`: `Platformer: Substack's Inevitable Extremist Content Amplific`
- `publication_identity`: `Platformer by Casey Newton`
- `stance`: `skeptical`
- `cta`: `null`
- `conclusions_or_recommendations` count: `3`

## Notes
- The initial smoke run returned `source_type=newsletter` but still fell back to the generic web-shaped `detailed_summary` list.
- Root cause was the newsletter structured prompt containing unescaped braces in the JSON example, which caused formatter failure before generation.
- After fixing the prompt and custom-domain router coverage, the website endpoint returned the expected newsletter payload shape.
