eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - Reddit iter-08 (extension tune, URLs #1-#3)

## brief_summary (/25)
`brief.op_intent_captured`: 5/6. Across the three URLs, the briefs now state the OP's central claim more directly than earlier loops. They still lose precision in places because some first sentences remain clipped by aggressive shortening, especially on the Rajkot and heroin threads.

`brief.response_range`: 4/6. The dominant reply pattern and at least one dissent lane are present in each brief, which is a real improvement. The remaining weakness is that the range is still compressed into broad headings rather than a fully readable spread of major advice, disagreement, and practical implications.

`brief.consensus_signal`: 3/4. Each brief now makes the center of gravity clearer, especially for the heroin threads where addiction warnings dominate. One point stays off because the consensus line is still template-shaped and sometimes too terse to express how strong or partial the agreement really was.

`brief.caveats_surfaced`: 2/3. The extension tune improved caveat handling conceptually, but it is not yet reliably surviving the final brief output on every URL. When the caveat line drops or gets squeezed, the moderation/risk signal remains underpowered relative to the rubric.

`brief.neutral_tone`: 4/4. The briefs stay restrained and do not add new judgment.

`brief.length_5_to_7_sentences`: 1/2. The brief builder is closer to the contract, but some outputs still land short after truncation pressure.

Subtotal: 19/25.

## detailed_summary (/45)
`detailed.reply_clusters`: 9/10. The outputs now consistently represent major opinion clusters instead of individual comments. The heroin threads especially show strong clustering around addiction warnings, autonomy/dissent, and harm-reduction implications.

`detailed.hedged_attribution`: 8/8. The summaries are generally careful to present user claims as thread claims rather than ground truth.

`detailed.counterarguments_included`: 7/7. Important minority views remain visible across all three URLs.

`detailed.external_refs_captured`: 5/6. External references and concrete examples are captured meaningfully, though the Rajkot thread could still make cited evidence feel slightly more anchored to named sources rather than condensed narrative.

`detailed.unresolved_questions`: 4/4. Open questions are clearly present and useful.

`detailed.moderation_context`: 4/5. The removed-comment divergence is captured where it matters and the heroin threads benefit from that. I am leaving one point off because this context is stronger in the detailed section than in the brief, which creates an avoidable mismatch.

`detailed.no_joke_chains`: 5/5. The summaries stay focused on substance.

Subtotal: 42/45.

## tags (/15)
`tags.count_7_to_10`: 2/2. The tag count is now in range.

`tags.subreddit_present`: 3/3. Present throughout.

`tags.thread_type`: 3/3. The thread-type tag now survives even on dense tag sets, which fixes a real recurring failure mode.

`tags.no_value_judgments`: 4/4. Neutral throughout.

`tags.topical_specificity`: 3/3. The topical tags remain strong and source-specific.

Subtotal: 15/15.

## label (/15)
`label.rsubreddit_prefix`: 6/6. Correct across all three URLs.

`label.central_issue`: 4/5. The labels are compact and broadly accurate, though the Rajkot label still compresses a debate-heavy thread into a narrower frame than ideal.

`label.neutral`: 4/4. Neutral throughout.

Subtotal: 14/15.

## Anti-patterns
`comment_claim_asserted_as_fact`: not clearly triggered.

`missing_removed_comment_note`: not clearly triggered in the detailed summaries, though brief-level caveat persistence still needs work.

`editorialized_stance`: not triggered.

## Most impactful improvement for iter-09
The extension closed the tagging hole, but the remaining ceiling is still the brief writer under a hard character budget. The next measurement loop should verify whether the new reserved thread-type behavior generalizes and whether the brief post-repair is now stable enough across all three training URLs. If another tuning pass were needed after that, it should not touch tags again; it should instead make the brief compressor sentence-priority-aware so caveat and dissent lines cannot be dropped when the summary is forced under length.

estimated_composite: 86.0
