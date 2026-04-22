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
## URL 1: https://www.reddit.com/r/IndianStockMarket/comments/1getc4l/rajkot_collapsed_hyundai_ipo/

### SUMMARY
```yaml
mini_title: r/IndianStockMarket To assert Rajkot investors disproportion
brief_summary: 'OP argued To assert that Rajkot investors disproportionately influence
  India''s IPO Grey Market. Many replies said Multiple users identified the post as
  heavily based on or plagiarized. Pushback included The Hyundai IPO''s reception
  was corrected from ''collapsed'' to ''lukewarm''. Context: Removed or missing comments
  may limit what is visible in.'
tags:
- r-indianstockmarket
- ipo
- greymarket
- gmp
- rajkot
- investing
- india
- duediligence
- discussion
detailed_summary:
- heading: op_intent
  bullets:
  - To assert that Rajkot investors disproportionately influence India's IPO Grey
    Market Premium (GMP) and are a critical hub for IPO sentiment, citing specific
    IPO case studies.
  sub_sections: {}
- heading: reply_clusters
  bullets:
  - '{"theme": "Post''s content identified as derived from external source", "reasoning":
    "Multiple users identified the post as heavily based on or plagiarized from an
    article by Anand Kalyanaraman in The Ken.", "examples": []}'
  - '{"theme": "Confirmation of Rajkot''s active stock market culture", "reasoning":
    "Commenters, including some from Rajkot, confirmed the city has a deep and active
    stock market culture, including a prominent grey market, local brokers, and illegal
    ''dabba trading'', with SEBI known to monitor the city.", "examples": []}'
  sub_sections: {}
- heading: counterarguments
  bullets:
  - The Hyundai IPO's reception was corrected from 'collapsed' to 'lukewarm', with
    fundamental factors cited as reasons for muted interest.
  - Hyundai's IPO was considered expensive (P/E of 26), structured as a 100% Offer
    for Sale (OFS) with proceeds going to the parent, and involved pre-IPO financial
    engineering (drained cash reserves via dividends, increased royalty percentage
    to parent).
  - Unfavorable general market conditions and a slowdown in the auto industry were
    also cited for Hyundai's lukewarm reception.
  - Critics questioned the flawed influence model, arguing that Rajkot's absolute
    contribution in INR might be significantly smaller than top-tier cities, limiting
    its market-moving power despite its application volume.
  sub_sections: {}
- heading: moderation_context
  bullets:
  - Rendered comments covered only part of the thread (56/114 visible; divergence
    50.88%). 24 removed comments were recovered from pullpush.io.
  sub_sections: {}
metadata:
  source_type: reddit
  url: https://www.reddit.com/r/IndianStockMarket/comments/1getc4l/rajkot_collapsed_hyundai_ipo
  author: Lazy-Transition8236
  date: null
  extraction_confidence: high
  confidence_reason: json endpoint ok; rendered=56/114 divergence=50.88%
  total_tokens_used: 14904
  gemini_pro_tokens: 13093
  gemini_flash_tokens: 1811
  total_latency_ms: 90113
  cod_iterations_used: 2
  self_check_missing_count: 3
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: r/IndianStockMarket To assert Rajkot investors disproportion
    brief_summary: 'OP argued To assert that Rajkot investors disproportionately influence
      India''s IPO Grey Market. Many replies said Multiple users identified the post
      as heavily based on or plagiarized. Pushback included The Hyundai IPO''s reception
      was corrected from ''collapsed'' to ''lukewarm''. Context: Removed or missing
      comments may limit what is visible in.'
    tags:
    - r-indianstockmarket
    - ipo
    - greymarket
    - gmp
    - rajkot
    - investing
    - india
    - duediligence
    - discussion
    detailed_summary:
      op_intent: To assert that Rajkot investors disproportionately influence India's
        IPO Grey Market Premium (GMP) and are a critical hub for IPO sentiment, citing
        specific IPO case studies.
      reply_clusters:
      - theme: Post's content identified as derived from external source
        reasoning: Multiple users identified the post as heavily based on or plagiarized
          from an article by Anand Kalyanaraman in The Ken.
        examples: []
      - theme: Confirmation of Rajkot's active stock market culture
        reasoning: Commenters, including some from Rajkot, confirmed the city has
          a deep and active stock market culture, including a prominent grey market,
          local brokers, and illegal 'dabba trading', with SEBI known to monitor the
          city.
        examples: []
      counterarguments:
      - The Hyundai IPO's reception was corrected from 'collapsed' to 'lukewarm',
        with fundamental factors cited as reasons for muted interest.
      - Hyundai's IPO was considered expensive (P/E of 26), structured as a 100% Offer
        for Sale (OFS) with proceeds going to the parent, and involved pre-IPO financial
        engineering (drained cash reserves via dividends, increased royalty percentage
        to parent).
      - Unfavorable general market conditions and a slowdown in the auto industry
        were also cited for Hyundai's lukewarm reception.
      - Critics questioned the flawed influence model, arguing that Rajkot's absolute
        contribution in INR might be significantly smaller than top-tier cities, limiting
        its market-moving power despite its application volume.
      unresolved_questions: []
      moderation_context: Rendered comments covered only part of the thread (56/114
        visible; divergence 50.88%). 24 removed comments were recovered from pullpush.io.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Post
Rajkot collapsed Hyundai IPO I always wanted to get into Gujarati circles to know more about stock investing but seeing the level of stock market involvement in Gujarat has piqued my interest even more. Rajkot, a tier-2 city in Gujarat, wrote the fate of India's biggest IPO to date. Interestingly, Rajkot is India's third-largest source of IPO applications. This is comparable to the level of involvement seen in a city as big as Mumbai (the financial capital of India), despite having only 10% of Mumbai's population. But that is not all. Rajkot also has a high participation through the grey market, which has influenced Hyundai's GMP. GMP is the number #1 factor that retail investors take into account before applying for an IPO. Companies make a sales pitch of their IPOs (through roadshows) to potential investors, brokers, and media houses to create hype. The roadshow circuits of IPO-bound companies focus on big cities, Mumbai and Ahmedabad, and a small, seemingly "out of place" city Rajkot. But this seemingly "out of place" city has to show interest in the grey market for the GMP to go up, thereby deciding the outcome of the IPO. Investors of Rajkot did not show much interest in the Hyundai IPO. The city, with its stock market culture and seasoned share brokers, is an important hub for the IPO grey market. Rajkot was supposedly a big IPO hub even back in the 1990s. Hyundai Motors GMP tanked day by day and a large part of this is due to disinterest from the city having the third-highest number of IPO applicants. In contrast, investors from the city showed interest in Waaree Energies IPO and the GMP went up by crazy margins. Surprising right? That investors from a tier-2 city can influence retail investors throughout the country when they decide not to invest in a particular IPO. Now after this observation, I remember my hunch about the Hyundai IPO GMP deliberately being bought down so that some large players can buy a fundamentally good company at a cheap valuation (by reducing competition during IPO). But my theory might also have some loopholes since this was only a casual observation. Anyway all of this information was interesting to read and ponder. https://www.reddit.com/r/IndianStockMarket/comments/1getc4l/rajkot_collapsed_hyundai_ipo/

Comments
AutoModerator: If you haven't already, please add your own analysis/opinions to your post to save it from being removed for being a Low Effort post. Please DO NOT ask for BUY/SELL advice without sharing your own opinions with reasons first. Such posts will be removed. Please also refer to the [FAQ](https://www.reddit.com/r/IndianStockMarket/comments/17bcg2a/frequently asked questions_post_your_common/) where most common questions have already been answered. Subscribe to our [weekly newsletter](https://pennyleaks.substack.com/) and join our Discord server using [Link 1](https://discord.gg/fDRj8mA66U) or [Link 2](https://discord.gg/EVgUnQ3CsF) *I am a bot, and this action was performed automatically. Please... [deleted]: Well, were you able to get into these circles of Gujarati investing masterminds? cocwiki: Im not getting my 2 minutes back. blackpearlinscranton: Abhishek Kar welcome to Reddit Chekkan_87: Hyundai IPO collapsed? Does Hyundai know this? pod_in_a_pea: OP ne Ken ka article chep diya - kam se kam original post main credit to de deta jonota20: Problem happened when they (Hyn mgmt) became too greedy and changed the price, before that GMP was higher. And market conditions were not favourable too when ipo opened for applying. If they brought the IPO during last year Nov or Dec, then would have gotten much higher GMP. In case of Waaree, they did the opposite, almost discounted 40% of the price at which unlisted shares were traded, but as market conditions were not favourable still GMP fell from Initial level. fahadsayed36: if Rajkot is at 3rd who's at the top 2? Mightyplague: So, the GMP is decided by a small bunch of people in a single city. What a shocking news, considering the shallow depth of the grey market. /s And this is not manipulation because nobody asks you to look at GMP as the sole piece of information before applying for an IPO. Tmkct: I recently read this on Twitter and was amazed. Lanky-Patience-1523: This is a copy paste job from The Ken article which came yesterday. Here: [https://the-ken.com/](https://the-ken.com/) https://preview.redd.it/m15e2vzjqpxd1.jpeg?width=1170&amp;format=pjpg&amp;auto=webp&amp;s=8df0430f22cb87bb73e5b458913691e63b016464 dc1222: So how does one figure out the state or city wise distribution of IPO applications? What's the name of the document in which this is published? nityanand69: I am greedy gujju from vadodara. Solid_Story9420: I don't think it could be entirely true. Your ranking of cities may be right but ranking could be misleading. For example, our guys will keep telling you that India will be the third largest economy in five years from now, which is technically correct but the gap between no. 2 and no.3 is so huge. So, it would be good to know in INR terms what percentage is filled by cities ranked 2 and 3. They could be influencers, granted, but I don't think that determines and drives the price significantly. tutya_th: Investing is more than charts. This real life explanation is a gem. Thanks for sharing, OP. anonymous_mystery_: Waree supremacy Ready-Race-1778: Wow you must be special to think ‘Gujaratis of Rajkot’ control share market. Baccha hai kya bhai? Ok_Collar3048: ![gif](giphy|OMeVt8yfiXm09VCsik) veertamizhan: New thinking new possibilities. trailblazer-sigma: I am from Rajkot and a seasoned full time trader too ActiveSpirit5343: Such a time waste this post babytiger10: What's the status with Swiggy ? [deleted]: So what do Rajkot/Gujarat say about Swiggy? [deleted]: [removed] Divyansh881: Nice hypothesis. Share data source my g the_epeolatrist: Super interesting, very well written! The low interest in Hyundai IPO was also because it was a complete OFS. All the proceeds went into the pocket of the parent entity. Plus auto industry has been slowing down in India. No-Sundae-1701: Interesting. But where did you get the info that Rajkot accounts for a substantial chunk of ipo applications ? I would like to see the source, thanks. christopher_jolan: I am from rajkot and I don't think this is true. isnotsochill: You know that most people here read The Ken, right? Please give credits to Anand Kalyanaraman, who is the Finance Reporter at The Ken, whose report you've shamelessly passed as your own observations. ak32009: Suna tha ki gujrat mein daaru ban h to log saste nashe kar lete hain.... 🤔🤔🤔 hailthegreatone: The post seems like an answer to a 5 marks question. Very little substance and same information written multiple times maancast: As a Rajkotian, I can proudly say that the above information is true, but it is just the mere facade of it. Market operations here are a completely different dynamic, and you'd have to experience it yourself in order to understand that. No_Hurry_3244: From finshots? No-Juggernaut3285: Why did I even read this Troll post!! confidenttrader1: Abhishek Kar naam badal kr reddit chala rha. fintech_1712: Yes there are tons of local brokers, who are engaged in grey market and dabba trading. Rajkot is way ahead in terms of share market and commodity trading. There are many stock operators and many times SEBI roaming in the city in common dress. Abhishek_Sen01: if Rajkot is at 3rd who's at the top 2? Space-floater4166: Any subReddit of Gujarati share brokers investors [deleted]: Hyundai IPO collapsed? That too because of some masterminds in Rajkot? Does Hyundai or the people of Rajkot know this? Damn, I'm out of the loop. Singhfrommumbai: So 3rd highest city was able to affect the gmp but 1st and 2nd were not? Doesn't really makes sense na bro Outside-Common-6820: Is there any source for this info? Any numbers that you can quote? baldha_: https://preview.redd.it/oy90t94tk1yd1.jpeg?width=1080&amp;format=pjpg&amp;auto=webp&amp;s=920dae0096808d175d11d3fb86c4e80738fe7e08 Ok_Abalone8973: But dont you think, you should go by logic and market stats, most of the automobile stocks are going down, may be this is the cause bva91: What a dumb take, no one 'collapsed' the Hyundai IPO.. it had a lukewarm reception because 26 times PE for an auto company is already generous. bva91: What a dumb take, no one 'collapsed' the Hyundai IPO.. it had a lukewarm reception because 26 times PE for an auto company is already generous. [deleted]: Hyundai execs already laughing in the boardroom..on successfully selling a rs.1400 worth share at rs. 1960. Nothing big of a background story here. pole_for_hire: Bhai data ka source to batao SaqMadiqq: If this is true, will they collapse the Swiggy IPO too? [deleted]: Comments made my day![gif](emote|free_emotes_pack|feels_good_man) Ok_Agent_478: Who and what is rajkot and Gujarati. Nonsense 🤮🤮

Recovered Comments
[u/courtsidecurry, score 1, recovered from pullpush.io] Please share the link [u/fahadsayed36, score 1, recovered from pullpush.io] if Rajkot is at 3rd who's at the top 2? [u/stinkingcheese, score 1, recovered from pullpush.io] Not yet [u/the_epeolatrist, score 1, recovered from pullpush.io] Super interesting, very well written! The low interest in Hyundai IPO was also because it was a complete OFS. All the proceeds went into the pocket of the parent entity. Plus auto industry has been slowing down in India. [u/Mightyplague, score 1, recovered from pullpush.io] So, the GMP is decided by a small bunch of people in a single city. What a shocking news, considering the shallow depth of the grey market. /s And this is not manipulation because nobody asks you to look at GMP as the sole piece of information before applying for an IPO. [u/Character_Ad7965, score 1, recovered from pullpush.io] Chutiya [u/jonota20, score 1, recovered from pullpush.io] Problem happened when when became too greedy and changed the price, before that GMP was higher. And market conditions were not favourable too. If they brought the IPO during last year Nov or Dec, then would have gotten much higher GMP. In case of Waaree, they did the opposite, almost discounted 40% of the price at which unlisted shares were traded, but as market conditions were not favourable still GMP fell from Initial level. [u/equinoxeror, score 1, recovered from pullpush.io] F [u/HSPq, score 1, recovered from pullpush.io] Why is it duping, the company might be bit overvalued but it is a great company with good fundamentals. [u/Waste-Conflict6014, score 1, recovered from pullpush.io] Source: Trust me bro [u/anonymous_mystery_, score 1, recovered from pullpush.io] Waree supremacy [u/ActiveSpirit5343, score 1, recovered from pullpush.io] Such a time waste this post [u/Neel_writes, score 1, recovered from pullpush.io] Hyundai IPO collapsed? That too because of some masterminds in Rajkot? Does Hyundai or the people of Rajkot know this? Damn, I'm out of the loop. [u/satish2143, score 1, recovered from pullpush.io] Daba trading i think [u/baldha_, score 1, recovered from pullpush.io] https://preview.redd.it/oy90t94tk1yd1.jpeg?width=1080&amp;format=pjpg&amp;auto=webp&amp;s=920dae0096808d175d11d3fb86c4e80738fe7e08 [u/bva91, score 1, recovered from pullpush.io] What a dumb take, no one 'collapsed' the Hyundai IPO.. it had a lukewarm reception because 26 times PE for an auto company is already generous. [u/bva91, score 1, recovered from pullpush.io] What a dumb take, no one 'collapsed' the Hyundai IPO.. it had a lukewarm reception because 26 times PE for an auto company is already generous. [u/simplyneatfact, score 1, recovered from pullpush.io] Hyundai execs already laughing in the boardroom..on successfully selling a rs.1400 worth share at rs. 1960. Nothing big of a background story here. [u/Critical-Doctor-2052, score 1, recovered from pullpush.io] Maruti and Mahindra have MASSIVE cash reserves on their books. Most of Hyundai's cash reserves got drained out by the Koreans as dividends just before the IPO. If Maruti and Mahindra also gave away most of their cash reserves as dividends to shareholders, their stock price would see a big downward adjustment and their PE ratios will go down significantly. Hyundai also increased royalty % to its parent just before the IPO. This is royalty on revenue, so margins will take a hit going forward. But the PE ratio publicised everywhere is for the old royalty % value. [u/Critical-Doctor-2052, score 1, recovered from pullpush.io] Alright. I'll spoonfeed the numbers to you, mate. Maruti current market cap = 3,49,000 cr Maruti current cash reserves = 89,000 cr Hyundai current market cap = 1,49,000 cr Hyundai current cash reserves = 11,000 cr Assuming Maruti gives out 78,000 crore as dividend today: Market cap: 2,71,000 cr Cash reserves: 11,000 cr Stock price: 8627 TTM PE: 19.3 Retrospectively applying Hyundai's new royalty % to FY24 results: TTM PE: 27.5 Mahindra is into various business verticals and holds large stakes in a number of listed and unlisted companies, so it's not directly comparable like this. [u/_nishank_, score 1, recovered from pullpush.io] Surat and Ahmedabad [u/Nams95, score 1, recovered from pullpush.io] You need to be relative or same caste. Parasites for country and nationalism [u/Ok_Set_6991, score 1, recovered from pullpush.io] Mumbai and Ahmedabad [u/tutya_th, score 1, recovered from pullpush.io] Investing is more than charts. This real life explanation is a gem. Thanks for sharing, OP.
```


