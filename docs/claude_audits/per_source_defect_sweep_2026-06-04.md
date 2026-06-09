# Per-Source Defect Sweep — 2026-06-04 (DIAGNOSE-ONLY)

**Scope decision (operator):** diagnose only, full per-source sweep, **no code/prod changes** this iteration. This report = the prioritized fix list for a *future, separately-approved* iteration.

**Method:** mined the **validated Claude judge** (iter-002; Claude won the human-anchored verdict) per-zettel outputs (`anti_patterns_triggered`, `rubric.components[].criteria_missed`, `caps_applied`, `editorialization_flags`, `g_eval`, `finesure`) + the raw summaries (`_data/<uuid>/summary.json`, regex doubling detector) + **human round-1** scores, across all 81. Pure local, $0. `analysis/defect_sweep.json` has the raw matrix.

**Methodology grounding (research, <5yr):** error-analysis prevalence+lift coding (Husain; Shankar UIST'24; FineSurE ACL'24); slice-eval with small-N gates (Domino, SliceFinder, paired bootstrap); conditional validators (Guardrails AI, NeMo); repetition cleanup (rep-n, idempotent anchored collapse); safe rollout (shadow→golden-gate→canary).

---

## 0. CRITICAL — separate ENGINE-WIDE / HARNESS ARTIFACTS from real per-source defects

These fire on **≈all 81 regardless of source** → they are NOT per-source summary defects and must not be "fixed" as such:

| Signal | Prevalence | Verdict |
|---|---|---|
| `tags.*` missing (count/specificity/source_marker/no_unsupported) | **81/81** | **Eval-feed artifact.** Production *does* emit tags (in `meta.json.structured_payload`); the harness fed the judge only `brief_summary`+`detailed_summary`, so the judge scores "no tags" everywhere. **Fix = harness feed (or confirm prod emits), not the summarizer.** |
| `label.*` missing (fast_identifier/makes_sense_alone) | **81/81** | Same artifact — `mini_title`/label exists in `structured_payload`, not fed to judge. |
| `generic_tags_or_ambiguous_label` anti-pattern → `generic_cap=90` | **74–81/81** | Direct consequence of the above; an artifact cap applied corpus-wide. Re-check after the feed fix. |
| `brief.length_5_to_7_sentences` missed | **70/81** | Briefs run 3–4 sentences vs rubric's 5–7. **Humans did NOT penalize this** (coverage/coherence ~0.8+), so this is **likely rubric over-strictness, not a real defect** — needs an explicit calibration call before any "fix." |

**Implication:** the earlier baseline composites were depressed partly by these artifacts. They explain a chunk of the Gemini/Claude composite gap and must be resolved in the harness before re-reading absolute composite levels.

---

## 1. Per-source findings — (A) source-wide vs (B) content-specific

### YouTube (n=33)
**(A) source-wide:**
- **Duplicated-attribution doubling — ≥8/33 (24%)** *(detector floor; may undercount variants)*. Confirmed spans: `"James Fadiman argues that james fadiman argues that"`, `"Aswath Damodaran argues that aswath damodaran argues that"`, `"David Heinemeier Hansson argues that david heinemeier hansson argues that"`, and the verb-swap variant `"The speaker argues that the speaker contends that"`. Appears in **both** brief and detailed; case-drift on the echo. **0% on every other source** → YouTube-concentrated. Hurts coherence/fluency (judge g_eval fluency 2.30/3, lowest of clean sources). **Fix: deterministic anchored idempotent collapse in the post-summary cleanup** (cheap, high-confidence).
- **Editorialization — 15/33 (45%)** added framing flagged by the judge.
- **Brief omits major units — 28/33 (85%)** (the brief doesn't enumerate the video's main sections).

**(B) content-specific (hypotheses, small-N):** doubling concentrates on **named-speaker / multi-speaker** videos (the attribution-prefix path) → a content trigger ("named speaker present") is the natural gate for the cleanup + a flag.

### web (n=19) — cleanest source
- **No source-specific defects of note.** Human faith **1.00**, coverage 0.97, coherence 0.99; doubling 0%; editorialization 3/19. Only the universal artifacts (§0) apply. **No action beyond §0.**

