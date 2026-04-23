You are an INDEPENDENT rubric reviewer, blind to any prior evaluator's scoring. Do NOT read eval.json.

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of your manual_review.md.

RUBRIC:
version: rubric_youtube.v1
source_type: youtube
composite_max_points: 100
components:
- id: brief_summary
  max_points: 25
  criteria:
  - id: brief.thesis_capture
    description: Brief summary states the video's central thesis or learning objective
      in one sentence.
    max_points: 5
    maps_to_metric:
    - g_eval.relevance
    - finesure.completeness
  - id: brief.format_identified
    description: Brief identifies the video format explicitly (tutorial/interview/lecture/commentary/etc.).
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
  - id: brief.speakers_captured
    description: Brief names the host/channel and any guests or key products/libraries
      discussed.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
    - qafact
  - id: brief.major_segments_outlined
    description: Brief outlines the major structural segments of the video (intro,
      sections, demo, conclusion).
    max_points: 5
    maps_to_metric:
    - finesure.completeness
    - g_eval.coherence
  - id: brief.takeaways_surfaced
    description: Brief highlights 2-3 takeaways a viewer would remember after watching.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
    - g_eval.relevance
  - id: brief.length_5_to_7_sentences
    description: Brief is 5-7 sentences.
    max_points: 2
    maps_to_metric:
    - g_eval.conciseness
  - id: brief.no_clickbait
    description: Brief does not reproduce clickbait/hook phrasing from the source
      title.
    max_points: 2
    maps_to_metric:
    - finesure.faithfulness
- id: detailed_summary
  max_points: 45
  criteria:
  - id: detailed.chronological_order
    description: Detailed bullets follow the video's chronological order.
    max_points: 6
    maps_to_metric:
    - g_eval.coherence
  - id: detailed.all_chapters_covered
    description: Every substantive chapter or major topic turn is covered by at least
      one bullet.
    max_points: 10
    maps_to_metric:
    - finesure.completeness
    - qafact
  - id: detailed.demonstrations_preserved
    description: Demonstrations, code walkthroughs, or live examples are captured.
    max_points: 6
    maps_to_metric:
    - finesure.completeness
  - id: detailed.caveats_preserved
    description: Warnings, caveats, limitations the speaker mentions are captured.
    max_points: 5
    maps_to_metric:
    - finesure.faithfulness
    - summac
  - id: detailed.examples_purpose_not_verbatim
    description: Examples/analogies summarized as PURPOSE, not reproduced verbatim.
    max_points: 5
    maps_to_metric:
    - finesure.conciseness
  - id: detailed.entities_named
    description: Products, libraries, datasets, or case studies referenced are named.
    max_points: 5
    maps_to_metric:
    - finesure.completeness
    - qafact
  - id: detailed.closing_takeaway
    description: The video's closing takeaway is explicitly captured.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
  - id: detailed.no_sponsor_padding
    description: Sponsor reads, intros, and 'like and subscribe' fluff are not given
      bullets.
    max_points: 4
    maps_to_metric:
    - finesure.conciseness
- id: tags
  max_points: 15
  criteria:
  - id: tags.count_7_to_10
    description: Exactly 7-10 tags.
    max_points: 2
    maps_to_metric:
    - finesure.conciseness
  - id: tags.topical_specificity
    description: Tags capture specific subject matter, not generic terms.
    max_points: 4
    maps_to_metric:
    - g_eval.relevance
  - id: tags.format_tag_present
    description: Includes a tag for content type (tutorial/interview/beginner/advanced).
    max_points: 2
    maps_to_metric:
    - g_eval.relevance
  - id: tags.technologies_named
    description: Named technologies/libraries/frameworks from the video are tagged.
    max_points: 3
    maps_to_metric:
    - finesure.completeness
  - id: tags.no_unsupported_claims
    description: No tags imply topics not actually covered.
    max_points: 4
    maps_to_metric:
    - finesure.faithfulness
    - summac
- id: label
  max_points: 15
  criteria:
  - id: label.content_first_3_to_5_words
    description: Label is 3-5 words (max 50 chars), content-first, declarative.
    max_points: 5
    maps_to_metric:
    - g_eval.conciseness
  - id: label.reflects_primary_topic
    description: Label reflects the primary topic, not side tangents.
    max_points: 5
    maps_to_metric:
    - g_eval.relevance
  - id: label.no_clickbait_retention
    description: Label removes clickbait/hook fragments from the original title.
    max_points: 5
    maps_to_metric:
    - finesure.faithfulness
