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
mini_title: r/IndianStockMarket Rajkot IPO influence debate
brief_summary: 'OP argued The central claim is that an IPO''s GMP will not. Many replies
  said There is general agreement that Rajkot has a deeply ingrained. The thread mostly
  converged on rajkot''s established market culture while gmp as a key retail. Pushback
  included The Hyundai IPO was considered expensive and was a. Context: Removed or
  missing comments may limit what is.'
tags:
- r-indianstockmarket
- ipo
- greymarket
- gmp
- investingbehavior
- india
- stockmarket
- valuation
- ofs
- duediligence
detailed_summary:
- heading: op_intent
  bullets:
  - 'The central claim is that an IPO''s GMP will not rise without interest from Rajkot''s
    grey market. The post cites two examples: 1. Hyundai IPO: Allegedly "collapsed"
    with a daily falling GMP due to a lack of interest from Rajkot investors. 2. Waaree
    Energies IPO: Allegedly saw a significant GMP increase driven by Rajkot''s interest.
    The author speculated, as a personal "hunch," that the low Hyundai GMP might have
    been a deliberate strategy by large players to acquire a fundamentally strong
    company at a lower valuation by suppressing retail competition.'
  sub_sections: {}
- heading: reply_clusters
  bullets:
  - '{"theme": "Rajkot''s Established Market Culture", "reasoning": "There is general
    agreement that Rajkot has a deeply ingrained stock market culture, serving as
    a major hub for local brokers, grey market activity, and \"dabba trading\" (unofficial
    trading). The Securities and Exchange Board of India (SEBI) is known to monitor
    the city.", "examples": []}'
  - '{"theme": "GMP as a Key Retail Decision Factor", "reasoning": "The premise that
    GMP is a highly influential factor for retail IPO applicants was undisputed.",
    "examples": []}'
  sub_sections: {}
- heading: counterarguments
  bullets:
  - The Hyundai IPO was considered expensive and was a 100% Offer For Sale (OFS),
    with no capital reinvested into the Indian business.
  - Prior to the IPO, Hyundai India drained cash reserves through dividends and increased
    royalty payments to its parent, leaving it with far lower cash (11,000 cr) than
    peers like Maruti (89,000 cr). One analysis calculated the true PE ratio was closer
    to 27.5 after accounting for the higher royalty.
  - A commenter directly refuted the Waaree Energies example, stating its GMP actually
    fell from initial levels due to poor market conditions, not rose significantly
    as claimed.
  - The broader market environment was not favorable at the time, and one user claimed
    Hyundai management became "too greedy and changed the price" to be higher than
    anticipated.
  - Skeptics questioned why the 3rd-ranked city for applications would wield more
    influence than the top two. The grey market's influence was also described as
    overstated due to its "shallow depth."
  - 'The source for the city-wise IPO application rankings was never provided. Critics
    noted that rank is misleading without knowing the absolute contribution in INR,
    as the gap between ranks #2 and #3 could be substantial.'
  - At least one user identifying as being from Rajkot stated, "I don't think this
    is true."
  sub_sections: {}
