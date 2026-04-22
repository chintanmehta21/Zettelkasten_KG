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
## URL 1: https://www.youtube.com/watch?v=hhjhU5MXZOo

### SUMMARY
```yaml
mini_title: 'DMT: Properties, Research, Experiences'
brief_summary: This summary provides a comprehensive review of Dimethyltryptamine
  (DMT), an endogenous psychedelic compound. It delves into its neuropharmacological
  properties, historical timeline, and various hypotheses concerning its subjective
  phenomena, including entity encounters and links to near-death experiences. Key
  figures like Chris Timmerman and Rick Strassman are highlighted for their significant
  re
tags:
- dmt
- dimethyltryptamine
- psychedelics
- neuropharmacology
- consciousness
- rick-strassman
- terrence-mckenna
- research
- mental-health
- altered-states
detailed_summary:
- heading: thesis
  bullets:
  - To provide a comprehensive overview of Dimethyltryptamine (DMT), covering its
    neuropharmacological properties, historical context, subjective effects, research
    findings, consumption methods, and therapeutic potential, while also addressing
    safety and research limitations.
  sub_sections: {}
- heading: format
  bullets:
  - review
  sub_sections: {}
- heading: chapters_or_segments
  bullets:
  - '{"timestamp": null, "title": "Properties & Neuropharmacology", "bullets": ["DMT
    is an endogenous psychedelic compound with an indole ring structure similar to
    serotonin, allowing it to bind to serotonin receptors.", "This binding disrupts
    the brain''s top-down hierarchical control, inducing a state of \"global hyperconnectivity\"
    where disparate brain regions communicate more freely.", "Neuroscientist Chris
    Timmerman proposes DMT causes \"functional deafferentation,\" a state where the
    brain disconnects from external sensory input to generate a vivid internal simulation,
    likened to \"dreaming with your eyes open.\"", "This hypothesis is supported by
    findings of theta wave patterns similar to those in REM sleep.", "Recent research
    suggests endogenous DMT levels in the brain may be significantly higher than previously
    believed and could be involved in normal physiological processes.", "A key goal
    of some modern research is to use DMT as a tool to understand the fundamental
    nature of consciousness and how the brain constructs reality."]}'
  - '{"timestamp": null, "title": "Timeline & Key Figures", "bullets": ["**1852-1857:**
    British botanist Richard Spruce documents indigenous Amazonian ceremonies using
    DMT-containing brews called \"capi\" (Brazil) and \"iawaska\" (Peru), sending
    samples of the *Banisteriopsis caapi* vine to England.", "**Early 1930s:** German-Canadian
    chemist Richard Manske first synthesizes N,N-dimethyltryptamine, though its psychoactive
    properties remained unknown.", "**1943:** Albert Hofmann''s self-experiment with
    250 micrograms of LSD on April 19 initiates modern psychedelic research.", "**1960s:**
    Researchers, including Julius Axelrod, find DMT in human blood and evidence of
    its presence in the brain.", "**Late 1960s:** Terrence McKenna has his first experience
    smoking DMT, later describing encounters with \"self-transforming machine elves.\"",
    "**1966-1971:** LSD is outlawed in the US (1966-68), and the 1971 UN Convention
    on Psychotropic Substances halts most psychedelic research for decades.", "**1990s:**
    Dr. Rick Strassman conducts the first US human study on psychedelics in over 20
    years, administering approximately 400 intravenous doses of DMT to 60 volunteers
    over a 5-year period.", "**2000:** Terrence McKenna dies, leaving a 500+ hour
    audio archive."]}'
  - '{"timestamp": null, "title": "Hypotheses on Subjective Phenomena", "bullets":
    ["**Strassman''s \"Spirit Molecule\" Hypothesis:** Proposes the body naturally
    releases DMT during profound life events such as birth, death, or mystical experiences.",
    "**Entity Encounters:** One hypothesis suggests DMT hyper-activates brain regions
    for social cognition, causing the brain to simulate social interactions that manifest
    as sentient beings.", "**Near-Death Experience (NDE) Link:** The DMT experience
    shares features with NDEs (e.g., seeing a light, altered time). Timmerman suggests
    the brain''s massive transformation may trigger a signal that it is dying.", "Supporting
    this, one study found a significant increase in DMT levels in rats after cardiac
    arrest, and other research suggests DMT may have a neuroprotective function against
    oxygen deprivation.", "However, a key difference is that DMT experiences are reported
    as being more visual, while NDEs are more disembodied."]}'
  - '{"timestamp": null, "title": "Reported Experiences & Study Data", "bullets":
    ["**Strassman''s Study (Subject 34):** A volunteer with a history of depression,
    a past suicide attempt, and pre-existing beliefs in spirit guides reported being
    \"blasted out of my body,\" encountering \"aggressive, terrifying\" colors, animated
    clowns, a \"Tinkerbell-like\" entity, and communicating telepathically with beings
    in \"deep space\" for whom she served as an emotional \"bridge.\"", "**Johns Hopkins
    Survey (2,500+ users on entity encounters):** Most users *saw* entities; >50%
    *heard* them; ~33% *touched* them. Communication was described as telepathic by
    85%. Common labels were \"beings,\" \"guides,\" \"spirits,\" and \"aliens\"; \"clowns,\"
    \"demons,\" or \"devils\" were less common. The most reported emotions were love,
    trust, and joy; fear was a minority experience.", "**Belief Change:** In one study
    of users reporting a \"God encounter experience,\" the percentage identifying
    as atheist dropped from 25% pre-experience to 7% post-experience."]}'
  - '{"timestamp": null, "title": "Consumption Methods & Related Compounds", "bullets":
    ["**Ayahuasca (Oral):** A brew requiring a DMT-containing plant and the *Banisteriopsis
    caapi* vine, which contains MAO inhibitors (MAOIs) that make DMT orally active.
    Onset is ~45 minutes, duration is several hours, and it often induces vomiting.",
    "**Smoking/Vaporizing:** Onset is nearly instant (<1 minute), with a peak experience
    lasting only a few minutes.", "**Snorting:** Onset takes a few minutes, with a
    duration slightly longer than smoking.", "**IV Injection:** Near-instantaneous
    onset, used in clinical research.", "**5-MeO-DMT:** A related compound found in
    Colorado River toad secretions (licking the toad is toxic). It is fast-acting
    but tends to produce fewer visual hallucinations than N,N-DMT."]}'
  - '{"timestamp": null, "title": "Constraints & Research Status", "bullets": ["**Safety:**
    DMT is considered physiologically safe and non-addictive, altering perception
    itself, unlike stimulants (e.g., cocaine) which primarily activate the brain''s
    reward system.", "However, \"set and setting\" (user''s mindset and physical environment)
    are critical for the experience''s outcome. \"Bad trips\" can occur, leaving some
    users shaken for days and experiencing flashbacks of frightening hallucinations.",
    "Psychedelics can worsen existing mental health conditions, particularly psychotic
    disorders, and should not be used without professional guidance.", "**Therapeutic
    Research:** A therapeutic theory for depression suggests DMT works by disrupting
    rigid, negative self-beliefs (e.g., \"I am worthless\"), allowing for dynamic
    change.", "Modern studies, such as psychiatrist Simon Ruffell''s work with veterans,
    are preliminary, involve small participant numbers, and have inconclusive results.
    Some participants have reported a worsening of their mental health post-experience."]}'
  sub_sections: {}
- heading: closing_takeaway
  bullets:
  - While DMT is physiologically safe and holds promise for understanding consciousness
    and treating conditions like depression by disrupting rigid thought patterns,
    its use requires careful consideration of "set and setting," professional guidance,
    and awareness of potential adverse effects, especially for individuals with pre-existing
    mental health conditions, as current therapeutic research remains preliminary
    and inconclusive.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=hhjhU5MXZOo
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=34612
  total_tokens_used: 27689
  gemini_pro_tokens: 23382
  gemini_flash_tokens: 4307
  total_latency_ms: 111187
  cod_iterations_used: 2
  self_check_missing_count: 8
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: 'DMT: Properties, Research, Experiences'
    brief_summary: This summary provides a comprehensive review of Dimethyltryptamine
      (DMT), an endogenous psychedelic compound. It delves into its neuropharmacological
      properties, historical timeline, and various hypotheses concerning its subjective
      phenomena, including entity encounters and links to near-death experiences.
      Key figures like Chris Timmerman and Rick Strassman are highlighted for their
      significant research contributions. The content also explores different consumption
      methods, safety considerations, and the current status of therapeutic research.
      While DMT shows promise for understanding consciousness and potentially treating
      conditions like depression by disrupting rigid thought patterns, the summary
      emphasizes the critical importance of "set and setting" and professional guidance
      due to potential adverse effects and the preliminary nature of current therapeutic
      studies.
    tags:
    - dmt
    - dimethyltryptamine
    - psychedelics
    - neuropharmacology
    - consciousness
    - rick-strassman
    - terrence-mckenna
    - research
    - mental-health
    - altered-states
    speakers:
    - Chris Timmerman
    - Richard Spruce
    - Richard Manske
    - Albert Hofmann
    - Julius Axelrod
    - Terrence McKenna
    - Rick Strassman
    - Simon Ruffell
    guests: null
    entities_discussed:
    - Dimethyltryptamine (DMT)
    - LSD
    - Ayahuasca
    - Banisteriopsis caapi
    - UN Convention on Psychotropic Substances
    - 5-MeO-DMT
    - Colorado River toad
    detailed_summary:
      thesis: To provide a comprehensive overview of Dimethyltryptamine (DMT), covering
        its neuropharmacological properties, historical context, subjective effects,
        research findings, consumption methods, and therapeutic potential, while also
        addressing safety and research limitations.
      format: review
      chapters_or_segments:
      - timestamp: null
        title: Properties & Neuropharmacology
        bullets:
        - DMT is an endogenous psychedelic compound with an indole ring structure
          similar to serotonin, allowing it to bind to serotonin receptors.
        - This binding disrupts the brain's top-down hierarchical control, inducing
          a state of "global hyperconnectivity" where disparate brain regions communicate
          more freely.
        - Neuroscientist Chris Timmerman proposes DMT causes "functional deafferentation,"
          a state where the brain disconnects from external sensory input to generate
          a vivid internal simulation, likened to "dreaming with your eyes open."
        - This hypothesis is supported by findings of theta wave patterns similar
          to those in REM sleep.
        - Recent research suggests endogenous DMT levels in the brain may be significantly
          higher than previously believed and could be involved in normal physiological
          processes.
        - A key goal of some modern research is to use DMT as a tool to understand
          the fundamental nature of consciousness and how the brain constructs reality.
      - timestamp: null
        title: Timeline & Key Figures
        bullets:
        - '**1852-1857:** British botanist Richard Spruce documents indigenous Amazonian
          ceremonies using DMT-containing brews called "capi" (Brazil) and "iawaska"
          (Peru), sending samples of the *Banisteriopsis caapi* vine to England.'
        - '**Early 1930s:** German-Canadian chemist Richard Manske first synthesizes
          N,N-dimethyltryptamine, though its psychoactive properties remained unknown.'
        - '**1943:** Albert Hofmann''s self-experiment with 250 micrograms of LSD
          on April 19 initiates modern psychedelic research.'
        - '**1960s:** Researchers, including Julius Axelrod, find DMT in human blood
          and evidence of its presence in the brain.'
        - '**Late 1960s:** Terrence McKenna has his first experience smoking DMT,
          later describing encounters with "self-transforming machine elves."'
        - '**1966-1971:** LSD is outlawed in the US (1966-68), and the 1971 UN Convention
          on Psychotropic Substances halts most psychedelic research for decades.'
        - '**1990s:** Dr. Rick Strassman conducts the first US human study on psychedelics
          in over 20 years, administering approximately 400 intravenous doses of DMT
          to 60 volunteers over a 5-year period.'
        - '**2000:** Terrence McKenna dies, leaving a 500+ hour audio archive.'
      - timestamp: null
        title: Hypotheses on Subjective Phenomena
        bullets:
        - '**Strassman''s "Spirit Molecule" Hypothesis:** Proposes the body naturally
          releases DMT during profound life events such as birth, death, or mystical
          experiences.'
        - '**Entity Encounters:** One hypothesis suggests DMT hyper-activates brain
          regions for social cognition, causing the brain to simulate social interactions
          that manifest as sentient beings.'
        - '**Near-Death Experience (NDE) Link:** The DMT experience shares features
          with NDEs (e.g., seeing a light, altered time). Timmerman suggests the brain''s
          massive transformation may trigger a signal that it is dying.'
        - Supporting this, one study found a significant increase in DMT levels in
          rats after cardiac arrest, and other research suggests DMT may have a neuroprotective
          function against oxygen deprivation.
        - However, a key difference is that DMT experiences are reported as being
          more visual, while NDEs are more disembodied.
      - timestamp: null
        title: Reported Experiences & Study Data
        bullets:
        - '**Strassman''s Study (Subject 34):** A volunteer with a history of depression,
          a past suicide attempt, and pre-existing beliefs in spirit guides reported
          being "blasted out of my body," encountering "aggressive, terrifying" colors,
          animated clowns, a "Tinkerbell-like" entity, and communicating telepathically
          with beings in "deep space" for whom she served as an emotional "bridge."'
        - '**Johns Hopkins Survey (2,500+ users on entity encounters):** Most users
          *saw* entities; >50% *heard* them; ~33% *touched* them. Communication was
          described as telepathic by 85%. Common labels were "beings," "guides," "spirits,"
          and "aliens"; "clowns," "demons," or "devils" were less common. The most
          reported emotions were love, trust, and joy; fear was a minority experience.'
        - '**Belief Change:** In one study of users reporting a "God encounter experience,"
          the percentage identifying as atheist dropped from 25% pre-experience to
          7% post-experience.'
      - timestamp: null
        title: Consumption Methods & Related Compounds
        bullets:
        - '**Ayahuasca (Oral):** A brew requiring a DMT-containing plant and the *Banisteriopsis
          caapi* vine, which contains MAO inhibitors (MAOIs) that make DMT orally
          active. Onset is ~45 minutes, duration is several hours, and it often induces
          vomiting.'
        - '**Smoking/Vaporizing:** Onset is nearly instant (<1 minute), with a peak
          experience lasting only a few minutes.'
        - '**Snorting:** Onset takes a few minutes, with a duration slightly longer
          than smoking.'
        - '**IV Injection:** Near-instantaneous onset, used in clinical research.'
        - '**5-MeO-DMT:** A related compound found in Colorado River toad secretions
          (licking the toad is toxic). It is fast-acting but tends to produce fewer
          visual hallucinations than N,N-DMT.'
      - timestamp: null
        title: Constraints & Research Status
        bullets:
        - '**Safety:** DMT is considered physiologically safe and non-addictive, altering
          perception itself, unlike stimulants (e.g., cocaine) which primarily activate
          the brain''s reward system.'
        - However, "set and setting" (user's mindset and physical environment) are
          critical for the experience's outcome. "Bad trips" can occur, leaving some
          users shaken for days and experiencing flashbacks of frightening hallucinations.
        - Psychedelics can worsen existing mental health conditions, particularly
          psychotic disorders, and should not be used without professional guidance.
        - '**Therapeutic Research:** A therapeutic theory for depression suggests
          DMT works by disrupting rigid, negative self-beliefs (e.g., "I am worthless"),
          allowing for dynamic change.'
        - Modern studies, such as psychiatrist Simon Ruffell's work with veterans,
          are preliminary, involve small participant numbers, and have inconclusive
          results. Some participants have reported a worsening of their mental health
          post-experience.
      demonstrations: []
      closing_takeaway: While DMT is physiologically safe and holds promise for understanding
        consciousness and treating conditions like depression by disrupting rigid
        thought patterns, its use requires careful consideration of "set and setting,"
        professional guidance, and awareness of potential adverse effects, especially
        for individuals with pre-existing mental health conditions, as current therapeutic
        research remains preliminary and inconclusive.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
The Strangest Drug Ever Studied

Transcript
Kind: captions Language: en This is test subject 34. She's just been given a substance often described as the [music] most powerful psychedelic drug in the world. It makes her feel like she's being launched into outer space. Other users report near-death experiences, profound insights, and mythical encounters with spiritual beings. The drug appears to shape the very foundations of human perception. &gt;&gt; It is one of the most weird and unexpected things a person can go through. &gt;&gt; We're talking about dimethylryptamine or DMT. In its pure synthetic form, it looks like an inconspicuous crystalline powder. &gt;&gt; It's a very simple molecule. &gt;&gt; And yet, DMT has been puzzling scientists around the globe for more than a century. The substance has been used in indigenous cultures for thousands of years. It occurs naturally in plants, animals, and even in the human body. But when it interacts with our brain, things seem to go completely off the rails. Many users say DMT fundamentally changed their lives. And yet, other experiences suggest there's more to DMT than profound revelations, mystical encounters, and medical promise. For some people, the substance can also open doors to the darkest corners of their consciousness. This is the enduring mystery of DMT. [music] &gt;&gt; [music] &gt;&gt; November 1852. This is British botonist Richard Spruce. For the past 3 years, he's been making his way through the Amazon rainforest to study plants. He's particularly interested in mosses. Along the way, he keeps encountering indigenous communities living deep in the jungle. He learns their languages and studies their customs. Right now, Spruce is staying with an indigenous group in what is now northwestern Brazil. Today is a special occasion. The tribe is about to hold a spiritual ceremony, and at the center of it all is this ritual brew. Its key ingredient is a specific type of Lyanna. Indigenous people have been drinking or chewing it for thousands of years. Some groups call it napa, others bako or pinde. This group calls it capi. And tonight, Spruce is going to try it himself. He watches several young members of the community drink the mixture before him. He notes that for about 10 minutes, they appear to be possessed with reckless fury. Then they calm down and simply continue dancing. Then it's his turn. But the tribe didn't just prepare copy for him. I had scarcely dispatched one cup of the nauseous beverage when the ruler of the feast came up with a woman bearing a large calabash [music] of Mandioa beer called casherie. After that, protocol demands that he top things off with a cigar and a cup of palm wine. Spruce has to fight off the urge to vomit and stretches out in a hammock. The copy is slowly kicking in. He later notes in his journal that white men taking copy all seem to report the same experience. They feel alternations of cold and heat, fear and boldness. The sight is disturbed and visions pass rapidly before the eyes wherein everything gorgeous and magnificent they have heard or read of seems combined. And presently the scene changes to things uncouthed and horrible. Hey, this is Jonas, one of the founders of Fern. It's not just psychedelics that can shape our minds. Our thoughts and emotions are molded by relationships, opportunities, but also uncertainty and major life events. For many in our team, pressures often come as [music] deadlines piling up. It's not always dramatic, but over time it can become serious. That's why we encourage our team and viewers to seek support if needed. Some choose to talk to a friend, a colleague, or professionals like the paid partner of today's video. BetterHelp matches you with credentialed therapists based on your preferences, and you can switch therapists anytime. [music] We are aware of the criticism surrounding the platform and online therapy certainly isn't for everyone, but we also believe it can be genuinely helpful to [music] many. Recent surveys show that 86% would use their service again and since 2023, BetterHelp has improved its data privacy practices. [music] Under new leadership, they've been certified by HighTrust, a globally recognized standard for healthcare data security. If you feel better might be helpful, click the link in the description or go to betterhelp.com/fern to get 10% off your first month. Spruce calls the plant bonisteria copy. Bonisteria was the term used at the time for a class of tropical climbing plants. Copy is an indigenous word for grass. He samples a couple of those vines, dries them, and has them shipped to England. Over the following years, Spruce keeps traveling South America and repeatedly comes across Cappy. One of these encounters takes place in 1857 among an indigenous group in Peru. They also use the vine to prepare a powerful brew. They mix it with other plants and call it iawaska. Spruce apparently doesn't drink it himself this time. Instead, he asks the locals to describe their experiences to him. To Spruce, the brew remains an unsolved mystery. He simply can't figure out which particular substances cause these extreme effects. He's already familiar with opium and cannabis, but copy seems to be much more potent. What he doesn't realize is that he's been looking in the wrong place. The plant he sent back to Europe isn't the key ingredient. Technically, it's not the Lyanna or Banisteria copy that produces the intoxicating effect. The real trigger is a special compound found in the leaves mixed into the brew. DMT, more precisely, NDMT. Its molecular structure is surprisingly simple compared to other psychedelics. Its complete name is N and dimethylryptamine, but we'll simply refer to it as DMT throughout this video. German Canadian chemist Richard Mans was the first to synthesize the substance in the early 1930s. Back then, he had no idea of its extraordinary psychoactive effects. At its core, DMT is characterized by a nitrogen atom bonded to two methyl groups, [music] hence the name dimethyl. A methyl group consists of one carbon atom bonded to three hydrogen atoms. It's one of the simplest building blocks in organic chemistry. The nitrogen atom is connected via short carbon chain to the most important part of the molecular structure, the so-called indole ring. The same structural feature can also be found in other known psychedelics like LSD or psilocybin. And within the molecular structure of serotonin, serotonin is a neurotransmitter, a molecule that carries chemical messages or signals between nerve cells. It plays a key role in some of our most essential bodily functions from mood, sleep, digestion, and nausea to wound healing and sexual desire. Because of their structural similarity, psychedelics like DMT combined to the same receptors usually used by serotonin are like key locks and drugs are like specific keys that act on specific key locks. And so these classic psychedelic drugs which with which DMT is one of them act on specific kilocks in the brain and specifically these serotonin receptors in the brain. This is Chris Timberman. He's a neuroscientist and one of the world's leading researchers on DMT. He spends much of his time traveling for research, so we're lucky enough to catch him on a video call. It's likely that DMT was also the main active compound in the brew that Spruce encountered back in the jungle. Today that mixture is widely known as iawasa. To produce it you mainly need two ingredients. The first one consists of plants that contain DMT. They grow across large parts of the Amazon basin though not exclusively there. The second ingredient is the capi lyana documented by spruce. It doesn't contain DMT itself but it is crucial for making the DMT in the brew psychoactive. Mixing and boiling the two together produces the psychedelic plant drink known as iawasa. Psychedelics are generally considered physiologically safe and non-addictive. That's one of the key differences between them and drugs like cocaine or empetamines. Those primarily act as stimulants. They artificially increase dopamine and neuroepinephrine levels in the brain and strongly [music] activate our reward system. Psychedelics, on the other hand, alter perception itself. Users may see or hear things that aren't there, hallucinate and lose their sense of time and space. Some report life-changing experiences. In many ways, psychedelic substances seem to fundamentally alter how we think and feel, which is precisely why DMT continues to fascinate scientists to this day. In terms of the psychological impact of the experiences, in terms of the subjective effects it generates, it is one of the most weird and unexpected things a person can go through. April 19th, 1943, a bike path near Basil in Switzerland. This is Swiss chemist Albert Hoffman. He works as a researcher for a Swiss pharmaceutical company. Riding next to him is his lab assistant. He explicitly asked her to come along. He's desperately trying to get home. Earlier that day, he started conducting an experiment on himself. He dissolved 250 g of lysurgic acid diialthamide in [music] water and ingested it. He had synthesized the compound in the lab after isolating it from the urgot fungus. And right now he's feeling a bit under the weather. Everything in my field of vision wavered and was distorted as if seen in a curved mirror. I also had the sensation of being unable to move from the spot. Nevertheless, my assistant later told me that we had traveled very rapidly. &gt;&gt; Stretching out on the couch back home doesn't help much either. &gt;&gt; My surroundings had now transformed themselves in more terrifying ways. Everything in the room spun around and familiar objects and pieces of furniture assumed grotesque, threatening forms. They were in constant motion, animated as if driven by an inner restlessness. The lady next door, whom I scarcely recognized, brought me milk. She was no longer Mrs. R, but appeared instead as a malevalent insidious witch wearing a colored mask. Albert Hoffman has just embarked on the world's first LSD trip. He has no idea what the substance does. He believed 250 micrograms to be prudently safe dose, but it turns out to be extraordinarily potent, and now he fears he may lose his mind. A few hours later, the effects slowly begin to soften. The trip becomes more pleasant. As he steps out into his garden after a spring rain, it feels as though he's seeing everything for the very first time. &gt;&gt; Everything glistened and sparkled in a fresh light. &gt;&gt; From that day on, Hoffman is convinced that this tiny molecule holds enormous power, that it could someday be of great value to medicine and psychiatry. His discovery jumpstarts the entire field of psychedelic research. Hoffman inspires many other scientists to follow his lead. [music] And in the 1950s, he becomes the first to isolate the psychoactive compounds psilocybin from psychedelic mushrooms. That's another major milestone. But psychedelic research also turns its attention to DMT. Scientists discover more and more plants that contain the substance. To date, it has been found in at least 50 different plant species. DMT has also been found in mammals like rats and rabbits. In the 1960s, a German researcher team even found traces of the substance in human blood. Shortly after, US Nobel Prizewinning scientist Julius Axelrod provided evidence that DMT occurs naturally in the human brain. It's even considered endogenous, meaning our own bodies produce it naturally. &gt;&gt; There's a saying that says DMT is everywhere, and it is also found in the human body and in a lot of mammals bodies as well. Throughout the 1960s, scientists keep isolating DMT in humans, animals, and plants. And meanwhile, psychedelics are starting to seep into popular culture. &gt;&gt; How often have you taken LSD? &gt;&gt; About four times. The swinging 60s [music] are the peak years of the hippie movement and psychedelics like LSD. The cultural revolution is fueled by activists, intellectuals, and artists alike. One of them is Terrence McKenna. He is just studying at Berkeley. He's 18 years old and has already done his fair share of experiments with psychedelics like LSD. But what he is about to experience tonight will eclipse everything he has ever felt. A friend has come to visit and brought this white crystallin powder. He claims it was stolen from a US Army chemical research facility. It's DMT. And for the first time in his life, young Terrence McKenna is about to smoke it. I had this hallucination of tumbling [music] forward into these fractal geometric shapes made of light. And then I found myself in the equivalent of the Pope's private chapel. And there were insect elf machines profering strange little tablets with strange writing on them. These self-transforming machine elf creatures were speaking in a colored language which condensed into rotating machines that were like fabraier eggs. All this stuff was so weird and so alien and [music] so unglishable that it was a complete shock. I mean, the literal turning inside out of my intellectual universe. It's like being [music] struck by noetic lightning. The experience completely changes McKenna's view of life and reality. He becomes convinced that there is another secret world, one we normally can't see or access. He drops out of university to chase this mystery. He travels to Nepal to meet Tibetan shamans. He works as a professional butterfly collector in Indonesia, and he ventures deep into the Colombian jungle with his brother and three friends. McKenna's description of the so-called machine elves becomes a cultural reference. Countless DMT users later report encountering mystical entities that closely match what he described. He dies in 2000, leaving behind an extensive audio archive with over 500 hours of theories on psychedelics and spirituality. A drug like synthetic iawaska pharmasa. Do people realize this is the same thing as has been taken for thousands of years down there? Do they realize its role in shamanic healing? &gt;&gt; By the late 1960s, authorities began cracking down on the widespread drug use in the US. Oh, &gt;&gt; you [music] know, I mean, if I was to say where I got it from, you know, it's illegal and everything. It's silly to say that. In 1966, California and Nevada become the first states to outlaw the production, sale, and possession of LSD. Two years later, the drug is banned across the entire country. &gt;&gt; America's public enemy number one is drug abuse. &gt;&gt; America's war on drugs soon extends to much of the rest of the world. In 1971, the United Nations adopts the Convention on Psychotropic Substances. Many countries outlaw psychedelic substances and sharply restrict their use, including DMT. From that point on, only a handful of approved scientific institutions are allowed to continue their research on them, and even they have to adhere to extremely strict regulations. For decades, DMT research effectively grinds to a halt. The whole class of compounds got pulled off the the clinical bench, and no research has gone on for 40 years. &gt;&gt; One of the tragedies to me is that the clinical research on these substances [music] pretty much stopped around 1970. Dr. Rick Strathman is a psychiatrist. He set on bringing psychedelic research back to life. His study is the first attempt to observe the effects of psychedelic substances in humans in the US in over 20 years. [music] He wants to know what DMT does to our mind and body. The participants are numbered. [music] Sarah is subject 34. She's in her early 40s and lives with her second husband. She has three children and works as a freelance writer. She has told the researchers that an angel once visited her when she had a high fever as a child and that every now and then she communicates with spirit guides for advice and support. She also suffers from depression. In her 20s, she overdosed on tranquilizers and was hospitalized for 2 weeks following the suicide attempt. Today, she wants to find out whether DMT can help her gain a deeper [music] understanding of herself and her relationship to the universe. The experiment is set to begin in just a few seconds. The onset of DMT's effects largely depend on how you consume it. Most recreational users smoke DMT using a glass pipe. This makes the effects kick in extremely fast, usually in under 1 minute. [music] The peak experience tends to last only a couple of minutes before wearing off. The smoke tastes unpleasant and can trigger coughing fits. Another substance closely related to N and DMT is called 5 MO DMT. This YouTuber smoked it for one of his videos. Others try to consume it like this. 5 mod DMT occurs naturally in secretions of the Colorado River toad. A common misconception is that licking the toad will get you high. It won't, and it can be extremely toxic. Most research today focuses on synthetic 5met. It also kicks in very fast and strong, but tends to produce far fewer visual hallucinations than NDMT. DMT can also be snorted. In that case, the effects take a few minutes to kick in, [music] but the trip also lasts a bit longer. Iaska usually contains the highest dose of DMT. The effects begin after around 45 minutes and can last several hours. But the brew is tough on the stomach. Many people have to throw up during the trip. Two things are paramount for a pleasant DMT experience. Set and setting. The right mix of emotional stability and soothing surroundings. Experts recommend a calm environment where users feel safe [music] and are able to lie down comfortably. Mixing substances can be extremely dangerous. Some users avoid alcohol, masturbation, and watching the news before attending an Iawaska retreat. But not even the best preparation can guarantee DMT won't produce what many call a bad trip. Some users online describe experiences that leave them shaken for days with flashbacks to vivid hallucinations of falling or flying through tunnels and encounters with frightening beings. Psychedelics can also worsen existing mental health issues. People who suffer from psychotic disorders or are mentally unstable should not take them. In general, DMT should never be used without professional guidance. Sarah's experience will be guided by Dr. Stman. In clinical settings like this one, DMT is administered via IV injection. It hits almost instantly. Sarah has previously been given a low introductory dose to see how her body reacts to the substance. Recreational users are advised to start with similar test doses. Sarah's lowd dose experience has been pleasant and relaxing. Now she's about to receive five full doses. She will go on five consecutive trips. After each one, Straman will let her come down to check in with her. She's all set. Sarah can feel the cool touch of Stman's hand, and she's trying to count her heartbeats. &gt;&gt; I got to three beats. Then there was a sound like a hum that turned into a whoosh. And then I was blasted out of my body at such speed with such force as if it were the speed of light. The colors were aggressive, terrifying. I felt as if they would consume me, as if I were on a warp speed conveyor belt heading straight into the cosmic psychedelic buzzsaw. I was terrified. I felt abandoned. I'm completely and totally lost. I have never been so alone. I was scared, but I kept telling myself, "Relax, surrender, embrace." It was all flashing and whirling lights. I was rather disappointed here. I'm expecting this profound spiritual experience and I get Las Vegas. But then before I had much time to be disappointed, I flew on and saw clowns performing. They were like toys or animated clowns. I had the overwhelming urge to laugh. I was kind of self-conscious about it at first, but I couldn't contain myself and I laughed out loud watching those clouds. Suddenly, a pulsating entity appeared in the patterns. It sounds weird to describe it as Tinkerbellike. It was trying to c
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 79f5a9b125e72937d44ecbb1cd276e4648cfc61bd147eec7c706541148bc6508
