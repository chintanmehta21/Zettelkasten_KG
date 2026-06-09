# Consolidated Issue Inventory — FILE 1: Source-Wide Common Issues (2026-06-04)

**Problems only — no solutions** (per operator constraint). Consolidates three analyses: the operator-provided codebase analysis (`docs/research/z_eval1_issues1.md`), our eval defect sweep (`per_source_defect_sweep_2026-06-04.md`), and our deep-research ∪ eval map (`per_source_problem_research_2026-06-04.md`), plus this session's code-verification.

### Priority scale (operator-defined — note P0 ≠ critical here)
- **P1 = Highest priority.**  **P2 = Medium.**  **P3 = Low / nice-to-have.**  **P0 = Deferred — "not required now, in future maybe."**
- Action order: **P1 → P2 → P3 → P0**.
- Ranking basis: user-visible impact × evidence-confidence × breadth/frequency × current necessity. *(Priority is about importance, not fix-effort; effort flagged separately where large. Re-rank freely — this is my proposed ordering.)*

### Evidence legend
✅EVAL = observed/confirmed in our eval · 🔧CODE✓ = root cause verified in code this session · 📄CODE? = code-path claim from `z_eval1_issues1.md`, not re-verified · 📚RES = deep-research (cited) · 💡INF = inference
### Root-cause stage
ROUTE · INGEST · EXTRACT · GEN (LLM) · POST (post-summary normalization) · HARNESS (eval-only)

---

## Ranked master table

