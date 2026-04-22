eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - Reddit iter-01 (baseline, URL #1)

## brief_summary (/25)
The brief does capture the OP's core claim in neutral language and it does name the dominant response pattern: many commenters think the Hyundai IPO underperformed because of valuation and structure rather than Rajkot-specific sentiment. What it does not do is fully show the response range, consensus shape, or the caveat layer around missing evidence and removed comments. It is also only one sentence, so it misses the required 5-7 sentence format. The tone stays neutral, which is good, but the brief still feels under-expanded for a Reddit thread with multiple competing explanations and strong skepticism about the original framing.

Score: 15/25

## detailed_summary (/45)
The detailed summary is strong on major reply clusters, hedged attribution, and counterarguments. It preserves the main dissent themes around plagiarism, exaggerated Rajkot influence, the 26x valuation, the OFS structure, and pre-IPO dividend and royalty decisions. It also keeps open questions instead of flattening the thread into a false consensus. The key miss is moderation context: the source clearly shows a large rendered-versus-total comment gap plus recovered comments, but the summary leaves `moderation_context` null and does not explain that removed comments materially affect what was visible. That omission matters for this rubric and likely caps the score ceiling.

Score: 34/45

## tags (/15)
The tags are topical, but they are still under-shaped for the Reddit rubric. There is no subreddit tag in the expected `r-...` style, no thread-type tag, and the hashtag formatting feels closer to social-post keywords than production Reddit note tags.

Score: 9/15

## label (/15)
The label starts with the subreddit prefix, which is the most important structural requirement, and it does point at the central issue. But it is too long, clipped at the end, and feels more like a rough title fragment than a finished compact label.

Score: 11/15

## Anti-patterns
I do not see obvious editorialized stance here, and the detailed section generally uses appropriate hedging for commenter claims. The big anti-pattern risk is `missing_removed_comment_note`: the source had substantial divergence and explicit recovered comments, but the summary does not surface that moderation gap. That is the most important improvement target for iter-02.

## Most impactful improvement for iter-02
The next loop should explicitly bind moderation metadata into the Reddit structured output whenever comment divergence is high. This thread already has the right discussion clusters and mostly sound hedging, so the fastest score gain is not more content density but stronger Reddit-specific framing: mention that rendered comments understate the full thread, preserve that removed-comment recovery happened, add a subreddit tag plus thread-type tag, and force the brief into a real 5-7 sentence summary that distinguishes OP claim, main pushback, and the strongest caveats.

estimated_composite: 69.0
