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
## URL 1: https://www.youtube.com/watch?v=zjkBMFhNj_g

### SUMMARY
```yaml
mini_title: LLM Architecture Training Security
brief_summary: 'In this lecture, Unidentified Presenter argues that large language
  models are complex, inscrutable artifacts built on the transformer architecture,
  undergoing intensive multi-stage training to achieve their capabilities. The closing
  takeaway: LLMs are rapidly evolving systems with immense potential, but their development
  is intertwined with significant challenges in understanding their internal workings,
  ensuring robust training, and mitigating sophisticated security vulnerabilities.'
tags:
- llm-architecture
- llm-training
- llm-security
- transformer-models
- ai-capabilities
- prompt-engineering
- machine-learning
- deep-learning
- ai-vulnerabilities
- lecture
detailed_summary:
- heading: Overview
  bullets:
  - In this lecture, Unidentified Presenter argues that large language models are
    complex, inscrutable artifacts built on the transformer architecture, undergoing
    intensive multi-stage training to achieve their capabilities.
  sub_sections:
    Format and speakers:
    - 'Format: lecture.'
    - 'Speakers: Unidentified Presenter.'
    Thesis:
    - Large Language Models are complex, inscrutable artifacts built on the Transformer
      architecture, undergoing intensive multi-stage training to achieve their capabilities.
      While rapidly advancing in areas like tool use and multimodality, they face
      significant security vulnerabilities that require ongoing research and mitigation.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    LLM Core Components and Market Landscape:
    - An LLM fundamentally comprises a parameters file containing weights and a code
      file defining its neural network architecture.
    - Despite the known mathematical operations of the Transformer architecture, the
      collaborative function of billions of parameters remains poorly understood,
      rendering LLMs "inscrutable artifacts.".
    - For instance, Meta AI's Llama 2 70B model stores 70 billion parameters as 140
      GB of float16 values, accompanied by a minimal ~500 lines of C code for local
      execution.
    - This contrasts with proprietary models like OpenAI's ChatGPT, which are only
      accessible through an interface.
    - The current market features a performance gap, with proprietary models such
      as GPT-4 and Claude leading, while open-source alternatives like Llama and Mistral
      are rapidly maturing.
    LLM Training Process:
    - LLM training is a computationally intensive process of lossy compression, whereas
      inference is comparatively inexpensive.
    - Stage 1, pre-training, focuses on next-word prediction using vast text corpora,
      forcing the model to learn grammar, facts, and reasoning.
    - The Llama 2 70B model, for example, was pre-trained on approximately 10 TB of
      internet text using 6,000 GPUs over 12 days, costing around $2 million and achieving
      a 100x compression ratio.
    - Pre-trained "base models" often hallucinate and exhibit one-dimensional knowledge,
      as illustrated by the "reversal curse" where a model might know a fact but not
      its inverse.
    - Stage 2, fine-tuning, transforms the base model into a helpful assistant by
      training on smaller, high-quality question-and-answer datasets, often created
      through human-machine collaboration.
    - An optional Stage 3 involves fine-tuning with comparisons, where human labelers
      rank multiple model responses, a method used in OpenAI's Reinforcement Learning
      from Human Feedback (RLHF).
    Evolving LLM Capabilities:
    - LLM performance on next-word prediction follows predictable scaling laws, indicating
      that increasing compute and data consistently improves results without requiring
      novel algorithmic breakthroughs.
    - These scaling trends show no signs of plateauing, fueling a significant demand
      for GPUs and data.
    - Models are increasingly capable of tool use, orchestrating external computational
      resources like browser searches, calculators, or image generation tools such
      as DALL-E.
    - Multimodality allows models to process and generate various data types, exemplified
      by GPT-4 generating HTML/JavaScript from a hand-drawn sketch or enabling speech-to-speech
      conversations.
    - The analogy of an LLM as an operating system kernel suggests it manages a memory
      hierarchy and coordinates tools, mirroring the proprietary vs. open-source dynamics
      of traditional OS markets.
    Future Research Directions:
    - A key research direction involves developing "System 2" models that can trade
      more computation time for higher accuracy on complex problems, moving beyond
      the current "System 1" constant-rate token generation.
    - Another area is self-improvement, inspired by DeepMind's AlphaGo, though the
      challenge for LLMs lies in the absence of a simple, automatic reward function
      for open-ended language tasks.
    - Customization, as seen in OpenAI's GPTs, focuses on creating specialized models
      through instructions and Retrieval-Augmented Generation (RAG) on user-uploaded
      files.
    LLM Security Vulnerabilities:
    - Jailbreaking involves bypassing safety filters through techniques like role-playing
      harmful requests, encoding malicious queries (e.g., Base64), or using adversarial
      suffixes.
    - Multimodal attacks can also jailbreak models by embedding crafted, invisible
      noise patterns within images.
    - Prompt injection hijacks model instructions, such as an attacker placing hidden
      commands in white text on a white background on a webpage for the LLM to follow.
    - Data exfiltration attacks, demonstrated with Google Bard and Google Docs, can
      instruct an LLM to embed private data into an image URL or exfiltrate it to
      another trusted domain via Google Apps Scripts.
    - Data poisoning, a backdoor attack, involves an attacker inserting a "sleeper
      agent" into training data, tied to a trigger phrase that corrupts the model's
      behavior when encountered.
- heading: Demonstrations
  bullets:
  - Example of Llama 2 70B model size and code.
  - Example of "reversal curse" with Tom Cruise's mother.
  - Example of ChatGPT orchestrating multiple tools (browser, calculator, Python,
    DALL-E).
  - Example of GPT-4 generating HTML/JavaScript from a hand-drawn sketch.
  - Examples of jailbreaking techniques (role-playing, encoding, adversarial suffixes,
    multimodal attacks).
  - Examples of prompt injection via hidden instructions on webpages.
  - Examples of data exfiltration using Google Bard and Google Docs/Apps Scripts.
  sub_sections: {}
- heading: Closing remarks
  bullets:
  - LLMs are rapidly evolving systems with immense potential, but their development
    is intertwined with significant challenges in understanding their internal workings,
    ensuring robust training, and mitigating sophisticated security vulnerabilities.
    Addressing these complexities is crucial for their safe and effective integration
    into various applications.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=zjkBMFhNj_g
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=220281
  total_tokens_used: 140927
  gemini_pro_tokens: 136679
  gemini_flash_tokens: 4248
  total_latency_ms: 136707
  cod_iterations_used: 2
  self_check_missing_count: 6
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: LLM Architecture Training Security
    brief_summary: 'In this lecture, Unidentified Presenter argues that large language
      models are complex, inscrutable artifacts built on the transformer architecture,
      undergoing intensive multi-stage training to achieve their capabilities. The
      closing takeaway: LLMs are rapidly evolving systems with immense potential,
      but their development is intertwined with significant challenges in understanding
      their internal workings, ensuring robust training, and mitigating sophisticated
      security vulnerabilities.'
    tags:
    - llm-architecture
    - llm-training
    - llm-security
    - transformer-models
    - ai-capabilities
    - prompt-engineering
    - machine-learning
    - deep-learning
    - ai-vulnerabilities
    - lecture
    speakers:
    - Unidentified Presenter
    guests: null
    entities_discussed:
    - Transformer architecture
    - Meta AI
    - Llama 2 70B
    - OpenAI
    - ChatGPT
    - GPT-4
    - Claude
    - Mistral
    - DALL-E
    - AlphaGo
    - Google Bard
    - Google Apps Scripts
    detailed_summary:
      thesis: Large Language Models are complex, inscrutable artifacts built on the
        Transformer architecture, undergoing intensive multi-stage training to achieve
        their capabilities. While rapidly advancing in areas like tool use and multimodality,
        they face significant security vulnerabilities that require ongoing research
        and mitigation.
      format: lecture
      chapters_or_segments:
      - timestamp: ''
        title: LLM Core Components and Market Landscape
        bullets:
        - An LLM fundamentally comprises a parameters file containing weights and
          a code file defining its neural network architecture.
        - Despite the known mathematical operations of the Transformer architecture,
          the collaborative function of billions of parameters remains poorly understood,
          rendering LLMs "inscrutable artifacts."
        - For instance, Meta AI's Llama 2 70B model stores 70 billion parameters as
          140 GB of float16 values, accompanied by a minimal ~500 lines of C code
          for local execution.
        - This contrasts with proprietary models like OpenAI's ChatGPT, which are
          only accessible through an interface.
        - The current market features a performance gap, with proprietary models such
          as GPT-4 and Claude leading, while open-source alternatives like Llama and
          Mistral are rapidly maturing.
      - timestamp: ''
        title: LLM Training Process
        bullets:
        - LLM training is a computationally intensive process of lossy compression,
          whereas inference is comparatively inexpensive.
        - Stage 1, pre-training, focuses on next-word prediction using vast text corpora,
          forcing the model to learn grammar, facts, and reasoning.
        - The Llama 2 70B model, for example, was pre-trained on approximately 10
          TB of internet text using 6,000 GPUs over 12 days, costing around $2 million
          and achieving a 100x compression ratio.
        - Pre-trained "base models" often hallucinate and exhibit one-dimensional
          knowledge, as illustrated by the "reversal curse" where a model might know
          a fact but not its inverse.
        - Stage 2, fine-tuning, transforms the base model into a helpful assistant
          by training on smaller, high-quality question-and-answer datasets, often
          created through human-machine collaboration.
        - An optional Stage 3 involves fine-tuning with comparisons, where human labelers
          rank multiple model responses, a method used in OpenAI's Reinforcement Learning
          from Human Feedback (RLHF).
      - timestamp: ''
        title: Evolving LLM Capabilities
        bullets:
        - LLM performance on next-word prediction follows predictable scaling laws,
          indicating that increasing compute and data consistently improves results
          without requiring novel algorithmic breakthroughs.
        - These scaling trends show no signs of plateauing, fueling a significant
          demand for GPUs and data.
        - Models are increasingly capable of tool use, orchestrating external computational
          resources like browser searches, calculators, or image generation tools
          such as DALL-E.
        - Multimodality allows models to process and generate various data types,
          exemplified by GPT-4 generating HTML/JavaScript from a hand-drawn sketch
          or enabling speech-to-speech conversations.
        - The analogy of an LLM as an operating system kernel suggests it manages
          a memory hierarchy and coordinates tools, mirroring the proprietary vs.
          open-source dynamics of traditional OS markets.
      - timestamp: ''
        title: Future Research Directions
        bullets:
        - A key research direction involves developing "System 2" models that can
          trade more computation time for higher accuracy on complex problems, moving
          beyond the current "System 1" constant-rate token generation.
        - Another area is self-improvement, inspired by DeepMind's AlphaGo, though
          the challenge for LLMs lies in the absence of a simple, automatic reward
          function for open-ended language tasks.
        - Customization, as seen in OpenAI's GPTs, focuses on creating specialized
          models through instructions and Retrieval-Augmented Generation (RAG) on
          user-uploaded files.
      - timestamp: ''
        title: LLM Security Vulnerabilities
        bullets:
        - Jailbreaking involves bypassing safety filters through techniques like role-playing
          harmful requests, encoding malicious queries (e.g., Base64), or using adversarial
          suffixes.
        - Multimodal attacks can also jailbreak models by embedding crafted, invisible
          noise patterns within images.
        - Prompt injection hijacks model instructions, such as an attacker placing
          hidden commands in white text on a white background on a webpage for the
          LLM to follow.
        - Data exfiltration attacks, demonstrated with Google Bard and Google Docs,
          can instruct an LLM to embed private data into an image URL or exfiltrate
          it to another trusted domain via Google Apps Scripts.
        - Data poisoning, a backdoor attack, involves an attacker inserting a "sleeper
          agent" into training data, tied to a trigger phrase that corrupts the model's
          behavior when encountered.
      demonstrations:
      - Example of Llama 2 70B model size and code.
      - Example of "reversal curse" with Tom Cruise's mother.
      - Example of ChatGPT orchestrating multiple tools (browser, calculator, Python,
        DALL-E).
      - Example of GPT-4 generating HTML/JavaScript from a hand-drawn sketch.
      - Examples of jailbreaking techniques (role-playing, encoding, adversarial suffixes,
        multimodal attacks).
      - Examples of prompt injection via hidden instructions on webpages.
      - Examples of data exfiltration using Google Bard and Google Docs/Apps Scripts.
      closing_takeaway: LLMs are rapidly evolving systems with immense potential,
        but their development is intertwined with significant challenges in understanding
        their internal workings, ensuring robust training, and mitigating sophisticated
        security vulnerabilities. Addressing these complexities is crucial for their
        safe and effective integration into various applications.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
[1hr Talk] Intro to Large Language Models

Transcript
Kind: captions Language: en hi everyone so recently I gave a [00:02] hi everyone so recently I gave a 30-minute talk on large language models [00:04] 30-minute talk on large language models [00:04] 30-minute talk on large language models just kind of like an intro talk um [00:06] just kind of like an intro talk um [00:06] just kind of like an intro talk um unfortunately that talk was not recorded [00:08] unfortunately that talk was not recorded [00:08] unfortunately that talk was not recorded but a lot of people came to me after the [00:10] but a lot of people came to me after the [00:10] but a lot of people came to me after the talk and they told me that uh they [00:11] talk and they told me that uh they [00:11] talk and they told me that uh they really liked the talk so I would just I [00:13] really liked the talk so I would just I [00:13] really liked the talk so I would just I thought I would just re-record it and [00:15] thought I would just re-record it and [00:15] thought I would just re-record it and basically put it up on YouTube so here [00:16] basically put it up on YouTube so here [00:16] basically put it up on YouTube so here we go the busy person's intro to large [00:19] we go the busy person's intro to large [00:19] we go the busy person's intro to large language models director Scott okay so [00:21] language models director Scott okay so [00:21] language models director Scott okay so let's begin first of all what is a large [00:24] let's begin first of all what is a large [00:24] let's begin first of all what is a large language model really well a large [00:26] language model really well a large [00:26] language model really well a large language model is just two files right [00:29] language model is just two files right [00:29] language model is just two files right um there will be two files in this [00:31] um there will be two files in this [00:31] um there will be two files in this hypothetical directory so for example [00:33] hypothetical directory so for example [00:33] hypothetical directory so for example working with a specific example of the [00:34] working with a specific example of the [00:34] working with a specific example of the Llama 270b model this is a large [00:38] Llama 270b model this is a large [00:38] Llama 270b model this is a large language model released by meta Ai and [00:41] language model released by meta Ai and [00:41] language model released by meta Ai and this is basically the Llama series of [00:43] this is basically the Llama series of [00:43] this is basically the Llama series of language models the second iteration of [00:45] language models the second iteration of [00:45] language models the second iteration of it and this is the 70 billion parameter [00:47] it and this is the 70 billion parameter [00:47] it and this is the 70 billion parameter model of uh of this series so there's [00:51] model of uh of this series so there's [00:51] model of uh of this series so there's multiple models uh belonging to the [00:54] multiple models uh belonging to the [00:54] multiple models uh belonging to the Llama 2 Series uh 7 billion um 13 [00:57] Llama 2 Series uh 7 billion um 13 [00:57] Llama 2 Series uh 7 billion um 13 billion 34 billion and 70 billion is the [01:00] billion 34 billion and 70 billion is the [01:00] billion 34 billion and 70 billion is the biggest one now many people like this [01:02] biggest one now many people like this [01:02] biggest one now many people like this model specifically because it is [01:04] model specifically because it is [01:04] model specifically because it is probably today the most powerful open [01:06] probably today the most powerful open [01:06] probably today the most powerful open weights model so basically the weights [01:08] weights model so basically the weights [01:08] weights model so basically the weights and the architecture and a paper was all [01:10] and the architecture and a paper was all [01:10] and the architecture and a paper was all released by meta so anyone can work with [01:12] released by meta so anyone can work with [01:12] released by meta so anyone can work with this model very easily uh by themselves [01:15] this model very easily uh by themselves [01:15] this model very easily uh by themselves uh this is unlike many other language [01:17] uh this is unlike many other language [01:17] uh this is unlike many other language models that you might be familiar with [01:18] models that you might be familiar with [01:18] models that you might be familiar with for example if you're using chat GPT or [01:20] for example if you're using chat GPT or [01:20] for example if you're using chat GPT or something like that uh the model [01:22] something like that uh the model [01:22] something like that uh the model architecture was never released it is [01:24] architecture was never released it is [01:24] architecture was never released it is owned by open aai and you're allowed to [01:26] owned by open aai and you're allowed to [01:26] owned by open aai and you're allowed to use the language model through a web [01:27] use the language model through a web [01:27] use the language model through a web interface but you don't have actually [01:29] interface but you don't have actually [01:29] interface but you don't have actually access to that model so in this case the [01:32] access to that model so in this case the [01:32] access to that model so in this case the Llama 270b model is really just two [01:35] Llama 270b model is really just two [01:35] Llama 270b model is really just two files on your file system the parameters [01:37] files on your file system the parameters [01:37] files on your file system the parameters file and the Run uh some kind of a code [01:40] file and the Run uh some kind of a code [01:40] file and the Run uh some kind of a code that runs those [01:41] that runs those [01:41] that runs those parameters so the parameters are [01:43] parameters so the parameters are [01:43] parameters so the parameters are basically the weights or the parameters [01:45] basically the weights or the parameters [01:45] basically the weights or the parameters of this neural network that is the [01:46] of this neural network that is the [01:47] of this neural network that is the language model we'll go into that in a [01:48] language model we'll go into that in a [01:48] language model we'll go into that in a bit because this is a 70 billion [01:51] bit because this is a 70 billion [01:51] bit because this is a 70 billion parameter model uh every one of those [01:53] parameter model uh every one of those [01:53] parameter model uh every one of those parameters is stored as 2 bytes and so [01:56] parameters is stored as 2 bytes and so [01:56] parameters is stored as 2 bytes and so therefore the parameters file here is [01:58] therefore the parameters file here is [01:58] therefore the parameters file here is 140 gigabytes and it's two bytes because [02:01] 140 gigabytes and it's two bytes because [02:01] 140 gigabytes and it's two bytes because this is a float 16 uh number as the data [02:04] this is a float 16 uh number as the data [02:04] this is a float 16 uh number as the data type now in addition to these parameters [02:06] type now in addition to these parameters [02:06] type now in addition to these parameters that's just like a large list of [02:08] that's just like a large list of [02:08] that's just like a large list of parameters uh for that neural network [02:11] parameters uh for that neural network [02:11] parameters uh for that neural network you also need something that runs that [02:13] you also need something that runs that [02:13] you also need something that runs that neural network and this piece of code is [02:15] neural network and this piece of code is [02:15] neural network and this piece of code is implemented in our run file now this [02:17] implemented in our run file now this [02:17] implemented in our run file now this could be a C file or a python file or [02:19] could be a C file or a python file or [02:19] could be a C file or a python file or any other programming language really uh [02:21] any other programming language really uh [02:21] any other programming language really uh it can be written any arbitrary language [02:23] it can be written any arbitrary language [02:23] it can be written any arbitrary language but C is sort of like a very simple [02:25] but C is sort of like a very simple [02:25] but C is sort of like a very simple language just to give you a sense and uh [02:27] language just to give you a sense and uh [02:27] language just to give you a sense and uh it would only require about 500 lines of [02:29] it would only require about 500 lines of [02:29] it would only require about 500 lines of C with no other dependencies to [02:31] C with no other dependencies to [02:31] C with no other dependencies to implement the the uh neural network [02:34] implement the the uh neural network [02:34] implement the the uh neural network architecture uh and that uses basically [02:36] architecture uh and that uses basically [02:37] architecture uh and that uses basically the parameters to run the model so it's [02:39] the parameters to run the model so it's [02:40] the parameters to run the model so it's only these two files you can take these [02:41] only these two files you can take these [02:41] only these two files you can take these two files and you can take your MacBook [02:44] two files and you can take your MacBook [02:44] two files and you can take your MacBook and this is a fully self-contained [02:45] and this is a fully self-contained [02:45] and this is a fully self-contained package this is everything that's [02:46] package this is everything that's [02:46] package this is everything that's necessary you don't need any [02:47] necessary you don't need any [02:47] necessary you don't need any connectivity to the internet or anything [02:49] connectivity to the internet or anything [02:49] connectivity to the internet or anything else you can take these two files you [02:51] else you can take these two files you [02:51] else you can take these two files you compile your C code you get a binary [02:53] compile your C code you get a binary [02:53] compile your C code you get a binary that you can point at the parameters and [02:55] that you can point at the parameters and [02:55] that you can point at the parameters and you can talk to this language model so [02:57] you can talk to this language model so [02:57] you can talk to this language model so for example you can send it text like [03:00] for example you can send it text like [03:00] for example you can send it text like for example write a poem about the [03:01] for example write a poem about the [03:01] for example write a poem about the company scale Ai and this language model [03:04] company scale Ai and this language model [03:04] company scale Ai and this language model will start generating text and in this [03:06] will start generating text and in this [03:06] will start generating text and in this case it will follow the directions and [03:07] case it will follow the directions and [03:07] case it will follow the directions and give you a poem about scale AI now the [03:10] give you a poem about scale AI now the [03:10] give you a poem about scale AI now the reason that I'm picking on scale AI here [03:12] reason that I'm picking on scale AI here [03:12] reason that I'm picking on scale AI here and you're going to see that throughout [03:13] and you're going to see that throughout [03:13] and you're going to see that throughout the talk is because the event that I [03:15] the talk is because the event that I [03:15] the talk is because the event that I originally presented uh this talk with [03:18] originally presented uh this talk with [03:18] originally presented uh this talk with was run by scale Ai and so I'm picking [03:20] was run by scale Ai and so I'm picking [03:20] was run by scale Ai and so I'm picking on them throughout uh throughout the [03:21] on them throughout uh throughout the [03:21] on them throughout uh throughout the slides a little bit just in an effort to [03:23] slides a little bit just in an effort to [03:23] slides a little bit just in an effort to make it [03:24] make it [03:24] make it concrete so this is how we can run the [03:27] concrete so this is how we can run the [03:27] concrete so this is how we can run the model just requires two files just [03:29] model just requires two files just [03:29] model just requires two files just requires a MacBook I'm slightly cheating [03:31] requires a MacBook I'm slightly cheating [03:31] requires a MacBook I'm slightly cheating here because this was not actually in [03:33] here because this was not actually in [03:33] here because this was not actually in terms of the speed of this uh video here [03:35] terms of the speed of this uh video here [03:35] terms of the speed of this uh video here this was not running a 70 billion [03:37] this was not running a 70 billion [03:37] this was not running a 70 billion parameter model it was only running a 7 [03:38] parameter model it was only running a 7 [03:38] parameter model it was only running a 7 billion parameter Model A 70b would be [03:40] billion parameter Model A 70b would be [03:41] billion parameter Model A 70b would be running about 10 times slower but I [03:42] running about 10 times slower but I [03:42] running about 10 times slower but I wanted to give you an idea of uh sort of [03:44] wanted to give you an idea of uh sort of [03:44] wanted to give you an idea of uh sort of just the text generation and what that [03:46] just the text generation and what that [03:46] just the text generation and what that looks like so not a lot is necessary to [03:50] looks like so not a lot is necessary to [03:50] looks like so not a lot is necessary to run the model this is a very small [03:52] run the model this is a very small [03:52] run the model this is a very small package but the computational complexity [03:55] package but the computational complexity [03:55] package but the computational complexity really comes in when we'd like to get [03:57] really comes in when we'd like to get [03:57] really comes in when we'd like to get those parameters so how do we get the [03:58] those parameters so how do we get the [03:59] those parameters so how do we get the parameters and where are they from uh [04:01] parameters and where are they from uh [04:01] parameters and where are they from uh because whatever is in the run. C file [04:03] because whatever is in the run. C file [04:03] because whatever is in the run. C file um the neural network architecture and [04:06] um the neural network architecture and [04:06] um the neural network architecture and sort of the forward pass of that Network [04:08] sort of the forward pass of that Network [04:08] sort of the forward pass of that Network everything is algorithmically understood [04:10] everything is algorithmically understood [04:10] everything is algorithmically understood and open and and so on but the magic [04:12] and open and and so on but the magic [04:12] and open and and so on but the magic really is in the parameters and how do [04:14] really is in the parameters and how do [04:14] really is in the parameters and how do we obtain them so to obtain the [04:17] we obtain them so to obtain the [04:17] we obtain them so to obtain the parameters um basically the model [04:19] parameters um basically the model [04:19] parameters um basically the model training as we call it is a lot more [04:21] training as we call it is a lot more [04:21] training as we call it is a lot more involved than model inference which is [04:23] involved than model inference which is [04:23] involved than model inference which is the part that I showed you earlier so [04:25] the part that I showed you earlier so [04:25] the part that I showed you earlier so model inference is just running it on [04:26] model inference is just running it on [04:26] model inference is just running it on your MacBook model training is a [04:28] your MacBook model training is a [04:28] your MacBook model training is a competition very involved process [04:29] competition very involved process [04:29] competition very involved process process so basically what we're doing [04:32] process so basically what we're doing [04:32] process so basically what we're doing can best be sort of understood as kind [04:34] can best be sort of understood as kind [04:34] can best be sort of understood as kind of a compression of a good chunk of [04:36] of a compression of a good chunk of [04:36] of a compression of a good chunk of Internet so because llama 270b is an [04:39] Internet so because llama 270b is an [04:39] Internet so because llama 270b is an open source model we know quite a bit [04:41] open source model we know quite a bit [04:41] open source model we know quite a bit about how it was trained because meta [04:43] about how it was trained because meta [04:43] about how it was trained because meta released that information in paper so [04:45] released that information in paper so [04:46] released that information in paper so these are some of the numbers of what's [04:47] these are some of the numbers of what's [04:47] these are some of the numbers of what's involved you basically take a chunk of [04:49] involved you basically take a chunk of [04:49] involved you basically take a chunk of the internet that is roughly you should [04:50] the internet that is roughly you should [04:50] the internet that is roughly you should be thinking 10 terab of text this [04:53] be thinking 10 terab of text this [04:53] be thinking 10 terab of text this typically comes from like a crawl of the [04:55] typically comes from like a crawl of the [04:55] typically comes from like a crawl of the internet so just imagine uh just [04:57] internet so just imagine uh just [04:57] internet so just imagine uh just collecting tons of text from all kinds [04:59] collecting tons of text from all kinds [04:59] collecting tons of text from all kinds of different websites and collecting it [05:00] of different websites and collecting it [05:00] of different websites and collecting it together so you take a large cheun of [05:03] together so you take a large cheun of [05:03] together so you take a large cheun of internet then you procure a GPU cluster [05:07] internet then you procure a GPU cluster [05:07] internet then you procure a GPU cluster um and uh these are very specialized [05:09] um and uh these are very specialized [05:09] um and uh these are very specialized computers intended for very heavy [05:12] computers intended for very heavy [05:12] computers intended for very heavy computational workloads like training of [05:13] computational workloads like training of [05:13] computational workloads like training of neural networks you need about 6,000 [05:15] neural networks you need about 6,000 [05:15] neural networks you need about 6,000 gpus and you would run this for about 12 [05:18] gpus and you would run this for about 12 [05:18] gpus and you would run this for about 12 days uh to get a llama 270b and this [05:21] days uh to get a llama 270b and this [05:21] days uh to get a llama 270b and this would cost you about $2 million and what [05:24] would cost you about $2 million and what [05:24] would cost you about $2 million and what this is doing is basically it is [05:25] this is doing is basically it is [05:25] this is doing is basically it is compressing this uh large chunk of text [05:29] compressing this uh large chunk of text [05:29] compressing this uh large chunk of text into what you can think of as a kind of [05:30] into what you can think of as a kind of [05:30] into what you can think of as a kind of a zip file so these parameters that I [05:32
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 0a5a9bbde5ce8a72ab4145af659fbad30988106e4ee831fedad747ad5419689b
