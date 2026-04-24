You are an INDEPENDENT rubric reviewer, blind to any prior evaluator's scoring. Do NOT read eval.json.

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of your manual_review.md.

RUBRIC:
version: rubric_reddit.v1
source_type: reddit
composite_max_points: 100
components:
- id: brief_summary
  max_points: 25
  criteria:
  - id: brief.op_intent_captured
    description: Brief states OP's core question, problem, or claim in neutral wording.
    max_points: 6
    maps_to_metric:
    - g_eval.relevance
    - finesure.completeness
  - id: brief.response_range
    description: Brief summarizes the range of responses (main solution, common advice,
      dissent).
    max_points: 6
    maps_to_metric:
    - finesure.completeness
  - id: brief.consensus_signal
    description: Brief describes consensus, partial agreement, or disagreement.
    max_points: 4
    maps_to_metric:
    - finesure.faithfulness
  - id: brief.caveats_surfaced
    description: Brief surfaces important caveats (regional, legal, risk).
    max_points: 3
    maps_to_metric:
    - finesure.faithfulness
  - id: brief.neutral_tone
    description: Brief is neutral; does not add summarizer's own judgment.
    max_points: 4
    maps_to_metric:
    - summac
  - id: brief.length_5_to_7_sentences
    description: Brief is 5-7 sentences.
    max_points: 2
    maps_to_metric:
    - g_eval.conciseness
- id: detailed_summary
  max_points: 45
  criteria:
  - id: detailed.reply_clusters
    description: Detailed summary represents major opinion clusters, not individual
      comments.
    max_points: 10
    maps_to_metric:
    - finesure.completeness
  - id: detailed.hedged_attribution
    description: Unverified comment claims use hedging language ('commenters argue');
      no assertion as truth.
    max_points: 8
    maps_to_metric:
    - finesure.faithfulness
    - summac
  - id: detailed.counterarguments_included
    description: Minority or contrarian viewpoints are included when substantively
      different.
    max_points: 7
    maps_to_metric:
    - finesure.completeness
  - id: detailed.external_refs_captured
    description: Data, experiments, external references cited by commenters are captured
      without fabrication.
    max_points: 6
    maps_to_metric:
    - finesure.faithfulness
    - qafact
  - id: detailed.unresolved_questions
    description: Unresolved questions or open points are listed.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
  - id: detailed.moderation_context
    description: If moderator actions or removed-comment divergence affects thread,
      it's noted.
    max_points: 5
    maps_to_metric:
    - finesure.completeness
  - id: detailed.no_joke_chains
    description: Joke chains, side-chatter, meta-discussion are not over-represented.
    max_points: 5
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
  - id: tags.subreddit_present
    description: Subreddit appears as a tag (e.g., 'r-askhistorians').
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
  - id: tags.thread_type
    description: Thread type tag present ('q-and-a', 'experience-report', 'best-practices').
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
  - id: tags.no_value_judgments
    description: No tags encode value judgments unless widely agreed in thread.
    max_points: 4
    maps_to_metric:
    - finesure.faithfulness
  - id: tags.topical_specificity
    description: Tags are specific, not generic.
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
- id: label
  max_points: 15
  criteria:
  - id: label.rsubreddit_prefix
    description: Label starts with 'r/<subreddit> ' followed by compact title.
    max_points: 6
    maps_to_metric:
    - g_eval.relevance
  - id: label.central_issue
    description: Label captures central issue that majority of comments address.
    max_points: 5
    maps_to_metric:
    - g_eval.relevance
  - id: label.neutral
    description: Label is neutral, not outrage/meme framing.
    max_points: 4
    maps_to_metric:
    - finesure.faithfulness
anti_patterns:
- id: comment_claim_asserted_as_fact
  description: An unverified commenter claim is stated as truth without hedging.
  auto_cap: 60
- id: missing_removed_comment_note
  description: num_comments > rendered_count but summary doesn't mention missing/removed
    comments.
  auto_cap: 75
- id: editorialized_stance
  description: Summary adds summarizer's own judgment absent from thread.
  auto_cap: 60
global_rules:
  editorialization_penalty:
    threshold_flags: 3


SUMMARY:
## URL 1: https://www.reddit.com/r/hinduism/comments/180eb1m/a_lifelong_atheist_turning_to_hindu_spirituality/

