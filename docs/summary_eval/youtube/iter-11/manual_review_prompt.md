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
## URL 1: https://www.youtube.com/watch?v=5t1vTLU7s40

### SUMMARY
```yaml
mini_title: LeCun on AI Limitations World
brief_summary: 'In this lecture, Yann LeCun argues that yann lecun argues that current
  auto-regressive large language models are fundamentally limited and cannot achieve
  human-level intelligence. It references GPT-4, Llama 2, and GANs. The closing takeaway:
  Yann LeCun concludes that open-source AI development is crucial for preventing the
  concentration of power and fostering a diverse, beneficial AI ecosystem.'
tags:
- ai
- machine-learning
- deep-learning
- yann-lecun
- meta-ai
- llms
- world-models
- open-source-ai
- ai-safety
- lecture
detailed_summary:
- heading: Overview
  bullets:
  - In this lecture, Yann LeCun argues that yann lecun argues that current auto-regressive
    large language models are fundamentally limited and cannot achieve human-level
    intelligence.
  sub_sections:
    Format and speakers:
    - 'Format: lecture.'
    - 'Speakers: Yann LeCun.'
    Thesis:
    - Yann LeCun argues that current auto-regressive Large Language Models are fundamentally
      limited and cannot achieve human-level intelligence. He proposes that advanced
      AI requires grounding in reality through sophisticated world models, like those
      built with Joint Embedding Predictive Architectures (JEPA), and objective-driven
      architectures for reasoning and planning.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    Limitations of Auto-Regressive LLMs:
    - Auto-regressive LLMs, such as GPT-4 and Llama 2, are not a viable path to human-level
      intelligence.
    - These models lack or possess only primitive versions of key capabilities like
      understanding the physical world, persistent memory, reasoning, and planning.
    - Their token-by-token generation is an "instinctive" process, sampling from a
      probability distribution, unlike human cognition which involves abstract planning.
    - The constant computational cost per generated token, regardless of problem complexity,
      indicates limited reasoning ability.
    - The auto-regressive method leads to compounding errors and hallucinations, with
      error probability increasing exponentially with output length.
    'The Data Gap: Sensory vs. Textual Information':
    - Intelligence cannot be achieved through text alone due to a significant disparity
      in information bandwidth and quality between language and sensory input.
    - "LLMs are trained on vast amounts of public text, estimated at 2 x 10\xB9\xB3\
      \ bytes, which would take a human 170,000 years to read."
    - "In contrast, a four-year-old child processes an estimated 10\xB9\u2075 bytes\
      \ of visual data alone, two orders of magnitude more than LLM training data."
    - Language is information-dense but lacks the redundancy of sensory data, making
      self-supervised learning from redundant data like video more effective for world
      models.
    - This quantitative and qualitative difference suggests most human knowledge is
      non-linguistic, explaining Moravec's Paradox where LLMs excel at abstract tasks
      but fail at physical ones.
    'World Models: From Generative Failures to JEPA':
    - Intelligence must be grounded in reality through a robust world model.
    - Early attempts by LeCun's team at FAIR to build world models using generative
      models (GANs, VAEs) to predict future video frames pixel-by-pixel were unsuccessful.
    - Representing probability distributions over high-dimensional, continuous spaces
      proved intractable for these generative methods, failing to produce useful features.
    - Joint Embedding Predictive Architecture (JEPA) offers a non-generative alternative
      that operates in an abstract representation space.
    - JEPA trains a predictor to output the representation of a full input from the
      representation of a corrupted input, learning predictable information while
      ignoring high-frequency details.
    - Recent non-contrastive methods like FAIR's I-JEPA for images and V-JEPA for
      videos have shown success, with V-JEPA being the first to learn useful video
      representations for action classification.
    Architecture for Objective-Driven AI:
    - LeCun proposes a modular, objective-driven AI architecture for reasoning and
      planning.
    - This architecture includes a JEPA-based World Model to simulate dynamics and
      predict future states based on actions.
    - A Cost/Energy-Based Model acts as a "critic," evaluating proposed action sequences
      by outputting a scalar "energy" value relative to an objective.
    - Inference occurs via optimization, where the system iteratively minimizes the
      cost function to find an optimal action sequence, allowing variable computation
      based on task difficulty.
    - A simple Decoder module translates the optimized action plan into natural language
      or other output formats.
    - This architecture supports hierarchical planning, though automatically learning
      hierarchical representations remains a challenge.
    Open Source as a Guardrail Against Centralized Power:
    - The primary danger of AI is the concentration of power in a few companies controlling
      proprietary systems.
    - LeCun draws an analogy to the printing press, which, despite short-term disruption,
      ultimately advanced humanity by enabling widespread knowledge.
    - A single "unbiased" AI system is impossible for all cultures; a diversity of
      AI systems is the only viable solution.
    - Open-source base models, such as Meta's Llama, allow organizations to fine-tune
      systems for specific needs, fostering competition and preventing control over
      the global "information diet.".
    - Examples include Llama adaptations for 22 Indian languages and a Senegalese
      startup using it for medical information.
    - Companies like Meta can open-source foundation models because their revenue
      comes from platform services, and open-sourcing accelerates progress and ecosystem
      growth.
    Deconstruction of AI Existential Risk ("Doomerism"):
    - Existential risk scenarios for AI are based on several false assumptions.
    - The "Event" fallacy assumes superintelligence will be sudden, whereas it will
      be a gradual development, allowing time for safety engineering.
    - The "Domination" fallacy incorrectly attributes a biological drive for dominance
      to intelligence itself, suggesting AI systems can be designed with submissive
      objectives.
    - The "Uncontrollable" fallacy is addressed by objective-driven architectures,
      which are inherently more controllable than auto-regressive LLMs because their
      behavior is constrained by optimizable objectives and safety guardrails.
    - Safety in AI, like in turbojet engines, is an intrinsic part of good engineering
      and design, not a separate field.
    - LeCun suggests "doomerism" stems from a distrust of human nature, while his
      optimism is rooted in the belief that people are fundamentally good and AI will
      empower that goodness.
- heading: Closing remarks
  bullets:
  - Yann LeCun concludes that open-source AI development is crucial for preventing
    the concentration of power and fostering a diverse, beneficial AI ecosystem. He
    dismisses common AI existential risk narratives as based on flawed assumptions,
    asserting that safety is an inherent outcome of good engineering and that AI will
    ultimately empower human goodness.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=5t1vTLU7s40
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=513705
  total_tokens_used: 327952
  gemini_pro_tokens: 323626
  gemini_flash_tokens: 4326
  total_latency_ms: 120002
  cod_iterations_used: 2
  self_check_missing_count: 6
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: LeCun on AI Limitations World
    brief_summary: 'In this lecture, Yann LeCun argues that yann lecun argues that
      current auto-regressive large language models are fundamentally limited and
      cannot achieve human-level intelligence. It references GPT-4, Llama 2, and GANs.
      The closing takeaway: Yann LeCun concludes that open-source AI development is
      crucial for preventing the concentration of power and fostering a diverse, beneficial
      AI ecosystem.'
    tags:
    - ai
    - machine-learning
    - deep-learning
    - yann-lecun
    - meta-ai
    - llms
    - world-models
    - open-source-ai
    - ai-safety
    - lecture
    speakers:
    - Yann LeCun
    guests: null
    entities_discussed:
    - GPT-4
    - Llama 2
    - GANs
    - VAEs
    - I-JEPA
    - V-JEPA
    - Llama
    detailed_summary:
      thesis: Yann LeCun argues that current auto-regressive Large Language Models
        are fundamentally limited and cannot achieve human-level intelligence. He
        proposes that advanced AI requires grounding in reality through sophisticated
        world models, like those built with Joint Embedding Predictive Architectures
        (JEPA), and objective-driven architectures for reasoning and planning.
      format: lecture
      chapters_or_segments:
      - timestamp: ''
        title: Limitations of Auto-Regressive LLMs
        bullets:
        - Auto-regressive LLMs, such as GPT-4 and Llama 2, are not a viable path to
          human-level intelligence.
        - These models lack or possess only primitive versions of key capabilities
          like understanding the physical world, persistent memory, reasoning, and
          planning.
        - Their token-by-token generation is an "instinctive" process, sampling from
          a probability distribution, unlike human cognition which involves abstract
          planning.
        - The constant computational cost per generated token, regardless of problem
          complexity, indicates limited reasoning ability.
        - The auto-regressive method leads to compounding errors and hallucinations,
          with error probability increasing exponentially with output length.
      - timestamp: ''
        title: 'The Data Gap: Sensory vs. Textual Information'
        bullets:
        - Intelligence cannot be achieved through text alone due to a significant
          disparity in information bandwidth and quality between language and sensory
          input.
        - "LLMs are trained on vast amounts of public text, estimated at 2 x 10\xB9\
          \xB3 bytes, which would take a human 170,000 years to read."
        - "In contrast, a four-year-old child processes an estimated 10\xB9\u2075\
          \ bytes of visual data alone, two orders of magnitude more than LLM training\
          \ data."
        - Language is information-dense but lacks the redundancy of sensory data,
          making self-supervised learning from redundant data like video more effective
          for world models.
        - This quantitative and qualitative difference suggests most human knowledge
          is non-linguistic, explaining Moravec's Paradox where LLMs excel at abstract
          tasks but fail at physical ones.
      - timestamp: ''
        title: 'World Models: From Generative Failures to JEPA'
        bullets:
        - Intelligence must be grounded in reality through a robust world model.
        - Early attempts by LeCun's team at FAIR to build world models using generative
          models (GANs, VAEs) to predict future video frames pixel-by-pixel were unsuccessful.
        - Representing probability distributions over high-dimensional, continuous
          spaces proved intractable for these generative methods, failing to produce
          useful features.
        - Joint Embedding Predictive Architecture (JEPA) offers a non-generative alternative
          that operates in an abstract representation space.
        - JEPA trains a predictor to output the representation of a full input from
          the representation of a corrupted input, learning predictable information
          while ignoring high-frequency details.
        - Recent non-contrastive methods like FAIR's I-JEPA for images and V-JEPA
          for videos have shown success, with V-JEPA being the first to learn useful
          video representations for action classification.
      - timestamp: ''
        title: Architecture for Objective-Driven AI
        bullets:
        - LeCun proposes a modular, objective-driven AI architecture for reasoning
          and planning.
        - This architecture includes a JEPA-based World Model to simulate dynamics
          and predict future states based on actions.
        - A Cost/Energy-Based Model acts as a "critic," evaluating proposed action
          sequences by outputting a scalar "energy" value relative to an objective.
        - Inference occurs via optimization, where the system iteratively minimizes
          the cost function to find an optimal action sequence, allowing variable
          computation based on task difficulty.
        - A simple Decoder module translates the optimized action plan into natural
          language or other output formats.
        - This architecture supports hierarchical planning, though automatically learning
          hierarchical representations remains a challenge.
      - timestamp: ''
        title: Open Source as a Guardrail Against Centralized Power
        bullets:
        - The primary danger of AI is the concentration of power in a few companies
          controlling proprietary systems.
        - LeCun draws an analogy to the printing press, which, despite short-term
          disruption, ultimately advanced humanity by enabling widespread knowledge.
        - A single "unbiased" AI system is impossible for all cultures; a diversity
          of AI systems is the only viable solution.
        - Open-source base models, such as Meta's Llama, allow organizations to fine-tune
          systems for specific needs, fostering competition and preventing control
          over the global "information diet."
        - Examples include Llama adaptations for 22 Indian languages and a Senegalese
          startup using it for medical information.
        - Companies like Meta can open-source foundation models because their revenue
          comes from platform services, and open-sourcing accelerates progress and
          ecosystem growth.
      - timestamp: ''
        title: Deconstruction of AI Existential Risk ("Doomerism")
        bullets:
        - Existential risk scenarios for AI are based on several false assumptions.
        - The "Event" fallacy assumes superintelligence will be sudden, whereas it
          will be a gradual development, allowing time for safety engineering.
        - The "Domination" fallacy incorrectly attributes a biological drive for dominance
          to intelligence itself, suggesting AI systems can be designed with submissive
          objectives.
        - The "Uncontrollable" fallacy is addressed by objective-driven architectures,
          which are inherently more controllable than auto-regressive LLMs because
          their behavior is constrained by optimizable objectives and safety guardrails.
        - Safety in AI, like in turbojet engines, is an intrinsic part of good engineering
          and design, not a separate field.
        - LeCun suggests "doomerism" stems from a distrust of human nature, while
          his optimism is rooted in the belief that people are fundamentally good
          and AI will empower that goodness.
      demonstrations: []
      closing_takeaway: Yann LeCun concludes that open-source AI development is crucial
        for preventing the concentration of power and fostering a diverse, beneficial
        AI ecosystem. He dismisses common AI existential risk narratives as based
        on flawed assumptions, asserting that safety is an inherent outcome of good
        engineering and that AI will ultimately empower human goodness.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
Yann Lecun: Meta AI, Open Source, Limits of LLMs, AGI & the Future of AI | Lex Fridman Podcast #416

Transcript
Kind: captions Language: en I see the danger of this concentration [00:02] I see the danger of this concentration of power to to proprietary AI systems as [00:06] of power to to proprietary AI systems as [00:06] of power to to proprietary AI systems as a much bigger danger than everything [00:08] a much bigger danger than everything [00:08] a much bigger danger than everything else what works against this is people [00:11] else what works against this is people [00:11] else what works against this is people who think that for reasons of security [00:15] who think that for reasons of security [00:15] who think that for reasons of security we should keep AI systems under lock and [00:17] we should keep AI systems under lock and [00:17] we should keep AI systems under lock and key because it's too dangerous to put it [00:19] key because it's too dangerous to put it [00:19] key because it's too dangerous to put it in the hands of of everybody that would [00:22] in the hands of of everybody that would [00:22] in the hands of of everybody that would lead to a very bad future in which all [00:26] lead to a very bad future in which all [00:26] lead to a very bad future in which all of our information diet is controlled by [00:28] of our information diet is controlled by [00:28] of our information diet is controlled by a small number of uh uh companies [00:30] a small number of uh uh companies [00:30] a small number of uh uh companies through proprietary systems I believe [00:32] through proprietary systems I believe [00:32] through proprietary systems I believe that people are fundamentally good and [00:34] that people are fundamentally good and [00:34] that people are fundamentally good and so if [00:36] so if [00:36] so if AI especially open source AI can um make [00:40] AI especially open source AI can um make [00:40] AI especially open source AI can um make them smarter it just empowers the [00:42] them smarter it just empowers the [00:42] them smarter it just empowers the goodness in humans so I I share that [00:45] goodness in humans so I I share that [00:45] goodness in humans so I I share that feeling okay I think people are Fally [00:48] feeling okay I think people are Fally [00:48] feeling okay I think people are Fally good uh and in fact a lot of doomers are [00:51] good uh and in fact a lot of doomers are [00:51] good uh and in fact a lot of doomers are doomers because they don't think that [00:54] doomers because they don't think that [00:54] doomers because they don't think that people are fundamentally [00:56] people are fundamentally [00:56] people are fundamentally good the following is a conversation [00:59] good the following is a conversation [00:59] good the following is a conversation with Yan laon his third time on this [01:02] with Yan laon his third time on this [01:02] with Yan laon his third time on this podcast he is the chief AI scientist at [01:04] podcast he is the chief AI scientist at [01:04] podcast he is the chief AI scientist at meta professor at NYU touring Award [01:07] meta professor at NYU touring Award [01:07] meta professor at NYU touring Award winner and one of the seminal figures in [01:10] winner and one of the seminal figures in [01:10] winner and one of the seminal figures in the history of artificial intelligence [01:13] the history of artificial intelligence [01:13] the history of artificial intelligence he and meta AI have been big proponents [01:16] he and meta AI have been big proponents [01:16] he and meta AI have been big proponents of open sourcing AI development and have [01:19] of open sourcing AI development and have [01:19] of open sourcing AI development and have been walking the walk by open sourcing [01:22] been walking the walk by open sourcing [01:22] been walking the walk by open sourcing many of their biggest models including [01:24] many of their biggest models including [01:24] many of their biggest models including llama 2 and eventually llama 3 also Yan [01:29] llama 2 and eventually llama 3 also Yan [01:29] llama 2 and eventually llama 3 also Yan has been an outspoken critic of those [01:32] has been an outspoken critic of those [01:32] has been an outspoken critic of those people in the AI Community who warn [01:35] people in the AI Community who warn [01:35] people in the AI Community who warn about the looming danger and existential [01:37] about the looming danger and existential [01:37] about the looming danger and existential threat of AGI he believes the AGI will [01:42] threat of AGI he believes the AGI will [01:42] threat of AGI he believes the AGI will be created one day but it will be good [01:45] be created one day but it will be good [01:45] be created one day but it will be good it will not Escape human control nor [01:48] it will not Escape human control nor [01:48] it will not Escape human control nor will it Dominate and kill all humans at [01:52] will it Dominate and kill all humans at [01:52] will it Dominate and kill all humans at this moment of Rapid AI development this [01:55] this moment of Rapid AI development this [01:55] this moment of Rapid AI development this happens to be somewhat a controversial [01:57] happens to be somewhat a controversial [01:57] happens to be somewhat a controversial position and so it's been fun seeing Yan [02:00] position and so it's been fun seeing Yan [02:01] position and so it's been fun seeing Yan get into a lot of intense and [02:02] get into a lot of intense and [02:02] get into a lot of intense and fascinating discussions [02:04] fascinating discussions [02:04] fascinating discussions online as we do in this very [02:07] online as we do in this very [02:07] online as we do in this very conversation this is the lexman podcast [02:10] conversation this is the lexman podcast [02:10] conversation this is the lexman podcast to support it please check out our [02:11] to support it please check out our [02:11] to support it please check out our sponsors in the description and now dear [02:14] sponsors in the description and now dear [02:14] sponsors in the description and now dear friends here's Yan [02:16] friends here's Yan [02:16] friends here's Yan laon you've had some strong [02:20] laon you've had some strong [02:20] laon you've had some strong statements technical statements about [02:22] statements technical statements about [02:22] statements technical statements about the future of artificial intelligence [02:24] the future of artificial intelligence [02:24] the future of artificial intelligence recently throughout your career actually [02:26] recently throughout your career actually [02:26] recently throughout your career actually but recently as well uh you've said that [02:30] but recently as well uh you've said that [02:30] but recently as well uh you've said that autoaggressive llms are uh not the way [02:34] autoaggressive llms are uh not the way [02:34] autoaggressive llms are uh not the way we're going to make progress towards [02:37] we're going to make progress towards [02:37] we're going to make progress towards superhuman intelligence these are the [02:39] superhuman intelligence these are the [02:39] superhuman intelligence these are the large language models like GPT 4 like [02:42] large language models like GPT 4 like [02:42] large language models like GPT 4 like llama 2 and 3 soon and so on how do they [02:44] llama 2 and 3 soon and so on how do they [02:44] llama 2 and 3 soon and so on how do they work and why are they not going to take [02:46] work and why are they not going to take [02:46] work and why are they not going to take us all the way for a number of reasons [02:49] us all the way for a number of reasons [02:49] us all the way for a number of reasons the first is that there is a number of [02:50] the first is that there is a number of [02:51] the first is that there is a number of characteristics of intelligent [02:53] characteristics of intelligent [02:53] characteristics of intelligent behavior for example the capacity to [02:57] behavior for example the capacity to [02:57] behavior for example the capacity to understand the world understand the [02:59] understand the world understand the [02:59] understand the world understand the physical world [03:01] physical world [03:01] physical world the ability to remember and retrieve [03:05] the ability to remember and retrieve [03:05] the ability to remember and retrieve things um persistent memory the ability [03:09] things um persistent memory the ability [03:09] things um persistent memory the ability to reason and the ability to plan those [03:12] to reason and the ability to plan those [03:12] to reason and the ability to plan those are four essential characteristic of [03:14] are four essential characteristic of [03:14] are four essential characteristic of intelligent um systems or entities [03:18] intelligent um systems or entities [03:18] intelligent um systems or entities humans [03:19] humans [03:19] humans animals lnms can do none of those or [03:23] animals lnms can do none of those or [03:23] animals lnms can do none of those or they can only do them in a very [03:25] they can only do them in a very [03:25] they can only do them in a very primitive way and uh they don't really [03:28] primitive way and uh they don't really [03:28] primitive way and uh they don't really understand the physical world don't [03:29] understand the physical world don't [03:29] understand the physical world don't really have persistent memory they can't [03:31] really have persistent memory they can't [03:31] really have persistent memory they can't really reason and they certainly can't [03:33] really reason and they certainly can't [03:33] really reason and they certainly can't plan and so you know if if if you expect [03:37] plan and so you know if if if you expect [03:37] plan and so you know if if if you expect the system to become intelligent just [03:40] the system to become intelligent just [03:40] the system to become intelligent just you know without having the possibility [03:42] you know without having the possibility [03:42] you know without having the possibility of doing those things you're making a [03:44] of doing those things you're making a [03:44] of doing those things you're making a mistake that is not to say that auto [03:47] mistake that is not to say that auto [03:47] mistake that is not to say that auto regressive LS are not useful they're [03:50] regressive LS are not useful they're [03:50] regressive LS are not useful they're certainly [03:51] certainly [03:52] certainly useful um that they're not interesting [03:55] useful um that they're not interesting [03:55] useful um that they're not interesting that we can't build a whole ecosystem of [03:58] that we can't build a whole ecosystem of [03:58] that we can't build a whole ecosystem of applications around them of course we [04:00] applications around them of course we [04:00] applications around them of course we can but as a path towards human level [04:04] can but as a path towards human level [04:04] can but as a path towards human level intelligence they're missing essential [04:07] intelligence they're missing essential [04:07] intelligence they're missing essential components and then there is another [04:09] components and then there is another [04:10] components and then there is another tidbit or or fact that I think is very [04:12] tidbit or or fact that I think is very [04:13] tidbit or or fact that I think is very interesting those llms are trained on [04:15] interesting those llms are trained on [04:15] interesting those llms are trained on enormous amounts of text basically the [04:18] enormous amounts of text basically the [04:18] enormous amounts of text basically the entirety of all publicly available text [04:20] entirety of all publicly available text [04:20] entirety of all publicly available text on the internet right that's [04:22] on the internet right that's [04:22] on the internet right that's typically on the order of 10 to the 13 [04:25] typically on the order of 10 to the 13 [04:26] typically on the order of 10 to the 13 tokens each token is typically two byes [04:28] tokens each token is typically two byes [04:28] tokens each token is typically two byes so that's two 10 to the 13 bytes as [04:30] so that's two 10 to the 13 bytes as [04:30] so that's two 10 to the 13 bytes as training data it would take you or me [04:33] training data it would take you or me [04:33] training data it would take you or me 170,000 years to just read through this [04:36] 170,000 years to just read through this [04:36] 170,000 years to just read through this at eight hours a day uh so it seems like [04:39] at eight hours a day uh so it seems like [04:39] at eight hours a day uh so it seems like an enormous amount of knowledge right [04:41] an enormous amount of knowledge right [04:41] an enormous amount of knowledge right that those systems can [04:43] that those systems can [04:43] that those systems can accumulate [04:45] accumulate [04:45] accumulate um but then you realize it's really not [04:47] um but then you realize it's really not [04:47] um but then you realize it's really not that much data if you you talk to [04:50] that much data if you you talk to [04:50] that much data if you you talk to developmental psychologist and they tell [04:52] developmental psychologist and they tell [04:52] developmental psychologist and they tell you a four-year-old has been awake for [04:54] you a four-year-old has been awake for [04:54] you a four-year-old has been awake for 16,000 hours in his [04:57] 16,000 hours in his [04:57] 16,000 hours in his life um [05:00] life um [05:00] life um and the amount of information that has [05:02] and the amount of information that has [05:02] and the amount of information that has uh reached the visual cortex of that [05:06] uh reached the visual cortex of that [05:06] uh reached the visual cortex of that child in four [05:07] child in four [05:07] child in four years um is about 10 to the 15 bytes and [05:12] years um is about 10 to the 15 bytes and [05:12] years um is about 10 to the 15 bytes and you can compute this by estimating that [05:14] you can compute this by estimating that [05:14] you can compute this by estimating that the optical nerve carry about 20 megab [05:17] the optical nerve carry about 20 megab [05:17] the optical nerve carry about 20 megab megabytes per second roughly and so 10^ [05:20] megabytes per second roughly and so 10^ [05:20] megabytes per second roughly and so 10^ the 15 bytes for a four-year-old versus [05:22] the 15 bytes for a four-year-old versus [05:23] the 15 bytes for a four-year-old versus 2 * 10 to 13 bytes for 170,000 years [05:27] 2 * 10 to 13 bytes for 170,000 years [05:27] 2 * 10 to 13 bytes for 170,000 years worth of reading what it tells you is [05:30] worth of reading what it tells you is [05:30] worth of reading what it tells you is that uh through sensory input we see a [05:34] that uh through sensory input we see a [05:34] that uh through sensory input we see a lot more information than we than we do [05:36] lot more information than we than we do [05:36] lot more information than we than we do through [05:37] through [05:37] through language and that despite our [05:39] language and that despite our [05:39] language and that despite our intuition most of what we learn and most [05:42] intuition most of what we learn and most [05:42] intuition most of what we learn and most of our knowledge is through our [05:45] of our knowledge is through our [05:45] of our knowledge is through our observation and interaction with the [05:47] observation and interaction with the [05:47] observation and interaction with the real world not through language [05:49] real world not through language [05:49] real world not through language everything that we learn in the first [05:50] everything that we learn in the first [05:50] everything that we learn in the first few years of life and uh certainly [05:53] few years of life and uh certainly [05:53] few years of life and uh certainly everything that animals learn has [05:54] everything that animals learn has [05:54] everything that animals learn has nothing to do with language so it would [05:57] nothing to do with language so it would [05:57] nothing to do with language so it would be good to uh maybe push against some of [05:59] be good to uh maybe push against some of [05:59] be good to uh maybe push against some of of the intuition behind what you're [06:00] of the intuition behind what you're [06:00] of the intuition behind what you're saying [06:02] saying [06:02] saying so it is true there's several orders of [06:05] so it is true there's several orders of [06:05] so it is true there's several orders of magnitude more data coming into the [06:07] magnitude more data coming into the [06:07] magnitude more data coming into the human [06:08] human [06:08] human mind much faster and the human mind is [06:11] mind much faster and the human mind is [06:11] mind much faster and the human mind is able to learn very quickly from that [06:12] able to learn very quickly from that [06:12] able to learn very quickly from that filter the data very quickly you know [06:15] filter the data very quickly you know [06:15] filter the data very quickly you know somebody might argue your comparison [06:17] somebody might argue your comparison [06:17] somebody might argue your comparison between sensory data versus language [06:19] between sensory data versus language [06:19] between sensory data versus language that language is already very compressed [06:23] that language is already very compressed [06:23] that language is already very compressed it already contains a lot more [06:24] it already contains a lot more [06:24] it already contains a lot more information than the bytes it takes to [06:26] information than the bytes it takes to [06:26] information than the bytes it takes to store them if you compare it to visual [06:28] store them if you compare it to visual [06:28] store them if you compare it to visual data so there's a lot of wisdom and [06:30] data so there's a lot of wisdom and [06:30] data so there's a lot of wisdom and language there's words and the way we [06:32] language there's words and the way we [06:32] language there's words and the way we stitch them together it already contains [06:34] stitch them together it already contains [06:34] stitch them together it already contains a lot of information so is it possible [06:38] a lot of information so is it possible [06:38] a lot of information so is it possible that language alone already has [06:43] that language alone already has [06:43] that language alone already has enough wisdom and knowledge in there to [06:47] enough wisdom and knowledge in there to [06:47] enough wisdom and knowledge in there to be able to from that language construct [06:49] be able to from that language construct [06:49] be able to from that language construct a a world model and understanding of the [06:52] a a world model and understanding of the [06:52] a a world model and understanding of the world an understanding of the physical [06:53] world an understanding of the physical [06:54] world an understanding of the physical world that you're saying L LMS lack so [06:56] world that you're saying L LMS lack so [06:56] world that you're saying L LMS lack so it's a big debate among uh philosophers [07:00] it's a big debate among uh philosophers [07:00] it's a big debate among uh philosophers and also cognitive scientists like [07:02] and also cognitive scientists like [07:02] and also cognitive scientists like whether intelligence needs to be [07:03] whether intelligence needs to be [07:03] whether intelligence needs to be grounded in [07:04] grounded in [07:05] grounded in reali
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 0baa39318d86ebc13aa2668d6f8c5c479047d249b9fc7f66bd96b485fbac74a1
