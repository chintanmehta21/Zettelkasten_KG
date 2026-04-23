You are an INDEPENDENT rubric reviewer, blind to any prior evaluator's scoring. Do NOT read eval.json.

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of your manual_review.md.

RUBRIC:
version: rubric_newsletter.v1
source_type: newsletter
composite_max_points: 100
components:
- id: brief_summary
  max_points: 25
  criteria:
  - id: brief.main_topic_thesis
    description: Brief states main topic or thesis in one sentence.
    max_points: 6
    maps_to_metric:
    - g_eval.relevance
    - finesure.completeness
  - id: brief.argument_structure
    description: Brief summarizes how the author structures their argument.
    max_points: 5
    maps_to_metric:
    - finesure.completeness
    - g_eval.coherence
  - id: brief.key_evidence
    description: Important evidence or examples are captured without invention.
    max_points: 5
    maps_to_metric:
    - finesure.faithfulness
    - qafact
  - id: brief.conclusions_distinct
    description: Author's conclusions/recommendations distinguished from background.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
  - id: brief.caveats_addressed
    description: If explicit caveats or counterarguments present, how author addresses
      them is summarized.
    max_points: 3
    maps_to_metric:
    - finesure.faithfulness
  - id: brief.stance_preserved
    description: Tone reflects author's stance without editorializing.
    max_points: 2
    maps_to_metric:
    - summac
- id: detailed_summary
  max_points: 45
  criteria:
  - id: detailed.sections_ordered
    description: Bullets represent major sections/argumentative steps in logical order.
    max_points: 8
    maps_to_metric:
    - g_eval.coherence
    - finesure.completeness
  - id: detailed.claims_source_grounded
    description: Claims in bullets are grounded in the source; no new claims.
    max_points: 8
    maps_to_metric:
    - finesure.faithfulness
    - summac
  - id: detailed.examples_captured
    description: Notable examples, case studies, data anchors are captured.
    max_points: 7
    maps_to_metric:
    - finesure.completeness
  - id: detailed.action_items
    description: Explicit action items / practical takeaways bulleted if present.
    max_points: 6
    maps_to_metric:
    - finesure.completeness
  - id: detailed.multiple_scenarios
    description: If multiple viewpoints/scenarios discussed, each gets a bullet.
    max_points: 6
    maps_to_metric:
    - finesure.completeness
  - id: detailed.no_footer_padding
    description: Unsubscribe language, house style, boilerplate not given bullets.
    max_points: 5
    maps_to_metric:
    - finesure.conciseness
  - id: detailed.bullets_specific
    description: Bullets concise yet specific; no vague paraphrase.
    max_points: 5
    maps_to_metric:
    - g_eval.conciseness
- id: tags
  max_points: 15
  criteria:
  - id: tags.count_7_to_10
    description: Exactly 7-10 tags.
    max_points: 2
    maps_to_metric:
    - finesure.conciseness
  - id: tags.domain_subdomain
    description: Main domain and subdomain tagged.
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
  - id: tags.key_concepts
    description: Key concepts or frameworks introduced in the piece tagged.
    max_points: 3
    maps_to_metric:
    - finesure.completeness
  - id: tags.type_intent
    description: Piece type tagged (opinion, research-summary, how-to, case-study).
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
  - id: tags.no_stance_misrepresentation
    description: Tags don't misrepresent stance (no 'bullish-call' on neutral piece).
    max_points: 4
    maps_to_metric:
    - finesure.faithfulness
- id: label
  max_points: 15
  criteria:
  - id: label.compact_declarative
    description: Label is a compact, declarative phrase reflecting main thesis.
    max_points: 6
    maps_to_metric:
    - g_eval.relevance
  - id: label.branded_source_rule
    description: For branded sources (Stratechery/Platformer/etc.), label includes
      publication name.
    max_points: 5
    maps_to_metric:
    - g_eval.relevance
  - id: label.informative_not_catchy
    description: Informative over catchy; obvious what the Zettel is about.
    max_points: 4
    maps_to_metric:
    - g_eval.conciseness
anti_patterns:
- id: stance_mismatch
  description: Summary's implied stance differs from source's detected stance.
  auto_cap: 60
- id: invented_number
  description: Summary cites a number, date, or source not present in the newsletter.
  auto_cap: 60
- id: branded_source_missing_publication
  description: Branded newsletter label missing publication name.
  auto_cap: 90
global_rules:
  editorialization_penalty:
    threshold_flags: 3


SUMMARY:
## URL 1: https://www.platformer.news/substack-nazi-push-notification/

