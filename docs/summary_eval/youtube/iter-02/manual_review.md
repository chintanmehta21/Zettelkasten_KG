eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - YouTube iter-02

## brief_summary (/25)
The brief summary is much stronger than the baseline because it clearly identifies DMT as the main topic, touches history, mechanism, delivery methods, and subjective effects, and avoids the previous fabricated chapter structure. It also surfaces a real high-level thesis about DMT's identity, neurological action, and experiential impact. The main weakness is that the brief appears truncated at the end, so it does not land a clean closing sentence or fully surface the final takeaway. It also still fails to identify the channel/host and does not explicitly name the featured researchers in the brief itself. The format is only implicit unless the reader looks at the detailed payload.

Score: 17/25

## detailed_summary (/45)
The detailed summary is materially improved and now follows a believable chronology from indigenous use and Richard Spruce through synthesis, psychedelic research, prohibition, Strassman's trials, administration modes, theories, and safety. It captures named entities, important mechanisms, subjective reports, and practical cautions with much better coverage than loop 1. The strongest part is that the summary now preserves the video's major educational arcs rather than inventing fake timestamped chapters. The main deduction is structural polish: several segments still use placeholder `00:00` timestamps instead of genuine in-video anchors, and the payload is dense enough that some topic groups feel more like note clusters than clean video segments. Even so, this is a solid source-grounded detailed summary.

Score: 39/45

## tags (/15)
The tags are specific, source-grounded, and useful for retrieval. They capture domain, mechanism, substance, history, and therapeutic context without slipping back into generic boilerplate. The main miss is format metadata: there is no explicit lecture/commentary/documentary-style tag, and there is no creator/channel tag even though the rubric encourages that. Still, this is a strong tag set overall.

Score: 13/15

## label (/15)
The label is much more content-first than the original clickbait title and correctly foregrounds DMT. It is concise and descriptive, though slightly broad and a little list-like. "Identity, History, Effects, and Theories" works for a knowledge note, but it still feels closer to a table-of-contents label than a crisp declarative title. This is a clear improvement over baseline and no longer reads as pure YouTube hook retention.

Score: 13/15

## Anti-patterns
No obvious `invented_chapter` issue in this run. No schema-fallback artifact. Residual issue: speaker/host capture is still weak because the brief does not identify the channel or foreground the key experts, even though some named people appear later in the detailed summary. The remaining timestamp placeholders in several later segments are worth watching, but they do not look like the same hallucinated-structure failure from iter-01.

## Most impactful improvement for iter-03
The next tuning pass should focus on the remaining briefing-quality misses: make the brief a complete 5-7 sentence synthesis, explicitly name the host/channel plus the most important researchers, and ensure the format is stated directly. After that, the next biggest quality lift would be replacing placeholder `00:00` segment anchors with more faithful coarse timestamps or clearer untimed section labeling so the detailed summary stays chronologically grounded without collapsing later sections together.

estimated_composite: 86.0
