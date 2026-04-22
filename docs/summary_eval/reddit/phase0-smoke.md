# Reddit Phase 0.5 smoke - 2026-04-22

## Exit criteria (per spec section 7.2 plus section 6.1)

- [x] POST `/api/v2/summarize` returns a successful Reddit summary response
- [ ] `reply_clusters` is non-empty (>= 1)
- [ ] If source had removed comments, `pullpush_fetched > 0` in metadata
- [x] `comment_divergence_pct` present in metadata

## Results

### API smoke request

Command target:

```bash
POST http://127.0.0.1:10000/api/v2/summarize
```

Payload:

```json
{"url":"https://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and/"}
```

Observed result:

```text
HTTP 200 OK
summary response returned for the Reddit URL after Gemini key discovery was fixed for the worktree
```

Status: API summarize is working locally again after fixing Gemini key discovery.

### Ingest-side validation from benchmark artifacts

- All 4 benchmark URLs returned `extraction_confidence="high"`.
- `comment_divergence_pct` was present for each benchmarked URL.
- The two expected removed-comment `r/IAmA` URLs now show positive `pullpush_fetched` counts in the refreshed benchmark artifacts.
