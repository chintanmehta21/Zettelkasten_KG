eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - YouTube iter-06

## Held-out assessment
The held-out behavior is clearly better than the weak cross-URL results from iter-05, but the same brief-layer issue still shows up: both summaries are anchored by strong detailed sections while the top brief remains compressed, slightly awkward, and not fully rubric-complete. So this looks like a good held-out pass with a real remaining polish gap rather than a fully production-grade finish.

## URL 1: Chess video

### brief_summary (/25)
The brief captures the thesis and format, but it still uses ellipsis-style compression and only lands as a short repaired paragraph rather than a natural 5-7 sentence synthesis. "Featured voices include Narrator" is also technically acceptable but weak. The major ideas are there, yet the note still reads mechanically repaired.

Score: 15/25

### detailed_summary (/45)
The detailed summary is rich and source-shaped. It covers the historical evolution of chess, transformations of the pieces, metaphorical framing, obsession narratives, infinity concepts, and notable historical figures. The structure is coherent and useful, though a few example-heavy bullets remain denser and more quote-adjacent than ideal.

Score: 42/45

### tags (/15)
The tags are specific, varied, and fit the subject well. They include the needed format cue and feel retrieval-ready.

Score: 15/15

### label (/15)
The label is concise, content-first, and faithful to the video's main idea. It is slightly abstract, but still strong.

Score: 14/15

### URL 1 subtotal
Score: 86/100

## URL 2: Petrodollar video

### brief_summary (/25)
This brief is stronger on topic framing and structural outline, but it still exhibits the same clipped `...` style and generic speaker handling. It communicates the thesis and broad section flow well enough, yet it still does not feel like a polished 5-7 sentence human-quality brief.

Score: 17/25

### detailed_summary (/45)
The detailed summary is very strong. It preserves the origin of the system, economic consequences, erosion factors, the illustrative collapse scenario, and broader reserve-currency history with impressive coverage. The demonstrations section also helps rather than bloats. This is close to full credit.

Score: 44/45

### tags (/15)
The tags are clear, specific, and useful. They cover the geopolitical, monetary, and energy dimensions without drifting.

Score: 15/15

### label (/15)
The label is clean, content-first, and aligned with the primary topic.

Score: 15/15

### URL 2 subtotal
Score: 91/100

## Anti-patterns
No obvious invented chapters or clickbait retention appear on the held-out set. The persistent quality issue is concentrated in the brief generator: sentence compression still leaves unfinished-feeling prose and generic narrator-style speaker capture. The detailed summaries are consistently much stronger than the briefs.

## Most important implication before prod-parity
Held-out quality looks viable enough to continue, but prod-parity should be treated as a real stress test for the brief layer. If iter-07 regresses or if the same clipped-brief pattern persists, YouTube likely needs the conditional extension loops focused specifically on brief naturalness and speaker salience rather than another broad structural rewrite.

estimated_composite: 89.0
