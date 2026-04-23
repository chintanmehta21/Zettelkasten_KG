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
## URL 1: https://www.youtube.com/watch?v=8jPQjjsBbIc

### SUMMARY
```yaml
mini_title: Pre Mortem Anticipating Failure Mitigating
brief_summary: 'In this lecture, Daniel Levitin argues that the pre-mortem, or prospective
  hindsight, is a technique for anticipating and mitigating failures by identifying
  potential problems in advance and establishing systems to prevent them. It references
  Pre-mortem, Prospective Hindsight, and Cortisol. The closing takeaway: The pre-mortem
  technique accepts human fallibility and aims not for perfection, but for establishing
  systems that effectively minimize the damage from inevitable failures.'
tags:
- pre-mortem
- risk-management
- decision-making
- cognitive-science
- psychology
- stress-management
- failure-prevention
- daniel-levitin
- lecture-summary
- lecture
detailed_summary:
- heading: Overview
  bullets:
  - In this lecture, Daniel Levitin argues that the pre-mortem, or prospective hindsight,
    is a technique for anticipating and mitigating failures by identifying potential
    problems in advance and establishing systems to prevent them.
  sub_sections:
    Format and speakers:
    - 'Format: lecture.'
    - 'Speakers: Daniel Levitin.'
    Thesis:
    - The pre-mortem, or prospective hindsight, is a technique for anticipating and
      mitigating failures by identifying potential problems in advance and establishing
      systems to prevent them. This method, advocated by Daniel Levitin and developed
      by Gary Klein, is designed to counteract the cognitive impairment caused by
      stress.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    Pre-Mortem Concept:
    - The pre-mortem technique, also known as prospective hindsight, aims to anticipate
      and mitigate potential failures.
    - It involves proactively identifying problems and establishing preventative systems
      before they occur.
    - Neuroscientist Daniel Levitin advocates for this method, which psychologist
      Gary Klein originally developed.
    - The core purpose is to counteract the cognitive impairment that stress can induce.
    - This approach encourages clear thinking in advance of potentially stressful
      situations.
    Stress and Cognitive Impairment:
    - Stress triggers the release of cortisol in the brain, which negatively impacts
      rational and logical thought processes.
    - This physiological response is an evolutionary fight-or-flight mechanism.
    - Elevated heart rate and modulated adrenaline are common physical manifestations
      of stress.
    - Non-essential bodily systems, such as digestion and the immune system, are temporarily
      shut down under stress.
    - Daniel Levitin's personal anecdote of being locked out of his house illustrates
      how stress impairs judgment, leading to forgotten items like a passport.
    - He later implemented a combination lockbox for a spare key, demonstrating a
      system created during a non-stressful state to prevent future issues.
    Counteracting Memory Flaws:
    - The brain's hippocampus excels at spatial memory for static objects but struggles
      with tracking moving items.
    - An experiment involving squirrels with disabled olfaction demonstrated their
      reliance on spatial memory to locate buried nuts.
    - A practical system for frequently misplaced objects involves designating a permanent,
      specific location for them.
    - For essential travel documents like passports, driver's licenses, and credit
      cards, taking a photograph and emailing it to oneself provides cloud-based access.
    - This digital backup ensures access to critical information if physical documents
      are lost or stolen.
    High-Stakes Decisions and NNT:
    - Medical choices serve as a representative example for other significant financial
      or social decisions.
    - A pre-mortem approach involves knowing the right questions to ask to rationally
      assess risks before stress clouds judgment.
    - The Number Needed to Treat (NNT) is a crucial metric for evaluating the efficacy
      of medical treatments.
    - NNT quantifies how many people must receive a treatment for one person to experience
      a benefit.
    - For a widely prescribed statin, the NNT is 300, meaning 300 people must take
      it for one year to prevent one adverse event.
    - However, statin side effects occur in 5% of patients, making a patient 15 times
      more likely to experience harm than benefit.
    Medical Efficacy and Informed Consent:
    - Prostate cancer surgery for men over 50 has an NNT of 49.
    - Approximately 50% of prostate cancer surgery patients experience significant
      side effects, including impotence, incontinence, or rectal tearing.
    - These side effects can persist for one to two years post-surgery.
    - GlaxoSmithKline estimates that 90% of drugs are effective in only 30-50% of
      the population.
    - This data is crucial for ensuring informed consent, enabling rational discussions
      about risks versus benefits.
    - A pre-mortem approach also includes pre-considering abstract quality-of-life
      questions, such as balancing a shorter, pain-free life against a longer life
      with pain.
    Damage Control Objective:
    - The primary objective of implementing the pre-mortem technique is not to achieve
      absolute perfection in outcomes.
    - It operates on the fundamental acceptance that humans are inherently flawed
      and will inevitably experience failures.
    - The system is specifically designed to proactively minimize the negative impact
      and extent of damage resulting from these anticipated failures.
    - By identifying potential issues beforehand, the pre-mortem allows for the creation
      of robust contingency plans.
    - This proactive approach ensures that when failures do occur, their consequences
      are significantly reduced and more manageable.
- heading: Demonstrations
  bullets:
  - Daniel Levitin's personal anecdote of being locked out of his house and forgetting
    his passport, illustrating stress-induced cognitive impairment and the subsequent
    creation of a preventative system.
  - An experiment with squirrels demonstrating the hippocampus's role in spatial memory
    and its limitations for tracking moving objects.
  - Analysis of statin efficacy using the Number Needed to Treat (NNT) metric, highlighting
    the risk-benefit ratio.
  - Analysis of prostate cancer surgery outcomes using the NNT metric and discussing
    common side effects.
  sub_sections: {}
- heading: Closing remarks
  bullets:
  - The pre-mortem technique accepts human fallibility and aims not for perfection,
    but for establishing systems that effectively minimize the damage from inevitable
    failures. By anticipating problems proactively, individuals can make more rational
    decisions and mitigate adverse outcomes.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=8jPQjjsBbIc
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=14468
  total_tokens_used: 18551
  gemini_pro_tokens: 15125
  gemini_flash_tokens: 3426
  total_latency_ms: 74483
  cod_iterations_used: 2
  self_check_missing_count: 4
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: Pre Mortem Anticipating Failure Mitigating
    brief_summary: 'In this lecture, Daniel Levitin argues that the pre-mortem, or
      prospective hindsight, is a technique for anticipating and mitigating failures
      by identifying potential problems in advance and establishing systems to prevent
      them. It references Pre-mortem, Prospective Hindsight, and Cortisol. The closing
      takeaway: The pre-mortem technique accepts human fallibility and aims not for
      perfection, but for establishing systems that effectively minimize the damage
      from inevitable failures.'
    tags:
    - pre-mortem
    - risk-management
    - decision-making
    - cognitive-science
    - psychology
    - stress-management
    - failure-prevention
    - daniel-levitin
    - lecture-summary
    - lecture
    speakers:
    - Daniel Levitin
    guests: null
    entities_discussed:
    - Pre-mortem
    - Prospective Hindsight
    - Cortisol
    - Hippocampus
    - Number Needed to Treat (NNT)
    - Statins
    - GlaxoSmithKline
    detailed_summary:
      thesis: The pre-mortem, or prospective hindsight, is a technique for anticipating
        and mitigating failures by identifying potential problems in advance and establishing
        systems to prevent them. This method, advocated by Daniel Levitin and developed
        by Gary Klein, is designed to counteract the cognitive impairment caused by
        stress.
      format: lecture
      chapters_or_segments:
      - timestamp: ''
        title: Pre-Mortem Concept
        bullets:
        - The pre-mortem technique, also known as prospective hindsight, aims to anticipate
          and mitigate potential failures.
        - It involves proactively identifying problems and establishing preventative
          systems before they occur.
        - Neuroscientist Daniel Levitin advocates for this method, which psychologist
          Gary Klein originally developed.
        - The core purpose is to counteract the cognitive impairment that stress can
          induce.
        - This approach encourages clear thinking in advance of potentially stressful
          situations.
      - timestamp: ''
        title: Stress and Cognitive Impairment
        bullets:
        - Stress triggers the release of cortisol in the brain, which negatively impacts
          rational and logical thought processes.
        - This physiological response is an evolutionary fight-or-flight mechanism.
        - Elevated heart rate and modulated adrenaline are common physical manifestations
          of stress.
        - Non-essential bodily systems, such as digestion and the immune system, are
          temporarily shut down under stress.
        - Daniel Levitin's personal anecdote of being locked out of his house illustrates
          how stress impairs judgment, leading to forgotten items like a passport.
        - He later implemented a combination lockbox for a spare key, demonstrating
          a system created during a non-stressful state to prevent future issues.
      - timestamp: ''
        title: Counteracting Memory Flaws
        bullets:
        - The brain's hippocampus excels at spatial memory for static objects but
          struggles with tracking moving items.
        - An experiment involving squirrels with disabled olfaction demonstrated their
          reliance on spatial memory to locate buried nuts.
        - A practical system for frequently misplaced objects involves designating
          a permanent, specific location for them.
        - For essential travel documents like passports, driver's licenses, and credit
          cards, taking a photograph and emailing it to oneself provides cloud-based
          access.
        - This digital backup ensures access to critical information if physical documents
          are lost or stolen.
      - timestamp: ''
        title: High-Stakes Decisions and NNT
        bullets:
        - Medical choices serve as a representative example for other significant
          financial or social decisions.
        - A pre-mortem approach involves knowing the right questions to ask to rationally
          assess risks before stress clouds judgment.
        - The Number Needed to Treat (NNT) is a crucial metric for evaluating the
          efficacy of medical treatments.
        - NNT quantifies how many people must receive a treatment for one person to
          experience a benefit.
        - For a widely prescribed statin, the NNT is 300, meaning 300 people must
          take it for one year to prevent one adverse event.
        - However, statin side effects occur in 5% of patients, making a patient 15
          times more likely to experience harm than benefit.
      - timestamp: ''
        title: Medical Efficacy and Informed Consent
        bullets:
        - Prostate cancer surgery for men over 50 has an NNT of 49.
        - Approximately 50% of prostate cancer surgery patients experience significant
          side effects, including impotence, incontinence, or rectal tearing.
        - These side effects can persist for one to two years post-surgery.
        - GlaxoSmithKline estimates that 90% of drugs are effective in only 30-50%
          of the population.
        - This data is crucial for ensuring informed consent, enabling rational discussions
          about risks versus benefits.
        - A pre-mortem approach also includes pre-considering abstract quality-of-life
          questions, such as balancing a shorter, pain-free life against a longer
          life with pain.
      - timestamp: ''
        title: Damage Control Objective
        bullets:
        - The primary objective of implementing the pre-mortem technique is not to
          achieve absolute perfection in outcomes.
        - It operates on the fundamental acceptance that humans are inherently flawed
          and will inevitably experience failures.
        - The system is specifically designed to proactively minimize the negative
          impact and extent of damage resulting from these anticipated failures.
        - By identifying potential issues beforehand, the pre-mortem allows for the
          creation of robust contingency plans.
        - This proactive approach ensures that when failures do occur, their consequences
          are significantly reduced and more manageable.
      demonstrations:
      - Daniel Levitin's personal anecdote of being locked out of his house and forgetting
        his passport, illustrating stress-induced cognitive impairment and the subsequent
        creation of a preventative system.
      - An experiment with squirrels demonstrating the hippocampus's role in spatial
        memory and its limitations for tracking moving objects.
      - Analysis of statin efficacy using the Number Needed to Treat (NNT) metric,
        highlighting the risk-benefit ratio.
      - Analysis of prostate cancer surgery outcomes using the NNT metric and discussing
        common side effects.
      closing_takeaway: The pre-mortem technique accepts human fallibility and aims
        not for perfection, but for establishing systems that effectively minimize
        the damage from inevitable failures. By anticipating problems proactively,
        individuals can make more rational decisions and mitigate adverse outcomes.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
How to stay calm when you know you'll be stressed | Daniel Levitin | TED

Transcript
Kind: captions Language: en [00:13] A few years ago, I broke into my own house. [00:16] I had just driven home, [00:18] it was around midnight in the dead of Montreal winter, [00:20] I had been visiting my friend, Jeff, across town, [00:23] and the thermometer on the front porch read minus 40 degrees -- [00:27] and don't bother asking if that's Celsius or Fahrenheit, [00:30] minus 40 is where the two scales meet -- [00:33] it was very cold. [00:34] And as I stood on the front porch fumbling in my pockets, [00:37] I found I didn't have my keys. [00:40] In fact, I could see them through the window, [00:42] lying on the dining room table where I had left them. [00:45] So I quickly ran around and tried all the other doors and windows, [00:48] and they were locked tight. [00:50] I thought about calling a locksmith -- at least I had my cellphone, [00:53] but at midnight, it could take a while for a locksmith to show up, [00:56] and it was cold. [01:00] I couldn't go back to my friend Jeff's house for the night [01:03] because I had an early flight to Europe the next morning, [01:05] and I needed to get my passport and my suitcase. [01:08] So, desperate and freezing cold, [01:10] I found a large rock and I broke through the basement window, [01:14] cleared out the shards of glass, [01:16] I crawled through, [01:17] I found a piece of cardboard and taped it up over the opening, [01:21] figuring that in the morning, on the way to the airport, [01:24] I could call my contractor and ask him to fix it. [01:26] This was going to be expensive, [01:28] but probably no more expensive than a middle-of-the-night locksmith, [01:31] so I figured, under the circumstances, I was coming out even. [01:36] Now, I'm a neuroscientist by training [01:39] and I know a little bit about how the brain performs under stress. [01:43] It releases cortisol that raises your heart rate, [01:46] it modulates adrenaline levels [01:49] and it clouds your thinking. [01:51] So the next morning, [01:53] when I woke up on too little sleep, [01:55] worrying about the hole in the window, [01:58] and a mental note that I had to call my contractor, [02:01] and the freezing temperatures, [02:02] and the meetings I had upcoming in Europe, [02:05] and, you know, with all the cortisol in my brain, [02:08] my thinking was cloudy, [02:10] but I didn't know it was cloudy because my thinking was cloudy. [02:13] (Laughter) [02:15] And it wasn't until I got to the airport check-in counter, [02:18] that I realized I didn't have my passport. [02:20] (Laughter) [02:22] So I raced home in the snow and ice, 40 minutes, [02:26] got my passport, raced back to the airport, [02:28] I made it just in time, [02:30] but they had given away my seat to someone else, [02:32] so I got stuck in the back of the plane, next to the bathrooms, [02:35] in a seat that wouldn't recline, on an eight-hour flight. [02:39] Well, I had a lot of time to think during those eight hours and no sleep. [02:43] (Laughter) [02:44] And I started wondering, are there things that I can do, [02:47] systems that I can put into place, [02:49] that will prevent bad things from happening? [02:51] Or at least if bad things happen, [02:53] will minimize the likelihood of it being a total catastrophe. [02:59] So I started thinking about that, [03:00] but my thoughts didn't crystallize until about a month later. [03:03] I was having dinner with my colleague, Danny Kahneman, the Nobel Prize winner, [03:07] and I somewhat embarrassedly told him about having broken my window, [03:10] and, you know, forgotten my passport, [03:13] and Danny shared with me [03:14] that he'd been practicing something called prospective hindsight. [03:19] (Laughter) [03:20] It's something that he had gotten from the psychologist Gary Klein, [03:24] who had written about it a few years before, [03:26] also called the pre-mortem. [03:28] Now, you all know what the postmortem is. [03:30] Whenever there's a disaster, [03:31] a team of experts come in and they try to figure out what went wrong, right? [03:36] Well, in the pre-mortem, Danny explained, [03:38] you look ahead and you try to figure out all the things that could go wrong, [03:42] and then you try to figure out what you can do [03:45] to prevent those things from happening, or to minimize the damage. [03:48] So what I want to talk to you about today [03:51] are some of the things we can do in the form of a pre-mortem. [03:55] Some of them are obvious, some of them are not so obvious. [03:58] I'll start with the obvious ones. [03:59] Around the home, designate a place for things that are easily lost. [04:05] Now, this sounds like common sense, and it is, [04:09] but there's a lot of science to back this up, [04:12] based on the way our spatial memory works. [04:15] There's a structure in the brain called the hippocampus, [04:18] that evolved over tens of thousands of years, [04:21] to keep track of the locations of important things -- [04:25] where the well is, where fish can be found, [04:27] that stand of fruit trees, [04:30] where the friendly and enemy tribes live. [04:32] The hippocampus is the part of the brain [04:34] that in London taxicab drivers becomes enlarged. [04:38] It's the part of the brain that allows squirrels to find their nuts. [04:41] And if you're wondering, somebody actually did the experiment [04:44] where they cut off the olfactory sense of the squirrels, [04:47] and they could still find their nuts. [04:49] They weren't using smell, they were using the hippocampus, [04:52] this exquisitely evolved mechanism in the brain for finding things. [04:57] But it's really good for things that don't move around much, [05:01] not so good for things that move around. [05:03] So this is why we lose car keys and reading glasses and passports. [05:07] So in the home, designate a spot for your keys -- [05:10] a hook by the door, maybe a decorative bowl. [05:13] For your passport, a particular drawer. [05:15] For your reading glasses, a particular table. [05:18] If you designate a spot and you're scrupulous about it, [05:21] your things will always be there when you look for them. [05:24] What about travel? [05:25] Take a cell phone picture of your credit cards, [05:28] your driver's license, your passport, [05:30] mail it to yourself so it's in the cloud. [05:32] If these things are lost or stolen, you can facilitate replacement. [05:37] Now these are some rather obvious things. [05:39] Remember, when you're under stress, the brain releases cortisol. [05:43] Cortisol is toxic, and it causes cloudy thinking. [05:46] So part of the practice of the pre-mortem [05:49] is to recognize that under stress you're not going to be at your best, [05:53] and you should put systems in place. [05:55] And there's perhaps no more stressful a situation [05:58] than when you're confronted with a medical decision to make. [06:02] And at some point, all of us are going to be in that position, [06:05] where we have to make a very important decision [06:07] about the future of our medical care or that of a loved one, [06:11] to help them with a decision. [06:12] And so I want to talk about that. [06:14] And I'm going to talk about a very particular medical condition. [06:17] But this stands as a proxy for all kinds of medical decision-making, [06:21] and indeed for financial decision-making, and social decision-making -- [06:25] any kind of decision you have to make [06:27] that would benefit from a rational assessment of the facts. [06:31] So suppose you go to your doctor and the doctor says, [06:34] "I just got your lab work back, your cholesterol's a little high." [06:39] Now, you all know that high cholesterol [06:42] is associated with an increased risk of cardiovascular disease, [06:46] heart attack, stroke. [06:47] And so you're thinking [06:49] having high cholesterol isn't the best thing, [06:51] and so the doctor says, "You know, I'd like to give you a drug [06:54] that will help you lower your cholesterol, a statin." [06:57] And you've probably heard of statins, [06:59] you know that they're among the most widely prescribed drugs [07:01] in the world today, [07:03] you probably even know people who take them. [07:05] And so you're thinking, "Yeah! Give me the statin." [07:07] But there's a question you should ask at this point, [07:10] a statistic you should ask for [07:11] that most doctors don't like talking about, [07:14] and pharmaceutical companies like talking about even less. [07:18] It's for the number needed to treat. [07:21] Now, what is this, the NNT? [07:23] It's the number of people that need to take a drug [07:26] or undergo a surgery or any medical procedure [07:29] before one person is helped. [07:31] And you're thinking, what kind of crazy statistic is that? [07:34] The number should be one. [07:35] My doctor wouldn't prescribe something to me [07:37] if it's not going to help. [07:39] But actually, medical practice doesn't work that way. [07:41] And it's not the doctor's fault, [07:43] if it's anybody's fault, it's the fault of scientists like me. [07:46] We haven't figured out the underlying mechanisms well enough. [07:48] But GlaxoSmithKline estimates [07:51] that 90 percent of the drugs work in only 30 to 50 percent of the people. [07:56] So the number needed to treat for the most widely prescribed statin, [08:00] what do you suppose it is? [08:02] How many people have to take it before one person is helped? [08:05] 300. [08:07] This is according to research [08:08] by research practitioners Jerome Groopman and Pamela Hartzband, [08:12] independently confirmed by Bloomberg.com. [08:14] I ran through the numbers myself. [08:17] 300 people have to take the drug for a year [08:20] before one heart attack, stroke or other adverse event is prevented. [08:24] Now you're probably thinking, [08:25] "Well, OK, one in 300 chance of lowering my cholesterol. [08:28] Why not, doc? Give me the prescription anyway." [08:30] But you should ask at this point for another statistic, [08:33] and that is, "Tell me about the side effects." Right? [08:36] So for this particular drug, [08:37] the side effects occur in five percent of the patients. [08:41] And they include terrible things -- [08:43] debilitating muscle and joint pain, gastrointestinal distress -- [08:47] but now you're thinking, "Five percent, [08:49] not very likely it's going to happen to me, [08:51] I'll still take the drug." [08:52] But wait a minute. [08:54] Remember under stress you're not thinking clearly. [08:56] So think about how you're going to work through this ahead of time, [08:59] so you don't have to manufacture the chain of reasoning on the spot. [09:02] 300 people take the drug, right? One person's helped, [09:05] five percent of those 300 have side effects, [09:07] that's 15 people. [09:09] You're 15 times more likely to be harmed by the drug [09:13] than you are to be helped by the drug. [09:16] Now, I'm not saying whether you should take the statin or not. [09:19] I'm just saying you should have this conversation with your doctor. [09:22] Medical ethics requires it, [09:24] it's part of the principle of informed consent. [09:26] You have the right to have access to this kind of information [09:29] to begin the conversation about whether you want to take the risks or not. [09:33] Now you might be thinking [09:34] I've pulled this number out of the air for shock value, [09:37] but in fact it's rather typical, this number needed to treat. [09:40] For the most widely performed surgery on men over the age of 50, [09:45] removal of the prostate for cancer, [09:47] the number needed to treat is 49. [09:50] That's right, 49 surgeries are done for every one person who's helped. [09:54] And the side effects in that case occur in 50 percent of the patients. [09:59] They include impotence, erectile dysfunction, [10:01] urinary incontinence, rectal tearing, [10:04] fecal incontinence. [10:06] And if you're lucky, and you're one of the 50 percent who has these, [10:09] they'll only last for a year or two. [10:12] So the idea of the pre-mortem is to think ahead of time [10:16] to the questions that you might be able to ask [10:19] that will push the conversation forward. [10:21] You don't want to have to manufacture all of this on the spot. [10:24] And you also want to think about things like quality of life. [10:27] Because you have a choice oftentimes, [10:29] do you I want a shorter life that's pain-free, [10:31] or a longer life that might have a great deal of pain towards the end? [10:35] These are things to talk about and think about now, [10:37] with your family and your loved ones. [10:39] You might change your mind in the heat of the moment, [10:42] but at least you're practiced with this kind of thinking. [10:45] Remember, our brain under stress releases cortisol, [10:49] and one of the things that happens at that moment [10:52] is a whole bunch on systems shut down. [10:54] There's an evolutionary reason for this. [10:56] Face-to-face with a predator, you don't need your digestive system, [10:59] or your libido, or your immune system, [11:02] because if you're body is expending metabolism on those things [11:05] and you don't react quickly, [11:07] you might become the lion's lunch, and then none of those things matter. [11:11] Unfortunately, [11:12] one of the things that goes out the window during those times of stress [11:16] is rational, logical thinking, [11:18] as Danny Kahneman and his colleagues have shown. [11:22] So we need to train ourselves to think ahead [11:25] to these kinds of situations. [11:27] I think the important point here is recognizing that all of us are flawed. [11:33] We all are going to fail now and then. [11:36] The idea is to think ahead to what those failures might be, [11:40] to put systems in place that will help minimize the damage, [11:44] or to prevent the bad things from happening in the first place. [11:48] Getting back to that snowy night in Montreal, [11:50] when I got back from my trip, [11:52] I had my contractor install a combination lock next to the door, [11:56] with a key to the front door in it, an easy to remember combination. [12:00] And I have to admit, [12:01] I still have piles of mail that haven't been sorted, [12:04] and piles of emails that I haven't gone through. [12:07] So I'm not completely organized, [12:09] but I see organization as a gradual process, [12:12] and I'm getting there. [12:13] Thank you very much. [12:14] (Applause)
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 7d2690ff8ba6d451a3a3c6f8eb4cfd5b98e1720a8e5eee99873cb0a74b1a160d
