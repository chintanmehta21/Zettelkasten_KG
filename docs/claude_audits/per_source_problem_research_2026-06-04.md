# Per-Source Summarization PROBLEMS — Research ∪ Our Eval (2026-06-04)

**Problems only — no solutions** (per operator constraint). Produced by a deep-research workflow: one dedicated research agent + one adversarial verifier per source (10 agents, ~690k tokens, all cited <5yr where possible), then connected here to our internal eval data (defect sweep + human-validated judge scores on 81 summaries). Raw research: workflow `wf_37c8bf88-0a1`.

## Legend — can our eval currently SEE the problem?
- **CONFIRMED** — directly observed in our defect sweep / human scores / silver verification.
- **PARTIAL** — indirectly indicated by our data.
- **UNCHECKED** — research-flagged; our harness *could* probe it but hasn't yet.
- **BLIND** — our harness *structurally cannot* see it (see meta-finding #1).
- Research column: `sup` = adversarially supported, `weak` = thin/inferred evidence (keep, don't over-weight).

---

## CROSS-CUTTING META-FINDINGS (the most important part)

1. **Our eval is BLIND to every UPSTREAM (ingestion) failure mode.** The judge scores the summary against the *pipeline's own extracted text / atomic-facts*, **not** the original source (audio, full HTML, live thread). So a summary can be "faithful" to a corrupted input and pass. **≈40% of the researched problems live here** — ASR errors, boilerplate contamination, paywall truncation, JS-render misses, deleted-Reddit-content, stale README versions. These are the harness's single biggest gap. *(Verified: `_data/<uuid>/source_text.md` is the pipeline's own extraction, near-identical to the summary — not independent ground truth.)*
2. **Our eval CONFIRMS the GENERATION-side failures** (hallucination, omission, verbosity, structure) for the sources where they bite — GitHub fabricated-API is the cleanest confirm (= research's `code-entity-hallucination`).
3. **"Judge overestimates faithfulness" is META-CONFIRMED by us** — the human verdict showed the prod-parity Gemini judge has ~0 / negative faithfulness correlation, and even the best judge (Claude) only ρ≈0.30. The literature's warning is our measured reality.
4. **Two of our biggest observed defects are NOT prominent in the literature** — the YouTube attribution **doubling** ("X argues that x argues that", 24%) is a generation/repetition artifact, and the **tags/label "missing" on 81/81** is a harness-feed artifact. Both are our-specific, beyond the researched set.

---

## YouTube  *(our eval sees: generation-side faithfulness/coverage; BLIND to transcript/audio/visual)*

| Issue | Axis | Ev | Our eval | Note |
|---|---|---|---|---|
| Abstractive hallucination (intrinsic/extrinsic) | faith | sup | **CONFIRMED** | invented_fact 18%, human faith 0.75 |
| **Attribution doubling** "X argues that x argues that" | coherence | — | **CONFIRMED (ours)** | 24% of YT; generation artifact, beyond the literature |
| Speaker misattribution (multi-speaker) | faith | sup | **PARTIAL** | silver caught repeated "wrong speaker tag"; eval blind vs audio |
| Named-entity ASR misrecognition | faith | sup | **PARTIAL/BLIND** | wrong names survive; eval can't check vs audio |
| No structure / topic boundaries → omission | coverage | sup | **PARTIAL** | brief omits major units 85% |
| Lost-in-the-middle (long videos) | coverage | sup | UNCHECKED | no positional probe yet |
| Sponsor/intro/outro filler contamination | concise | sup | UNCHECKED | could detect; editorialization 45% adjacent |
| Coreference errors (conversational) | faith | sup | UNCHECKED | — |
| ASR error propagation | faith | sup | **BLIND** | upstream; eval scores vs transcript not audio |
| Disfluency noise (fillers/false starts) | concise | sup | **BLIND** | upstream transcript |
| Missing punctuation/segmentation | coherence | sup | **BLIND** | upstream auto-caption format |
| Visual-information loss | coverage | sup | **BLIND** | needs video |
| Over-compression omission · clickbait-metadata bias | cov·meta | weak | UNCHECKED | thin evidence |

## Web  *(our eval sees: web is our CLEANEST source — human 1.00/0.97; generation-side fine; BLIND to extraction/fetch)*

| Issue | Axis | Ev | Our eval | Note |
|---|---|---|---|---|
| Verbosity / length bias | concise | sup | **CONFIRMED** | conciseness weakest even on web (0.76 vs faith 1.00) |
| Metadata misattribution (date/author/quote) | metadata | sup | **PARTIAL** | judge flags `missing_meta` [author,date,url] |
| Input-truncation tail loss | coverage | sup | **PARTIAL** | we hit this historically (DMT atomic-facts truncation bug) |
| Intrinsic/extrinsic hallucination | faith | sup | PARTIAL | minimal on web (faith 1.00) |
| Coherence discontinuity / entity confusion | coherence | sup | PARTIAL | doubling is one instance (cross-source) |
| Lead bias · lost-in-the-middle · missing-context · thin-promotional | cov·faith | sup | UNCHECKED | not probed |
| Boilerplate contamination | faith | sup | **BLIND** | upstream extraction (clean for our web set, hence high scores) |
| HTML-structure loss · JS-render miss · paywall reconstruction | struct·cov·faith | sup | **BLIND** | upstream fetch/extraction |
| Mixed-content bleed (comments/sidebars) | coverage | weak | BLIND | thin evidence |

## Reddit  *(our eval sees: WORST faithfulness+coverage 0.50/0.50, editorialization 80%, invented 40%)*

| Issue | Axis | Ev | Our eval | Note |
|---|---|---|---|---|
| Intrinsic/extrinsic hallucination | faith | sup | **CONFIRMED** | invented_fact 40%, human faith 0.50 |
| Dialogue salient-utterance omission | coverage | sup | **CONFIRMED** | brief misses major units 100%, coverage 0.50 |
| Anti-bot wall → thin/empty fetch | metadata | sup | **CONFIRMED** | our own docs note thin Reddit w/o OAuth; silver "fetch-blocked" |
| Deleted/removed content gaps | coverage | sup | **PARTIAL/BLIND** | upstream; compounds the thin fetch |
| Minority-opinion marginalization | coverage | sup | **PARTIAL** | brief misses distinctive_signal 100% |
| Sycophancy agreement-smoothing | faith | sup | **PARTIAL** | editorialization 80% (added framing) |
| Sarcasm/irony polarity flip | faith | sup | UNCHECKED | likely part of low faith; not isolated |
| Slang/jargon/meme misread · toxic/figurative · redundancy-conflict | faith·concise | sup | UNCHECKED | — |
| Lost-in-the-middle (long threads) | coverage | sup | UNCHECKED | — |
| Speaker-attribution · unverified-as-fact · vote-signal misread | faith·cov | weak | UNCHECKED | thin evidence |

## GitHub  *(our eval sees: unfocused bullets 100%, low concise/coherence 0.51/1.67-of-3, fabricated API verified)*

| Issue | Axis | Ev | Our eval | Note |
|---|---|---|---|---|
| **Code-entity hallucination** (fake APIs/CLI/params) | faith | sup | **CONFIRMED (strong)** | theiagen `/center --pathogen`, Dendron `/sub`, Athens — adversarially verified |
| README-only view misreads purpose (no cross-file) | faith | sup | **CONFIRMED** | root cause of the fabricated API |
| Key-fact omission + verbosity | concise | sup | **CONFIRMED** | conciseness 0.51, unfocused bullets 100% |
| World-knowledge bleed (memorized repo facts) | faith | sup | **PARTIAL** | fabricated sections read as memorized |
| Missing purpose/status (rare in source) | coverage | sup | **PARTIAL** | brief misses major units 100% |
| Stale/version-mismatched content | faith | sup | **PARTIAL** | silver caught theiagen "v4.1.0 stale → now v4.2.0" |
| Badges/tables/ASCII noise misread | structure | sup | **PARTIAL** | empty `''` category placeholders (silver) |
| Long-README truncation · lost-in-the-middle | coverage | sup | UNCHECKED | omission_cap 67% adjacent |
| README↔About metadata mismatch | metadata | sup | UNCHECKED | — |
| Structure-collapse · multilingual · monorepo · awesome-list | struct·cov | weak | UNCHECKED | thin/inferred |

## Newsletter  *(our eval: n=2, NO statistical conclusion — research applies, our data can't confirm)*

| Issue | Axis | Ev | Our eval | Note |
|---|---|---|---|---|
| Judge overestimates faithfulness (eval-loop risk) | other | sup | **CONFIRMED (corpus-wide)** | our human verdict proved it |
| Opinion-as-fact · opinion-smoothing · sponsor leakage | faith | sup | UNCHECKED (n=2) | core newsletter risks |
| Intrinsic/extrinsic hallucination · failure-to-synthesize · positional bias · verbosity | faith·cov·concise | sup | UNCHECKED (n=2) | — |
| **Indirect prompt injection** (hidden HTML instructions) | faith/security | sup | **UNCHECKED (security gap)** | untrusted 3rd-party HTML; OWASP LLM01 |
| promo-hype · author-attribution · boilerplate · multitopic · over-compression · relative-date · coherence-collapse | mixed | weak | UNCHECKED (n=2) | thin evidence |

---

## What this gives us
- **Confirmed by our data (act-worthy):** GitHub code-entity hallucination + omission/verbosity; Reddit hallucination + omission + thin-fetch; YouTube hallucination + doubling; web verbosity; the judge-overestimates-faithfulness meta-risk.
- **Biggest blind spot:** upstream ingestion failures (ASR, extraction, fetch, paywall, deleted content) — **the harness can't see them today**; would need an original-source-vs-extraction probe (not just summary-vs-extraction).
- **Security gap surfaced:** indirect prompt injection via newsletter/web HTML — never probed.
- **Newsletter:** unresolvable at n=2 → needs a top-up pull before any newsletter-specific conclusion.

*Caveats: per-source eval N is small (12–33; newsletter 2); "weak"-tagged items have thin/inferred citations; CONFIRMED uses the validated Claude judge + human scores + adversarial silver checks. No solutions proposed, per scope.*
