eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - YouTube iter-04

## URL 1: DMT video

### brief_summary (/25)
This brief regresses from iter-03. It opens with a usable thesis and identifies the piece as a video, but the phrasing is awkward, the format cue is weak because it falls back to `other`, and the brief truncates mid-sentence at "Featured voices include Dr." That truncation means the speaker requirement is not actually satisfied, the major section outline is only partial, and the 5-7 sentence target is missed by a wide margin. The output is still source-grounded, but it no longer feels production-ready at the top level.

Score: 11/25

### detailed_summary (/45)
The detailed summary remains the strongest part. It preserves the overall chronology from indigenous and scientific history through chemistry, subjective effects, safety, endogenous DMT theories, and therapeutic research. Named experts, compounds, and cautions are captured well, and sponsor filler is excluded. The main deductions are that some segment timestamps are still coarse `N/A` anchors and a few examples are close to verbatim anecdote carryover rather than compact purpose-focused synthesis.

Score: 40/45

### tags (/15)
The topical tags are strong and specific, but the format tag regresses because `other` is too generic to be very useful. The set is still retrieval-friendly and does not obviously imply unsupported topics.

Score: 13/15

### label (/15)
The label is content-first and non-clickbait, but it is somewhat flat and generic. It identifies the subject correctly without hook retention, so the main issue is polish rather than faithfulness.

Score: 13/15

### URL 1 subtotal
Score: 77/100

## URL 2: Silk Road video

### brief_summary (/25)
This brief is much better. It states the format, central thesis, and the main causal arc from ideology and marketplace operation to investigation, arrest, and sentencing. The main remaining miss is that it compresses everything into one long sentence, so it still does not read like the rubric's intended 5-7 sentence viewer-oriented brief with clearly surfaced segments and takeaways.

Score: 19/25

### detailed_summary (/45)
The detailed summary is strong, chronological, and specific. It covers Ulbricht's background, Silk Road operations, the investigation, corrupt agents, the murder-for-hire allegations, and the trial/sentencing sequence. Important entities and dates are preserved, and the structure reads like a useful note rather than transcript debris.

Score: 44/45

### tags (/15)
The tags are specific, balanced, and include the needed format signal. They cover topic, ideology, infrastructure, and law-enforcement context without drifting into unsupported claims.

Score: 15/15

### label (/15)
The label is concise, content-first, and accurately centered on the video's main topic. It is plain but effective, with no clickbait retention.

Score: 14/15

### URL 2 subtotal
Score: 92/100

## Anti-patterns
No invented chapter issue is visible in either sample. The main regression is robustness of the brief layer: URL 1 shows a real truncation failure and a generic format fallback, while URL 2 still compresses too much information into a single sentence. This means the schema-side repair improved some cases but is not yet consistently durable across different YouTube transcript shapes.

## Most impactful improvement for iter-05
The next tuning pass should harden brief synthesis so it cannot terminate mid-speaker list and cannot settle on `other` when the transcript clearly supports a documentary/commentary/explainer-style cue. The best fix is likely deterministic post-processing that expands short or truncated briefs into a complete 5-7 sentence paragraph from already-extracted thesis, segments, speakers, and closing takeaway, while also banning incomplete trailing speaker prefixes like "Featured voices include Dr."

estimated_composite: 84.5