### SUMMARY
```yaml
mini_title: r/hinduism share personal anecdote demonstrating scientific
brief_summary: 'OP''s main point was To share a personal anecdote demonstrating how
  scientific inquiry led a lifelong atheist. The dominant replies focused on Personal
  Resonance and Validation. Consensus stayed around personal resonance and validation
  while historical and philosophical links to science. Dissent centered on Philosophies
  like Advaita Vedanta are for personal growth and serve a different. Caveat: removed
  or missing comments may limit what is visible in the thread.'
tags:
- r-hinduism
- q-and-a
- atheism
- hinduism
- spirituality
- science
- particle-physics
- consciousness
- advaita-vedanta
- philosophy
detailed_summary:
- heading: OP Intent
  bullets:
  - To share a personal anecdote demonstrating how scientific inquiry led a lifelong
    atheist to embrace Hindu spirituality, specifically Advaita Vedanta, and to challenge
    the blanket statement that religion is anti-science by highlighting perceived
    consistencies between modern physics/consciousness research and ancient philosophical
    traditions.
  sub_sections: {}
- heading: Reply Clusters
  bullets:
  - 'Personal Resonance and Validation: Many commenters expressed strong agreement
    and shared similar personal journeys, finding validation in the OP''s narrative
    of discovering spiritual meaning through a scientific or intellectual lens.'
  - 'Historical and Philosophical Links to Science: Some users elaborated on perceived
    historical connections or philosophical alignments between Eastern traditions
    like Advaita Vedanta and modern scientific concepts, particularly in quantum physics
    and psychology.'
  - 'Critique of Direct Science-Religion Equivalence: A notable cluster of comments
    cautioned against adopting philosophies solely based on their perceived consistency
    with science, arguing that philosophy and science serve different purposes or
    disputing the direct historical claims of scientific influence.'
  sub_sections:
    Personal Resonance and Validation:
    - I just stumbled here. And dude, i gotta yell you. This is exactly my story.
      And i am Indian by birth. And i feel blessed to have found the path to the truth.
    - Same happened to me.
    - Good brother! Same here. Took the long route but finding new things everytime
      which science and words cannot even explain at this time.
    - Born a Hindu, got interested in it recently in early 20s. All the Adhyatamic
      concepts regarding Atma, Brahm, chetna, Maya, Sansar etc. got me interested
      in it. Accepted it by heart. Not ever leaving it now.
    Historical and Philosophical Links to Science:
    - "I think that's pretty sound thinking. Quantum Physics was heavily inspired\
      \ by the teachings of Advaita Vedanta, especially after Max M\xFCller translated\
      \ the Upanishads and other texts from the tradition into German. Heisenberg\
      \ and Von Weizsacker are generally considered the fathers of quantum physics,\
      \ they both had extensive knowledge of Advaita Vedanta and acknowledged the\
      \ influence of this philosophy on their thinking."
    - "When someone looks for only science in religion. They won't find any religion\
      \ that postulates solely scientific truths. But when you look at the combination\
      \ of meaning, purpose, science, and spirituality. Hinduism takes the cake \U0001F370"
    - His idea of the collective subconscious was largely based on advaitin ideas,
      whereas Freud's interpretation of the libido had its roots in Hindu teachings
      on Kundalini. Note as well, that simulation theory is gaining ground among ever
      more scientists, that is another major philosophical concept from Hinduism,
      which posits that the world is fundamentally a holographic construct or illusion
      (maya).
    Critique of Direct Science-Religion Equivalence:
    - Well do not turn to religion or philosophies just because you think it's consistent
      with science. Philosophies like Advaita vedanta are for completely different
      purpose, they don't claim any science there theories and ideas serve a different
      purpose even if science is against them it's still relevant because science
      serves a totally different purpose.
    - I think where you're mistaken is the idea that eastern traditions somehow dealt
      with this better than western ones. That's definitely not the case. Hinduism
      isn't based on science, and the Sanskrit texts are just as much word soup as
      anything. Western philosophy also recognized consciousness as fundamental, for
      example a lot of Abrahamic thought like Christian and Islamic theology is Platonic
      and believes in a "universal consciousness".
    - Respectfully, this is a crock of bullshit. Vedanta Philosophy cannot be credited
      with QM. Just because someone believes or has read something doesn't mean whatever
      they do is a product of that. A simple example... Virat Kohli is a Hindu. He's
      a great batsman. Can we credit Hinduism for his Batting techniques? We can credit
      the person he is to Hinduism.
- heading: Counterarguments
  bullets:
  - Philosophies like Advaita Vedanta are for personal growth and serve a different
    purpose than science; their relevance isn't dependent on scientific validation,
    and they might even be relevant if science contradicts them.
  - The idea that Eastern traditions handled the concept of consciousness as fundamental
    better than Western ones is debatable, as Western philosophy (e.g., Platonic,
    Abrahamic thought) also recognized universal consciousness.
  - Hinduism is not based on science, and Sanskrit texts can be as ambiguous as other
    religious texts.
  - Vedanta Philosophy cannot be directly credited with Quantum Mechanics; personal
    beliefs or readings do not automatically translate into scientific credit for
    one's work.
  - A direct claim that Quantum Mechanics was 'written in the Vedas' is a misinterpretation
    or exaggeration.
  - There's a need for specific, non-jargonistic explanations of how Hinduism follows
    basic scientific rules, to avoid confirmation bias or confusion.
  sub_sections: {}
- heading: Unresolved Questions
  bullets:
  - What meaningful stepping stones or insights can be offered to a Western atheist
    lurker interested in this subject?
  - What specifically persuaded the OP to follow the Hindu path as opposed to other
    hermetic or Gnostic traditions?
  - In which specific video does Dr. Hoffman discuss Advaita Vedanta?
  - What are the specific aspects of Hinduism that make it scientific, avoiding jargon
    and complex topics that could lead to bias?
  sub_sections: {}
- heading: Moderation Context
  bullets:
  - Rendered comments covered only part of the thread (13/38 visible; divergence 65.79%).
    25 removed comments were recovered from pullpush.io.
  sub_sections: {}
metadata:
  source_type: reddit
  url: https://www.reddit.com/r/hinduism/comments/180eb1m/a_lifelong_atheist_turning_to_hindu_spirituality
  author: _ashok_kumar
  date: null
  extraction_confidence: high
  confidence_reason: json endpoint ok; rendered=13/38 divergence=65.79%
  total_tokens_used: 5359
  gemini_pro_tokens: 0
  gemini_flash_tokens: 5359
  total_latency_ms: 41445
  cod_iterations_used: 0
  self_check_missing_count: 0
  patch_applied: false
  engine_version: 2.0.0
  structured_payload:
    mini_title: r/hinduism share personal anecdote demonstrating scientific
    brief_summary: 'OP''s main point was To share a personal anecdote demonstrating
      how scientific inquiry led a lifelong atheist to. The dominant replies focused
      on Personal Resonance and Validation. Consensus stayed around personal resonance
      and validation while historical and philosophical links to science. Dissent
      centered on Philosophies like Advaita Vedanta are for personal growth and serve
      a different. Caveat: removed or missing comments may limit what is visible in
      the thread.'
    tags:
    - r-hinduism
    - q-and-a
    - atheism
    - hinduism
    - spirituality
    - science
    - particle-physics
    - consciousness
    - advaita-vedanta
    - philosophy
    detailed_summary:
      op_intent: To share a personal anecdote demonstrating how scientific inquiry
        led a lifelong atheist to embrace Hindu spirituality, specifically Advaita
        Vedanta, and to challenge the blanket statement that religion is anti-science
        by highlighting perceived consistencies between modern physics/consciousness
        research and ancient philosophical traditions.
      reply_clusters:
      - theme: Personal Resonance and Validation
        reasoning: Many commenters expressed strong agreement and shared similar personal
          journeys, finding validation in the OP's narrative of discovering spiritual
          meaning through a scientific or intellectual lens.
        examples:
        - I just stumbled here. And dude, i gotta yell you. This is exactly my story.
          And i am Indian by birth. And i feel blessed to have found the path to the
          truth.
        - Same happened to me.
        - Good brother! Same here. Took the long route but finding new things everytime
          which science and words cannot even explain at this time.
        - Born a Hindu, got interested in it recently in early 20s. All the Adhyatamic
          concepts regarding Atma, Brahm, chetna, Maya, Sansar etc. got me interested
          in it. Accepted it by heart. Not ever leaving it now.
      - theme: Historical and Philosophical Links to Science
        reasoning: Some users elaborated on perceived historical connections or philosophical
          alignments between Eastern traditions like Advaita Vedanta and modern scientific
          concepts, particularly in quantum physics and psychology.
        examples:
        - "I think that's pretty sound thinking. Quantum Physics was heavily inspired\
          \ by the teachings of Advaita Vedanta, especially after Max M\xFCller translated\
          \ the Upanishads and other texts from the tradition into German. Heisenberg\
          \ and Von Weizsacker are generally considered the fathers of quantum physics,\
          \ they both had extensive knowledge of Advaita Vedanta and acknowledged\
          \ the influence of this philosophy on their thinking."
        - "When someone looks for only science in religion. They won't find any religion\
          \ that postulates solely scientific truths. But when you look at the combination\
          \ of meaning, purpose, science, and spirituality. Hinduism takes the cake\
          \ \U0001F370"
        - His idea of the collective subconscious was largely based on advaitin ideas,
          whereas Freud's interpretation of the libido had its roots in Hindu teachings
          on Kundalini. Note as well, that simulation theory is gaining ground among
          ever more scientists, that is another major philosophical concept from Hinduism,
          which posits that the world is fundamentally a holographic construct or
          illusion (maya).
      - theme: Critique of Direct Science-Religion Equivalence
        reasoning: A notable cluster of comments cautioned against adopting philosophies
          solely based on their perceived consistency with science, arguing that philosophy
          and science serve different purposes or disputing the direct historical
          claims of scientific influence.
        examples:
        - Well do not turn to religion or philosophies just because you think it's
          consistent with science. Philosophies like Advaita vedanta are for completely
          different purpose, they don't claim any science there theories and ideas
          serve a different purpose even if science is against them it's still relevant
          because science serves a totally different purpose.
        - I think where you're mistaken is the idea that eastern traditions somehow
          dealt with this better than western ones. That's definitely not the case.
          Hinduism isn't based on science, and the Sanskrit texts are just as much
          word soup as anything. Western philosophy also recognized consciousness
          as fundamental, for example a lot of Abrahamic thought like Christian and
          Islamic theology is Platonic and believes in a "universal consciousness".
        - Respectfully, this is a crock of bullshit. Vedanta Philosophy cannot be
          credited with QM. Just because someone believes or has read something doesn't
          mean whatever they do is a product of that. A simple example... Virat Kohli
          is a Hindu. He's a great batsman. Can we credit Hinduism for his Batting
          techniques? We can credit the person he is to Hinduism.
      counterarguments:
      - Philosophies like Advaita Vedanta are for personal growth and serve a different
        purpose than science; their relevance isn't dependent on scientific validation,
        and they might even be relevant if science contradicts them.
      - The idea that Eastern traditions handled the concept of consciousness as fundamental
        better than Western ones is debatable, as Western philosophy (e.g., Platonic,
        Abrahamic thought) also recognized universal consciousness.
      - Hinduism is not based on science, and Sanskrit texts can be as ambiguous as
        other religious texts.
      - Vedanta Philosophy cannot be directly credited with Quantum Mechanics; personal
        beliefs or readings do not automatically translate into scientific credit
        for one's work.
      - A direct claim that Quantum Mechanics was 'written in the Vedas' is a misinterpretation
        or exaggeration.
      - There's a need for specific, non-jargonistic explanations of how Hinduism
        follows basic scientific rules, to avoid confirmation bias or confusion.
      unresolved_questions:
      - What meaningful stepping stones or insights can be offered to a Western atheist
        lurker interested in this subject?
      - What specifically persuaded the OP to follow the Hindu path as opposed to
        other hermetic or Gnostic traditions?
      - In which specific video does Dr. Hoffman discuss Advaita Vedanta?
      - What are the specific aspects of Hinduism that make it scientific, avoiding
        jargon and complex topics that could lead to bias?
      moderation_context: Rendered comments covered only part of the thread (13/38
        visible; divergence 65.79%). 25 removed comments were recovered from pullpush.io.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Post
A lifelong atheist turning to Hindu spirituality because of science The following is a personal anecdote and I am only sharing this because I see a lot of blanket statements on Reddit and on the internet in general around how religion is anti-science. I used to think the same but now my perspective has widened. Here’s how and why- I became an atheist a long time ago because I realized all the religious figures around me were basically making word salads whenever I asked them any questions and that they didn’t really have any answers. OTOH science appealed to me because it is logical, evidence based and is falsifiable. The interest in physics and mathematics grew stronger through the years and even though I studied engineering and took up a career in software engineering, I kept up with the latest research specifically in the area of high energy particle physics because I believe that’s where we are trying to answer the most fundamental question of ‘what in the hell is going on?’ When the Higgs particle was finally discovered at LHC, I was ecstatic just like most others who were paying attention to what was going on in particle physics. Soon after though, some physicists working at the LHC (most notably, Nima Arkani Hamed) published papers where they expressed doubts that space and time may not be fundamental and there may be a deeper structure underneath that in turn gives rise to space time as emergent phenomenon. In the last 10 years, they’ve done a ton of follow up work that has proven beyond doubt that they aren’t just hallucinating. They’ve in fact discovered some candidate structures (e.g. the amplituhedron) that give rise to fundamental particles and their properties along with causation without assuming the existence of space or time in the beginning. Obviously more research needs to be done to discover the exact nature of these geometric structures and their properties. While all of this was going on, I came across Prof. Don Hoffman who was working on a theory of consciousness. His research posits that in fact if you take consciousness (conscious agents to be more precise) to be the fundamental unit of existence, you can mathematically show that interactions among a network of conscious agents can give rise to structures that become fundamental particles along with their properties such as spin and mass along with causation. If you’d like to dig deeper in the science, you can look up the work of both [Nima Arkani Hamed](https://youtu.be/GL77oOnrPzY?si=T-62RyYRurJWz9c8) who leads a team of high energy particle physicists at the CERN supercollider and that of [Prof. Donald Hoffman](https://youtu.be/UrQRVitzPkY?si=a1bPPareJEyqchXN) who is a Professor Emeritus of Cognitive Sciences at the University of California, Irvine. So how did this lead me to religion? Well, in one of his interviews, Prof Hoffman spoke about how some eastern philosophical traditions talk about consciousness being the fundamental unit of existence and he gave the example of Advaita Vedanta. That’s when I started digging deep into this philosophical tradition and I found the principles to be quite consistent with the scientific method. To all those scientifically inclined, I’d encourage you to keep an open mind and not draw blanket conclusions just because that view is popular. I still struggle with all the pseudoscience that various religious gurus and institutions espouse but there are parts of religion that are logical, and actually make sense scientifically. https://www.reddit.com/r/hinduism/comments/180eb1m/a_lifelong_atheist_turning_to_hindu_spirituality/

Comments
superr_husky: I just stumbled here. And dude, i gotta yell you. This is exactly my story. And i am Indian by birth. And i feel blessed to have found the path to the truth. _ashok_kumar: What is frustrating to me is that i was born and raised in India and i had no idea about Vedanta until i was well into my thirties. Worse, a foreigner had to introduce it. I wish as a society and a civilization, we took more pride in our heritage and paid attention to the knowledge that’s there in the Upanishads. bipin44: Well do not turn to religion or philosophies just because you think it's consistent with science. Philosophies like Advaita vedanta are for completely different purpose, they don't claim any science there theories and ideas serve a different purpose even if science is against them it's still relevant because science serves a totally different purpose. For example no one likes to jump from a building not because science has proved that there is something like gravity and it pulls you down but simply because you don't want to die. Same with these philosophies they are for personal growth their theories could be proved wrong maybe 100 years later no one knows so follow them if you find it help... Kartik_800: Born a Hindu, got interested in it recently in early 20s. All the Adhyatamic concepts regarding Atma, Brahm, chetna, Maya, Sansar etc. got me interested in it. Accepted it by heart. Not ever leaving it now. Dumuzzi: I think that's pretty sound thinking. Quantum Physics was heavily inspired by the teachings of Advaita Vedanta, especially after Max Müller translated the Upanishads and other texts from the tradition into German. Heisenberg and Von Weizsacker are generally considered the fathers of quantum physics, they both had extensive knowledge of Advaita Vedanta and acknowledged the influence of this philosophy on their thinking. Von Weizsacker in particular impressed Hindu religious scholars with his deep knowledge and understanding of Advaitin concepts on a trip to visit his friend, Gopi Krishna in Kashmir. He wrote a long essay on the unitive nature of the universe and the fundamental nature of con... UniversalHuman000: When someone looks for only science in religion. They won't find any religion that postulates solely scientific truths. But when you look at the combination of meaning, purpose, science, and spirituality. Hinduism takes the cake 🍰 [deleted]: Same happened to me. Lonely_Cosmonaut: What could you offer me (a western atheist lurker) as meaningful stepping stones or insights into this subject. I’m open minded to unidentified (by modern science) layers of existence but I want to know more about what persuaded you to follow the Hindu path as opposed to any other hermetic tradition or even Gnostic ones. painintheeyes: Good brother! Same here. Took the long route but finding new things everytime which science and words cannot even explain at this time. rohur_x: Happy for you brother. Can you recall in which video Dr. Hoffan talks about Advait Vedanta? marmulak: I think where you're mistaken is the idea that eastern traditions somehow dealt with this better than western ones. That's definitely not the case. Hinduism isn't based on science, and the Sanskrit texts are just as much word soup as anything. Western philosophy also recognized consciousness as fundamental, for example a lot of Abrahamic thought like Christian and Islamic theology is Platonic and believes in a "universal consciousness". I've studied Vedanta before, and I'm not sure if "consciousness" is actually the core concept, but rather "being" and the soul. serious-aspirant: In my case it was this one video that fascinated me. I will recommend you to watch it too https://youtu.be/EvOEU3R9gng?feature=shared [deleted]: What are the specifics, which made you think it's scientific?. Avoid bringing big jargons and complex topics, they can easily be confused, confirmed as par one's bias, in lack of knowledge most often. Just check if Hinduism followes the basic scientific rule. That will clear stuff.

Recovered Comments
[u/Top-Tomatillo210, score 1, recovered from pullpush.io] Same happened to me. [u/Lonely_Cosmonaut, score 1, recovered from pullpush.io] What could you offer me (a western atheist lurker) as meaningful stepping stones or insights into this subject. I’m open minded to unidentified (by modern science) layers of existence but I want to know more about what persuaded you to follow the Hindu path as opposed to any other hermetic tradition or even Gnostic ones. [u/feelinghothothotter, score 1, recovered from pullpush.io] I'm sorry. Respectfully, this is a crock of bullshit. Vedanta Philosophy cannot be credited with QM. Just because someone believes or has read something doesn't mean whatever they do is a product of that. A simple example... Virat Kohli is a Hindu. He's a great batsman. Can we credit Hinduism for his Batting techniques? We can credit the person he is to Hinduism. [u/feelinghothothotter, score 1, recovered from pullpush.io] I did. And you're right, he said Quantum Mechanics was written in the Vedas. [u/wisewaternexus, score 1, recovered from pullpush.io] &gt;What is frustrating to me is that i was born and raised in India and i had no idea about Vedanta until i was well into my thirties. Worse, a foreigner had to introduce it. How can you blame yourself for this? It's the government's fault—they abandoned our own education system in favor of a Western one. It's not your fault. India is still controlled in subtle ways by the Western world, though most people don’t realize it. [u/superr_husky, score 1, recovered from pullpush.io] I just stumbled here. And dude, i gotta yell you. This is exactly my story. And i am Indian by birth. And i feel blessed to have found the path to the truth. [u/UniversalHuman000, score 1, recovered from pullpush.io] When someone looks for only science in religion. They won't find any religion that postulates solely scientific truths. But when you look at the combination of meaning, purpose, science, and spirituality. Hinduism takes the cake 🍰 [u/serious-aspirant, score 1, recovered from pullpush.io] In my case it was this one video that fascinated me. I will recommend you to watch it too https://youtu.be/EvOEU3R9gng?feature=shared [u/serious-aspirant, score 1, recovered from pullpush.io] Upanishads are vedantas right? They are indeed vedic [u/Dumuzzi, score 1, recovered from pullpush.io] I think that's pretty sound thinking. Quantum Physics was heavily inspired by the teachings of Advaita Vedanta, especially after Max Müller translated the Upanishads and other texts from the tradition into German. Heisenberg and Von Weizsacker are generally considered the fathers of quantum physics, they both had extensive knowledge of Advaita Vedanta and acknowledged the influence of this philosophy on their thinking. Von Weizsacker in particular impressed Hindu religious scholars with his deep knowledge and understanding of Advaitin concepts on a trip to visit his friend, Gopi Krishna in Kashmir. He wrote a long essay on the unitive nature of the universe and the fundamental nature of consciousness to it, as a foreword to Gopi Krishna's first book, Kundalini: The Evolutionary Energy in Man. You might find this essay online, it's worth a read. It should also be noted that modern psychology was also heavily influenced by Advaitin and other Hindu concepts. Jung travelled to India and studied many yogis and sadhus. He also lectured on Kundalini, which was published in book form, you can read that online. His idea of the collective subconscious was largely based on advaitin ideas, whereas Freud's interpretation of the libido had its roots in Hindu teachings on Kundalini. Note as well, that simulation theory is gaining ground among ever more scientists, that is another major philosophical concept from Hinduism, which posits that the world is fundamentally a holographic construct or illusion (maya). [u/_ashok_kumar, score 1, recovered from pullpush.io] What is frustrating to me is that i was born and raised in India and i had no idea about Vedanta until i was well into my thirties. Worse, a foreigner had to introduce it. I wish as a society and a civilization, we took more pride in our heritage and paid attention to the knowledge that’s there in the Upanishads. [u/_ashok_kumar, score 1, recovered from pullpush.io] Scaling this means figuring out a way to get the message across to the masses. [u/_ashok_kumar, score 1, recovered from pullpush.io] I am glad we found this path. But it is insane that people born in India even in the Hindu faith have to take this long route to find our own roots. Anyway, very happy for you. [u/_ashok_kumar, score 1, recovered from pullpush.io] I am glad we found this path. But it is insane that people born in India even in the Hindu faith have to take this long route to find our own roots. Anyway, very happy for you. [u/_ashok_kumar, score 1, recovered from pullpush.io] Hard to disagree with that. I am trying to at least get kids in my family familiarized with this. With the learnings from this experience, hopefully will be able to figure out how to scale this. [u/_ashok_kumar, score 1, recovered from pullpush.io] Thank you. [u/_ashok_kumar, score 1, recovered from pullpush.io] I am just saying that science led me to spirituality. I have found spiritual experiences to be fulfilling in themselves. I no longer ‘need’ science to stay with spirituality. Both will hold importance for me independently. [u/Kartik_800, score 1, recovered from pullpush.io] Born a Hindu, got interested in it recently in early 20s. All the Adhyatamic concepts regarding Atma, Brahm, chetna, Maya, Sansar etc. got me interested in it. Accepted it by heart. Not ever leaving it now. [u/_ashok_kumar, score 1, recovered from pullpush.io] This requires a prolonged conversation and I don’t think this format of comments and replies is good enough for it. Do you mind sending me a DM? Can get on a call some day and discuss if you’re interested. [u/_ashok_kumar, score 1, recovered from pullpush.io] In a nutshell though, I was looking for something that didn’t require ‘faith’ to begin with, allowed me to remain skeptical and keep asking questions so long as I wasn’t satisfied with the logic of it all. Only Advaita fit this bill. [u/jivanyatra, score 1, recovered from pullpush.io] This is an important understanding to have regardless of path or tradition IMHO. [u/Dumuzzi, score 1, recovered from pullpush.io] I'm not a Hindu and neither was Von Weizsacker or Jung. You can read the teachings of a particular philosophy, in this case AV and agree or disagree with it, let it inspire you to have new ideas and new thinking, without being part of that particular religion. This has nothing to do with Hinduism as a religion or belief or lack of in deities. Science is a branch of philosophy, so it must be placed in its proper context. There are many ways for us to understand, study and classify the world, science is one method, but it is not philosophy, the latter is responsible for the conceptual framework by which we understand the world around us and helps us make sense of it. I did not say that AV can be credited with QM, only that the philosophical ideas contained therein, especially non-duality and the unitive principle was an inspiration for developing some of the scientific ideas around QM, especially in von Weizsacker's case, which we know from his own writings and lectures. Philosophy is not science, but it is needed to help us think clearly and develop ideas that may one day serve as the basis of scientific theories. It does not replace empirical study, which is needed to confirm a theory. [u/painintheeyes, score 1, recovered from pullpush.io] Good brother! Same here. Took the long route but finding new things everytime which science and words cannot even explain at this time. [u/_ashok_kumar, score 1, recovered from pullpush.io] He has talked about it several times but I am unable to recall a specific video. But fear not. He recently had a [conversation](https://www.youtube.com/watch?v=S57DSgRWBRM) with Swami Sarvapriyananda where they go into a lot of detail. [u/aloof_aware, score 1, recovered from pullpush.io] Society starts with you :P
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 1120be18714f9c56f7e7966d0589827a40842f56d1f84292d078e1a5075c017a
