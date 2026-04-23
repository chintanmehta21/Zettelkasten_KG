# Reddit ingest landscape - 2026-04-22

## Key decisions

- Anonymous JSON endpoint stays primary. It was fast and reliable across all 4 benchmark URLs in this pass.
- `pullpush.io` stays enrichment-only and only triggers when `comment_divergence_pct >= 20`.
  Rationale: it materially improved recovered-comment coverage after the parameter fix, but anonymous JSON is still the faster and more stable primary ingest path.
- PRAW or OAuth is still not justified here. For read-only ingest, it adds auth surface without improving the benchmark outcome we measured.

## Findings after benchmark

- The phase-0.5 benchmark produced `success_rate=1.00` for both anonymous JSON strategies.
- Both expected removed-comment `r/IAmA` threads showed very high divergence (`86.47%` and `88.66%`) and now yielded positive archive recovery after switching to the bare submission id expected by PullPush.
- Current archive-landscape signals remain noisy: public discussion indicates intermittent PullPush availability, historic Pushshift disruptions after Reddit API restrictions, and partial fallback use of Arctic Shift or mirrors when PullPush misses content.

## Sources checked

- PullPush API entrypoint: <https://pullpush.io/>
- Recent Pushshift outage discussion from March 4, 2026: <https://www.reddit.com/r/pushshift/comments/1rkypsc/outage_pushshift_api_and_data/>
- Community discussion referencing Arctic Shift as an alternative when PullPush is unavailable: <https://www.reddit.com/r/techsupport/comments/1lg4z70/is_there_any_way_to_view_deleted_reddit_accounts/>