| ID | Issue | Stage | Evidence | Axis | Priority |
|---|---|---|---|---|---|
| CS-1 | **Extraction-surface mismatch** — summary is faithful to a partial/noisy *extraction*, not the true source | INGEST/EXTRACT | ✅EVAL 🔧CODE✓ 📚RES | faithfulness | **P1** |
| CS-2 | **Eval can't measure true groundedness** — `source_text.md` ≈ saved summary; judge over-rates faithfulness; old NLI path was "broken" | HARNESS | ✅EVAL 📄CODE? 📚RES | (meta) | **P1** |
| CS-3a | **Judge not fed tags/label** → false "missing" on 81/81 + `generic_cap` corpus-wide; inflates `generic_tags_or_ambiguous_label` | HARNESS | ✅EVAL 🔧CODE✓ | metadata | **P1** |
| YT-1 | **YouTube templated lead-in + attribution doubling + generic/wrong speaker** | POST | ✅EVAL 🔧CODE✓ | coherence/faith | **P1** |
| RD-1 | **Reddit partial-thread summarized as complete** (flagged by a note, surface not fixed) | INGEST | ✅EVAL 🔧CODE✓ | coverage/faith | **P1** |
| GH-1 | **GitHub public-surface hallucination/overreach** (fabricated APIs/CLI/flags) | GEN/INGEST | ✅EVAL(verified) 📄CODE? | faithfulness | **P1** |
| CS-3b | **Product tag/label specificity drift** (real casing/count/specificity drift in *stored* tags) | GEN/POST | 📄CODE? | metadata | **P2** |
| CS-4 | **Schema / serialization fragility** (malformed JSON, schema-failure, many fallback builders) | GEN/POST | ✅EVAL 📄CODE? | (structure) | **P2** *(partly mitigated by shipped Fix #2 retry+backfill)* |
| CS-5 | **Over/under-compression tension** — some outputs too generic, some barely compressed/verbose | GEN | ✅EVAL 📚RES | conciseness | **P2** |
| CS-6 | **Within-source subtype confusion** (rationale for File 2) | ROUTE/GEN | ✅EVAL 📄CODE? | (coverage) | **P2** |
| GH-2 | **GitHub unfocused bullets / one-bullet-per-unit violation + low conciseness** | GEN | ✅EVAL | conciseness | **P2** |
| WB-1 | **Web naive generic route** — ambiguous label/primary-unit on broad pages, large-page undercoverage, reference-page list-devolution | EXTRACT/GEN | ✅EVAL 📄CODE? | coverage | **P2** |
| NL-1 | **Newsletter template-scaffolding leakage** (`**ID:**` etc.) + CTA/promo contamination + shape confusion | EXTRACT/POST | 📄CODE? 📚RES (eval n=2) | faith/structure | **P2** *(low eval evidence)* |
| CS-7 | **No original-source-vs-extraction probe** (the harness gap that hides all upstream failures) | HARNESS | ✅EVAL 📚RES | (meta) | **P3** *(big lift)* |

---

## Detail (P1 first)

### P1 — highest priority

**CS-1 · Extraction-surface mismatch.** The deepest cross-source problem, confirmed by *both* independent analyses. Faithfulness is judged against the pipeline's extracted text, so a summary can faithfully reflect a *bad surface*: YouTube transcript-tier/metadata-only fallback, Reddit partial thread (see RD-1), GitHub volatile surfaces, Web naive HTML. Affects every source; the single biggest driver of "looks-faithful-but-isn't."

**CS-2 · Eval can't measure true groundedness.** `source_text.md` is frozen from `canonical_zettels.body_md` and is often near-identical to the saved `detailed_summary` (both analyses agree). Our human verdict separately proved the prod-parity Gemini judge has ~0/negative faithfulness correlation and even Claude only ρ≈0.30. Net: trust the corpus for **recurring visible defects + ingest pathologies**, not for absolute factuality scores.

**CS-3a · Judge not fed tags/label (harness).** Production emits tags + `mini_title` in `structured_payload`, but the harness fed the judge only `brief`+`detailed`. Result: `tags.*`/`label.*` scored "missing" on **81/81**, `generic_cap=90` applied corpus-wide, and `generic_tags_or_ambiguous_label` became the dominant "top error." **Reconciliation:** `z_eval1_issues1.md` reads that dominant error as a *product* defect; our deeper dig shows it is **largely a harness-feed artifact** — separate it from CS-3b before acting.

**YT-1 · YouTube templated lead-in + doubling.** Root cause **code-verified**: `youtube/schema.py:534` deterministically builds `f"In this {format_name}, {speaker} argues that {thesis_sentence.lower()…}"`. When the model's thesis already begins "{Speaker} argues that…", this wraps a *second*, lowercased attribution → `"…argues that aswath damodaran argues that…"`. `"The speaker"` is the generic fallback (`schema.py:159, 528`). Eval: doubling in 24% of YT (≥8/33); `z_eval1_issues1.md`: 31/33 templated, 21/33 generic speaker. **A deterministic post-processing bug, not an LLM hallucination.**

**RD-1 · Reddit partial-thread-as-complete.** Code-verified: `reddit/summarizer.py:330–342` computes `comment_divergence_pct` and, when ≥20%, appends a `moderation_context` note ("rendered/total visible; divergence %"); the prompt also asks to "mention missing/removed comments." But the summary is still built on the partial rendered surface and `extraction_confidence` passes through unchanged. Eval: reddit human faith/cov **0.50/0.50** (worst source); `z_eval1_issues1.md`: ~27.5% mean comment coverage, 14/15 threads >50% divergence.

**GH-1 · GitHub public-surface hallucination.** Adversarially verified last session against live repos: theiagen (`/center --pathogen --Please`), Dendron (`/sub`), Athens — fabricated API/CLI/endpoint tokens absent from the README, plus empty `''` category placeholders. The judge *under-detects* these (`invented_fact` 1/12 vs ≥3 confirmed). Per `z_eval1_issues1.md` the ingestor mixes README + issues + commits + releases + workflows, widening the surface the model can over-synthesize from. **Actively harmful** (users copy-paste fake APIs).

### P2 — medium
- **CS-3b** product tag/label specificity drift (stored-tag casing/count/specificity) — real but smaller than CS-3a; from `z_eval1_issues1.md`'s stored-tag review (not re-verified by me).
- **CS-4** schema/serialization fragility — malformed persisted JSON, schema-failure paths, multiple fallback builders; partly mitigated by the already-shipped Fix #2 (validation-aware retry + backfill).
- **CS-5** over/under-compression — conciseness is our weakest axis (0.51 github → 0.76 web); compounded by verbosity/length bias in generation+judging.
- **CS-6** within-source subtype confusion — the engine already has YT-format / GitHub-archetype / newsletter-shape classifiers; failures differ by subtype (this is the rationale for File 2).
- **GH-2** unfocused bullets — `detailed.one_bullet_per_unit` missed 12/12, conciseness 0.51.
- **WB-1** naive web route — `fetch → extract_html_text → length-threshold`, no shape/boilerplate routing; weak primary-unit on broad/hybrid/reference pages. Web is otherwise our strongest source (human 1.00/0.97).
- **NL-1** newsletter scaffolding leakage + CTA/promo + shape confusion — the engine *already* has a repair pass for `**ID:**`-style artifacts (evidence the class is real), but eval n=2 can't confirm prevalence.

### P3 — low
- **CS-7** absence of an original-source-vs-extraction probe — the harness change that would *let us see* all the upstream failures (CS-1). High value but a large build; ranked P3 as a discrete harness project rather than a per-summary defect.

---

## Caveats
- Per-source eval N is small (youtube 33, web 19, reddit 15, github 12, newsletter 2) → P1 source-wide signals are solid direction; newsletter cannot be concluded at n=2.
- `📄CODE?` items are code-path claims carried from `z_eval1_issues1.md` and **not independently re-verified this session** — flagged so they aren't treated as confirmed.
- Priorities are my proposed ranking on the operator's scale; re-rank as needed. **No fixes proposed (scope = problems only).**