anti_patterns:
- id: clickbait_label_retention
  description: Label retains YouTube clickbait phrasing ('You won't believe...', 'This
    changes EVERYTHING').
  auto_cap: 90
  detection_hint: Look for exclamation marks, superlatives, curiosity-gap phrasing
    in label.
- id: example_verbatim_reproduction
  description: Brief or detailed summary reproduces an example/analogy verbatim.
  auto_cap: null
  penalty_points: 3
- id: editorialized_stance
  description: Summary introduces stance/framing not present in source.
  auto_cap: 60
- id: speakers_absent
  description: Summary fails to identify the host or any referenced people.
  auto_cap: 75
- id: invented_chapter
  description: Summary invents a chapter or segment not present in the video.
  auto_cap: 60
global_rules:
  editorialization_penalty:
    threshold_flags: 3
    cap_on_trigger: 60


SUMMARY:
## URL 1: https://www.youtube.com/watch?v=TxbE79-1OSI

### SUMMARY
```yaml
mini_title: African Wildlife Showreel 2017
brief_summary: In this commentary, Robert Hofmeyr argues that robert hofmeyr's 2017
  showreel aims to provide a pure visual experience of african wildlife, relying on
  high-quality cinematography and an accompanying musical score rather than spoken
  narration or factual commentary. The video moves through Visual Showcase and Audio
  Composition.
tags:
- african-wildlife
- nature-showreel
- robert-hofmeyr
- visual-showcase
- non-narrative
- 4k-footage
- wildlife-cinematography
- ambient-music
- short-film
- commentary
detailed_summary:
- heading: Overview
  bullets:
  - In this commentary, Robert Hofmeyr argues that robert hofmeyr's 2017 showreel
    aims to provide a pure visual experience of african wildlife, relying on high-quality
    cinematography and an accompanying musical score rather than spoken narration
    or factual commentary.
  sub_sections:
    Format and speakers:
    - 'Format: commentary.'
    - 'Speakers: Robert Hofmeyr.'
    Thesis:
    - Robert Hofmeyr's 2017 showreel aims to provide a pure visual experience of African
      wildlife, relying on high-quality cinematography and an accompanying musical
      score rather than spoken narration or factual commentary. The video's primary
      objective is aesthetic appreciation of nature.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    Visual Showcase and Audio Composition:
    - The video functions as a visual showreel, presenting diverse scenes of African
      wildlife.
    - The audio track predominantly features non-verbal music throughout its duration.
    - No narrative commentary or descriptive information about the depicted wildlife
      is present in the transcript.
    - Isolated lexical items, such as 'so' and 'uh', are briefly noted in the transcript
      at various points.
    - The word 'thank you' appears once, and 'foreign' is repeated without contextual
      meaning.
    - The video's structure emphasizes continuous visual flow rather than segmented
      topics or discussions.
- heading: Demonstrations
  bullets:
  - The entire video serves as a visual demonstration of African wildlife in its natural
    habitat.
  sub_sections: {}
- heading: Closing remarks
  bullets:
  - The video offers an immersive, non-narrated visual journey through African nature,
    inviting viewers to experience the beauty of wildlife without explicit educational
    content. Its value lies in the aesthetic presentation of high-definition footage.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=TxbE79-1OSI
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=247
  total_tokens_used: 3273
  gemini_pro_tokens: 1418
  gemini_flash_tokens: 1855
  total_latency_ms: 34544
  cod_iterations_used: 2
  self_check_missing_count: 0
  patch_applied: false
  engine_version: 2.0.0
  structured_payload:
    mini_title: African Wildlife Showreel 2017
    brief_summary: In this commentary, Robert Hofmeyr argues that robert hofmeyr's
      2017 showreel aims to provide a pure visual experience of african wildlife,
      relying on high-quality cinematography and an accompanying musical score rather
      than spoken narration or factual commentary. The video moves through Visual
      Showcase and Audio Composition.
    tags:
    - african-wildlife
    - nature-showreel
    - robert-hofmeyr
    - visual-showcase
    - non-narrative
    - 4k-footage
    - wildlife-cinematography
    - ambient-music
    - short-film
    - commentary
    speakers:
    - Robert Hofmeyr
    guests: null
    entities_discussed: []
    detailed_summary:
      thesis: Robert Hofmeyr's 2017 showreel aims to provide a pure visual experience
        of African wildlife, relying on high-quality cinematography and an accompanying
        musical score rather than spoken narration or factual commentary. The video's
        primary objective is aesthetic appreciation of nature.
      format: commentary
      chapters_or_segments:
      - timestamp: ''
        title: Visual Showcase and Audio Composition
        bullets:
        - The video functions as a visual showreel, presenting diverse scenes of African
          wildlife.
        - The audio track predominantly features non-verbal music throughout its duration.
        - No narrative commentary or descriptive information about the depicted wildlife
          is present in the transcript.
        - Isolated lexical items, such as 'so' and 'uh', are briefly noted in the
          transcript at various points.
        - The word 'thank you' appears once, and 'foreign' is repeated without contextual
          meaning.
        - The video's structure emphasizes continuous visual flow rather than segmented
          topics or discussions.
      demonstrations:
      - The entire video serves as a visual demonstration of African wildlife in its
        natural habitat.
      closing_takeaway: The video offers an immersive, non-narrated visual journey
        through African nature, inviting viewers to experience the beauty of wildlife
        without explicit educational content. Its value lies in the aesthetic presentation
        of high-definition footage.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
4K African Wildlife | African Nature Showreel 2017 by Robert Hofmeyr

Transcript
Kind: captions Language: en [Music] [01:03] [Music] so [01:05] so [01:05] so [Music] so [01:34] so [Music] [02:09] [Music] [02:09] [Music] uh [Music] [02:37] [Music] thank you [Music] [03:03] [Music] foreign [03:05] foreign [03:05] foreign [Music]
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): a70793253b51a21cca3deb704f253e663204c5b8b31e6f8e4010aff085f742c6
