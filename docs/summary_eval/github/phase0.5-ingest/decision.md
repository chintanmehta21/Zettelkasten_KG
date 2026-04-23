# GitHub Phase 0.5 - decision

## Enrichment API calls (all required)

1. `GET /repos/{slug}/pages` -> Pages deployment URL
2. `GET /repos/{slug}/actions/workflows` -> CI presence and workflow count
3. `GET /repos/{slug}/releases?per_page=5` -> maturity signal
4. `GET /repos/{slug}/languages` -> language composition percentages
5. `GET /repos/{slug}/contents` -> root directory listing for tests, benchmarks, examples, and docs detection

Plus 1 cached Gemini Flash call for the architecture overview.

## Acceptance

- 3 GitHub URLs in `links.txt` all return `extraction_confidence="high"`.
- At least 2 of the 3 URLs should expose multiple enrichment signals.
- `architecture_overview` should be non-empty and at least 50 characters on all 3 URLs.

## Outcome

- `01-readme-only`: `mean_chars=23277.67`, `signal_coverage_pct=0.0`
- `02-full-signals`: `mean_chars=23638.0`, `signal_coverage_pct=100.0`

## Decision

- Keep the full-signal path enabled by default.
- Keep the architecture overview additive and cached.
- Keep GitHub PAT usage optional for the end user by relying on server-side credential discovery; on this machine the `gh` authenticated session is a safe fallback when `GITHUB_TOKEN` is not exported.
