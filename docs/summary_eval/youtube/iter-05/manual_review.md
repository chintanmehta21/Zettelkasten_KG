eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - YouTube iter-05

## URL 1: DMT video

### brief_summary (/25)
This is an improvement over iter-04 in that the brief no longer dies at `Dr.` and now carries an explicit format tag plus speaker sentence. But the repair is still visibly synthetic: the first sentence ends with `profoundly...`, the brief is only four sentences rather than the intended 5-7, and the highlighted names skew toward early historical figures rather than the video's more important modern experts. So the top-level note is more stable, but still not polished enough for production-grade YouTube briefing.

Score: 16/25

### detailed_summary (/45)
The detailed summary remains strong. It covers history, chemistry, prohibition, subjective effects, neuroscience theories, and therapeutic potential in a coherent order, while preserving named entities and caveats. The main deductions are that timestamps are still overly coarse and some quoted experiential details remain close to verbatim rather than clearly summarized for purpose.

Score: 41/45

### tags (/15)
The tags are specific and retrieval-friendly, and `commentary` now anchors the format cleanly. No obvious unsupported claims show up here.

Score: 15/15

### label (/15)
The label is concise, content-first, and much better than a hook-retained YouTube title. It is slightly generic, but still very usable as a knowledge-note label.

Score: 14/15

### URL 1 subtotal
Score: 86/100

## URL 2: Silk Road video

### brief_summary (/25)
The brief captures the thesis, format, and major arc, but it still reads like a compressed template rather than natural prose. The ellipses weaken confidence, and "Featured voices include Ross Ulbricht" is technically valid but thin for a video that is really driven by investigative narration and multiple case figures. It also does not surface takeaways as cleanly as the rubric wants.

Score: 17/25

### detailed_summary (/45)
The detailed summary is very good. It preserves chronology, operational details, the investigation, corrupt-agent subplot, and sentencing outcome with strong specificity. The structure is useful and grounded.

Score: 44/45

### tags (/15)
The tags are specific, format-aware, and well centered on the topic. They look production-usable.

Score: 15/15

### label (/15)
The label is direct, clean, and faithful to the main topic with no clickbait retention.

Score: 14/15

### URL 2 subtotal
Score: 90/100

## URL 3: Cannabis-use video

### brief_summary (/25)
This brief again shows the new stable structure but also the same new weakness: compressed sentence fragments ending in ellipses, thin speaker handling, and a slightly mechanical topic restatement. The core thesis is clear and the format is explicit, but the prose still feels repaired rather than authored.

Score: 16/25

### detailed_summary (/45)
The detailed summary is strong and highly structured. It covers prevalence, life-stage effects, social and romantic consequences, career harms, and mental-health consequences in a readable progression. It feels much closer to the target quality than the brief.

Score: 43/45

### tags (/15)
The tags are topical and useful, with a correct format tag. They are a touch broad in places, but still solid overall.

Score: 14/15

### label (/15)
The label is content-first and non-clickbait, though a bit abstract compared with the stronger labels above.

Score: 13/15

### URL 3 subtotal
Score: 86/100

## Anti-patterns
The old truncation bug is materially improved, but a new polish issue is now obvious across multiple URLs: the brief synthesizer is over-compressing with `...`, which leaves prose feeling unfinished even when it is technically complete. Speaker prioritization is also not yet robust enough; it can select early-mentioned names or placeholder-like speakers instead of the most salient modern experts or narrator-facing identities. Detailed summaries are consistently much stronger than the brief layer.

## Most impactful improvement for iter-06
The next fix should replace ellipsis-based word clipping in the brief repair path with sentence-complete compression that never emits `...` inside the final brief. In the same pass, speaker prioritization should bias toward the most salient explanatory voices near the dense analytical sections rather than the earliest named people in the transcript. If those two issues are resolved without destabilizing the detailed summary, YouTube should be much closer to held-out readiness.

estimated_composite: 87.0
