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
## URL 1: https://www.youtube.com/watch?v=jNQXAC9IVRw

### SUMMARY
```yaml
mini_title: Me at Zoo Elephant Observation
brief_summary: 'In this vlog, Unknown Speaker argues that the video offers a straightforward,
  personal observation of elephants at a zoo, focusing on their distinctive physical
  features and the speaker''s immediate reaction. The video moves through Elephant
  Observation. It references elephants. The closing takeaway: The video''s takeaway
  is the simplicity and directness of the observation, indicating that the speaker''s
  commentary is brief and focused solely on the immediate visual experience.'
tags:
- zoo-visit
- elephant-observation
- short-video
- personal-commentary
- animal-facts
- youtube-classic
- vlogging
- simple-observations
- vlog
detailed_summary:
- heading: Overview
  bullets:
  - In this vlog, Unknown Speaker argues that the video offers a straightforward,
    personal observation of elephants at a zoo, focusing on their distinctive physical
    features and the speaker's immediate reaction.
  sub_sections:
    Format and speakers:
    - 'Format: vlog.'
    - 'Speakers: Unknown Speaker.'
    Thesis:
    - The video offers a straightforward, personal observation of elephants at a zoo,
      focusing on their distinctive physical features and the speaker's immediate
      reaction.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    "00:01 \u2014 Elephant Observation":
    - The speaker initiates their narration by establishing their location in front
      of the elephants at the zoo.
    - A key factual observation is made regarding the elephants' notably long trunks.
    - The speaker offers a subjective assessment, describing the elephants' long trunks
      as "cool.".
    - An animal sound is audibly captured within the video segment.
- heading: Closing remarks
  bullets:
  - The video's takeaway is the simplicity and directness of the observation, indicating
    that the speaker's commentary is brief and focused solely on the immediate visual
    experience.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=jNQXAC9IVRw
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=293
  total_tokens_used: 2836
  gemini_pro_tokens: 1162
  gemini_flash_tokens: 1674
  total_latency_ms: 30578
  cod_iterations_used: 2
  self_check_missing_count: 0
  patch_applied: false
  engine_version: 2.0.0
  structured_payload:
    mini_title: Me at Zoo Elephant Observation
    brief_summary: 'In this vlog, Unknown Speaker argues that the video offers a straightforward,
      personal observation of elephants at a zoo, focusing on their distinctive physical
      features and the speaker''s immediate reaction. The video moves through Elephant
      Observation. It references elephants. The closing takeaway: The video''s takeaway
      is the simplicity and directness of the observation, indicating that the speaker''s
      commentary is brief and focused solely on the immediate visual experience.'
    tags:
    - zoo-visit
    - elephant-observation
    - short-video
    - personal-commentary
    - animal-facts
    - youtube-classic
    - vlogging
    - simple-observations
    - vlog
    speakers:
    - Unknown Speaker
    guests: null
    entities_discussed:
    - elephants
    detailed_summary:
      thesis: The video offers a straightforward, personal observation of elephants
        at a zoo, focusing on their distinctive physical features and the speaker's
        immediate reaction.
      format: vlog
      chapters_or_segments:
      - timestamp: 00:01
        title: Elephant Observation
        bullets:
        - The speaker initiates their narration by establishing their location in
          front of the elephants at the zoo.
        - A key factual observation is made regarding the elephants' notably long
          trunks.
        - The speaker offers a subjective assessment, describing the elephants' long
          trunks as "cool."
        - An animal sound is audibly captured within the video segment.
        - The commentary concludes with the speaker stating that there is nothing
          further to elaborate on.
      demonstrations: []
      closing_takeaway: The video's takeaway is the simplicity and directness of the
        observation, indicating that the speaker's commentary is brief and focused
        solely on the immediate visual experience.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
Me at the zoo

Transcript
Kind: captions Language: en [00:01] All right, so here we are, in front of the elephants [00:05] the cool thing about these guys is that they have really... [00:07] really really long trunks [00:12] and that's cool [00:14] (baaaaaaaaaaahhh!!) [00:16] and that's pretty much all there is to say
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 21887d997aba67e28ba5de24d12adc8b773a830b3a413deb37d3a5e0f6b934ab