## URL 2: https://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and/

### SUMMARY
```yaml
mini_title: r/IAmA intended to share their first-time
brief_summary: 'OP argued The original poster intended to share their first-time heroin
  experience, framing. Many replies said Former addicts highlighted that the user''s
  mindset (feeling in control, rationalizing. Pushback included A minority agreed
  that one-time use does not automatically lead. Context: Removed or missing comments
  may limit what is visible in.'
tags:
- r-iama
- heroin
- first-time-use
- addiction-warnings
- substance-use-disorder
- harm-reduction
- drug-culture
- opioids
- psychological-effects
- social-critique
detailed_summary:
- heading: op_intent
  bullets:
  - The original poster intended to share their first-time heroin experience, framing
    it as a valuable insight gained from curiosity and risk-taking. They later updated
    to dismiss community warnings and announce plans to try cocaine.
  sub_sections: {}
- heading: reply_clusters
  bullets:
  - '{"theme": "Heroin Addiction Path", "reasoning": "Former addicts highlighted that
    the user''s mindset (feeling in control, rationalizing use, pride) mirrors their
    own early stages of addiction, emphasizing the insidious nature of opiate dependence
    and the rapid development of tolerance and physical addiction.", "examples": ["One
    former CIO claimed to have spent over $500,000 on their habit.", "A professional
    shared a parallel story of trying cocaine on a whim, leading to rapid addiction
    and career/savings destruction.", "The first high is uniquely powerful; subsequent
    use becomes a futile attempt to recapture that initial experience.", "A user who
    saw one friend die and another become permanently disabled from overdoses admitted
    they ''still *want* it.''", "Tolerance builds quickly; daily or near-daily use
    can lead to physical addiction in as little as one week to a few months.", "Withdrawal
    was described as ''pure hell.''", "Commenters shared personal accounts of friends
    who died or suffered permanent brain damage from heroin overdoses."]}'
  sub_sections: {}
- heading: counterarguments
  bullets:
  - A minority agreed that one-time use does not automatically lead to addiction.
  - One user suggested it could be treated like pharmaceutical opioids (e.g., Oramorph)
    for 'infrequent special occasions.'
  - One commenter with a history of polysubstance use argued methamphetamine is more
    'instantly' addictive and claimed most people they knew who tried heroin did not
    become addicted.
  - A chronic pain patient distinguished between medical use of prescription opiates
    and street heroin, discussing their own abuse of prescriptions and the struggle
    of being an opiate user while their partner is a recovering heroin addict.
  - Commenters noted the hypocrisy of a generally pro-legalization community lecturing
    the user on personal choice, drawing parallels to the dangers of legal alcohol.
  - Others observed the experience highlights how US drug laws are rooted in classism
    and racism.
  sub_sections: {}
- heading: unresolved_questions
  bullets:
  - Did the original poster experience nausea, a common belief for new users?
  sub_sections: {}
- heading: moderation_context
  bullets:
  - Rendered comments covered only part of the thread (103/761 visible; divergence
    86.47%).
  sub_sections: {}
metadata:
  source_type: reddit
  url: https://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and
  author: SpontaneousH
  date: null
  extraction_confidence: high
  confidence_reason: json endpoint ok; rendered=103/761 divergence=86.47%
  total_tokens_used: 20481
  gemini_pro_tokens: 18333
  gemini_flash_tokens: 2148
  total_latency_ms: 103366
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: r/IAmA intended to share their first-time
    brief_summary: 'OP argued The original poster intended to share their first-time
      heroin experience, framing. Many replies said Former addicts highlighted that
      the user''s mindset (feeling in control, rationalizing. Pushback included A
      minority agreed that one-time use does not automatically lead. Context: Removed
      or missing comments may limit what is visible in.'
    tags:
    - r-iama
    - heroin
    - first-time-use
    - addiction-warnings
    - substance-use-disorder
    - harm-reduction
    - drug-culture
    - opioids
    - psychological-effects
    - social-critique
    detailed_summary:
      op_intent: The original poster intended to share their first-time heroin experience,
        framing it as a valuable insight gained from curiosity and risk-taking. They
        later updated to dismiss community warnings and announce plans to try cocaine.
      reply_clusters:
      - theme: Heroin Addiction Path
        reasoning: Former addicts highlighted that the user's mindset (feeling in
          control, rationalizing use, pride) mirrors their own early stages of addiction,
          emphasizing the insidious nature of opiate dependence and the rapid development
          of tolerance and physical addiction.
        examples:
        - One former CIO claimed to have spent over $500,000 on their habit.
        - A professional shared a parallel story of trying cocaine on a whim, leading
          to rapid addiction and career/savings destruction.
        - The first high is uniquely powerful; subsequent use becomes a futile attempt
          to recapture that initial experience.
        - A user who saw one friend die and another become permanently disabled from
          overdoses admitted they 'still *want* it.'
        - Tolerance builds quickly; daily or near-daily use can lead to physical addiction
          in as little as one week to a few months.
        - Withdrawal was described as 'pure hell.'
        - Commenters shared personal accounts of friends who died or suffered permanent
          brain damage from heroin overdoses.
      counterarguments:
      - A minority agreed that one-time use does not automatically lead to addiction.
      - One user suggested it could be treated like pharmaceutical opioids (e.g.,
        Oramorph) for 'infrequent special occasions.'
      - One commenter with a history of polysubstance use argued methamphetamine is
        more 'instantly' addictive and claimed most people they knew who tried heroin
        did not become addicted.
      - A chronic pain patient distinguished between medical use of prescription opiates
        and street heroin, discussing their own abuse of prescriptions and the struggle
        of being an opiate user while their partner is a recovering heroin addict.
      - Commenters noted the hypocrisy of a generally pro-legalization community lecturing
        the user on personal choice, drawing parallels to the dangers of legal alcohol.
      - Others observed the experience highlights how US drug laws are rooted in classism
        and racism.
      unresolved_questions:
      - Did the original poster experience nausea, a common belief for new users?
      moderation_context: Rendered comments covered only part of the thread (103/761
        visible; divergence 86.47%).
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Post
I did Heroin yesterday. I am not a drug user and have never done anything besides pot back when I was a teen, AMA (this is a little long) I have never been a drug user, I drink once in a while and smoked pot years ago back when I was a teen in highschool a few times and that's it. I'm 24 now, have a masters and a well paying full time job. Yesterday I was walking throgh Washington Square Park where I pass every day and there are always people there looking to sell drugs (not in the park anymore due to cameras, but it is well known you can meet a dealer than and do the transaction elsewhere these days). They usually don't solicit drugs to you unless you stop to stand around near one of them for some reason or look like you're looking for something. Yesterday I happened to stop by a row of benches to check some messages on my phone when a dealer on the bench to my right asks me if I need anything. My life has been pretty boring the last few years and I feel like I haven't really lived, taken any risks, or done anything crazy so I figured what the hell maybe I'll buy some pot, it's been a while. I said yeah and after asking my several times if I'm a cop he gives me his number and tells me to meet him at a fast food place several blocks away and he will 'hook me up.' I say alright and nervously check to make sure I have cash and go meet this shady looking dude. We sit down and after hounding me asking if I'm a cop he asks what I need, I tell him I just want a dime bag and he says something like "Naw sorry man, I only sell half ounces, you can take that and I've got some coke and H." At this point I didn't want to buy half an ounce of pot, I probably never smoked more than an eighth in my life but then I started considering his last word, Heroin. I've heard so much about it and how crazy addictive it is and seen it in the movies and TV (I'm thinking The Wire here, one of my favorite shows) and it really started to intrigue me. I've always wondered what it would be like to do Heroin. Out of no where I say I'll take the H and we do the deal there. I give him the cash under the table and he slides me a small order of fries with a little stamped wax baggie in it then he tells me to let him leave first. I put it in my pocket then nervously race home my heart racing cannot believing what I just did. I held onto that bag in my pocket palms sweating the whole ride home. When I get home I open the bag and dump some golden flakes and powder on my glass coffee table. At this point I don't even know what to do, I know you can snort heroin but it looked all flaky so I try to remember how they did it in the movies but they always seem to inject it in film so I start googling "how to snort Heroin' like an idiot and do a little research on the stuff and how much to take. I used a card to get it into a fine powder and move a small 'bump' to the side which I inhaled through a dollar bill. I didn't feel anything yet so I snorted a small line which was essentially half the bag (there was very little inside). I waited and in a few minutes I had the most pleasurable feeling of pure relaxation and bliss wash over me. I just sat there and everything felt amazing. I nodded off and it was great, I had the TV on but wasn't paying attention, I must have sat around for 4 hours doing nothing but feel total pleasure. It was like a full body orgasm times 10 that kept going on and on. When I would nod off it felt like I was in a pure conscious lucid dream like state, sometimes it felt like I was leaving my body. At this point I did the rest of it and stayed up all night and must have been high for 10 hours straight. i might have slept at one point, it's hard to tell the difference when you nod off and everything feels good regardless, just the feeling of being under a blanket was amazing. I was blown away by the power of this drug and just how orgasmic it felt. I never understood why people did drugs before and got so hooked on them but now I see why. I have the urge to do it again but I will resist and not do it, at least not for a long time. I understand the addiction potential and how someone could easily tear apart their lives with this stuff. Heroin is pure powdered pleasure, I actually feel proud of myself for having the balls to do something this crazy and I feel like it was a valuable life experience and my window into another world and part of society. I will never forget the day I did heroin. Now, ask me anything. **New Edit: I have a lot of respect for most posters and drug addicts with experience here but this Redditor/addict is why people have the negative stereotypes they do about junkies:** http://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and/c0d6prn **Edit: Please no more comments telling me I'm going to be a homeless addict dying of an overdose now, don't lecture me with all of your misconceptions and lack of any real knowledge or experience about the drug. I understand if you know someone who has been hurt by it, we all do. Any drug can ruin lives, please ask me questions instead of trying to lecture me and do some research first before spewing lies.** ========================================== **Update 2: I don't regret this at all and I see a lot of talk about how cocaine isn't as bad as heroin and people telling anyone considering trying a hard drug to do coke instead. I've known and seen a lot of heavy coke users, many who have become addicted and ODed and I find it disturbing that people think coke is acceptable because some 'higher class' circles find it socially acceptable. I'm thinking the young Wall Street and college crowds here who associate it with money and being cool and is easily manageable to use for recreation, while society tells them that Heroin is for the poor and destitute and leads to automatic addiction and suffering.** **So I plan to try cocaine the next chance I get and compare the two in terms of effects and experience. Doing Heroin was memorable and life changing and I know I can handle anything once. I've done my research on coke and know the risks, so if anyone has any questions or opinions on that matter feel free to chime in. Whether it is to tell me I'm a fucking idiot or to give me advice, whatever. This is an experiment and an adventure in life, I'll report back once I try it.** https://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and/

Comments
NeverTrustAJunky: Wait, did you eat the fucking fries or what? Don't leave me hanging bro! [deleted]: [removed] formfactor: Yes, opioid molecules are the best on earth. It really is the greatest feeling life has to offer. Unfortunately once I got a taste for that feeling it was all over. Opioids are the most addictive drugs on the planet. Once your body gets addicted the withdrawl is pure hell. Be very very careful not to injest the stuff everyday, because in a matter of a week you will be completely addicted. I was very suprised at how fast my tolerance went up and how fast I was craving the stuff. I'm now clean of it and taking suboxone to minimize the withdraw. It has helped, but I can never take another opioid without my body going completely crazy for it. Enjoy it, but save it for a rainy day. Opioid addict... [deleted]: Not a question just a suggestion based on knowledge gained from years as a heroin addict. Don't do it again. EVER. There is nothing so terrible in this world as heroin withdrawals. It takes doing heroin every day or every other day for about 2-3 months to get your first habit, but that time goes by real fast when you are high. Just leave it alone. Seriously. topicproman: Hello... Your story sounds very similar to the way I first tried cocaine. I was a successful career guy as a creative professional in the TV business, and had never really used drugs. I tried it one night on a whim when a friend had some, and had a similarly incredible first-time experience. I had the same thoughts of "Wow, I see why people love this and get hooked. I won't do it any more though." Within a year I had become seriously addicted, depleted my savings account, run up several credit cards to the max, run from the cops while I was high, done a month in jail for evading arrest, had to move in with my parents, and lost my job and my career. The difficulty with addiction and drugs is... erez27: You seem very literate and self-conscious. Can you please describe the sensation with more detail? What kind of pleasure did you feel? How did it affect your state of mind and train of thought? Can you compare it to any familiar sensations (in quality, not intensity)? test450: Just wanted to let you know you sound exactly like I did when I first did dope. Same optimistic and sense of self control that us thrill seekers have. Smart enough to rationalize and study exactly what was going on. That was over $500,000 ago. I was a CIO and built a very successful company while hiding track marks. Eventually it all fell apart. I od'd several times and now I steal from my best friend and hate myself. dynamicinterface: hypothetically, if you were to become addicted, what would be the first thing you'd pawn off for money? hardman52: Heroin is not the most addictive drug. Most people I've known who've tried it didn't get addicted. Now speed-crank-meth, whatever you want to call it, THAT'S an instant addiction. All drugs are dangerous, and I don't know of anyone whose life was better by taking them. I say this having done drugs for 14 years when I was young. I've done LSD 400+ times, speed for a couple of years, and various other drugs, including heroin. I haven't done drugs for more than 30 years now, and if it were possible to go back and never to have done them, I would. I also think they should all be legal, except for speed, which causes violence. miasma66: Thanks for doing your best to combat the myth that you'll be ZOMG ADDICTED HOMELESS JUNKIE after one hit; it doesn't work that way. I've never done street heroin but I've experimented with plenty of similar drugs (particularly Oramorph, which is seriously good shit if you can get hold of it) to know what it'd be like. I can easily see how people get addicted to it though, it's one of the most intensely pleasurable experiences I've ever had I think, and I've tried a lot more than my fair share of drugs over the years. Definitely one for infrequent special occasions, isn't it! demogorgon: I have been a chronic pain patient for over 5 years. I get tons of opiates (hydromorphone) every week so I don't have much of a need to look for anything on the street, although I have always been curious about H. If I tried all I could get here would be some tar. My girlfriend (who also uses my reddit accounts) Is a recovering addict from heroin, and tells me again and again how H is a whole different game than my prescriptions. I don't doubt IV use is. It has caused some struggle, her being a recovering addict while I need to be on prescription opiates (which I do abuse sometimes...) anyways just thought I'd throw in a small part of my story. And by the way, given the chance I'd never hav... [deleted]: Try LSD. mind expanding, zero addiction, life changing. Pierce the illusion. coleman57: sheesh, sure are an awful lot of ninnies on this thread. i chased the dragon in amsterdam in 1987. after the hurling was over, the "i couldn't possibly care about anything" feeling kicked in, and i'll never forget it. someone could have told me my mother had just died a horrible death and i would have said "oh...that's too bad." really, it is another plane of existence. i can see why people who have chronic psychological or physical pain get addicted to it. i however, had something to live for, so i never did it again. but i don't regret it one bit, just like you. [deleted]: I'm seeing red flags all over your post, like this: &gt;I have the urge to do it again but I will resist and not do it, **at least not for a long time.** &gt;I actually **feel proud of myself** for having the balls to do something this crazy and I feel like it was a valuable life experience The problem with opiate addiction is that it creeps up on you in such a subtle way that you won't notice until you're already in deep. When you find yourself planning out a schedule for using, you're already in trouble. When you're thinking about how good it felt, you're already in trouble. When you'll never forget the day you first tried it, you're already in trouble. The only way to win is by not playi... qapmoc: Sounds a lot like morphine. I had my elbow crushed, collarbone broken and I was in the worst pain of my life.. But after a shot of morphine I felt the best I ever have. I would not be doing shit like that recreationally though. [deleted]: [deleted] 1234qwert: ....And so SpontaneousH turned half of reddit.com into heroin addicts with his story about a 8-10hr full body orgasm. nwootten: Was there a bad hangover? [deleted]: You are treading dangerous waters. (Obligatory warning) On to the questions: How often do you find yourself thinking about your experience since your use? Did you feel any negative effects stemming from your use? Physically/mentally? Why would you consider doing it again? As an experienced drug user you are showing signs that could lead you to addiction. Just be careful and do considerable research on what you're planning to do before you do it. Yeah I see you don't really want to be lectured about how it can ruin lives, but you really are messing with something that can kill you. I've had multiple friends OD and die using it. I went the other route, I chose cocaine. As a rule of thumb hero... joe12321: Just curious... I know you don't intend to do it again, but if by some wacky happenstance you run across someone who offers you heroin next week, are you sure you'd say no? [deleted]: &gt; Update 2: I don't regret this at all and I see a lot of talk about how cocaine isn't as bad as heroin and people telling anyone considering trying a hard drug to do coke instead. I've known and seen a lot of heavy coke users, many who have become addicted and ODed and I find it disturbing that people think coke is acceptable because some 'higher class' circles find it socially acceptable. That's the second mind-fuck when it comes to doing drugs in the US. You learn that racism/classism is at the very core of drug laws. The first mind-fuck, as I've said in another thread, is realizing you've been lied to so hard about how dangerous drugs are. Thanks for writing about your experience. I... scarrister: I think you have a masters in creative writing. philliez: Wow... now I'm tempted to do an IAMA for my meth years. One thing I don't get though: what's with the alternate accounts to admit things and answer questions? No reason to be so ashamed IMO pungen: thanks a lot for posting this. ive been offered heroin a bunch and would never try it, but i've always wondered what it was like from the perspective of a non-addict. just curious - a junkie i used to know told me people throw up right after they do heroin every time. did this happen to you? was the person lying? flixer: It's really stupid to do heroin alone, especially the first time. Don't do that again! People die! Trust me, I know. I used to do heroin 15 or so years ago; I loved it. So did my friends, some of whom are dead or brain-damaged from it now. I really think it's a dangerous drug. I'm all for legalizing EVERYTHING, but I really think that's one thing that's best avoided. Be careful, man. drgreedy911: If you use a needle it is even BETTER. Using heroin as a recreational drug is just such a great idea. [deleted]: [deleted] [deleted]: Did you remember the whole experience, or do you feel like you were unaware during most of it? Do you feel like you could have done anything besides sitting on the couch while doing it (reading, writing, solving the world's problems etc)? I have always been partial to psychedelics myself for the creativity/self discovery. whentoastersfly: So which is worse - heroin or Reddit? [deleted]: Didn't seeing how much the drug ruins lives in The Wire put you off instead of inspire you? AnythingApplied: The first time is always by far the best. Every other time is just trying to achieve the high of your first time trying it. You will never have that experience again, however hard you pursue it. heyzeuschristo: I have to agree with you, OP, the feeling of heroin is second to none. I had done a fair share of opiates in college. I started with crappy mid-grade weed in high school, eventually graduating to designer strains as a freshman in college. I soon found myself bored with weed, so while I continued to smoke it a ton, I also started to dabble in coke, hallucinogens, and opiates. Coke was never my thing, I don't like uppers. LSD and mushrooms were a joy, but is never something I have craved. Doing oxycontin for the first time was eye-opening. I was hanging with a neighbor late night one Saturday who offered me a 20mg to "chill out." I made the mistake of snorting it all within a few minutes. WOW... abuckley77: Whether you know it or not, whether you become addictted or not, you will be chasing that proverbial dragon for the rest of your life. I've seen it happen to so many kids i grew up with, who keep chasing that feeling or whatever it is happened to them when they did heroin or OCs. I myself have struggled through addiction in my teens. It might not even be drug related, but that physiological and psychological feeling will be something you try to mimic, it will be a driving force in your life. I hope these are all just assumptions, and i know that you have a great solid life, but that is what concerns me the most. You have so much to lose, please don't try it again, not even once. Magento: I'm not entierly sure how to phrase my question, so feel free to answer any way you like. Looking back at it, do you find heroin "boring"? I did opium in Thailand lots of years ago. Smoked a bunch and to me it was the least rewarding drug I've ever taken. Yes, I did get a pleasant feeling, but since I had already escaped all my troubles and was already in a happy state of mind it didn't change much for me. Smoking pot can make me raving mad, going into a full on psycosis, seeing god and solving world problems. Acid or stronger stuff I can't even touch because my brain is to fragile. Speed and coke just makes me "normal", but at least it gives me the feeling of having superpowers. Getting dr... american_idle: Fuck heroin. It's awesome. Too awesome. The only reason I stopped is because I lost two good friends to it. One died after an OD. The other is still alive, but he's all but a vegetable. He just started walking last year with the help of a walker. He still can't speak, shakes like he's got Parkinson's. (And this guy used to be a star 225lb wrestler in high school and college all paid for by a scholarship.) We were just kids having fun. Fuck heroin. (All of that happened in a month and I have to admit I still *want* it.) Smoke weed, drink, take shrooms, whatever. Have fun w/ all of that shit. But if I could give any advice to the curious it would be this: skip heroin and skip meth. Those are... IWillKickU: Dude, fuck all the haters. I find it inconcievable that the same community that rallies behind marijuana legalization, the Portugal drug approach, and Ron Paul, is now going "ZOMG DRUGS R BAD 4 U!" I say good foor you, for trying something new. Good for you for experiencing life. Obviously there are risks, but come the fuck on, we have a [whole subreddit](http://reddit.com/r/beer) for a drug that's more addictive than H, kills more people, leads to more criminal behavior, and takes more lives. All of you cautionary tales folks need to go there and post 57 comments in every thread warning them of alchohalism. I've never done H, or any drug harder than pot, but if I did and opened the floor f... cbranden: Your experience sounds just about like 
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): c49e9ae93f32941a9e38b2303231ce7ac4f236e3d67cff7f204391d55a931e8f
