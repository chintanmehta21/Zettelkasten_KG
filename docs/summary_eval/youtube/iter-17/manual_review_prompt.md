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
## URL 1: https://www.youtube.com/watch?v=0e0duD8_LFE

### SUMMARY
```yaml
mini_title: JLPT N5 Listening Practice Test
brief_summary: 'In this walkthrough, The Nihongo Nook argues that the video serves
  as a practical, self-paced listening comprehension practice test for the japanese
  language proficiency test (jlpt) n5 level, offering immediate feedback to aid in
  exam preparation. The closing takeaway: This resource provides a direct and efficient
  method for N5 candidates to assess and improve their listening skills, making it
  a valuable tool for independent study and exam readiness.'
tags:
- jlpt-n5
- japanese-language
- listening-practice
- nihongo-nook
- language-learning
- test-preparation
- chokai
- educational-resource
- self-study
- walkthrough
detailed_summary:
- heading: Overview
  bullets:
  - In this walkthrough, The Nihongo Nook argues that the video serves as a practical,
    self-paced listening comprehension practice test for the japanese language proficiency
    test (jlpt) n5 level, offering immediate feedback to aid in exam preparation.
  sub_sections:
    Format and speakers:
    - 'Format: walkthrough.'
    - 'Speakers: The Nihongo Nook.'
    Thesis:
    - The video serves as a practical, self-paced listening comprehension practice
      test for the Japanese Language Proficiency Test (JLPT) N5 level, offering immediate
      feedback to aid in exam preparation.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    JLPT N5 Listening Practice Questions:
    - "The video presents a comprehensive practice test specifically tailored for\
      \ the JLPT N5 listening comprehension section, known as ch\u014Dkai."
    - It is structured to simulate an actual exam environment, preparing learners
      for the types of questions they will encounter.
    - A defining characteristic of this practice test is the immediate display of
      answers following each question, facilitating instant self-correction and learning.
    - The content is designed for individuals targeting the 2025 JLPT N5 examination,
      ensuring relevance and up-to-date practice material.
    - The practice questions cover various scenarios and dialogue types typically
      found in the N5 listening section, challenging comprehension skills.
    - Background music, "Serpantine" by Vlad Gluschenko, is used under a Creative
      Commons license, providing a consistent audio environment.
    - This format allows learners to progress at their own pace, reviewing difficult
      questions as needed without external guidance.
- heading: Demonstrations
  bullets:
  - A full-length practice test for the JLPT N5 listening comprehension section, including
    questions and immediate answers.
  sub_sections: {}
- heading: Closing remarks
  bullets:
  - This resource provides a direct and efficient method for N5 candidates to assess
    and improve their listening skills, making it a valuable tool for independent
    study and exam readiness.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=0e0duD8_LFE
  author: null
  date: null
  extraction_confidence: low
  confidence_reason: All transcript tiers failed; metadata-only fallback (composite
    capped at 75)
  total_tokens_used: 2952
  gemini_pro_tokens: 1115
  gemini_flash_tokens: 1837
  total_latency_ms: 33430
  cod_iterations_used: 2
  self_check_missing_count: 1
  patch_applied: false
  engine_version: 2.0.0
  structured_payload:
    mini_title: JLPT N5 Listening Practice Test
    brief_summary: 'In this walkthrough, The Nihongo Nook argues that the video serves
      as a practical, self-paced listening comprehension practice test for the japanese
      language proficiency test (jlpt) n5 level, offering immediate feedback to aid
      in exam preparation. The closing takeaway: This resource provides a direct and
      efficient method for N5 candidates to assess and improve their listening skills,
      making it a valuable tool for independent study and exam readiness.'
    tags:
    - jlpt-n5
    - japanese-language
    - listening-practice
    - nihongo-nook
    - language-learning
    - test-preparation
    - chokai
    - educational-resource
    - self-study
    - walkthrough
    speakers:
    - The Nihongo Nook
    guests: null
    entities_discussed:
    - JLPT N5
    - Serpantine
    - Creative Commons Attribution 3.0 Unported
    detailed_summary:
      thesis: The video serves as a practical, self-paced listening comprehension
        practice test for the Japanese Language Proficiency Test (JLPT) N5 level,
        offering immediate feedback to aid in exam preparation.
      format: walkthrough
      chapters_or_segments:
      - timestamp: ''
        title: JLPT N5 Listening Practice Questions
        bullets:
        - "The video presents a comprehensive practice test specifically tailored\
          \ for the JLPT N5 listening comprehension section, known as ch\u014Dkai."
        - It is structured to simulate an actual exam environment, preparing learners
          for the types of questions they will encounter.
        - A defining characteristic of this practice test is the immediate display
          of answers following each question, facilitating instant self-correction
          and learning.
        - The content is designed for individuals targeting the 2025 JLPT N5 examination,
          ensuring relevance and up-to-date practice material.
        - The practice questions cover various scenarios and dialogue types typically
          found in the N5 listening section, challenging comprehension skills.
        - Background music, "Serpantine" by Vlad Gluschenko, is used under a Creative
          Commons license, providing a consistent audio environment.
        - This format allows learners to progress at their own pace, reviewing difficult
          questions as needed without external guidance.
      demonstrations:
      - A full-length practice test for the JLPT N5 listening comprehension section,
        including questions and immediate answers.
      closing_takeaway: This resource provides a direct and efficient method for N5
        candidates to assess and improve their listening skills, making it a valuable
        tool for independent study and exam readiness.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
JLPT N5 JAPANESE LISTENING PRACTICE TEST 2025 WITH ANSWERS ちょうかい

Channel
The Nihongo Nook

Transcript
JLPT N5 JAPANESE LISTENING PRACTICE TEST 2025 WITH ANSWERS ちょうかい JLPT - N5 聴解, ちょうかい You can check answers in the End of every question. JLPT N5 JAPANESE LISTENING PRACTICE TEST 2025 WITH ANSWERS (ちょうかい ) Music: Vlad Gluschenko — Serpantine License: Creative Commons Attribution 3.0 Unported: https://creativecommons.org/licenses/by/3.0/deed.en #jlpt #jlpt #listening_practice #N5
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 19c064940d1b4396bf63aee275d9fa0fd7e639ee58300fe5d5931eb6a8347b8e
