# GitHub ingest landscape - 2026-04-22

## References

- GitHub REST API `2022-11-28`; authenticated requests get the higher request budget and are still free for this use case.
- `/repos/{slug}/pages`, `/actions/workflows`, `/releases`, `/languages`, and `/contents` are the canonical sources for the rubric signals this phase needs.

## Key decisions

- No general web search is needed for the signal layer itself because the GitHub REST API is the primary source of truth.
- For local desktop execution, GitHub ingest now falls back to `gh auth token` when `GITHUB_TOKEN` is not exported. That keeps the website behavior robust on this machine without requiring the end user to pass anything beyond the URL.
- Architecture overview remains a single Gemini Flash call cached per repo slug. Failures in that path stay non-fatal so repository ingest still succeeds.
