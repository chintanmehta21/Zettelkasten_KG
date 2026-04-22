# GitHub Phase 0.5 smoke - 2026-04-22

## Exit criteria

- [x] POST `/api/v2/summarize` returns a successful GitHub summary response for `owner/repo`
- [ ] `architecture_overview` surfaced explicitly in the summary payload
- [ ] `detailed_summary` exposes populated `public_interfaces`
- [ ] summary metadata directly surfaces `pages_url`, `has_workflows`, `releases`, and `languages`
- [x] `extraction_confidence="high"`

## Results

### API smoke request

URL used:

```text
https://github.com/fastapi/fastapi
```

Observed result:

```text
HTTP 200 OK
mini_title=fastapi/fastapi
extraction_confidence=high
```

### Notes

- The website end-user path now succeeds for a plain GitHub URL with no extra credentials passed by the user.
- The enriched ingest layer did run successfully in the server logs: Pages, workflows, releases, languages, root listing, and architecture generation were all exercised.
- The current `/api/v2/summarize` response shape still does not expose all of those ingest-side GitHub-specific fields directly in the returned summary payload, so those schema-surface items remain follow-up work.
