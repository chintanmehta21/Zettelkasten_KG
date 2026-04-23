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
## URL 1: https://www.youtube.com/watch?v=1aA1WGON49E

### SUMMARY
```yaml
mini_title: Optimizing Talks Internet Audiences
brief_summary: 'In this lecture, Woody Roseland argues that woody roseland argues
  that public speakers should prioritize the internet audience over the live one,
  adapting their format for short attention spans to ensure content is seen and shared
  effectively in the digital age. The closing takeaway: The closing takeaway is that
  speakers must adapt their content to be extremely brief and optimized for online
  consumption to effectively reach and engage modern audiences with diminished attention
  spans.'
tags:
- public-speaking
- internet-audience
- attention-span
- digital-age
- tedx-talk
- woody-roseland
- communication
- online-content
- lecture
- short-form-video
detailed_summary:
- heading: Overview
  bullets:
  - In this lecture, Woody Roseland argues that woody roseland argues that public
    speakers should prioritize the internet audience over the live one, adapting their
    format for short attention spans to ensure content is seen and shared effectively
    in the digital age.
  sub_sections:
    Format and speakers:
    - 'Format: lecture.'
    - 'Speakers: Woody Roseland.'
    Thesis:
    - Woody Roseland argues that public speakers should prioritize the internet audience
      over the live one, adapting their format for short attention spans to ensure
      content is seen and shared effectively in the digital age.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    Audience Priority Shift:
    - Woody Roseland asserts that the internet audience holds greater importance than
      the live audience for content dissemination.
    - He claims that online viewers are primarily responsible for content being widely
      "seen and shared.".
    - Roseland contrasts the perceived value of an immediate live audience with that
      of a "random person scrolling Facebook.".
    - The speaker emphasizes that the reach and impact of a talk are predominantly
      determined by its online performance.
    - This perspective suggests a fundamental re-evaluation of how speakers should
      approach their presentations for maximum influence.
    Declining Attention Spans:
    - Roseland states that human attention spans have significantly diminished since
      2009.
    - He emphatically declares that modern attention spans are effectively "gone"
      and "dead.".
    - As personal evidence, he mentions not having watched a full 18-minute TED talk
      in "literally years.".
    - This observation underscores the necessity for speakers to adapt their delivery
      methods to current cognitive patterns.
    - The argument implies that traditional long-form content struggles to retain
      engagement in the current digital landscape.
    Brevity as a Solution:
    - Roseland demonstrates his central thesis by delivering his entire talk in under
      one minute.
    - The short duration serves as practical proof of his argument for adapting to
      digital attention spans.
    - He highlights reaching the 44-second mark before concluding with his final joke.
    - This format choice directly illustrates the effectiveness of extreme conciseness
      in capturing attention.
    - The talk itself acts as an example of how to deliver a compelling message within
      a minimal timeframe for an internet audience.
- heading: Demonstrations
  bullets:
  - The entire talk serves as a demonstration of delivering a concise message within
    a very short timeframe, embodying the speaker's argument for brevity.
  sub_sections: {}
- heading: Closing remarks
  bullets:
  - The closing takeaway is that speakers must adapt their content to be extremely
    brief and optimized for online consumption to effectively reach and engage modern
    audiences with diminished attention spans. Prioritizing the internet audience
    ensures wider dissemination and impact for any message.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=1aA1WGON49E
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=1180
  total_tokens_used: 4370
  gemini_pro_tokens: 2291
  gemini_flash_tokens: 2079
  total_latency_ms: 38207
  cod_iterations_used: 2
  self_check_missing_count: 2
  patch_applied: false
  engine_version: 2.0.0
  structured_payload:
    mini_title: Optimizing Talks Internet Audiences
    brief_summary: 'In this lecture, Woody Roseland argues that woody roseland argues
      that public speakers should prioritize the internet audience over the live one,
      adapting their format for short attention spans to ensure content is seen and
      shared effectively in the digital age. The closing takeaway: The closing takeaway
      is that speakers must adapt their content to be extremely brief and optimized
      for online consumption to effectively reach and engage modern audiences with
      diminished attention spans.'
    tags:
    - public-speaking
    - internet-audience
    - attention-span
    - digital-age
    - tedx-talk
    - woody-roseland
    - communication
    - online-content
    - lecture
    - short-form-video
    speakers:
    - Woody Roseland
    guests: null
    entities_discussed:
    - TEDxMileHigh
    - Facebook
    - TED talk
    detailed_summary:
      thesis: Woody Roseland argues that public speakers should prioritize the internet
        audience over the live one, adapting their format for short attention spans
        to ensure content is seen and shared effectively in the digital age.
      format: lecture
      chapters_or_segments:
      - timestamp: ''
        title: Audience Priority Shift
        bullets:
        - Woody Roseland asserts that the internet audience holds greater importance
          than the live audience for content dissemination.
        - He claims that online viewers are primarily responsible for content being
          widely "seen and shared."
        - Roseland contrasts the perceived value of an immediate live audience with
          that of a "random person scrolling Facebook."
        - The speaker emphasizes that the reach and impact of a talk are predominantly
          determined by its online performance.
        - This perspective suggests a fundamental re-evaluation of how speakers should
          approach their presentations for maximum influence.
      - timestamp: ''
        title: Declining Attention Spans
        bullets:
        - Roseland states that human attention spans have significantly diminished
          since 2009.
        - He emphatically declares that modern attention spans are effectively "gone"
          and "dead."
        - As personal evidence, he mentions not having watched a full 18-minute TED
          talk in "literally years."
        - This observation underscores the necessity for speakers to adapt their delivery
          methods to current cognitive patterns.
        - The argument implies that traditional long-form content struggles to retain
          engagement in the current digital landscape.
      - timestamp: ''
        title: Brevity as a Solution
        bullets:
        - Roseland demonstrates his central thesis by delivering his entire talk in
          under one minute.
        - The short duration serves as practical proof of his argument for adapting
          to digital attention spans.
        - He highlights reaching the 44-second mark before concluding with his final
          joke.
        - This format choice directly illustrates the effectiveness of extreme conciseness
          in capturing attention.
        - The talk itself acts as an example of how to deliver a compelling message
          within a minimal timeframe for an internet audience.
      demonstrations:
      - The entire talk serves as a demonstration of delivering a concise message
        within a very short timeframe, embodying the speaker's argument for brevity.
      closing_takeaway: The closing takeaway is that speakers must adapt their content
        to be extremely brief and optimized for online consumption to effectively
        reach and engage modern audiences with diminished attention spans. Prioritizing
        the internet audience ensures wider dissemination and impact for any message.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
A one minute TEDx Talk for the digital age | Woody Roseland | TEDxMileHigh

Transcript
Kind: captions Language: en [00:00] Transcriber: Victor Borges Reviewer: David DeRuwe [00:11] Wow, [00:13] what an audience. [00:14] But if I'm being honest, I don't care what you think of my talk. [00:18] I don't. [00:19] I care what the internet thinks of my talk. [00:21] (Laughter) [00:22] Because they are the ones who get it seen and shared. [00:24] And I think that's where most people get it wrong. [00:26] They're talking to you, here, [00:28] instead of talking to you, random person scrolling Facebook. [00:34] Thanks for the click. [00:36] You see, back in 2009, [00:37] we all had these weird little things called attention spans. [00:41] (Laughter) [00:42] Yeah, they're gone. They're gone. We killed them. They're dead. [00:46] I'm trying to think of the last time I watched an 18-minute TED talk. [00:50] It's been years, literally years. [00:52] So if you're giving a TED talk, keep it quick. [00:55] I'm doing mine in under a minute. [00:57] I'm at 44 seconds right now; [00:59] that means we've got time for one final joke. [01:01] Why are balloons so expensive? [01:04] (Audience) "Why?" [01:05] Woody Roseland: Inflation. [01:06] (Laughter) [01:08] (Applause)
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 2b71c5c6474aa909e77d3131a335eac87cf9d6b8a8c9acc27681121f2c9c520b
