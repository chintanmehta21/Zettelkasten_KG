eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - YouTube iter-08

## URL 1: DMT lecture

### brief_summary (/25)
The brief now has the right five-sentence shell and it does identify the format, thesis area, and two real figures from the talk. But it still reads as mechanically repaired rather than naturally written. The thesis sentence is grammatically broken, the segment outline names only the first two sections even though the detailed summary shows a much larger structure, and the final takeaway sentence truncates into "DMT is a powerful," which leaves the viewer without a usable conclusion. So this is no longer a fake-chapters failure, but it is still well below a production-grade brief.

Score: 13/25

### detailed_summary (/45)
The detailed section is strong. It follows a coherent arc from mechanism to history, subjective effects, safety, and therapeutic research. It preserves concrete examples and demonstrations, including the Spruce account, Hofmann, McKenna, Strassman's study, survey evidence, and the PTSD/Ayahuasca research thread. Caveats are also present, especially the uncertainty around endogenous function, the psychological-risk language, and the emphasis on set and setting. The only real weakness is that it is quite dense and a little list-heavy, but it remains faithful and useful.

Score: 35/45

### tags (/15)
The tags are specific, source-grounded, and format-aware. They capture the topic cluster cleanly and do not appear to overclaim.

Score: 14/15

### label (/15)
The label is concise and content-first, but it is slightly generic relative to the richer scope of the video. It tells me the topic, not the distinctive angle.

Score: 11/15

### URL 1 subtotal
Score: 73/100

## URL 2: Ross Ulbricht / Silk Road commentary

### brief_summary (/25)
This brief is still structurally broken. It names the thesis area and the format, but the first sentence ends awkwardly at "leading," the segment sentence is clipped, and the closing sentence does not actually contain a takeaway. Speaker capture is thin because Ross Ulbricht is named, but the host voice, collaborators, investigators, and corrupt agents that shape the narrative do not surface in the brief. It feels like a repair template filled with fragments instead of a human-readable summary.

Score: 7/25

### detailed_summary (/45)
The detailed summary is substantially better than the brief. It lays out the chronology from Ulbricht's background through site creation, investigation, corruption, arrest, trial, and aftermath. It names the important entities and people, preserves the technical evidence trail, and keeps the murder-for-hire discussion framed as allegations rather than confirmed killings. The main gap is that there are no explicit demonstrations/examples bullets despite the narrative relying heavily on concrete investigative episodes and supporting evidence.

Score: 28/45

### tags (/15)
The tags are strong overall. They capture the core domain, the main figure, the operational technologies, and the law-enforcement context. Nothing here looks unsupported.

Score: 14/15

### label (/15)
The label is clear and non-clickbait, but it undersells the legal and investigative dimension of the video and reads a bit too generic for such a specific story.

Score: 8/15

### URL 2 subtotal
Score: 57/100

## URL 3: Cannabis Use Disorder commentary

### brief_summary (/25)
This is the weakest brief in the batch. The thesis is partially present, but the sentence truncates at "substantial negative," the speaker line uses the placeholder "The Source," and the final takeaway sentence is effectively empty. The structural outline is better than nothing, yet it only gestures at the first two segments while the detailed summary clearly spans progression, life-stage impacts, relationships, career, and mental health. It fails the user-experience test even though the underlying material is strong.

Score: 5/25

### detailed_summary (/45)
The detailed summary is coherent and source-shaped. It preserves the stance distinction between severe addiction and casual use, then moves through prevalence, progression, the 20s, the 30s, and mental-health effects in a sensible order. It captures the main warnings and practical claims, including the four-week cessation test and the loneliness/isolation loop. The weakness is entity and speaker salience: the summary does not identify an actual presenter or channel and therefore still feels somewhat depersonalized at the top.

Score: 26/45

### tags (/15)
The tags are specific to the topic and appropriately typed with a format tag. They are less rich than the Ross Ulbricht or DMT sets, but they are still accurate.

Score: 14/15

### label (/15)
The label is factual and non-clickbait, though slightly abstract compared with the video's stronger life-consequence framing.

Score: 8/15

### URL 3 subtotal
Score: 53/100

## Anti-patterns
I do not see invented chapters or obvious editorialized stance in this batch. The recurring problem is a brief-generation anti-pattern that is not formally named in the rubric: clipped repair sentences that look structurally compliant while still failing on completeness and readability. URL 3 also comes close to a speakers-absent style failure because "The Source" is not a meaningful speaker identity.

## Most impactful improvement for iter-09
The next loop should stop trying to synthesize the brief from isolated fragments and instead derive it from the validated detailed payload with explicit completeness guards. Concretely, the repair path needs to refuse truncated thesis/takeaway fragments, forbid placeholder speaker entities like "The Source," and require one sentence each for thesis, structure, named people, remembered takeaways, and ending implication before emitting a brief. The detailed layer is already carrying the content; the brief builder is still destroying it during compression.

estimated_composite: 61.0
