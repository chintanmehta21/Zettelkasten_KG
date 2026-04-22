eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - YouTube iter-02 (first tune, URL #1)

## brief_summary (/25)
The brief is materially better than iter-01. It now reads like a real multi-sentence abstract and clearly identifies the video's core topic, major scientific themes, and high-level takeaways around safety, consciousness, and therapeutic uncertainty. It also explicitly names important figures such as Chris Timmerman and Rick Strassman, which helps the speaker/entity coverage criterion. The format is still somewhat fuzzy: this feels closer to a documentary review or science explainer, but the brief does not quite anchor that distinction in a clean viewer-facing phrase. It still misses the host or channel identity, which remains a recurring YouTube-specific weakness. The segment outline is stronger than before, though it leans thematic rather than reflecting the video's actual narrated progression. It avoids clickbait and now satisfies the 5-7 sentence expectation.
Score: 20/25

## detailed_summary (/45)
This loop fixes one of the prior run's most obvious structural issues by dropping fake `00:00` timestamps, which is a clear improvement. The summary now reads as a better organized research-style overview, with strong entity coverage and more explicit grouping of hypotheses, methods, consumption modes, and research status. However, it may have over-corrected into a taxonomy of themes that feels cleaner than the source's real flow, and several segment titles still look synthesized rather than directly grounded in transcript turns. The unsupported Simon Ruffell / veterans note remains a faithfulness concern, because it still reads like imported context rather than something solidly anchored in the source. There are also places where vivid examples and coined phrases remain closer to source language than ideal, especially in experience descriptions and McKenna-related imagery. Caveats and safety guidance are preserved well, and the closing takeaway is stronger than in iter-01. Overall this is more polished, but still not fully source-grounded enough for production-grade scoring.
Score: 31/45

## tags (/15)
The tags are still within range and remain specific to the topic. They cover the compound, the research area, and important figures, and they avoid obvious unsupported topics. The main miss is unchanged from iter-01: there is still no explicit format or audience tag such as `lecture`, `documentary`, `science-video`, or `explainer`. A few tags also remain a little broad compared with the sharper source-grounded ones.
Score: 12/15

## label (/15)
The label is much better. It is content-first, concise, and clearly about the primary topic rather than a side tangent. It also strips away any clickbait impulse and reads like a clean note title. This is the strongest component of the loop-2 output.
Score: 15/15

## Anti-patterns
`clickbait_label_retention`: no.

`example_verbatim_reproduction`: mild yes. Some experiential phrasing remains too close to source language.

`editorialized_stance`: no obvious editorialization beyond a slightly smoothed research-summary tone.

`speakers_absent`: no. Referenced people are named, though the host/channel is still missing.

`invented_chapter`: borderline yes. The null timestamps remove the worst placeholder problem, but the segment taxonomy still feels model-authored rather than faithfully derived from the source's actual chaptering.

## Most impactful improvement for iter-03
The next loop should focus on grounding segment structure in the transcript's real narrative order instead of building a neat topical taxonomy. Right now the summary is more readable, but it still behaves like an editorial synthesis of the video's ideas rather than a faithful reconstruction of how the video actually unfolds. The highest-value fix would be to bind `chapters_or_segments` more tightly to sequential transcript transitions and to suppress imported research claims that are not explicitly present, while also forcing the host/channel and a format tag into the brief/tag surfaces.

estimated_composite: 61.2
