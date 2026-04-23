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
mini_title: r/IndianStockMarket post intended to highlight disproportion
brief_summary: 'OP argued The original post intended to highlight the disproportionate
  influence of Rajkot. Many replies said Commenters widely acknowledged Rajkot as
  a major hub for stock and. Pushback included The IPO did not ''collapse'' but rather
  had a ''lukewarm. Context: The Reddit post was an uncredited copy of an article.'
tags:
- r-indianstockmarket
- hyundai-ipo
- rajkot-investors
- grey-market-premium
- ipo-valuation
- offer-for-sale
- indian-financial-markets
- market-sentiment
- due-diligence
- financial-journalism
detailed_summary:
- heading: op_intent
  bullets:
  - The original post intended to highlight the disproportionate influence of Rajkot
    investors on the Hyundai India IPO, alleging their disinterest led to its 'collapse'
    by dictating the Grey Market Premium (GMP). It also speculated that large players
    might have deliberately suppressed GMP to acquire shares at a lower valuation.
  sub_sections: {}
- heading: reply_clusters
  bullets:
  - '{"theme": "Rajkot''s Significant Role in Indian Financial Markets", "reasoning":
    "Commenters widely acknowledged Rajkot as a major hub for stock and commodity
    trading with a deep-rooted market culture dating back to the 1990s. Its investor
    community is considered to have a notable presence, with involvement comparable
    to Mumbai despite a smaller population.", "examples": ["Rajkot is India''s third-largest
    source of IPO applications.", "Major IPO roadshows specifically target Mumbai,
    Ahmedabad, and Rajkot.", "A Rajkot resident confirmed the general claims about
    the city''s influence."]}'
  - '{"theme": "Rajkot''s Grey Market and Regulatory Scrutiny", "reasoning": "The
    city has a high concentration of local brokers active in the grey market and unofficial
    ''dabba trading.'' This activity reportedly attracts significant regulatory scrutiny.",
    "examples": ["SEBI officials are often alleged to operate in plain clothes in
    the city due to this activity."]}'
  sub_sections: {}
- heading: counterarguments
  bullets:
  - The IPO did not 'collapse' but rather had a 'lukewarm reception.'
  - It is illogical that the third-largest city of applicants could have more impact
    than the top two cities.
  - The comparison to Waaree Energies IPO was flawed, as Waaree's GMP also fell from
    initial levels.
  - No official source was provided to substantiate the claim about city-wise IPO
    application rankings.
  - The Price-to-Earnings (P/E) ratio of 26x was considered expensive or 'generous'
    for an automobile company.
  - The IPO was a 100% Offer for Sale (OFS), meaning all proceeds went to the South
    Korean parent company, not for funding Hyundai India's growth.
  - Just before the IPO, Hyundai India paid large dividends to its parent, draining
    cash reserves.
  - Hyundai India increased the royalty percentage paid to its parent on revenue,
    negatively impacting future margins, leading to an effective P/E ratio of 27.5,
    unfavorable compared to Maruti.
  - Broader market sentiment was not favorable at the time.
  - Hyundai management became 'greedy,' increasing the final price and dampening initial
    enthusiasm.
  sub_sections: {}
- heading: unresolved_questions
  bullets:
  - Is there official data to substantiate city-wise IPO application rankings, particularly
    Rajkot's alleged position as the third-largest source?
  - What is the true extent of Rajkot investors' direct power to influence or 'collapse'
    major IPOs versus merely reflecting sentiment?
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
  total_tokens_used: 15042
  gemini_pro_tokens: 12782
  gemini_flash_tokens: 2260
  total_latency_ms: 87545
  cod_iterations_used: 2
  self_check_missing_count: 4
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: r/IndianStockMarket post intended to highlight disproportion
    brief_summary: 'OP argued The original post intended to highlight the disproportionate
      influence of Rajkot. Many replies said Commenters widely acknowledged Rajkot
      as a major hub for stock and. Pushback included The IPO did not ''collapse''
      but rather had a ''lukewarm. Context: The Reddit post was an uncredited copy
      of an article.'
    tags:
    - r-indianstockmarket
    - hyundai-ipo
    - rajkot-investors
    - grey-market-premium
    - ipo-valuation
    - offer-for-sale
    - indian-financial-markets
    - market-sentiment
    - due-diligence
    - financial-journalism
    detailed_summary:
      op_intent: The original post intended to highlight the disproportionate influence
        of Rajkot investors on the Hyundai India IPO, alleging their disinterest led
        to its 'collapse' by dictating the Grey Market Premium (GMP). It also speculated
        that large players might have deliberately suppressed GMP to acquire shares
        at a lower valuation.
      reply_clusters:
      - theme: Rajkot's Significant Role in Indian Financial Markets
        reasoning: Commenters widely acknowledged Rajkot as a major hub for stock
          and commodity trading with a deep-rooted market culture dating back to the
          1990s. Its investor community is considered to have a notable presence,
          with involvement comparable to Mumbai despite a smaller population.
        examples:
        - Rajkot is India's third-largest source of IPO applications.
        - Major IPO roadshows specifically target Mumbai, Ahmedabad, and Rajkot.
        - A Rajkot resident confirmed the general claims about the city's influence.
      - theme: Rajkot's Grey Market and Regulatory Scrutiny
        reasoning: The city has a high concentration of local brokers active in the
          grey market and unofficial 'dabba trading.' This activity reportedly attracts
          significant regulatory scrutiny.
        examples:
        - SEBI officials are often alleged to operate in plain clothes in the city
          due to this activity.
      counterarguments:
      - The IPO did not 'collapse' but rather had a 'lukewarm reception.'
      - It is illogical that the third-largest city of applicants could have more
        impact than the top two cities.
      - The comparison to Waaree Energies IPO was flawed, as Waaree's GMP also fell
        from initial levels.
      - No official source was provided to substantiate the claim about city-wise
        IPO application rankings.
      - The Price-to-Earnings (P/E) ratio of 26x was considered expensive or 'generous'
        for an automobile company.
      - The IPO was a 100% Offer for Sale (OFS), meaning all proceeds went to the
        South Korean parent company, not for funding Hyundai India's growth.
      - Just before the IPO, Hyundai India paid large dividends to its parent, draining
        cash reserves.
      - Hyundai India increased the royalty percentage paid to its parent on revenue,
        negatively impacting future margins, leading to an effective P/E ratio of
        27.5, unfavorable compared to Maruti.
      - Broader market sentiment was not favorable at the time.
      - Hyundai management became 'greedy,' increasing the final price and dampening
        initial enthusiasm.
      unresolved_questions:
      - Is there official data to substantiate city-wise IPO application rankings,
        particularly Rajkot's alleged position as the third-largest source?
      - What is the true extent of Rajkot investors' direct power to influence or
        'collapse' major IPOs versus merely reflecting sentiment?
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


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): e50d342f91b4fd1387a6bb37b1031b759b692de185b872316affd8fcfee8d386