- heading: unresolved_questions
  bullets:
  - Why does Rajkot, as the alleged 3rd-ranked city for IPO applications, supposedly
    wield more influence than the top two cities?
  - What is the absolute INR contribution of Rajkot's IPO applications, and how does
    it compare to other major cities?
  - What is the actual depth and overall influence of the grey market on IPO pricing
    and retail investor behavior?
  - Was the low Hyundai GMP a deliberate strategy by large players to acquire the
    company at a lower valuation by suppressing retail competition, as speculated?
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
  total_tokens_used: 15667
  gemini_pro_tokens: 13396
  gemini_flash_tokens: 2271
  total_latency_ms: 91541
  cod_iterations_used: 2
  self_check_missing_count: 3
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: r/IndianStockMarket Rajkot IPO influence debate
    brief_summary: 'OP argued The central claim is that an IPO''s GMP will not. Many
      replies said There is general agreement that Rajkot has a deeply ingrained.
      The thread mostly converged on rajkot''s established market culture while gmp
      as a key retail. Pushback included The Hyundai IPO was considered expensive
      and was a. Context: Removed or missing comments may limit what is.'
    tags:
    - r-indianstockmarket
    - ipo
    - greymarket
    - gmp
    - investingbehavior
    - india
    - stockmarket
    - valuation
    - ofs
    - duediligence
    detailed_summary:
      op_intent: 'The central claim is that an IPO''s GMP will not rise without interest
        from Rajkot''s grey market. The post cites two examples: 1. Hyundai IPO: Allegedly
        "collapsed" with a daily falling GMP due to a lack of interest from Rajkot
        investors. 2. Waaree Energies IPO: Allegedly saw a significant GMP increase
        driven by Rajkot''s interest. The author speculated, as a personal "hunch,"
        that the low Hyundai GMP might have been a deliberate strategy by large players
        to acquire a fundamentally strong company at a lower valuation by suppressing
        retail competition.'
      reply_clusters:
      - theme: Rajkot's Established Market Culture
        reasoning: There is general agreement that Rajkot has a deeply ingrained stock
          market culture, serving as a major hub for local brokers, grey market activity,
          and "dabba trading" (unofficial trading). The Securities and Exchange Board
          of India (SEBI) is known to monitor the city.
        examples: []
      - theme: GMP as a Key Retail Decision Factor
        reasoning: The premise that GMP is a highly influential factor for retail
          IPO applicants was undisputed.
        examples: []
      counterarguments:
      - The Hyundai IPO was considered expensive and was a 100% Offer For Sale (OFS),
        with no capital reinvested into the Indian business.
      - Prior to the IPO, Hyundai India drained cash reserves through dividends and
        increased royalty payments to its parent, leaving it with far lower cash (11,000
        cr) than peers like Maruti (89,000 cr). One analysis calculated the true PE
        ratio was closer to 27.5 after accounting for the higher royalty.
      - A commenter directly refuted the Waaree Energies example, stating its GMP
        actually fell from initial levels due to poor market conditions, not rose
        significantly as claimed.
      - The broader market environment was not favorable at the time, and one user
        claimed Hyundai management became "too greedy and changed the price" to be
        higher than anticipated.
      - Skeptics questioned why the 3rd-ranked city for applications would wield more
        influence than the top two. The grey market's influence was also described
        as overstated due to its "shallow depth."
      - 'The source for the city-wise IPO application rankings was never provided.
        Critics noted that rank is misleading without knowing the absolute contribution
        in INR, as the gap between ranks #2 and #3 could be substantial.'
      - At least one user identifying as being from Rajkot stated, "I don't think
        this is true."
      unresolved_questions:
      - Why does Rajkot, as the alleged 3rd-ranked city for IPO applications, supposedly
        wield more influence than the top two cities?
      - What is the absolute INR contribution of Rajkot's IPO applications, and how
        does it compare to other major cities?
      - What is the actual depth and overall influence of the grey market on IPO pricing
        and retail investor behavior?
      - Was the low Hyundai GMP a deliberate strategy by large players to acquire
        the company at a lower valuation by suppressing retail competition, as speculated?
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
mini_title: r/IAmA first-time heroin risks
brief_summary: OP argued To document a first-time heroin experience, driven by boredom
  and. Many replies said The majority of responses came from former opiate addicts
  who. The thread mostly converged on warnings of inevitable addiction while addiction
  is not guaranteed. Pushback included Addiction is not guaranteed; some individuals
  use heroin infrequently.
tags:
- r-iama
- heroin
- addiction
- opiates
- risk-perception
- drug-culture
- reddit
- classism
- harm-reduction
- experience-report
detailed_summary:
- heading: op_intent
  bullets:
  - To document a first-time heroin experience, driven by boredom and media intrigue,
    while asserting perceived control over addiction and challenging societal distinctions
    between drugs like heroin and cocaine based on classism.
  sub_sections: {}
