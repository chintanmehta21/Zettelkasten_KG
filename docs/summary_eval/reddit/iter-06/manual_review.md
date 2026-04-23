eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - Reddit iter-06 (held-out, URL #4)

## brief_summary (/25)
`brief.op_intent_captured`: 5/6. The brief does identify the OP's main move as a personal shift from atheism toward Advaita, so the central subject is present. It loses a point because the phrasing is clipped and drops some of the scientific-intellectual framing that appears central to the post.

`brief.response_range`: 3/6. The brief gestures toward resonance, broader agreement, and pushback, which means the response spread is partially represented. It still reads as compressed fragments rather than a clean range of viewpoints, so the reader does not get an especially usable picture of how the thread diversified.

`brief.consensus_signal`: 3/4. The line about the thread mostly converging on personal journeys from materialism to spirituality does communicate the dominant current. I am leaving one point off because the convergence sentence is grammatically broken enough that the signal is weaker than it should be.

`brief.caveats_surfaced`: 2/3. The brief does preserve the main caution against tying philosophical adoption too tightly to changeable scientific consistency. That is a meaningful caveat, though the summary does not surface the removed-comment limitation that materially affects this thread's evidentiary completeness.

`brief.neutral_tone`: 4/4. The wording stays descriptive rather than preachy or mocking. Even when summarizing disputes, it does not inject its own stance.

`brief.length_5_to_7_sentences`: 0/2. This is four sentences, not the required five to seven.

Subtotal: 17/25.

## detailed_summary (/45)
`detailed.reply_clusters`: 8/10. The detailed section clearly groups major currents rather than turning into a comment-by-comment digest. The clusters are meaningful and distinct, but they are still a little narrow for a high-divergence thread with many recovered comments, so I would expect a bit more breadth if it were fully maxed out.

`detailed.hedged_attribution`: 7/8. Most contested or user-generated claims are presented with appropriate distancing, especially around historical influence and spiritual-scientific interpretation. I am holding back one point because a few bullets still read close to factual narration rather than explicitly marked commenter attribution.

`detailed.counterarguments_included`: 7/7. The summary does a strong job preserving substantive dissent, including disagreement about scientific validation, Western philosophy parallels, text interpretation, and the direct Vedanta-to-quantum lineage claim. This is one of the strongest parts of the output.

`detailed.external_refs_captured`: 5/6. It captures named ideas and figures such as emergent spacetime, conscious agents, Jung, Freud, and quantum-mechanics references without obvious fabrication in the summary itself. I am leaving one point off because the treatment is broad and could be a little clearer about which references are thread claims rather than established historical facts.

`detailed.unresolved_questions`: 4/4. The open questions section is concrete, relevant, and genuinely unresolved by the thread.

`detailed.moderation_context`: 5/5. This is excellent. It explicitly notes the rendered/total mismatch, quantifies divergence, and states that removed comments were recovered via pullpush.io.

`detailed.no_joke_chains`: 5/5. The detailed summary stays focused on substantive discussion and does not over-index on side chatter.

Subtotal: 41/45.

## tags (/15)
`tags.count_7_to_10`: 0/2. There are ten topical tags plus the subreddit tag, so the count exceeds the required range.

`tags.subreddit_present`: 3/3. `r-hinduism` is present.

`tags.thread_type`: 0/3. I do not see a thread-type tag such as `q-and-a`, `experience-report`, or `best-practices`.

`tags.no_value_judgments`: 4/4. The tags are topical and do not encode praise, outrage, or verdicts.

`tags.topical_specificity`: 3/3. The tags are specific and useful rather than generic.

Subtotal: 10/15.

## label (/15)
`label.rsubreddit_prefix`: 6/6. The label begins with `r/hinduism` as required.

`label.central_issue`: 4/5. The title captures the OP's journey well, but it underplays the thread's strong debate around science, Vedanta, and interpretation.

`label.neutral`: 4/4. The label is calm and non-editorialized.

Subtotal: 14/15.

## Anti-patterns
`comment_claim_asserted_as_fact`: not clearly triggered. Most disputed claims are framed as user positions or arguments rather than settled truth.

`missing_removed_comment_note`: not triggered. The moderation-context bullet explicitly acknowledges removed-comment divergence and recovery.

`editorialized_stance`: not triggered. The summary remains neutral.

## Most impactful improvement for iter-07
The biggest remaining issue is still the brief contract. The held-out detailed summary is strong enough to pass most of the Reddit-specific rubric, but the brief remains compressed into brittle sentence fragments and misses the required five-to-seven-sentence shape. For prod-parity, the next improvement should be a deterministic brief post-processor that rewrites Reddit briefs into a fixed neutral template: sentence 1 for OP intent, sentence 2 for dominant reply pattern, sentence 3 for dissent, sentence 4 for consensus level, sentence 5 for caveat or moderation limitation, with optional sentence 6 for open question when present. That would address both readability and the persistent brief-scoring ceiling without disturbing the stronger detailed behavior.

estimated_composite: 82.0
