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
## URL 1: https://www.youtube.com/watch?v=wjZofJX0v4M

### SUMMARY
```yaml
mini_title: Transformer GPT 3 Architecture Explained
brief_summary: 'In this lecture, Unidentified Speaker argues that the transformer
  neural network architecture, introduced in 2017, is the foundational technology
  for the ai boom of the early 2020s, with gpt models generating text by predicting
  the next token based on learned probability distributions. The closing takeaway:
  The Transformer architecture, exemplified by GPT-3, represents a powerful paradigm
  for AI text generation, relying on intricate data processing steps and massive parameter
  counts to achieve i.'
tags:
- transformer
- gpt-3
- deep-learning
- neural-networks
- ai-architecture
- machine-translation
- tokenization
- backpropagation
- technical-explanation
- lecture
detailed_summary:
- heading: Overview
  bullets:
  - In this lecture, Unidentified Speaker argues that the transformer neural network
    architecture, introduced in 2017, is the foundational technology for the ai boom
    of the early 2020s, with gpt models generating text by predicting the next token
    based on learned probability distributions.
  sub_sections:
    Format and speakers:
    - 'Format: lecture.'
    - 'Speakers: Unidentified Speaker.'
    Thesis:
    - The Transformer neural network architecture, introduced in 2017, is the foundational
      technology for the AI boom of the early 2020s, with GPT models generating text
      by predicting the next token based on learned probability distributions. These
      models are initially pretrained on general datasets and can be subsequently
      fine-tuned for specific tasks.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    Core Architecture & Timeline:
    - The Transformer neural network, introduced by Google in 2017 for machine translation,
      is the foundational technology for the AI boom of the early 2020s.
    - GPT models are trained to predict the next token in a sequence of text, producing
      a probability distribution for possible tokens.
    - The "Pretrained" aspect signifies initial learning from a general dataset, followed
      by potential fine-tuning for specific applications.
    - Text generation operates in a loop where the model predicts, samples, appends,
      and repeats, with quality highly dependent on model scale.
    - An example illustrated GPT-3's ability to generate coherent stories compared
      to GPT-2's nonsensical output from the same prompt.
    - Training large models carries significant risks, including overfitting or intractable
      computational challenges.
    - Transformer applications extend to audio-to-text, text-to-speech, and text-to-image
      generation, exemplified by DALL-E and Midjourney.
    - Chatbot implementations use a "system prompt" to establish context and require
      additional training steps for conversational AI.
    Data Processing Flow:
    - Input text undergoes tokenization, converting it into a sequence of discrete
      tokens.
    - Each token is then mapped to a high-dimensional numerical vector using an embedding
      matrix, which also incorporates positional information.
    - The sequence of vectors passes through repeating processing layers, each containing
      attention and Multi-Layer Perceptron (MLP) blocks.
    - Attention blocks enable vectors to exchange information and update their meanings
      based on contextual relationships.
    - MLP blocks process each vector independently, akin to asking questions and updating
      the vector based on the answers.
    - The final vector in the sequence is multiplied by an unembedding matrix to produce
      raw scores, or logits, for every possible token.
    - During training, all vectors in the final layer contribute to next-token predictions
      for efficiency.
    - The softmax function converts the list of logits into a valid probability distribution,
      ensuring values are between 0 and 1 and sum to 1.
    Technical Components & Parameters:
    - Transformers are deep learning models that perform computations primarily through
      matrix multiplications on numerical arrays called tensors.
    - Their behavior is determined by tunable parameters, or weights, which are learned
      from data using the backpropagation algorithm.
    - It is important to distinguish between the model's static weights and the dynamic
      activation data being processed for a given input.
    - The word embedding matrix (W_E) contains unique vector columns for each token,
      representing semantic meaning in a geometric space.
    - The dot product between embedding vectors measures their alignment and can test
      semantic hypotheses, such as `woman - man` being similar to `king - queen`.
    - The unembedding matrix (W_U) maps the final context-rich vector back to the
      vocabulary space to generate output logits.
    - The softmax function converts logits to probabilities, and a temperature (T)
      parameter controls randomness, with `T > 1` for more randomness and `T < 1`
      for sharper distributions.
    - A temperature of `T = 0` results in deterministic token selection, always choosing
      the most likely token.
    GPT-3 Specifications:
    - GPT-3 comprises 175 billion total parameters.
    - These parameters are organized into nearly 28,000 distinct matrices across eight
      different categories.
    - The model's vocabulary size consists of 50,257 unique tokens.
    - Each token is represented by a high-dimensional vector with 12,288 dimensions.
    - The embedding (W_E) and unembedding (W_U) matrices each contain approximately
      617 million parameters.
    - GPT-3 has a fixed context size limit of 2,048 tokens, which restricts the amount
      of prior text it can consider.
    - This context size limitation can cause the model to lose coherence in extended
      conversations.
- heading: Demonstrations
  bullets:
  - Comparison of GPT-3 vs. GPT-2 text generation coherence from the same prompt.
  sub_sections: {}
- heading: Closing remarks
  bullets:
  - The Transformer architecture, exemplified by GPT-3, represents a powerful paradigm
    for AI text generation, relying on intricate data processing steps and massive
    parameter counts to achieve its capabilities. Understanding its core components,
    from tokenization to the softmax function, is crucial for comprehending the mechanics
    behind modern large language models.
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=wjZofJX0v4M
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=32687
  total_tokens_used: 29561
  gemini_pro_tokens: 25904
  gemini_flash_tokens: 3657
  total_latency_ms: 102041
  cod_iterations_used: 2
  self_check_missing_count: 7
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: Transformer GPT 3 Architecture Explained
    brief_summary: 'In this lecture, Unidentified Speaker argues that the transformer
      neural network architecture, introduced in 2017, is the foundational technology
      for the ai boom of the early 2020s, with gpt models generating text by predicting
      the next token based on learned probability distributions. The closing takeaway:
      The Transformer architecture, exemplified by GPT-3, represents a powerful paradigm
      for AI text generation, relying on intricate data processing steps and massive
      parameter counts to achieve i'
    tags:
    - transformer
    - gpt-3
    - deep-learning
    - neural-networks
    - ai-architecture
    - machine-translation
    - tokenization
    - backpropagation
    - technical-explanation
    - lecture
    speakers:
    - Unidentified Speaker
    guests: null
    entities_discussed:
    - Transformer
    - GPT
    - GPT-2
    - GPT-3
    - DALL-E
    - Midjourney
    detailed_summary:
      thesis: The Transformer neural network architecture, introduced in 2017, is
        the foundational technology for the AI boom of the early 2020s, with GPT models
        generating text by predicting the next token based on learned probability
        distributions. These models are initially pretrained on general datasets and
        can be subsequently fine-tuned for specific tasks.
      format: lecture
      chapters_or_segments:
      - timestamp: ''
        title: Core Architecture & Timeline
        bullets:
        - The Transformer neural network, introduced by Google in 2017 for machine
          translation, is the foundational technology for the AI boom of the early
          2020s.
        - GPT models are trained to predict the next token in a sequence of text,
          producing a probability distribution for possible tokens.
        - The "Pretrained" aspect signifies initial learning from a general dataset,
          followed by potential fine-tuning for specific applications.
        - Text generation operates in a loop where the model predicts, samples, appends,
          and repeats, with quality highly dependent on model scale.
        - An example illustrated GPT-3's ability to generate coherent stories compared
          to GPT-2's nonsensical output from the same prompt.
        - Training large models carries significant risks, including overfitting or
          intractable computational challenges.
        - Transformer applications extend to audio-to-text, text-to-speech, and text-to-image
          generation, exemplified by DALL-E and Midjourney.
        - Chatbot implementations use a "system prompt" to establish context and require
          additional training steps for conversational AI.
      - timestamp: ''
        title: Data Processing Flow
        bullets:
        - Input text undergoes tokenization, converting it into a sequence of discrete
          tokens.
        - Each token is then mapped to a high-dimensional numerical vector using an
          embedding matrix, which also incorporates positional information.
        - The sequence of vectors passes through repeating processing layers, each
          containing attention and Multi-Layer Perceptron (MLP) blocks.
        - Attention blocks enable vectors to exchange information and update their
          meanings based on contextual relationships.
        - MLP blocks process each vector independently, akin to asking questions and
          updating the vector based on the answers.
        - The final vector in the sequence is multiplied by an unembedding matrix
          to produce raw scores, or logits, for every possible token.
        - During training, all vectors in the final layer contribute to next-token
          predictions for efficiency.
        - The softmax function converts the list of logits into a valid probability
          distribution, ensuring values are between 0 and 1 and sum to 1.
      - timestamp: ''
        title: Technical Components & Parameters
        bullets:
        - Transformers are deep learning models that perform computations primarily
          through matrix multiplications on numerical arrays called tensors.
        - Their behavior is determined by tunable parameters, or weights, which are
          learned from data using the backpropagation algorithm.
        - It is important to distinguish between the model's static weights and the
          dynamic activation data being processed for a given input.
        - The word embedding matrix (W_E) contains unique vector columns for each
          token, representing semantic meaning in a geometric space.
        - The dot product between embedding vectors measures their alignment and can
          test semantic hypotheses, such as `woman - man` being similar to `king -
          queen`.
        - The unembedding matrix (W_U) maps the final context-rich vector back to
          the vocabulary space to generate output logits.
        - The softmax function converts logits to probabilities, and a temperature
          (T) parameter controls randomness, with `T > 1` for more randomness and
          `T < 1` for sharper distributions.
        - A temperature of `T = 0` results in deterministic token selection, always
          choosing the most likely token.
      - timestamp: ''
        title: GPT-3 Specifications
        bullets:
        - GPT-3 comprises 175 billion total parameters.
        - These parameters are organized into nearly 28,000 distinct matrices across
          eight different categories.
        - The model's vocabulary size consists of 50,257 unique tokens.
        - Each token is represented by a high-dimensional vector with 12,288 dimensions.
        - The embedding (W_E) and unembedding (W_U) matrices each contain approximately
          617 million parameters.
        - GPT-3 has a fixed context size limit of 2,048 tokens, which restricts the
          amount of prior text it can consider.
        - This context size limitation can cause the model to lose coherence in extended
          conversations.
      demonstrations:
      - Comparison of GPT-3 vs. GPT-2 text generation coherence from the same prompt.
      closing_takeaway: The Transformer architecture, exemplified by GPT-3, represents
        a powerful paradigm for AI text generation, relying on intricate data processing
        steps and massive parameter counts to achieve its capabilities. Understanding
        its core components, from tokenization to the softmax function, is crucial
        for comprehending the mechanics behind modern large language models.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
Transformers, the tech behind LLMs | Deep Learning Chapter 5

Transcript
Kind: captions Language: en [00:00] The initials GPT stand for Generative Pretrained Transformer. [00:05] So that first word is straightforward enough, these are bots that generate new text. [00:09] Pretrained refers to how the model went through a process of learning [00:13] from a massive amount of data, and the prefix insinuates that there's [00:16] more room to fine-tune it on specific tasks with additional training. [00:20] But the last word, that's the real key piece. [00:23] A transformer is a specific kind of neural network, a machine learning model, [00:27] and it's the core invention underlying the current boom in AI. [00:31] What I want to do with this video and the following chapters is go through a [00:35] visually-driven explanation for what actually happens inside a transformer. [00:39] We're going to follow the data that flows through it and go step by step. [00:43] There are many different kinds of models that you can build using transformers. [00:47] Some models take in audio and produce a transcript. [00:51] This sentence comes from a model going the other way around, [00:54] producing synthetic speech just from text. [00:56] All those tools that took the world by storm in 2022 like DALL-E and Midjourney [01:01] that take in a text description and produce an image are based on transformers. [01:06] Even if I can't quite get it to understand what a pi creature is supposed to be, [01:09] I'm still blown away that this kind of thing is even remotely possible. [01:13] And the original transformer introduced in 2017 by Google was invented for [01:18] the specific use case of translating text from one language into another. [01:22] But the variant that you and I will focus on, which is the type that [01:26] underlies tools like ChatGPT, will be a model that's trained to take in a piece of text, [01:31] maybe even with some surrounding images or sound accompanying it, [01:34] and produce a prediction for what comes next in the passage. [01:38] That prediction takes the form of a probability distribution [01:41] over many different chunks of text that might follow. [01:45] At first glance, you might think that predicting the next word [01:47] feels like a very different goal from generating new text. [01:50] But once you have a prediction model like this, [01:52] a simple thing you could try to make it generate, a longer piece of text, [01:56] is to give it an initial snippet to work with, [01:58] have it take a random sample from the distribution it just generated, [02:02] append that sample to the text, and then run the whole process again to make [02:05] a new prediction based on all the new text, including what it just added. [02:10] I don't know about you, but it really doesn't feel like this should actually work. [02:13] In this animation, for example, I'm running GPT-2 on my laptop and having it repeatedly [02:17] predict and sample the next chunk of text to generate a story based on the seed text. [02:22] The story just doesn't actually really make that much sense. [02:26] But if I swap it out for API calls to GPT-3 instead, which is the same basic model, [02:31] just much bigger, suddenly almost magically we do get a sensible story, [02:35] one that even seems to infer that a pi creature would live in a land of math and [02:40] computation. [02:41] This process here of repeated prediction and sampling is essentially [02:44] what's happening when you interact with ChatGPT, [02:47] or any of these other large language models, and you see them producing [02:50] one word at a time. [02:52] In fact, one feature that I would very much enjoy is the ability to [02:55] see the underlying distribution for each new word that it chooses. [03:03] Let's kick things off with a very high level preview [03:06] of how data flows through a transformer. [03:08] We will spend much more time motivating and interpreting and expanding [03:11] on the details of each step, but in broad strokes, [03:14] when one of these chatbots generates a given word, here's what's going on under the hood. [03:19] First, the input is broken up into a bunch of little pieces. [03:22] These pieces are called tokens, and in the case of text these tend to be [03:26] words or little pieces of words or other common character combinations. [03:30] If images or sound are involved, then tokens could be little [03:34] patches of that image or little chunks of that sound. [03:37] Each one of these tokens is then associated with a vector, meaning some list of numbers, [03:42] which is meant to somehow encode the meaning of that piece. [03:45] If you think of these vectors as giving coordinates in some very high dimensional space, [03:50] words with similar meanings tend to land on vectors that are [03:53] close to each other in that space. [03:55] This sequence of vectors then passes through an operation that's [03:58] known as an attention block, and this allows the vectors to talk to [04:01] each other and pass information back and forth to update their values. [04:04] For example, the meaning of the word model in the phrase "a machine learning [04:08] model" is different from its meaning in the phrase "a fashion model". [04:12] The attention block is what's responsible for figuring out which [04:15] words in context are relevant to updating the meanings of which other words, [04:19] and how exactly those meanings should be updated. [04:22] And again, whenever I use the word meaning, this is [04:25] somehow entirely encoded in the entries of those vectors. [04:29] After that, these vectors pass through a different kind of operation, [04:32] and depending on the source that you're reading this will be referred [04:35] to as a multi-layer perceptron or maybe a feed-forward layer. [04:38] And here the vectors don't talk to each other, [04:40] they all go through the same operation in parallel. [04:43] And while this block is a little bit harder to interpret, [04:45] later on we'll talk about how the step is a little bit like asking a long list [04:49] of questions about each vector, and then updating them based on the answers [04:53] to those questions. [04:54] All of the operations in both of these blocks look like a [04:58] giant pile of matrix multiplications, and our primary job is [05:01] going to be to understand how to read the underlying matrices. [05:06] I'm glossing over some details about some normalization steps that happen in between, [05:10] but this is after all a high-level preview. [05:13] After that, the process essentially repeats, you go back and forth [05:17] between attention blocks and multi-layer perceptron blocks, [05:20] until at the very end the hope is that all of the essential meaning [05:24] of the passage has somehow been baked into the very last vector in the sequence. [05:28] We then perform a certain operation on that last vector that produces a probability [05:33] distribution over all possible tokens, all possible little chunks of text that might [05:37] come next. [05:38] And like I said, once you have a tool that predicts what comes next [05:42] given a snippet of text, you can feed it a little bit of seed text and [05:45] have it repeatedly play this game of predicting what comes next, [05:49] sampling from the distribution, appending it, and then repeating over and over. [05:53] Some of you in the know may remember how long before ChatGPT came into the scene, [05:57] this is what early demos of GPT-3 looked like, [06:00] you would have it autocomplete stories and essays based on an initial snippet. [06:05] To make a tool like this into a chatbot, the easiest starting point is to have a [06:09] little bit of text that establishes the setting of a user interacting with a [06:13] helpful AI assistant, what you would call the system prompt, [06:17] and then you would use the user's initial question or prompt as the first bit of [06:21] dialogue, and then you have it start predicting what such a helpful AI assistant [06:25] would say in response. [06:27] There is more to say about an added step of training that's required [06:30] to make this work well, but at a high level this is the idea. [06:35] In this chapter, you and I are going to expand on the details of what happens at the very [06:39] beginning of the network, at the very end of the network, [06:42] and I also want to spend a lot of time reviewing some important bits of background [06:46] knowledge, things that would have been second nature to any machine learning engineer by [06:50] the time transformers came around. [06:53] If you're comfortable with that background knowledge and a little impatient, [06:56] you could probably feel free to skip to the next chapter, [06:58] which is going to focus on the attention blocks, [07:00] generally considered the heart of the transformer. [07:03] After that, I want to talk more about these multi-layer perceptron blocks, [07:06] how training works, and a number of other details that will have been skipped up to [07:11] that point. [07:12] For broader context, these videos are additions to a mini-series about deep learning, [07:16] and it's okay if you haven't watched the previous ones, [07:18] I think you can do it out of order, but before diving into transformers specifically, [07:22] I do think it's worth making sure that we're on the same page about the basic premise [07:27] and structure of deep learning. [07:29] At the risk of stating the obvious, this is one approach to machine learning, [07:33] which describes any model where you're using data to somehow determine how a model [07:37] behaves. [07:39] What I mean by that is, let's say you want a function that takes in [07:42] an image and it produces a label describing it, [07:44] or our example of predicting the next word given a passage of text, [07:48] or any other task that seems to require some element of intuition [07:51] and pattern recognition. [07:53] We almost take this for granted these days, but the idea with machine learning is that [07:57] rather than trying to explicitly define a procedure for how to do that task in code, [08:02] which is what people would have done in the earliest days of AI, [08:05] instead you set up a very flexible structure with tunable parameters, [08:09] like a bunch of knobs and dials, and then, somehow, [08:11] you use many examples of what the output should look like for a given input to tweak [08:16] and tune the values of those parameters to mimic this behavior. [08:19] For example, maybe the simplest form of machine learning is linear regression, [08:24] where your inputs and outputs are each single numbers, [08:27] something like the square footage of a house and its price, [08:30] and what you want is to find a line of best fit through this data, you know, [08:34] to predict future house prices. [08:37] That line is described by two continuous parameters, [08:40] say the slope and the y-intercept, and the goal of linear [08:43] regression is to determine those parameters to closely match the data. [08:48] Needless to say, deep learning models get much more complicated. [08:52] GPT-3, for example, has not two, but 175 billion parameters. [08:58] But here's the thing, it's not a given that you can create some giant [09:01] model with a huge number of parameters without it either grossly [09:05] overfitting the training data or being completely intractable to train. [09:10] Deep learning describes a class of models that in the [09:13] last couple decades have proven to scale remarkably well. [09:16] What unifies them is that they all use the same training algorithm, [09:19] it's called backpropagation, we talked about it in previous chapters, [09:22] and the context that I want you to have as we go in is that in order for this [09:26] training algorithm to work well at scale, these models have to follow a certain [09:30] specific format. [09:31] And if you know this format going in, it helps to explain many of the choices for how a [09:36] transformer processes language, which otherwise run the risk of feeling kinda arbitrary. [09:41] First, whatever kind of model you're making, the [09:43] input has to be formatted as an array of real numbers. [09:46] This could simply mean a list of numbers, it could be a two-dimensional array, [09:50] or very often you deal with higher dimensional arrays, [09:53] where the general term used is tensor. [09:56] You often think of that input data as being progressively transformed into many [10:00] distinct layers, where again, each layer is always structured as some kind of [10:04] array of real numbers, until you get to a final layer which you consider the output. [10:09] For example, the final layer in our text processing model is a list of numbers [10:13] representing the probability distribution for all possible next tokens. [10:17] In deep learning, these model parameters are almost always referred to as weights, [10:22] and this is because a key feature of these models is that the only way these [10:25] parameters interact with the data being processed is through weighted sums. [10:30] You also sprinkle some non-linear functions throughout, [10:32] but they won't depend on parameters. [10:35] Typically, though, instead of seeing the weighted sums all naked [10:38] and written out explicitly like this, you'll instead find them [10:41] packaged together as various components in a matrix vector product. [10:46] It amounts to saying the same thing, if you think back to how matrix vector [10:50] multiplication works, each component in the output looks like a weighted sum. [10:54] It's just often conceptually cleaner for you and me to think [10:58] about matrices that are filled with tunable parameters that [11:01] transform vectors that are drawn from the data being processed. [11:06] For example, those 175 billion weights in GPT-3 are [11:10] organized into just under 28,000 distinct matrices. [11:14] Those matrices in turn fall into eight different categories, [11:17] and what you and I are going to do is step through each one of those categories to [11:21] understand what that type does. [11:23] As we go through, I think it's kind of fun to reference the specific [11:27] numbers from GPT-3 to count up exactly where those 175 billion come from. [11:31] Even if nowadays there are bigger and better models, [11:34] this one has a certain charm as the first large-language [11:37] model to really capture the world's attention outside of ML communities. [11:41] Also, practically speaking, companies tend to keep much tighter [11:44] lips around the specific numbers for more modern networks. [11:47] I just want to set the scene going in, that as you peek under the [11:50] hood to see what happens inside a tool like ChatGPT, [11:53] almost all of the actual computation looks like matrix vector multiplication. [11:57] There's a little bit of a risk getting lost in the sea of billions of numbers, [12:01] but you should draw a very sharp distinction in your mind between [12:05] the weights of the model, which I'll always color in blue or red, [12:08] and the data being processed, which I'll always color in gray. [12:12] The weights are the actual brains, they are the things learned during training, [12:16] and they determine how it behaves. [12:18] The data being processed simply encodes whatever specific input is [12:22] fed into the model for a given run, like an example snippet of text. [12:27] With all of that as foundation, let's dig into the first step of this text processing [12:31] example, which is to break up the input into little chunks and turn those chunks into [12:35] vectors. [12:37] I mentioned how those chunks are called tokens, [12:39] which might be pieces of words or punctuation, [12:41] but every now and then in this chapter and especially in the next one, [12:44] I'd like to just pretend that it's broken more cleanly into words. [12:48] Because we humans think in words, this will just make it much [12:51] easier to reference little examples and clarify each step. [12:55] The model has a predefined vocabulary, some list of all possible words, [12:59] say 50,000 of them, and the first matrix that we'll encounter, [13:03] known as the embedding matrix, has a single column for each one of these words. [13:08] These columns are what determines what vector each word turns into in that first step. [13:15] We label it W_E, and like all the matrices we see, [13:18] its values begin random, but they're going to be learned based on data. [13:23] Turning words into vectors was common practice in machine learning long before [13:27] transformers, but it's a little weird if you've never seen it before, [13:30] and it sets the foundation for everything that follows, [13:33] so let's take a moment to get familiar with it. [13:36] We often call this embedding a word, which invites you to think of these [13:39] vectors very geometrically as points in some high dimensional space. [13:44] Visualizing a list of three numbers as coordinates for points in 3D space would [13:48] be no problem, but word embeddings tend to be much much higher dimensional. [13:52] In GPT-3 they have 12,288 dimensions, and as you'll see, [13:55] it matters to work in a space that has a lot of distinct directions. [14:01] In the same way that you could take a two-dimensional slice through a 3D space [14:05] and project all the points onto that slice, for the sake of animating word [14:08] embeddings that a simple model is giving me, I'm going to do an analogous [14:12] thing by choosing a three-dimensional slice through this very high dimensional space, [14:16] and projecting the word vectors down onto that and displaying the results. [14:21] The big idea here is that as a model tweaks and tunes its weights to determine [14:25] how exactly words get embedded as vectors during training, [14:28] it tends to settle on a set of embeddings where directions in the space have a [14:33] kind of semantic meaning. [14:34] For the simple word-to-vector model I'm running here, [14:37] if I run a search for all the words whose embeddings are closest to that of tower, [14:42] you'll notice how they all seem to give very similar tower-ish vibes. [14:46] And if you want to pull up some Python and play along at home, [14:48] this is the specific model that I'm using to make the animations. [14:51] It's not a transformer, but it's enough to illustrate the [14:54] idea that directions in the space can carry semantic meaning. [14:58] A very classic example of this is how if you take the difference between [15:02] the vectors for woman and man, something you would visualize as a [15:05] little vector in the space connecting the tip of one to the tip of the other, [15:09] it's very similar to the difference between king and queen. [15:15] So let's say you didn't know the word for a female monarch, [15:18] you could find it by taking king, adding this woman minus man direction, [15:22] and searching for the embedding closest to that point. [15:27] At least, kind of. [15:28] Despite this being a classic example for the model I'm playing with, [15:31] the true embedding of queen is actually a little farther off than this would suggest, [15:35] presumably because the way queen is used in training data is not merely a feminine [15:39] version of king. [15:41] When I played around, family relations seemed to illustrate the idea much better. [15:46] The point is, it looks like during training the model found it advantageous to [15:50] choose embeddings such that one direction in this space encodes gender information. [15:56] Another example is that if you take the embedding of Italy, [16:00] and you subtract the embedding of Germany, and add that to the embedding of Hitler, [16:04] you get something very close to the embedding of Mussolini. [16:08] It's as if the model learned to associate some directions with Italian-ness, [16:13] and others with WWII axis leader
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 1006a1e394ffa81580217bcc29ce7abad649aca081ea83c0d7cac2ab0dd76b8b