- heading: reply_clusters
  bullets:
  - '{"theme": "Warnings of Inevitable Addiction", "reasoning": "The majority of responses
    came from former opiate addicts who stated the user''s narrative of self-control
    and rationalization was identical to their own before addiction. This mindset
    was identified as a classic precursor to dependency. Commenters warned that opiate
    addiction ''creeps up on you,'' with red flags including planning future use,
    romanticizing the first high, and feeling pride. The first high is often unrepeatable
    (''chasing the dragon''), and withdrawal was described as ''pure hell''.", "examples":
    ["One former CIO cited spending over $500,000 on his habit.", "Another user lost
    his career and was jailed after trying cocaine on a whim.", "Heroin withdrawal
    was described as ''pure hell'' and ''the most terrible thing in this world''."]}'
  - '{"theme": "Addiction is Not Guaranteed", "reasoning": "A minority view challenged
    the inevitability of addiction, citing personal experiences and relative risks.
    Some users reported using heroin or powerful opiates once or infrequently without
    developing dependency, with one citing a 1987 experience in Amsterdam. Others
    criticized the community for lecturing the user while broadly supporting drug
    legalization, noting legal alcohol is more addictive and deadly.", "examples":
    ["A user with 14 years of drug experience argued that methamphetamine is ''an
    instant addiction,'' whereas most people they knew who tried heroin did not become
    addicted.", "One user cited a 1987 experience in Amsterdam, after which they never
    used again."]}'
  sub_sections: {}
- heading: counterarguments
  bullets:
  - Addiction is not guaranteed; some individuals use heroin infrequently without
    dependency.
  - Methamphetamine is considered more instantly addictive than heroin by some experienced
    users.
  - Community criticism of the user is hypocritical given support for drug legalization
    and the known dangers of legal substances like alcohol.
  sub_sections: {}
- heading: unresolved_questions
  bullets:
  - Is the original poster's account of their first heroin experience authentic?
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
  total_tokens_used: 20381
  gemini_pro_tokens: 18273
  gemini_flash_tokens: 2108
  total_latency_ms: 109834
  cod_iterations_used: 2
  self_check_missing_count: 4
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: r/IAmA first-time heroin risks
    brief_summary: OP argued To document a first-time heroin experience, driven by
      boredom and. Many replies said The majority of responses came from former opiate
      addicts who. The thread mostly converged on warnings of inevitable addiction
      while addiction is not guaranteed. Pushback included Addiction is not guaranteed;
      some individuals use heroin infrequently.
    tags:
    - r-iama
    - heroin
    - addiction
    - opiates
    - risk-perception
    - drug-culture
    - reddit
    - classism
    - harm-reduction
    - experience-report
    detailed_summary:
      op_intent: To document a first-time heroin experience, driven by boredom and
        media intrigue, while asserting perceived control over addiction and challenging
        societal distinctions between drugs like heroin and cocaine based on classism.
      reply_clusters:
      - theme: Warnings of Inevitable Addiction
        reasoning: The majority of responses came from former opiate addicts who stated
          the user's narrative of self-control and rationalization was identical to
          their own before addiction. This mindset was identified as a classic precursor
          to dependency. Commenters warned that opiate addiction 'creeps up on you,'
          with red flags including planning future use, romanticizing the first high,
          and feeling pride. The first high is often unrepeatable ('chasing the dragon'),
          and withdrawal was described as 'pure hell'.
        examples:
        - One former CIO cited spending over $500,000 on his habit.
        - Another user lost his career and was jailed after trying cocaine on a whim.
        - Heroin withdrawal was described as 'pure hell' and 'the most terrible thing
          in this world'.
      - theme: Addiction is Not Guaranteed
        reasoning: A minority view challenged the inevitability of addiction, citing
          personal experiences and relative risks. Some users reported using heroin
          or powerful opiates once or infrequently without developing dependency,
          with one citing a 1987 experience in Amsterdam. Others criticized the community
          for lecturing the user while broadly supporting drug legalization, noting
          legal alcohol is more addictive and deadly.
        examples:
        - A user with 14 years of drug experience argued that methamphetamine is 'an
          instant addiction,' whereas most people they knew who tried heroin did not
          become addicted.
        - One user cited a 1987 experience in Amsterdam, after which they never used
          again.
      counterarguments:
      - Addiction is not guaranteed; some individuals use heroin infrequently without
        dependency.
      - Methamphetamine is considered more instantly addictive than heroin by some
        experienced users.
      - Community criticism of the user is hypocritical given support for drug legalization
        and the known dangers of legal substances like alcohol.
      unresolved_questions:
      - Is the original poster's account of their first heroin experience authentic?
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


## URL 3: https://www.reddit.com/r/IAmA/comments/9ohdc/2_weeks_ago_i_tried_heroin_once_for_fun_and_made/

### SUMMARY
```yaml
mini_title: r/IAmA first-time heroin risks
brief_summary: OP argued To document a rapid descent into heroin addiction, share
  the. Many replies said Community members, including experienced users and recovering
  addicts, expressed alarm. The thread mostly converged on alarm and warning of predictable
  addiction trajectory while post as. Pushback included A significant portion of the
  community accused the poster.
tags:
- r-iama
- heroin-addiction
- drug-abuse
- iv-drug-use
- withdrawal
- relapse
- community-support
- harm-reduction
- cautionary-tale
- mental-health
detailed_summary:
- heading: op_intent
  bullets:
  - To document a rapid descent into heroin addiction, share the immediate consequences
    including a transition to IV use, and express internal conflict and suicidal ideation
    while seeking community engagement.
  sub_sections: {}
- heading: reply_clusters
  bullets:
  - '{"theme": "Alarm and Warning of Predictable Addiction Trajectory", "reasoning":
    "Community members, including experienced users and recovering addicts, expressed
    alarm and warned the poster about the well-known, destructive path of heroin addiction,
    emphasizing its rapid control and severe withdrawal symptoms.", "examples": ["Experienced
    users, including an IV morphine addict and a 5-year recovering heroin addict,
    warned the poster was on a well-known path to losing everything.", "Withdrawal
    was described as ''the high, but turned inside out.''", "Commenter `swac` observed
    the poster had been using for 11 consecutive hours while replying to comments,
    highlighting the drug''s immediate control."]}'
  - '{"theme": "Post as a Cautionary Tale", "reasoning": "Many readers found the post
    served as a powerful deterrent, eliminating their curiosity about heroin and reinforcing
    its destructive potential through shared anecdotes of ruined lives and long-term
    health consequences.", "examples": ["Many readers stated the post eliminated their
    curiosity about heroin.", "User `focks` shared the story of ''Jaime,'' a promising
    16-year-old whose life was destroyed by the drug.", "Another commenter told of
    their father, who got clean but later died from long-term health complications
    (hepatitis) related to his years of use, which had also led to homelessness and
    jail time."]}'
  - '{"theme": "Analysis of Poster''s Motivation and Attention-Seeking", "reasoning":
    "A commenter questioned if the online attention the poster was receiving was part
    of the drug''s appeal, suggesting a potential shift from seeking attention to
    further degradation.", "examples": ["A commenter questioned if the online attention
    was part of the drug''s appeal, warning the poster could go from an ''attention
    whore to regular whore.''"]}'
  sub_sections: {}
- heading: counterarguments
  bullets:
  - A significant portion of the community accused the poster of fabricating the story
    for attention, prompting the photo evidence.
  - One user (`HyperSpaz`) decided to treat the post as a troll's to manage their
    own emotional response.
  - One commenter suggested the girlfriend's decision to leave indicated she might
    not be a suitable partner, as crises reveal character.
  - User `hajk` shared an anecdote of a city architect who was a functional addict,
    claiming that by using a clean supply and gear, the architect's life expectancy
    was only reduced by a few years, a risk they compared to tobacco use.
  sub_sections: {}
- heading: unresolved_questions
  bullets:
  - What was the ultimate outcome of the poster's recovery attempts and long-term
    well-being?
  - To what extent is the 'functional addict' anecdote presented by `hajk` generalizable
    or representative of heroin use?
  - What were the long-term psychological impacts of documenting such a rapid descent
    into addiction publicly on the poster's recovery and identity?
  sub_sections: {}
- heading: moderation_context
  bullets:
  - Rendered comments covered only part of the thread (114/1005 visible; divergence
    88.66%). 21 removed comments were recovered from pullpush.io.
  sub_sections: {}
metadata:
  source_type: reddit
  url: https://www.reddit.com/r/IAmA/comments/9ohdc/2_weeks_ago_i_tried_heroin_once_for_fun_and_made
  author: SpontaneousH
  date: null
  extraction_confidence: high
  confidence_reason: json endpoint ok; rendered=114/1005 divergence=88.66%
  total_tokens_used: 24241
  gemini_pro_tokens: 21850
  gemini_flash_tokens: 2391
  total_latency_ms: 101998
  cod_iterations_used: 2
  self_check_missing_count: 4
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: r/IAmA first-time heroin risks
    brief_summary: OP argued To document a rapid descent into heroin addiction, share
      the. Many replies said Community members, including experienced users and recovering
      addicts, expressed alarm. The thread mostly converged on alarm and warning of
      predictable addiction trajectory while post as. Pushback included A significant
      portion of the community accused the poster.
    tags:
    - r-iama
    - heroin-addiction
    - drug-abuse
    - iv-drug-use
    - withdrawal
    - relapse
    - community-support
    - harm-reduction
    - cautionary-tale
    - mental-health
    detailed_summary:
      op_intent: To document a rapid descent into heroin addiction, share the immediate
        consequences including a transition to IV use, and express internal conflict
        and suicidal ideation while seeking community engagement.
      reply_clusters:
      - theme: Alarm and Warning of Predictable Addiction Trajectory
        reasoning: Community members, including experienced users and recovering addicts,
          expressed alarm and warned the poster about the well-known, destructive
          path of heroin addiction, emphasizing its rapid control and severe withdrawal
          symptoms.
        examples:
        - Experienced users, including an IV morphine addict and a 5-year recovering
          heroin addict, warned the poster was on a well-known path to losing everything.
        - Withdrawal was described as 'the high, but turned inside out.'
        - Commenter `swac` observed the poster had been using for 11 consecutive hours
          while replying to comments, highlighting the drug's immediate control.
      - theme: Post as a Cautionary Tale
        reasoning: Many readers found the post served as a powerful deterrent, eliminating
          their curiosity about heroin and reinforcing its destructive potential through
          shared anecdotes of ruined lives and long-term health consequences.
        examples:
        - Many readers stated the post eliminated their curiosity about heroin.
        - User `focks` shared the story of 'Jaime,' a promising 16-year-old whose
          life was destroyed by the drug.
        - Another commenter told of their father, who got clean but later died from
          long-term health complications (hepatitis) related to his years of use,
          which had also led to homelessness and jail time.
      - theme: Analysis of Poster's Motivation and Attention-Seeking
        reasoning: A commenter questioned if the online attention the poster was receiving
          was part of the drug's appeal, suggesting a potential shift from seeking
          attention to further degradation.
        examples:
        - A commenter questioned if the online attention was part of the drug's appeal,
          warning the poster could go from an 'attention whore to regular whore.'
      counterarguments:
      - A significant portion of the community accused the poster of fabricating the
        story for attention, prompting the photo evidence.
      - One user (`HyperSpaz`) decided to treat the post as a troll's to manage their
        own emotional response.
      - One commenter suggested the girlfriend's decision to leave indicated she might
        not be a suitable partner, as crises reveal character.
      - User `hajk` shared an anecdote of a city architect who was a functional addict,
        claiming that by using a clean supply and gear, the architect's life expectancy
        was only reduced by a few years, a risk they compared to tobacco use.
      unresolved_questions:
      - What was the ultimate outcome of the poster's recovery attempts and long-term
        well-being?
      - To what extent is the 'functional addict' anecdote presented by `hajk` generalizable
        or representative of heroin use?
      - What were the long-term psychological impacts of documenting such a rapid
        descent into addiction publicly on the poster's recovery and identity?
      moderation_context: Rendered comments covered only part of the thread (114/1005
        visible; divergence 88.66%). 21 removed comments were recovered from pullpush.io.
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Post
2 weeks ago I tried heroin 'once for fun' and made an AMA, I have been using since and shot up for the first time today, AMA Weds night update: fucking I;m still withdrawling throwing up and sweating out gallons of sweat. i really want to use and relapse right now, I know i shouldn't. these urges are so strong and overpowering. Please help me if you can before I get the chance to. **1000 comment update:** **Fuck my life. I wish I was trolling and this was all some elaborate lie.** I was doing everything right, have been clean, and somehow a rumor got out that Ive been using and my girlfriend found out and she basically broke up with me last night but is now putting that decision on hold. I have some serious unrelated business/work I need to attend to in two hours and I don't know if I'll be in any state to be able to and be ready. I can't stop crying. Fuck heroin. Fuck my life. I guess I don't need to say that since heroin pretty much fucked my life for me in under two weeks, I just want to die. **NA UPDATE** Went to NA, I shared my story and it seemed to hit a lot of people, I cried, I got a lot of support and numbers and feel like I'm in a good place and truly believe I never have to use again. I will be going back. Update #whatever: I slept for about 30 hours, sweat out my entire body and now I feel ok. I also took a shit for the first time in like a week which was pretty awesome. I can stop this on my own, I don't even think I need NA but I'm not ruling it out, I have no craving or desire to do heroin. I'm sure some of you will be quick to say I need real support and maybe you're right, but right now I think I'll be ok. New update: i appreciate all the genuine concern adn advice. I finished my stash (bad idea but too late), threw out my needles, and am too faded to respond to comments for now. When I sober up in a couple hours I'll check out some NA meetings. **EDIT:** I nodded off after taking another hit at 4AM and couldn't be bothered to look at this anymore and just woke up sore with a headache. For those of you who think I'm a troll because I can do heroin and type well with good grammar, fuck off. It's not that hard if you type slowly and carefully without looking at the screen (the screen is a blur and too bright) and it's challenging but I would rather post coherently than like an idiot, I know it's hard to believe someone dumb enough to do heroin is 'intelligent' in other regards. Comments disintegrated into mindless bandwagon accusations of being a troll, I wanted to engage in a discussion and know I need help and my mind isn't exactly right. I'll sift through the posts and respond to the genuine ones once I feel better. **[For people calling fake is this enough proof for you?](http://imgur.com/7KOrf.jpg) Do you want to see my track marks too? They're not pretty and this is under 24 hours after first shooting up. I'm not proud of any of this and posted it here because I can't tell anyone in my life and don't want to keep it to myself. I figured doing another IAMA would give me the opportunity to talk about my issues anonymously and help realize the extent of my problem through feedback, the assholes saying this is all fake trolling can fuck themselves. People can post about being prostitutes and all sorts of things that harm a large number of other people but dismiss someone on the track to becoming an addict who needs help and just wants to talk and maybe help some other people form making the same mistakes.** I appreciate the people giving legitimate advice and asking questions. I'm going to the next NA meeting I can find.... ================================================================================ I know there will be a lot of people telling me 'I told you so' and urging me to seek help, and they are right. That's all good and trust me I know the danger I am in of ruining my life but **let's please keep this an AMA first and foremost.** I will be checking out an NA meeting this week and I know I am on a fast track to becoming an addict and I want to stop it before it gets out of control and I'm physically addicted. No one in my life can know about this and I want to stop before it is too late I have been using for 2-3 day periods then taking a couple days off then using again. The breaks were in part to try not to get hooked and in part because I had an unreliable dealer who charged me more than double what I should be paying. I got ripped off several times when I tried to buy off the street (my former dealer is the guy who I first bought from). Today I met a guy through some internet channels who said he could get bundles (10 small bags of heroin) for significantly less than half the price my old dealer gave me on his 'most fair' deal. He also happened to be an IV user and had a stash of sealed needles and supplies and offered to shoot me up. I had kind of hoped I would find someone who would and he was a pro finding my small hidden veins and injecting a bag in one shot. To quote trainspotting "Take the best orgasm you've ever had, multiply by 1000, and you're still nowhere near it." He gave me some new needles and tourniquets and when I got home I tried to do it myself. After not hitting a vein countless times I finally got a red flag and was good to go. I have injected 5 bags since 4pm, the last one a little less than an hour ago and am tempted to do one more. AMA. Forgive me for any delays if I nod off... https://www.reddit.com/r/IAmA/comments/9ohdc/2_weeks_ago_i_tried_heroin_once_for_fun_and_made/

Comments
lebalove: oh, dear. i'm an IV morphine addict, so i know where you're coming from. in my opinion, there's no going back now. you're going to be in for one hell of a ride. so you found heroin. you know you like it. hell, you love it. like the chase, like the catch, like the high. opiates are like kissing god. and once you have tried them, there's no going back. if you don't clean up now, or clean up soon (within a month), this is what you can expect. * after a few days of continuous use, you will become physically dependent. the withdrawals from opiates are like the high, but turned inside out. imagine how much pleasure you get when you push the plunger all the way down, and you feel the smack hit you... [deleted]: My question is how strong are you? The way you talk about it I think she has you already, a heroin addiction can be beaten but it depends on luck and strength. I used heroin 10 years ago, daily for a period of 2 years. I loved it. I wouldn't be surprised if I have a taste once or twice more in my life, or some equivalent experience, I have a hankering to smoke some opium at some point. Anyway, as we all know heroin is a dangerous drug and vastly more dangerous if you are a noob. For example while I was learning the ropes I overdosed 4 times. Fortunately I always used with others at the beginning, they all knew cpr and we all kept an eye on one another. Another thing I had going for me was o... [deleted]: Didn't you say you weren't going to use again? For awhile? What changed your mind? Is this alarming? Have you told your friends/family? FWIW, seeing your followup AMA is heart-breaking. I identified with your first one since it reminded me of the first time I did coke, including having to bear similar criticism from friends/family. But I hadn't used again for weeks, and the last time I did it was nearly a month ago. The contrast is interesting. I assumed heroin would be the same. Followup AMA implies not. Or that we're different people. Or that you're in a more vulnerable place. Maybe the difference is that I'm discussing my drug use with everyone around me, it's not this dirty secret and t... Squibbles1077: I saw you're first post and honestly, it made me want to try heroin, but I knew better. Now I'm seeing this post and I'm close to tears. Please, for your own good, get help. This is some serious shit that you're in to. frozentoad: No verbal assaults from me, you've made a decision that you'll have to live with. I hope you're ok and can get free of heroin. knottyrye: I have to say I'm really deeply saddened and moved by this AMA...I followed your last one and have thought about you many times since then. My Dad was addicted to heroin for years when he was in his late teens. He went to jail, lost everything and was homeless before he met my Mom. He straightened his life out and gave up everything (alcohol, drugs, etc) before I was born. My Dad was the best person I ever knew and worked daily to fight his addictions. I am sure of this even though I was too young to understand the extent of what he went through. He chose to quit and he did - never looked back. But it was too late. On my 10th birthday my parents sat us down to tell us that my Dad had all fo... gecker: This is such an intense story. I just feel like I should tell you that this is not forgettable, and it cannot be read without taking something without me taking something from it. followthesinner: Do you think it would be less of a rush for you if you weren't getting all this attention online? If you get hooked you might easily go from attention whore to regular whore. [deleted]: Somehow I can't stop thinking about you and coming back to this thread. How have you been doing? hellafun: Why did you do it a second time? Surely your body had the desire but hadn't yet developed a real physical dependency, at least not on the scale it sounds like you're trying to foster now... why did you choose to walk down this path? [deleted]: [deleted] [deleted]: [deleted] [deleted]: &gt; Weds night update: fucking I;m still withdrawling throwing up and sweating out gallons of sweat. i really want to use and relapse right now, I know i shouldn't. these urges are so strong and overpowering. Please help me if you can before I get the chance to. No one can stop you from relapsing except yourself. I can only repeat myself: IT WILL GET BETTER! This is the easiest chance for withdrawal you'll ever get. [How strong are you?](http://www.reddit.com/r/IAmA/comments/9ohdc/2_weeks_ago_i_tried_heroin_once_for_fun_and_made/c0dnfmq) You said that there are NA meetings all day and night, go there! Or have you already relapsed? Good luck! (Fearing the worst and hoping for the best.) kwiztas: quit now from a 5 year heroin addict who quit. QUIT NOW PLEASE trimalchio: If the internet thinks its a bad idea, it might be a really fucking bad idea. [deleted]: I'm upvoting this so others can learn not to be so stupid. [deleted]: &gt; my girlfriend found out and she basically broke up with me last night but is now putting that decision on hold You sound very sorry for yourself and this is going to color your perception of events. Here's how I see it: If she can abandon you at a time like this maybe she's not the girl of your dreams. Part of being human is feeling fear, and part of dealing with fear means we sometimes hurt those around us. Most reasonable people know this and will forgive and forget. An apology should be enough. If not, maybe it's not such a bad thing that she's exiting your life. An event like this makes the house of cards collapse. Everyone shows their true colors, everything gets re-priced. You'll... [deleted]: [deleted] Gadianton: Wow, I read your first thread and was wondering what was going on with you a couple of days ago. I'm glad you say you are going to NA tonight and have quit. Also good that you deleted your dealer's numbers. You should have blocked them though, because they may try calling you. I really hope you follow through with NA. Frankly, if I were you I'd take 2 weeks off my job immediately and go to the best facility I could right away. I know you think you can save money and/or do it alone. But you have to be honest, you made quite a few promises in your last thread that you weren't able to keep. You haven't hit the real test of your willpower yet. Scientific studies have shown that humans constantl... shafir: Damn man. Obviously the stupidest fucking thing you've done in your life. But I want to thank you for posting this on Reddit. I know hundreds, thousands, millions of people do heroin, but I've never actually realized how one gets hooked, and how scary it is. There goes any thought of me trying it. Ever Thank you, and I hope you work things out. Tell someone that cares about you, please, do it for yourself. Stop worrying about other people knowing, and focus on getting rid of the fucking habit [deleted]: [deleted] Ashiro: For starters I suggest you read up on it at Erowid for a few hours. The worst thing you can do is to state you're getting addicted to something. You're basically relinquishing power of your own decisions to a drug when you say you're addicted. You're making it more concrete. So research, read and digest all the facts you can about heroin. Turn it into a science project and know the drug inside-out. It'll empower you to make the right decisions. focks: Let me tell you a little story about a girl named Jaime. Jaime was 16, drop-dead gorgeous, and on top of the world. She had a great relationship with someone she really cared about, she had a great job helping with the community, and was on the honour roll at her high school. Jaime wasn't a shy girl by any means; very outspoken. Needless to say, she got along with anyone she ever met. Jaime grew up with a semi-religious family with specific views on certain subjects. Her parents taught her the difference between right and wrong, and how being a homosexual is wrong. Jaime understood and lived by those principles/rules/bullshit for nearly her entire life. Then she met a girl and fell in love.... masharunya: Okay, inspired by the story about Jaime, I've decided to share a story about one my patients. It's pretty damn graphic, so I apologize in advance. It was my second quarter of nursing school and our clinical was at the county hospital. My patient was a 60+ year old man, homeless for about half of those years. Very underweight, labs showed severe malnutrition and rampant infection. He was covered in old scars (a strange large "dent" near his sternum was notable) and had an old, poorly set bone break (the bone protruded in a bump on his shin, thinly covered in skin). His liver and kidneys were a mess. He'd been found delirious with fever on the street and brought into the ER. The source of the... spatulahead: Hey there, how are you doing? demlog: Dammit, not only are you about to destroy your life but now you are single-handedly responsible for far too many lost hours of my life reading about this trainwreck. There goes any interest (if any) interest I had lingering to experience heroin. swac: This is going to sound rude, but you seem to be heavily downplaying the drug's control over you in all of your replies. You've been sitting at home doing heroin for the last 11 hours, dude. [deleted]: Do you think it is possible for anyone to try heroin once and not get hooked? [deleted]: whoah.. dude. watch requiem of a dream and it will scare you sober. [deleted]: [deleted] tuna_safe_dolphin: In case it isn't clear, you're a junkie. It's been fun reading your last AMA. . . mvoccaus: If I may be philosophical for a moment... Life is all about novelty. It's the novelty of our experiences that make life worth living. You'll remember your whole life who your first crush was, how exciting it was to drive a car the first time, or getting drunk, or getting lucky with that beautiful girl. But the novelty of any experience will wear out after it's been repeated too much. I wish driving my car each day to work could be as exciting as the first time I got behind the wheel, but it's not. The toys from when I was a kid can't keep my attention any more. The songs I have on my iPod have played themselves too many times. But, and listen, because this is important, there are other song... [deleted]: [deleted] hajk: I knew a doctor who looked after drug addicts. One of his patients was prominent city architect. The guy was definitely an addict but he managed his habit and because he managed was able to work and afford the best stuff. Current research indicates that his patient will probably die a few years before someone else, in other words with a clean supply (and gear) it may be considered medically less dangerous than tobacco. [deleted]: Maybe I should look this up, and this probably isn't a question you would expect, but...can you take me through the process of how you're 'shooting up' ? [deleted]: Not sure if you answered this in your other AMA, but do you have a job? How is this new habit affecting that part of your life? [deleted]: Right, so, here's my question: Are you willing to leave at least some sort of contact information for us, assuming you're genuine? [deleted]: Hey man, I have no experience with heroin other than my cousin got hooked and stole stuff from my house and from my uncle. He's in prison now. Clean up before you damage more lives than your own. Being that high isn't worth the collateral damage. Start trying to find some awesome pot (ever try Alaskan?) instead of heroin. Oh yeah, I did nearly get hooked on vicodin once - I guess vicodin is sort of a lesser cousin of heroin. Nice feeling, but once it felt like I needed more to feel the same high, I stopped entirely. To all the people on here crying troll, just stop. There is nothing to be gained from that sort of crap. This guy MIGHT be a troll, BUT he also might be dead serious. Giving som... [deleted]: STOP please HyperSpaz: I give up. I will treat the poster as a troll forthwith, regardless of the truth, whether he is a troll. The emotional distress is too great. booklaptopsoda: &gt;I have injected 5 bags since 4pm, the last one a little less than an hour ago and am tempted to do one more. Holy shit dude! You are going to die! fluff_mcfuck: I want to see your track marks. btw, nice laptop. How long do you think it will be before you sell it for a bag of brown? UniQueLyEviL: Best of luck getting far *far* the fuck away from it. Please run as fast as you can...before it turns you into a monster... DCMurphy: Everyone here is begging you to stop, but I'm not going to preach and tell you to stop. Addictive personalities are not really a choice, but are instead a propensity to keep doing what feels good in a very Hedonistic manner. To be perfectly and brutally honest, it's not you that you're hurting the most. Heroin is on my big 3 "do not do" list, along with Crystal Meth and Crack Cocaine. And now that you've shot up, especially since you've shot up, you're on the slipperiest slope imaginable. If you have any children or anyone who depends on you, you're just screwing them over. I'm not going to get into personal details here but heroin has already fucked with my life enough to know that, and I... withnailandI: Enjoy it. Kicking it after addiction is hell on fucking earth. Imagine wanting to blow your brains out. Then multiply that times 1000. (Some people like Kurt Cobain *would* rather blow their brains out than live without. If you keep using you're going to know exactly how he felt. Fun fun fun.) Araya213: Are you aware that what you're doing is incredibly fucking stupid. Get help now, real help, not NA. Check yourself into a rehab center and get it out of your system. [deleted]: [deleted] [deleted]: [deleted] Crizack: This is a covert D.A.R.E. campaign. EvolutionTheory: I was just linked to this thread from another where someone asked what heroine felt like. I am amazingly grateful for finding this. When I read your first IAmA "SpontaneousH" you sounded exactly like I think I would if I first tried it. Then, to see your later responses of being addicted I had to do a literal double take. You were completely rational and I was leaning towards trying it but to see this history occur with you is truly frightening. Your posts may have saved my life. I think what really touches home is the apparent and assumed intelligence and education you have. It's easy to dismiss the writings of some uneducat
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): c977365ab16c9916616c2d425c6b16177807bceb9d36d32f275c320a1515308b
