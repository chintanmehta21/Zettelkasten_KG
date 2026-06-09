# Consolidated Issue Inventory — FILE 2: Content-Type-Conditional Add-On Sub-Module Surfaces (2026-06-04)

**Problems only — no solutions.** Each row = a failure mode that fires **only for a specific content subtype within a source**, i.e. a surface where a *future* conditional add-on sub-module would gate. This file names the **problem + its content trigger**, not any module design. Consolidates `docs/research/z_eval1_issues1.md` + our eval sweep + deep-research map.

### Priority scale (operator-defined — P0 ≠ critical here)
- **P1 = Highest.**  **P2 = Medium.**  **P3 = Low.**  **P0 = Deferred — "not required now, in future maybe."**
- **Why the no-eval-data sources are P0:** arXiv / podcast / twitter / linkedin / hackernews / document are *supported by the engine* but have **zero samples in the 81-zettel eval** and ~zero current ingest volume — so they are genuinely "future-maybe," exactly the operator's P0.
- Evidence legend: ✅EVAL · 🔧CODE✓ · 📄CODE? (claim from `z_eval1_issues1.md`, unverified) · 📚RES · 💡INF.

---

## P1 — highest priority (eval-backed, high-volume, subtype clearly drives a distinct failure)

| ID | Source · content trigger | Conditional failure (the sub-module surface) | Evidence | Axis |
|---|---|---|---|---|
| F2-1 | **YouTube · multi-speaker** (interview / debate / panel / reaction) | Speaker/role misattribution — statements bound to the wrong person; collapses to `"The speaker"` when diarization absent | ✅EVAL(silver "wrong speaker tag" recurring) 🔧CODE✓("The speaker" fallback) 📚RES(diarization 11–15% DER) | faithfulness |
| F2-2 | **GitHub · thin-API / library / CLI repos** (README lacks explicit API/CLI section) | Invented public surface — fabricated endpoints/flags/params (the verified theiagen/Dendron/Athens pattern); concentrated on repos where the API isn't README-grounded | ✅EVAL(adversarially verified) 📄CODE?(README+volatile-surface mixing) | faithfulness |
| F2-3 | **Reddit · high-deletion / moderated / deep-argument-chain** | Consensus + coverage collapse — most of the thread invisible, minority/dissent branches dropped, "top-few-comments" summary presented as the whole | ✅EVAL(faith/cov 0.50; divergence highest here) 🔧CODE✓(divergence note only) 📚RES | coverage/faith |

## P2 — medium

| ID | Source · content trigger | Conditional failure | Evidence | Axis |
|---|---|---|---|---|
| F2-4 | **YouTube · visually-anchored** (tutorial / walkthrough / coding-screencast / product demo) | Visual-content loss — transcript-only summary drops on-screen code/slides/demos; "as you can see here" referents vanish | 📚RES 💡INF (eval-**BLIND**: needs video) | coverage |
| F2-5 | **YouTube · commentary vs lecture** | Wrong lead-in register / templated thesis tuned to the wrong format | ✅EVAL 🔧CODE✓(format classifier exists) | coherence |
| F2-6 | **Web · reference/index page** (encyclopedia, listicle, hub) | List-devolution — summary becomes a long name-heavy list instead of a retrieval-usable abstraction; weak primary-unit | ✅EVAL 📄CODE?(no shape routing) 📚RES | coverage |
| F2-7 | **Web · how-to / investigative / policy-essay / scientific-explainer** | Shape-specific failures — caveat/qualifier loss, mid/late-section undercoverage on long pages | ✅EVAL 📚RES | coverage/faith |
| F2-8 | **Reddit · AMA / advice / link-post** | Shape confusion — OP-question vs answer separation, unverified advice flattened to fact, linked-article vs comment conflation | 📄CODE? 📚RES 💡INF | faithfulness |
| F2-9 | **Newsletter · commentary-essay / roundup / link-digest** | Shape confusion + multi-topic section drop; template-scaffolding leakage differs by shape | 📄CODE?(shape classifier+repair exist) 📚RES (eval n=2) | coverage/structure |
| F2-10 | **Newsletter / Web · untrusted HTML** | **Indirect prompt injection** — hidden instructions (white-text / zero-width / alt / aria) hijack the summary (OWASP LLM01) | 📚RES (never probed) | faith/**security** |

> F2-10 is a **security** surface; unproven in our corpus but serious — operator may re-rank to P1 on security grounds.

## P0 — deferred ("not required now, in future maybe": engine-supported but **zero eval data + ~zero current volume**)

| ID | Source | Content-conditional failure surfaces (problems) | Evidence |
|---|---|---|---|
| F2-P0-a | **arXiv** | abstract-only undercoverage · methods/results/limitations facet imbalance · contribution-vs-prior-work conflation · benchmark/result-table infidelity | 📚RES 📄CODE?(arXiv post-cleanup + taxonomy anticipate it) |
| F2-P0-b | **Podcast** | speaker-turn scramble · sponsor-segment leakage · host/guest role confusion · show-notes-vs-transcript mismatch · long-episode chapter-compression loss | 📚RES 💡INF |
| F2-P0-c | **Twitter/X** | root-tweet loss · sarcasm / quote-tweet endorsement confusion · media/screenshot context loss · event-time drift across an evolving thread | 📚RES 💡INF |
| F2-P0-d | **LinkedIn** | promotional framing summarized as fact · personal anecdote over-generalized to universal advice · recruiting/CTA blending into factual summary | 📚RES 💡INF |
| F2-P0-e | **Hacker News** | article-vs-comment duality (conflating linked-article claims with commenter reactions) · consensus misread from a small visible slice · title/submission summarized as the article | 📚RES 💡INF |
| F2-P0-f | **Document** (PDF / OCR / slides / tables) | reading-order failure · table/figure omission · caption detachment · section-header hierarchy corruption | 📚RES 💡INF |

---

## Notes
- **The two-level matrix is the right model** (source family → content subtype); the engine already moved this way (YouTube format classifier, GitHub archetype classifier, newsletter shape classifier) — so subtype-conditional surfaces are not hypothetical for the eval-backed sources.
- **P1/P2 vs P0 split = evidence availability**, not intrinsic importance: P0 items may matter once those sources gain volume/eval samples. The remediation prerequisite for most P0 sources is a **top-up eval pull** (esp. newsletter, currently n=2, which keeps several P2 items at low confidence).
- `📄CODE?` = code-path claim from `z_eval1_issues1.md`, **not re-verified this session**. `💡INF` = research-informed inference, no direct eval/code proof.
- **No fixes / no module designs proposed (scope = problems only).** Re-rank freely — this is my proposed ordering on your scale.
