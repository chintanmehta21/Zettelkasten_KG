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
## URL 1: https://www.youtube.com/watch?v=CtrhU7GOjOg

### SUMMARY
```yaml
mini_title: Petrodollar s Decline US Dominance
brief_summary: This lecture explores the potential decline of the petrodollar system
  and its implications for U. S. Global dominance. An The speaker outlines a hypothetical
  scenario where geopolitical shifts and perceived U. S. Security failures lead Gulf
  States to challenge the dollar's role in oil trade. The presentation details the
  petrodollar's historical context, the Gulf States' economic diversification, and
  the leverage they hold through oil production.
tags:
- lecture
- petrodollar
- geopolitics
- us-economy
- china-trade
- oil-market
- reserve-currency
- middle-east
- financial-system
- global-dominance
detailed_summary:
- heading: Overview
  bullets:
  - This lecture explores the potential decline of the petrodollar system and its
    implications for U.
  sub_sections:
    Format and speakers:
    - 'Format: lecture.'
    - 'Speakers: Strait of Hormuz.'
    Core argument:
    - The petrodollar system, a 50-year-old agreement underpinning U.S. economic dominance,
      is vulnerable to a "slow bleed" due to shifting geopolitical alliances and perceived
      U.S. security failures, potentially ending American global financial supremacy.
- heading: Chapter walkthrough
  bullets: []
  sub_sections:
    Challenging the Petrodollar System:
    - A hypothetical scenario on March 15, 2026, depicts a Pakistani tanker, the Karachi,
      trading oil in Chinese yuan through the Strait of Hormuz.
    - This scenario directly challenges the petrodollar system, a 50-year agreement
      where six Gulf States sell oil in U.S. dollars.
    - In exchange for dollar-denominated oil sales, the U.S. provides military protection
      to these Gulf States.
    - This arrangement has historically underpinned the U.S. economy and its global
      financial leverage.
    - The hypothetical conflict involves the U.S. and Israel eliminating Iran's supreme
      leader, leading to regional attacks.
    - These attacks cause Gulf States to perceive the U.S. security guarantees as
      failing, undermining the petrodollar bargain.
    - The potential end of the petrodollar is presented as a "slow bleed" rather than
      an immediate collapse, threatening U.S. global dominance.
    Historical Context and Regional Transformation:
    - Oil was first discovered in Bahrain in 1932, initiating a significant transformation
      of the region.
    - By the 1990s, oil wealth had converted nomadic towns into modern metropolises
      across the Gulf.
    - This state-controlled wealth established a non-democratic social contract, where
      governments distributed riches for political obedience.
    - The system relies heavily on continuous cash flow and sustained regional stability.
    - To diversify their economies, Saudi Arabia invested heavily in tourism and entertainment.
    - The UAE developed into a major finance hub, while Qatar hosted the World Cup
      to boost its global profile.
    - Tourism now contributes approximately 12% of the GDP in both Saudi Arabia and
      the UAE, and Gulf sovereign wealth funds manage trillions in global assets.
    Hypothetical Conflict's Economic Fallout:
    - The hypothetical conflict immediately destabilizes the region, undoing years
      of perceived safety within weeks.
    - Iranian missile strikes target the six Gulf nations, shutting down the world's
      largest oil and gas refineries.
    - This results in a loss of 6.7 million barrels per day, costing about $1 billion
      daily.
    - The economic fallout threatens the ruling regimes of the Gulf States.
    Gulf States' Oil Leverage and Dollar's Reserve Status:
    - Gulf States control nearly one-third of global oil output and over half of the
      world's reserves, providing leverage to pressure the U.S. by cutting production.
    - The 1973 oil embargo (in response to Western support for Israel) serves as a
      historical precedent, causing oil prices to rise from $3 to $10 per barrel and
      U.S. inflation to peak at over 13%.
    - Despite reduced U.S. reliance on Gulf oil (10% vs. one-third previously) and
      its status as the world's largest oil producer, the dollar's reserve currency
      status (60% of foreign exchange reserves) is crucial.
    - The dollar's reserve status is almost entirely backed by the petrodollar agreement.
    - Similar to the 19th-century British Empire's pound, the U.S. can borrow and
      print money without major domestic inflation due to global demand for dollars
      to buy oil.
    - The global oil industry, worth $3.7 trillion annually (3% of world GDP), forces
      countries to use the dollar as a middleman for 90% of trade outside the U.S.
    - This system has allowed the U.S. to run a trade deficit every year since 1976,
      accumulating $26 trillion in net foreign debt.
    - It provides a hidden subsidy to Americans worth nearly $3,000 per person annually,
      with the 2025 deficit estimated at nearly $900 billion.
    Erosion of U.S. Security Guarantees and China's Alternative:
    - In the hypothetical conflict, Gulf States are angered by the U.S. failing to
      uphold security guarantees and reportedly refusing to restock Qatar's Patriot
      interceptor missiles.
    - This follows a 2019 incident where the U.S. did not respond to Iranian drone
      strikes on Saudi oil facilities, which knocked out 5% of the world's supply.
    - While switching from the dollar is challenging due to market inertia, China
      emerges as a viable alternative.
    - China's share of world trade has increased sevenfold in two decades to 14% of
      global exports, and it possesses the world's largest military by personnel.
    - China is already Saudi Arabia's largest trading partner, and they have a currency
      swap agreement to trade in yuan and rial.
    Gulf Investments, U.S. Debt, and the "Slow Bleed":
    - A secret clause of the original petrodollar deal, revealed in 2016, mandated
      Gulf states to reinvest their dollars into U.S. financial assets.
    - By 1977, Saudi Arabia held 20% of all foreign-owned U.S. debt; official holdings
      were $117 billion in 2016.
    - These investments are crucial for the U.S., which has nearly $39 trillion in
      debt and pays over $1 trillion annually in interest.
    - A two-percentage-point rise in interest rates would cost an additional $700
      billion annually.
    - The petrodollar system's erosion is described as a "slow bleed," with Saudi
      Arabia shifting billions to Asian markets.
    - Gulf sovereign wealth funds (managing over $3 trillion) are diversifying away
      from U.S. assets.
    - Saudi Arabia is also deepening defense ties with China, indicating a further
      shift.
- heading: Closing remarks
  bullets:
  - 'Recap: The petrodollar''s erosion is a "slow bleed" with profound consequences
    for American financial supremacy.'
  sub_sections: {}
metadata:
  source_type: youtube
  url: https://www.youtube.com/watch?v=CtrhU7GOjOg
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: transcript via tier=ytdlp_player_rotation len=79794
  total_tokens_used: 8678
  gemini_pro_tokens: 0
  gemini_flash_tokens: 8678
  total_latency_ms: 39908
  cod_iterations_used: 0
  self_check_missing_count: 0
  patch_applied: false
  engine_version: 2.0.0
  structured_payload:
    mini_title: Petrodollar s Decline US Dominance
    brief_summary: This lecture explores the potential decline of the petrodollar
      system and its implications for U. S. Global dominance. An The speaker outlines
      a hypothetical scenario where geopolitical shifts and perceived U. S. Security
      failures lead Gulf States to challenge the dollar's role in oil trade. The presentation
      details the petrodollar's historical context, the Gulf States' economic diversification,
      and the leverage they hold through oil production.
    tags:
    - petrodollar
    - geopolitics
    - us-economy
    - china-trade
    - oil-market
    - reserve-currency
    - middle-east
    - lecture
    - financial-system
    - global-dominance
    speakers:
    - Strait of Hormuz
    guests: null
    entities_discussed:
    - Petrodollar system
    - Strait of Hormuz
    - Yuan
    - Rial
    - Patriot interceptor missiles
    - Karachi (tanker)
    - Sovereign wealth funds
    detailed_summary:
      thesis: The petrodollar system, a 50-year-old agreement underpinning U.S. economic
        dominance, is vulnerable to a "slow bleed" due to shifting geopolitical alliances
        and perceived U.S. security failures, potentially ending American global financial
        supremacy.
      format: lecture
      chapters_or_segments:
      - timestamp: ''
        title: Challenging the Petrodollar System
        bullets:
        - A hypothetical scenario on March 15, 2026, depicts a Pakistani tanker, the
          Karachi, trading oil in Chinese yuan through the Strait of Hormuz.
        - This scenario directly challenges the petrodollar system, a 50-year agreement
          where six Gulf States sell oil in U.S. dollars.
        - In exchange for dollar-denominated oil sales, the U.S. provides military
          protection to these Gulf States.
        - This arrangement has historically underpinned the U.S. economy and its global
          financial leverage.
        - The hypothetical conflict involves the U.S. and Israel eliminating Iran's
          supreme leader, leading to regional attacks.
        - These attacks cause Gulf States to perceive the U.S. security guarantees
          as failing, undermining the petrodollar bargain.
        - The potential end of the petrodollar is presented as a "slow bleed" rather
          than an immediate collapse, threatening U.S. global dominance.
      - timestamp: ''
        title: Historical Context and Regional Transformation
        bullets:
        - Oil was first discovered in Bahrain in 1932, initiating a significant transformation
          of the region.
        - By the 1990s, oil wealth had converted nomadic towns into modern metropolises
          across the Gulf.
        - This state-controlled wealth established a non-democratic social contract,
          where governments distributed riches for political obedience.
        - The system relies heavily on continuous cash flow and sustained regional
          stability.
        - To diversify their economies, Saudi Arabia invested heavily in tourism and
          entertainment.
        - The UAE developed into a major finance hub, while Qatar hosted the World
          Cup to boost its global profile.
        - Tourism now contributes approximately 12% of the GDP in both Saudi Arabia
          and the UAE, and Gulf sovereign wealth funds manage trillions in global
          assets.
      - timestamp: ''
        title: Hypothetical Conflict's Economic Fallout
        bullets:
        - The hypothetical conflict immediately destabilizes the region, undoing years
          of perceived safety within weeks.
        - Iranian missile strikes target the six Gulf nations, shutting down the world's
          largest oil and gas refineries.
        - This results in a loss of 6.7 million barrels per day, costing about $1
          billion daily.
        - The economic fallout threatens the ruling regimes of the Gulf States.
      - timestamp: ''
        title: Gulf States' Oil Leverage and Dollar's Reserve Status
        bullets:
        - Gulf States control nearly one-third of global oil output and over half
          of the world's reserves, providing leverage to pressure the U.S. by cutting
          production.
        - The 1973 oil embargo (in response to Western support for Israel) serves
          as a historical precedent, causing oil prices to rise from $3 to $10 per
          barrel and U.S. inflation to peak at over 13%.
        - Despite reduced U.S. reliance on Gulf oil (10% vs. one-third previously)
          and its status as the world's largest oil producer, the dollar's reserve
          currency status (60% of foreign exchange reserves) is crucial.
        - The dollar's reserve status is almost entirely backed by the petrodollar
          agreement.
        - Similar to the 19th-century British Empire's pound, the U.S. can borrow
          and print money without major domestic inflation due to global demand for
          dollars to buy oil.
        - The global oil industry, worth $3.7 trillion annually (3% of world GDP),
          forces countries to use the dollar as a middleman for 90% of trade outside
          the U.S.
        - This system has allowed the U.S. to run a trade deficit every year since
          1976, accumulating $26 trillion in net foreign debt.
        - It provides a hidden subsidy to Americans worth nearly $3,000 per person
          annually, with the 2025 deficit estimated at nearly $900 billion.
      - timestamp: ''
        title: Erosion of U.S. Security Guarantees and China's Alternative
        bullets:
        - In the hypothetical conflict, Gulf States are angered by the U.S. failing
          to uphold security guarantees and reportedly refusing to restock Qatar's
          Patriot interceptor missiles.
        - This follows a 2019 incident where the U.S. did not respond to Iranian drone
          strikes on Saudi oil facilities, which knocked out 5% of the world's supply.
        - While switching from the dollar is challenging due to market inertia, China
          emerges as a viable alternative.
        - China's share of world trade has increased sevenfold in two decades to 14%
          of global exports, and it possesses the world's largest military by personnel.
        - China is already Saudi Arabia's largest trading partner, and they have a
          currency swap agreement to trade in yuan and rial.
      - timestamp: ''
        title: Gulf Investments, U.S. Debt, and the "Slow Bleed"
        bullets:
        - A secret clause of the original petrodollar deal, revealed in 2016, mandated
          Gulf states to reinvest their dollars into U.S. financial assets.
        - By 1977, Saudi Arabia held 20% of all foreign-owned U.S. debt; official
          holdings were $117 billion in 2016.
        - These investments are crucial for the U.S., which has nearly $39 trillion
          in debt and pays over $1 trillion annually in interest.
        - A two-percentage-point rise in interest rates would cost an additional $700
          billion annually.
        - The petrodollar system's erosion is described as a "slow bleed," with Saudi
          Arabia shifting billions to Asian markets.
        - Gulf sovereign wealth funds (managing over $3 trillion) are diversifying
          away from U.S. assets.
        - Saudi Arabia is also deepening defense ties with China, indicating a further
          shift.
      demonstrations: []
      closing_takeaway: The petrodollar's erosion is a "slow bleed" with profound
        consequences for American financial supremacy.
    _youtube_format:
      format: lecture
      confidence: 0.583
    _dense_verify:
      format_label: talk
      missing_fact_count: 0
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Video
America is Losing Control of the Petrodollar

Transcript
Kind: captions Language: en The 15th of March 2026 marked a historic [00:03] The 15th of March 2026 marked a historic day as oil aboard the Pakistani owned [00:06] day as oil aboard the Pakistani owned [00:06] day as oil aboard the Pakistani owned tanker Karachi passed safely through the [00:08] tanker Karachi passed safely through the [00:08] tanker Karachi passed safely through the straight of Hormuz. Denominated not in [00:10] straight of Hormuz. Denominated not in [00:10] straight of Hormuz. Denominated not in US dollars but in Chinese yuan. That [00:13] US dollars but in Chinese yuan. That [00:13] US dollars but in Chinese yuan. That same day, another vessel also went [00:15] same day, another vessel also went [00:15] same day, another vessel also went through carrying crude on a yuan aligned [00:17] through carrying crude on a yuan aligned [00:18] through carrying crude on a yuan aligned route. But it challenges an agreement [00:19] route. But it challenges an agreement [00:19] route. But it challenges an agreement which has underpinned the very [00:21] which has underpinned the very [00:21] which has underpinned the very foundation of America's economy, the [00:23] foundation of America's economy, the [00:23] foundation of America's economy, the petro dollar. In return for American [00:25] petro dollar. In return for American [00:25] petro dollar. In return for American protection, the Gulf States, these six [00:27] protection, the Gulf States, these six [00:27] protection, the Gulf States, these six countries here, would prop up American [00:29] countries here, would prop up American [00:29] countries here, would prop up American interest and sell their oil in dollars. [00:32] interest and sell their oil in dollars. [00:32] interest and sell their oil in dollars. But a deal that was supposed to secure [00:34] But a deal that was supposed to secure [00:34] But a deal that was supposed to secure American dominance instead handed a [00:36] American dominance instead handed a [00:36] American dominance instead handed a small group of countries extraordinary [00:38] small group of countries extraordinary [00:38] small group of countries extraordinary leverage over the most powerful country [00:40] leverage over the most powerful country [00:40] leverage over the most powerful country on Earth. Since the US and Israel wiped [00:42] on Earth. Since the US and Israel wiped [00:42] on Earth. Since the US and Israel wiped out Iran's supreme leader, a wave of [00:45] out Iran's supreme leader, a wave of [00:45] out Iran's supreme leader, a wave of attacks have spread across the region. [00:47] attacks have spread across the region. [00:47] attacks have spread across the region. The Gulf States didn't sign up for this. [00:49] The Gulf States didn't sign up for this. [00:49] The Gulf States didn't sign up for this. For 50 years, their deal with America [00:51] For 50 years, their deal with America [00:51] For 50 years, their deal with America has held. But right now, for the first [00:53] has held. But right now, for the first [00:53] has held. But right now, for the first time, the very countries propping up the [00:55] time, the very countries propping up the [00:55] time, the very countries propping up the American economy are watching the terms [00:57] American economy are watching the terms [00:57] American economy are watching the terms of that bargain fall apart. So what [00:59] of that bargain fall apart. So what [00:59] of that bargain fall apart. So what happens when they decide to stop playing [01:01] happens when they decide to stop playing [01:01] happens when they decide to stop playing ball? Maybe not an immediate collapse, [01:03] ball? Maybe not an immediate collapse, [01:04] ball? Maybe not an immediate collapse, but a slow bleed and one that could [01:06] but a slow bleed and one that could [01:06] but a slow bleed and one that could bring America's era of global dominance [01:08] bring America's era of global dominance [01:08] bring America's era of global dominance down with it. So how did a handful of [01:10] down with it. So how did a handful of [01:10] down with it. So how did a handful of desert states end up with this much [01:12] desert states end up with this much [01:12] desert states end up with this much leverage over the most powerful country [01:14] leverage over the most powerful country [01:14] leverage over the most powerful country on Earth? To answer that, you have to [01:16] on Earth? To answer that, you have to [01:16] on Earth? To answer that, you have to understand what they've built and how [01:18] understand what they've built and how [01:18] understand what they've built and how quickly it can fall apart. In the last [01:21] quickly it can fall apart. In the last [01:21] quickly it can fall apart. In the last century, the Gulf States have gone [01:22] century, the Gulf States have gone [01:22] century, the Gulf States have gone through an enormous transformation, [01:24] through an enormous transformation, [01:24] through an enormous transformation, largely thanks to one thing, oil. Oil [01:27] largely thanks to one thing, oil. Oil [01:27] largely thanks to one thing, oil. Oil was first discovered in Bahrain in 1932, [01:30] was first discovered in Bahrain in 1932, [01:30] was first discovered in Bahrain in 1932, and within decades, the entire region [01:33] and within decades, the entire region [01:33] and within decades, the entire region was producing it. And by the 1990s, that [01:35] was producing it. And by the 1990s, that [01:35] was producing it. And by the 1990s, that oil money had completely transformed [01:37] oil money had completely transformed [01:37] oil money had completely transformed what these places look like. Areas which [01:40] what these places look like. Areas which [01:40] what these places look like. Areas which had once been nomadic desert towns [01:41] had once been nomadic desert towns [01:42] had once been nomadic desert towns suddenly became sprawling metropolises. [01:44] suddenly became sprawling metropolises. [01:44] suddenly became sprawling metropolises. Dubai alone went from a modest trading [01:46] Dubai alone went from a modest trading [01:46] Dubai alone went from a modest trading port to a city of glass towers in barely [01:48] port to a city of glass towers in barely [01:48] port to a city of glass towers in barely a generation. But this wasn't just an [01:51] a generation. But this wasn't just an [01:51] a generation. But this wasn't just an economic boom. It reshaped how these [01:53] economic boom. It reshaped how these [01:53] economic boom. It reshaped how these countries were governed. Oil wealth was [01:55] countries were governed. Oil wealth was [01:55] countries were governed. Oil wealth was entirely statec controlled, which meant [01:57] entirely statec controlled, which meant [01:57] entirely statec controlled, which meant that everything, wages, subsidies, [01:59] that everything, wages, subsidies, [01:59] that everything, wages, subsidies, infrastructure, flowed from a [02:01] infrastructure, flowed from a [02:01] infrastructure, flowed from a centralized system financed by oil. And [02:04] centralized system financed by oil. And [02:04] centralized system financed by oil. And in exchange for political obedience, the [02:06] in exchange for political obedience, the [02:06] in exchange for political obedience, the government distributed enough of that [02:08] government distributed enough of that [02:08] government distributed enough of that wealth to keep people compliant. It's a [02:10] wealth to keep people compliant. It's a [02:10] wealth to keep people compliant. It's a social contract, just not a democratic [02:13] social contract, just not a democratic [02:13] social contract, just not a democratic one. And as long as it holds, it works. [02:15] one. And as long as it holds, it works. [02:15] one. And as long as it holds, it works. But the deal only holds if two things [02:17] But the deal only holds if two things [02:17] But the deal only holds if two things are true. The money keeps flowing and [02:20] are true. The money keeps flowing and [02:20] are true. The money keeps flowing and the region stays stable, which is why in [02:22] the region stays stable, which is why in [02:22] the region stays stable, which is why in recent decades, the Gulf States have [02:24] recent decades, the Gulf States have [02:24] recent decades, the Gulf States have made an enormous effort to diversify and [02:26] made an enormous effort to diversify and [02:26] made an enormous effort to diversify and rebrand. Saudi Arabia has poured [02:28] rebrand. Saudi Arabia has poured [02:28] rebrand. Saudi Arabia has poured hundreds of billions into tourism and [02:30] hundreds of billions into tourism and [02:30] hundreds of billions into tourism and entertainment. The UAE has marketed [02:32] entertainment. The UAE has marketed [02:32] entertainment. The UAE has marketed itself as a global hub for finance and [02:35] itself as a global hub for finance and [02:35] itself as a global hub for finance and innovation, and Qatar hosted the World [02:37] innovation, and Qatar hosted the World [02:37] innovation, and Qatar hosted the World Cup. These countries were no longer [02:39] Cup. These countries were no longer [02:39] Cup. These countries were no longer content to simply be oil exporters. They [02:41] content to simply be oil exporters. They [02:41] content to simply be oil exporters. They wanted to be players on the world stage. [02:43] wanted to be players on the world stage. [02:43] wanted to be players on the world stage. Today, tourism alone accounts for [02:45] Today, tourism alone accounts for [02:45] Today, tourism alone accounts for roughly 12% of Saudi's GDP and around [02:48] roughly 12% of Saudi's GDP and around [02:48] roughly 12% of Saudi's GDP and around 12% of the UAE's. Dubai's international [02:50] 12% of the UAE's. Dubai's international [02:50] 12% of the UAE's. Dubai's international airport is the busiest in the world for [02:52] airport is the busiest in the world for [02:52] airport is the busiest in the world for international passengers. And the [02:54] international passengers. And the [02:54] international passengers. And the region's sovereign wealth funds manage [02:56] region's sovereign wealth funds manage [02:56] region's sovereign wealth funds manage trillions of dollars in global, more [02:58] trillions of dollars in global, more [02:58] trillions of dollars in global, more importantly, American assets. But all of [03:01] importantly, American assets. But all of [03:01] importantly, American assets. But all of this, the skyscrapers, the airlines, the [03:03] this, the skyscrapers, the airlines, the [03:03] this, the skyscrapers, the airlines, the funds, is underpinned by one thing. The [03:06] funds, is underpinned by one thing. The [03:06] funds, is underpinned by one thing. The perception that this is a safe, [03:08] perception that this is a safe, [03:08] perception that this is a safe, predictable place to park your money and [03:10] predictable place to park your money and [03:10] predictable place to park your money and do business. And in just a matter of [03:12] do business. And in just a matter of [03:12] do business. And in just a matter of weeks, 30 years of building that [03:14] weeks, 30 years of building that [03:14] weeks, 30 years of building that perception came undone. &gt;&gt; After the US and Israel launched strikes [03:27] &gt;&gt; After the US and Israel launched strikes on Iran, the country quickly retaliated. [03:29] on Iran, the country quickly retaliated. [03:30] on Iran, the country quickly retaliated. Civilian areas and military bases alike [03:32] Civilian areas and military bases alike [03:32] Civilian areas and military bases alike across the six nations of the Gulf were [03:34] across the six nations of the Gulf were [03:34] across the six nations of the Gulf were hit by missile strikes. The biggest oil [03:36] hit by missile strikes. The biggest oil [03:36] hit by missile strikes. The biggest oil refinery in the world was shut down. the [03:38] refinery in the world was shut down. the [03:38] refinery in the world was shut down. the biggest gas refinery in the world was [03:40] biggest gas refinery in the world was [03:40] biggest gas refinery in the world was shut down. And this is already costing [03:42] shut down. And this is already costing [03:42] shut down. And this is already costing the region around 6.7 million barrels [03:45] the region around 6.7 million barrels [03:45] the region around 6.7 million barrels per day. And at current prices, it's [03:46] per day. And at current prices, it's [03:46] per day. And at current prices, it's roughly a billion dollars every single [03:48] roughly a billion dollars every single [03:48] roughly a billion dollars every single day. And remember, these countries [03:50] day. And remember, these countries [03:50] day. And remember, these countries aren't democracies. There's no election [03:52] aren't democracies. There's no election [03:52] aren't democracies. There's no election to absorb public anger. The social [03:54] to absorb public anger. The social [03:54] to absorb public anger. The social contract in every one of these countries [03:56] contract in every one of these countries [03:56] contract in every one of these countries depends on the government being able to [03:58] depends on the government being able to [03:58] depends on the government being able to keep the money flowing and the streets [04:00] keep the money flowing and the streets [04:00] keep the money flowing and the streets safe. And when that breaks down, the [04:02] safe. And when that breaks down, the [04:02] safe. And when that breaks down, the regime itself is at risk. But here's the [04:04] regime itself is at risk. But here's the [04:04] regime itself is at risk. But here's the thing. These aren't powerless countries. [04:06] thing. These aren't powerless countries. [04:06] thing. These aren't powerless countries. They spent 50 years quietly building [04:08] They spent 50 years quietly building [04:08] They spent 50 years quietly building themselves into the loadbearing wall of [04:11] themselves into the loadbearing wall of [04:11] themselves into the loadbearing wall of the global economy. And if they decide [04:13] the global economy. And if they decide [04:13] the global economy. And if they decide America is threatening their survival, [04:15] America is threatening their survival, [04:15] America is threatening their survival, they have the tools to make Washington [04:17] they have the tools to make Washington [04:17] they have the tools to make Washington feel it. Combined, they control nearly a [04:19] feel it. Combined, they control nearly a [04:19] feel it. Combined, they control nearly a third of global oil output every year, [04:21] third of global oil output every year, [04:21] third of global oil output every year, with by far the largest share coming [04:23] with by far the largest share coming [04:23] with by far the largest share coming from Saudi Arabia. Even more [04:25] from Saudi Arabia. Even more [04:25] from Saudi Arabia. Even more importantly, they also control well over [04:27] importantly, they also control well over [04:27] importantly, they also control well over half of the world's oral reserves. [04:29] half of the world's oral reserves. [04:29] half of the world's oral reserves. Essentially, the price of oil is [04:30] Essentially, the price of oil is [04:30] Essentially, the price of oil is extremely dependent on whatever these [04:32] extremely dependent on whatever these [04:32] extremely dependent on whatever these countries decide to do or not to do. If [04:35] countries decide to do or not to do. If [04:35] countries decide to do or not to do. If they were to say threaten to cut [04:37] they were to say threaten to cut [04:37] they were to say threaten to cut production entirely for a sustained [04:39] production entirely for a sustained [04:39] production entirely for a sustained period of time unless the US stops the [04:41] period of time unless the US stops the [04:41] period of time unless the US stops the invasion, they could send global energy [04:43] invasion, they could send global energy [04:43] invasion, they could send global energy prices soaring, which should be more [04:45] prices soaring, which should be more [04:45] prices soaring, which should be more than enough to pressure the United [04:46] than enough to pressure the United [04:46] than enough to pressure the United States into pulling back or at the very [04:48] States into pulling back or at the very [04:48] States into pulling back or at the very least discourage it from turning this [04:50] least discourage it from turning this [04:50] least discourage it from turning this into a long drawn out occupation. And [04:52] into a long drawn out occupation. And [04:52] into a long drawn out occupation. And time and time again, we have seen one of [04:54] time and time again, we have seen one of [04:54] time and time again, we have seen one of the main success metrics Trump uses is [04:56] the main success metrics Trump uses is [04:56] the main success metrics Trump uses is the markets. And Trump, in particular, [04:58] the markets. And Trump, in particular, [04:58] the markets. And Trump, in particular, ran a campaign promising to bring energy [05:01] ran a campaign promising to bring energy [05:01] ran a campaign promising to bring energy prices down. So having the opposite [05:02] prices down. So having the opposite [05:02] prices down. So having the opposite happen just before the midterm elections [05:04] happen just before the midterm elections [05:04] happen just before the midterm elections would be a political nightmare. If all [05:06] would be a political nightmare. If all [05:06] would be a political nightmare. If all of that sounds a bit extreme, it's worth [05:08] of that sounds a bit extreme, it's worth [05:08] of that sounds a bit extreme, it's worth remembering that a version of this has [05:10] remembering that a version of this has [05:10] remembering that a version of this has happened before. In 1973, in response to [05:13] happened before. In 1973, in response to [05:13] happened before. In 1973, in response to Western support for Israel during the [05:15] Western support for Israel during the [05:15] Western support for Israel during the Yongiper war, oil producing Middle [05:17] Yongiper war, oil producing Middle [05:17] Yongiper war, oil producing Middle Eastern countries led by Saudi Arabia [05:19] Eastern countries led by Saudi Arabia [05:19] Eastern countries led by Saudi Arabia abruptly shut off the flow of oil to the [05:21] abruptly shut off the flow of oil to the [05:21] abruptly shut off the flow of oil to the US, drying up the steady stream of [05:24] US, drying up the steady stream of [05:24] US, drying up the steady stream of Middle Eastern crude that Western [05:25] Middle Eastern crude that Western [05:25] Middle Eastern crude that Western economies had come to depend on and [05:27] economies had come to depend on and [05:27] economies had come to depend on and sending oil prices from $3 to $10 per [05:30] sending oil prices from $3 to $10 per [05:30] sending oil prices from $3 to $10 per barrel in just a couple of months. This [05:32] barrel in just a couple of months. This [05:32] barrel in just a couple of months. This kicked off nearly a decade of high [05:34] kicked off nearly a decade of high [05:34] kicked off nearly a decade of high inflation across the West, peaking at [05:36] inflation across the West, peaking at [05:36] inflation across the West, peaking at over 13% in the US. And before long, [05:39] over 13% in the US. And before 
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 1fd521913c4e1484fb0770932f2d1f4e573f86d0c4a96ef3931e64a66e2c71f7
