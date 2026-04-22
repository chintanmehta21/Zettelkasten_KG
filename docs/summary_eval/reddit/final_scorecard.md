# Reddit - Final Scorecard

## Per-loop progression
| Loop | URLs | Composite (mean) | Faithfulness (min) | Notes |
|---|---|---:|---:|---|
| 1 (baseline) | #1 | 70.30 | 0.67 | baseline; weak brief, missing thread-type tag, missing moderation note handling |
| 2 (tune) | #1 | 92.95 | 1.00 | major recovery after hedging, moderation-context, and label/tag repairs |
| 3 (tune) | #1 | 95.65 | 1.00 | training URL near ceiling; still somewhat overfit to known thread shape |
| 4 (probe) | #1, #2 | 58.00 | 0.545 | overfitting surfaced on heroin thread; brief and label quality collapsed |
| 5 (joint) | #1, #2, #3 | 75.63 | 0.50 | broader Reddit tune helped but did not clear convergence gate |
| 6 (held-out) | #4 | 81.10 | 0.82 | first held-out miss; triggered extension path |
| 7 (prod-parity) | skipped | n/a | n/a | skipped in this closeout because a Naruto-compatible login path was not available from the current worktree |
| 8 (extension) | #1, #2, #3 | 85.12 | 0.80 | fixed recurring thread-type-tag loss and improved brief recovery |
| 9 (extension final) | #4 | 94.18 | 0.909 | held-out recovered strongly after extension; no caps or anti-patterns fired |

## Acceptance (spec §10.1)
- [ ] Training URL composite >= 92 in >= 3 of last 5 tuning iters
- [ ] Training URL ragas_faithfulness >= 0.95
- [ ] URLs #1, #2, #3 each >= 88 at loop 5
- [ ] Held-out URL #4 composite >= 88 + ragas >= 0.95
- [ ] Prod-parity delta <= 5
- [x] No hallucination cap triggered in loops 5-9
- [x] `r/<subreddit>` label regex match held in the final held-out run

**Overall: DEGRADED**

## What Improved
- Reserved-tag normalization now keeps the subreddit tag and thread-type tag even when the topical tag list is already full.
- Reddit brief repair now prioritizes caveat retention and produces materially cleaner held-out briefs than iter-06.
- Held-out quality improved from 81.10 to 94.18 after the extension pass, with no anti-pattern caps in the final held-out run.

## Root Cause Of The Remaining Gap
- The held-out composite recovered above threshold, but faithfulness stayed at 0.909 rather than the required 0.95.
- The remaining miss is mostly in brief compression rather than detailed-structure coverage: the content is now broadly right, but the brief formatter still over-compresses sentence shape and nuance.
- Cross-URL stability remains weaker than the spec target because loop-5 never cleared the multi-URL >= 88 gate for URLs #1-#3.

## Prod-Parity Note
- The requested Naruto final iteration could not be executed from the current worktree because the expected `docs/login_details.txt` path was unavailable here.
- Per the fallback instruction, the plan was closed using the final CLI held-out iteration instead of blocking on unavailable prod-parity auth.

## Pullpush Enrichment Verification
- Moderation divergence was preserved in the detailed summaries on the high-divergence Reddit threads and remained present in the final held-out output.
- The cached summary metadata in this worktree did not expose a reliable `pullpush_fetched` count for scorecard automation, so the verification evidence here is qualitative rather than numeric.

## Lessons
- Tag normalization needs reserved slots for rubric-critical tags; appending them and truncating later is not robust enough.
- Brief repair needs sentence-priority rules, not just sentence-count rules, or caveats and dissent will keep getting dropped under length pressure.
- Held-out recovery was possible without further evaluator changes; the productive fixes were Reddit-schema-local rather than rubric or evaluator edits.

## Known Risks
- Prod-parity verification was skipped in this closeout because a usable Naruto login path was not available from the current worktree.
- The single held-out URL gives low statistical power even though the final held-out score recovered strongly.
- Faithfulness is still below the formal production-grade threshold on the final held-out run.