### reddit (n=15) — weakest on faithfulness/coverage
**(A) source-wide:**
- **Low faithfulness & coverage — human 0.50 / 0.50** (≈3/5), the lowest of any source, human-confirmed (not just judge).
- **Very high editorialization — 12/15 (80%)** + **invented_fact 6/15 (40%)** + **missing_primary_unit 9/15 (60%)**.
- **Brief misses major_units AND distinctive_signal — 15/15 (100%)** (source-concentrated: distinctive_signal misses don't appear on web/youtube). Lowest judge coherence/fluency (1.73 / 1.53 of 3).

**(B) content-specific (hypotheses):** high-comment threads → invented "consensus" / OP-vs-commenter conflation (matches the per-source criteria's "OP/comment separation, attribution NLI" concern). Likely the root of the low faithfulness.

### github (n=12) — weakest on conciseness/coherence + fabrication
**(A) source-wide:**
- **Unfocused/multi-topic bullets + missing units — `detailed.one_bullet_per_unit` 12/12, `detailed.bullets_focused` 12/12, `brief.major_units` 12/12 (all 100%)** — source-concentrated structural defect.
- **Low conciseness & coherence** — human conc **0.56**, judge conc 0.51, g_eval coherence 1.67/3 (lowest); omission_cap 8/12 (67%).

**(B) content-specific — HIGH CONFIDENCE (adversarially verified):**
- **Fabricated "Public API / Interfaces" section with non-existent endpoints/flags.** Verified against live repos: theiagen (`/center`, `--pathogen`, `--Please`), Dendron (`/sub`), Athens (`@gmail.com`, `//summary`), plus empty `''` category placeholders + duplicated Overview blocks. **The judge under-detects this** (`invented_fact` only 1/12) — consistent with faithfulness ρ=0.30 being only moderate. **Content trigger:** READMEs lacking an explicit API/CLI section → summarizer invents one. This is the clearest **(B)** add-on-detector candidate: "GitHub summary asserts an API/CLI/endpoint token absent from the source."

### newsletter (n=2) — Tier C, no conclusion
Human ~1.0 across axes; n=2 is below the statistical floor. **Reported, not concluded.** Needs a top-up pull before any newsletter-specific claim.

---

## 2. Prioritized fix list (for a FUTURE approved iteration — nothing applied now)

| # | Defect | Source | Type | Fix approach (research-backed) | Confidence / effort |
|---|---|---|---|---|---|
| 1 | Attribution doubling | YouTube | A | Deterministic **anchored idempotent collapse** in post-summary cleanup (verb allow-list + same-subject + adjacency + NFC/casefold compare, emit original); ship with collapse-tests + legit-repetition negatives + idempotency property test | **High / low** |
| 2 | tags/label "missing" (+generic_cap) | ALL (artifact) | Harness | Feed tags/`mini_title` to the judge, or confirm prod emits them; then re-check `generic_cap` | High / low |
| 3 | Fabricated API/interface section | GitHub | B | Content-conditional **validator** (FLAG-first): assert API/CLI/endpoint tokens in summary appear in source; route on "github + no API section in README" | **High (verified) / med** |
| 4 | Low faithfulness + editorialization + invented consensus | reddit | A+B | Prompt/extraction: OP/comment separation + attribution; FLAG-only editorialization detector | Med / med-high |
| 5 | Unfocused bullets + missing units | GitHub | A | Prompt/rubric: one-bullet-per-unit enforcement; structural FLAG | Med / med |
| 6 | Editorialization | YouTube | A | FLAG-only editorialization detector (shared with reddit) | Med / med |
| 7 | brief length 5–7 | ALL | Rubric? | **Calibration decision first** (humans didn't penalize) — recalibrate rubric OR lengthen brief; do not auto-"fix" | Needs call / low |

**Rollout gate for ALL of the above (when approved):** shadow (compute, don't apply) → CI-gate on the frozen 81 (no axis regresses, paired per-item, alter-rate budget, idempotency asserted) → canary behind a flag. FLAG-by-default; promote to auto-FIX only after measuring false-positive rate on the 81.

---

## 3. Caveats
- **Small N** per source (12–33; newsletter 2). Per-source (A) signals at ≥60–85% prevalence are solid direction; finer (B) content-type splits are **hypotheses** to confirm on a fresh pull before building a module (per slice-eval research).
- **The judge under-detects some fabrication** (esp. GitHub) — rely on the targeted detector + the silver/adversarial evidence, not the judge's `invented_fact` count, for #3.
- Defect signals use the **validated Claude judge**; the prod-parity Gemini judge is unreliable on faithfulness/coverage/conciseness (see human verdict) and was not used here.