### SUMMARY
```yaml
mini_title: 'Platformer: Substack''s Nazi promotion, an inevitable outcome'
brief_summary: Platformer by Casey Newton addresses Substack's accidental promotion
  of a Nazi newsletter, "NatSocToday." The issue argues this incident was an "inevitable"
  outcome of Substack's policy to host extremist content combined with its use of
  automated growth tools like push notifications and recommendations.
tags:
- platform-governance
- content-moderation
- algorithmic-amplification
- free-expression
- platform-policy
- tech-ethics
- newsletter-platforms
- extremism
- analysis
- case-study
detailed_summary:
  publication_identity: Platformer (by Casey Newton)
  issue_thesis: Substack's accidental promotion of a Nazi newsletter was an inevitable
    consequence of its policies, exposing the conflict between its "neutral infrastructure"
    stance and its use of automated growth tools.
  sections:
  - heading: The Event
    bullets:
    - On a Monday, Substack sent a push notification to an undisclosed number of users
      promoting "NatSocToday," a newsletter self-described as serving the "National
      Socialist and White Nationalist Community."
    - According to a *User Mag* report by Taylor Lorenz, the publication has called
      Jewish people a "sickness" and advocated for eradicating minorities to create
      a "White homeland."
    - The platform's recommendation system also suggested other white nationalist
      publications to users who clicked on the "NatSocToday" profile.
  - heading: Substack's Response
    bullets:
    - The company issued an apology, calling the push alert a "serious error" that
      caused "distress."
    - It stated it took the "relevant system offline" to diagnose the problem and
      prevent recurrence.
  - heading: Casey Newton's Framing
    bullets:
    - 'Newton argues the event was not an accident but an "inevitable" result of combining
      two factors: a refusal to deplatform or demonetize pro-Nazi publications, and
      the use of "social media-style growth hacks" like automated recommendations
      and push alerts.'
    - This combination ensures that extremist content, which the platform permits,
      will eventually be amplified by its own automated systems.
    - Newton had previously predicted this specific scenario, warning that a user
      could receive a push alert for a publication with a swastika logo.
  - heading: Implications
    bullets:
    - The incident challenges the viability of a platform claiming to be "neutral
      infrastructure" while simultaneously employing algorithmic systems designed
      for growth and promotion.
    - A platform's "free expression" rhetoric is in direct conflict with the reality
      of its automated systems, which can amplify the content the platform claims
      to merely host.
  - heading: Context
    bullets:
    - Newton's publication, *Platformer*, left Substack the previous year over the
      company's refusal to act on what Newton specified were "literal 1930s German
      Nazis."
    - At the time, *Platformer*'s decision was criticized as a "pro-censorship crusade"
      (Glenn Greenwald), a stunt to boost paid subscriptions, or an overreaction,
      with some claiming not enough Nazi publications had been found to justify it.
    - Newton presents the accidental promotion as a vindication of his earlier decision
      to leave the platform.
  conclusions_or_recommendations:
  - The incident was not an accident but an inevitable result of Substack's policy
    to host pro-Nazi publications combined with its use of automated growth tools.
  - This event challenges the viability of a platform claiming "neutral infrastructure"
    while using algorithmic promotion, highlighting a conflict between "free expression"
    rhetoric and the reality of automated amplification.
  - The incident serves as a vindication of *Platformer*'s earlier decision to leave
    Substack over similar concerns.
  stance: skeptical
  cta: null
metadata:
  source_type: newsletter
  url: https://www.platformer.news/substack-nazi-push-notification/
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: HTML article text extracted via direct
  total_tokens_used: 6743
  gemini_pro_tokens: 4838
  gemini_flash_tokens: 1905
  total_latency_ms: 78273
  cod_iterations_used: 2
  self_check_missing_count: 3
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: 'Platformer: Substack''s Nazi promotion, an inevitable outcome'
    brief_summary: Platformer by Casey Newton addresses Substack's accidental promotion
      of a Nazi newsletter, "NatSocToday." The issue argues this incident was an "inevitable"
      outcome of Substack's policy to host extremist content combined with its use
      of automated growth tools like push notifications and recommendations. Newton
      highlights the conflict between Substack's "neutral infrastructure" claim and
      the reality of its algorithmic amplification. The newsletter details the event,
      Substack's apology, Newton's critical framing, and the broader implications
      for platform governance. It also provides context, noting Platformer's prior
      departure from Substack over similar concerns, presenting the incident as a
      vindication. No explicit call to action is mentioned.
    tags:
    - platform-governance
    - content-moderation
    - algorithmic-amplification
    - free-expression
    - platform-policy
    - tech-ethics
    - newsletter-platforms
    - extremism
    - analysis
    - case-study
    detailed_summary:
      publication_identity: Platformer (by Casey Newton)
      issue_thesis: Substack's accidental promotion of a Nazi newsletter was an inevitable
        consequence of its policies, exposing the conflict between its "neutral infrastructure"
        stance and its use of automated growth tools.
      sections:
      - heading: The Event
        bullets:
        - On a Monday, Substack sent a push notification to an undisclosed number
          of users promoting "NatSocToday," a newsletter self-described as serving
          the "National Socialist and White Nationalist Community."
        - According to a *User Mag* report by Taylor Lorenz, the publication has called
          Jewish people a "sickness" and advocated for eradicating minorities to create
          a "White homeland."
        - The platform's recommendation system also suggested other white nationalist
          publications to users who clicked on the "NatSocToday" profile.
      - heading: Substack's Response
        bullets:
        - The company issued an apology, calling the push alert a "serious error"
          that caused "distress."
        - It stated it took the "relevant system offline" to diagnose the problem
          and prevent recurrence.
      - heading: Casey Newton's Framing
        bullets:
        - 'Newton argues the event was not an accident but an "inevitable" result
          of combining two factors: a refusal to deplatform or demonetize pro-Nazi
          publications, and the use of "social media-style growth hacks" like automated
          recommendations and push alerts.'
        - This combination ensures that extremist content, which the platform permits,
          will eventually be amplified by its own automated systems.
        - Newton had previously predicted this specific scenario, warning that a user
          could receive a push alert for a publication with a swastika logo.
      - heading: Implications
        bullets:
        - The incident challenges the viability of a platform claiming to be "neutral
          infrastructure" while simultaneously employing algorithmic systems designed
          for growth and promotion.
        - A platform's "free expression" rhetoric is in direct conflict with the reality
          of its automated systems, which can amplify the content the platform claims
          to merely host.
      - heading: Context
        bullets:
        - Newton's publication, *Platformer*, left Substack the previous year over
          the company's refusal to act on what Newton specified were "literal 1930s
          German Nazis."
        - At the time, *Platformer*'s decision was criticized as a "pro-censorship
          crusade" (Glenn Greenwald), a stunt to boost paid subscriptions, or an overreaction,
          with some claiming not enough Nazi publications had been found to justify
          it.
        - Newton presents the accidental promotion as a vindication of his earlier
          decision to leave the platform.
      conclusions_or_recommendations:
      - The incident was not an accident but an inevitable result of Substack's policy
        to host pro-Nazi publications combined with its use of automated growth tools.
      - This event challenges the viability of a platform claiming "neutral infrastructure"
        while using algorithmic promotion, highlighting a conflict between "free expression"
        rhetoric and the reality of automated amplification.
      - The incident serves as a vindication of *Platformer*'s earlier decision to
        leave Substack over similar concerns.
      stance: skeptical
      cta: null
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Article
Substack promotes a Nazi The company has long wanted to be seen as neutral infrastructure — this week, we saw why that’s a fantasy Casey Newton Jul 31, 2025 — 9 min read (Substack) This week, Substack apologized after sending a push alert promoting one of the pro-Nazi blogs on its network. Today, let’s talk about what it reveals about the gap between the company’s rhetoric around free expression and the reality of its approach. Taylor Lorenz had the story in User Mag : Substack sent a push alert encouraging users to subscribe to a Nazi newsletter that claimed Jewish people are a sickness and that we must eradicate minorities to build a “White homeland.” NatSocToday describes itself as “a weekly newsletter featuring opinions and news important to the National Socialist and White Nationalist Community.” The push alert was sent to an undisclosed number of users’ phones on Monday. Some people posted about the app alert on social media, confused why they were being prompted to subscribe to a Nazi blog. Moreover, anyone who clicked on the newsletter's profile saw recommendations for other white nationalist publications on the network. Substack said the alert was an accident. “We discovered an error that caused some people to receive push notifications they should never have received,” the company told Lorenz. “In some cases, these notifications were extremely offensive or disturbing. This was a serious error, and we apologize for the distress it caused. We have taken the relevant system offline, diagnosed the issue, and are making changes to ensure it doesn’t happen again.” This story piqued my interest in part because Platformer left Substack last year over the company’s decision not to remove or even demonetize pro-Nazi publications. (And when I say Nazi, I’m talking about literal 1930s German Nazis.) At the time, some critics accused us of overreacting. Some said we hadn’t found enough Nazi publications to justify leaving . Others said it was a stunt to boost paid subscriptions . Glenn Greenwald said it was part of a pro-censorship crusade on the part of liberal media. “The great cause of this species of liberal journalists is not confronting power centers or exposing deceit and crimes,” he wrote, “but whining and agitating that social media platforms must censor more.” In truth, we had more than one reason to leave. But foremost among them was the certainty that Substack’s Nazi problem would only get worse with time. Once it announced that right-wing extremists were free to set up shop on its network and start selling subscriptions, their arrival was a certainty. And because the platform invests heavily in social media-style growth hacks, it was inevitable that Substack would actively promote Nazi blogs across various surfaces. People would download the Substack app to read Platformer ; they would enable push notifications to be informed of new editions; and then sometime after that there would be a push featuring a publication with a swastika logo. Well, here we are. The inevitable happened. Given how likely all this was, I don’t have much to add about the push notification itself. I did, however, find the company’s statement about it curious. This post is for paying subscribers only Subscribe now Already have an account? Sign in

Title
Substack promotes a Nazi

Subtitle
The company has long wanted to be seen as neutral infrastructure — this week, we saw why that’s a fantasy

Preheader
The company has long wanted to be seen as neutral infrastructure — this week, we saw why that’s a fantasy

CTAs
- Subscribe (#/portal/signup) - Subscribe now (#/portal/signup) - Sign up (#/portal/)
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 5fb1a3c1df5ae5b4c3a9f6863daedd03e68228fae653c73cfafb1a6b19f9c9a6
