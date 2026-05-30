# NLI + LLM-Judge Combination Strategy — Deep-Research Verdict

**Date:** 2026-05-30
**Method:** deep-research workflow (wf_15c54ed6-838) — 5 search angles, ~15 sources,
3-vote adversarial verification (2/3 refutes to kill). 50 claims survived, 25 refuted.
Synthesis salvaged from the journal after the runner stalled at the final write step.

## TL;DR VERDICT

| # | Question | Verdict | Confidence |
|---|---|---|---|
| a | Combination strategy | **Drop strict-AND. Use NLI-first cascade / OR-with-review.** | high |
| b | Judge-gated short-circuit (Option A) | **UNSAFE — do not apply.** | high (inference) |
| c | Threshold | **Stop inheriting 0.7. Calibrate (F-beta β>1) or use expert-audit + fixed recall target.** | high |

**Both of my v2 design choices were wrong:** the LOOSE AND-gate is non-standard and has a
false-negative-veto flaw, and the short-circuit I recommended (Option A) is exactly the
unsafe case. The operator's instinct to research before applying was correct.

## Evidence (all adversarially verified)

### 1. No SOTA framework uses strict-AND of two verifiers (3-0)
- **RAGAS**: single per-claim LLM verdict, `supported/total` ratio. HHEM variant *substitutes*
  a T5 classifier for the LLM (still one verifier per step). No AND, no second-verifier agreement.
- **DeepEval**: LLM-judge only (extract claims, classify with same model). No NLI partner.
- **FineSurE** (ACL 2024): standalone 9-category LLM classifier; NLI appears only as a baseline it beats.
- **MiniCheck** (EMNLP 2024): positioned as a >400× cheaper *standalone replacement* for the LLM judge — proposes no ensemble/cascade/AND.
- **SelfCheckGPT**: NLI and Prompt variants are *interchangeable alternatives*, never conjoined.
- Sources: ragas docs, deepeval docs, arXiv 2407.00908, 2404.10774, 2303.08896.
- **→ Our LOOSE AND-gate is a non-standard, more-conservative combiner no SOTA framework validates.**

### 2. LLM judges systematically UNDER-report contradictions (false-negative/leniency bias) (3-0)
- **FaithJudge** (EMNLP 2025 Industry, o3-mini-high): "tends to underpredict hallucinations"
  across Command-R / Mistral / Qwen — high specificity, weak sensitivity (FN-dominant).
- **Judging-the-Judges** (2024): leniency bias, P+ > 0.50; "well-aligned models produce more FP than FN" (under-report errors).
- Faithfulness recall **30–60%** on inconsistent summaries (catches >95% of consistent ones).
- Sources: arXiv 2505.04847, 2406.12624, 2406.13929.
- **→ An AND-gate REQUIRING the judge to also flag lets every judge false-negative VETO a correct
  NLI contradiction — silently burying real hallucinations. This is the core flaw.**

### 3. MAX/OR-recall aggregation beats MIN/AND for grounding (medium, 2-1; intra-verifier)
- SummaC operator ablation: max-then-mean = **72.1%** bAcc; every MIN/AND-containing combo 53–68.8%.
- Source: SummaC, TACL 2022. Caveat: intra-verifier (sentence pairs within one NLI), not two-verifier — strong supporting direction, not a direct measurement of our setup.

### 4. NLI-at-claim-level is correct and a legitimate standalone scorer (3-0)
- SummaC-Conv 74.4% bAcc vs 61.3% doc-level MNLI. Validates MiniCheck-at-claim — NLI should NOT be subordinated beneath a less-reliable judge.

### 5. Threshold 0.5 is the MiniCheck default (balanced acc, symmetric costs) (3-0)
- Paper: "we set t=0.5" midpoint, deliberately zero-shot, BAcc weights FP/FN equally.
- **Our 0.7 is an un-calibrated precision-favoring deviation the paper does not justify.**
- Under our asymmetric costs (FN = bad summary slips through is worse), recalibrate via
  F-beta (β>1) or Youden's J on a held-out labeled set — threshold and combination are *separate* levers.

### REFUTED (do NOT use)
- Learned/Optuna-weighted ensemble (arXiv 2504.19254) refuted 0-3 as "industry standard" — over-engineered for an 81-item harness with no labeled training set.

## Empirical proof on our data — `1c0af8ec` (confirmed real hallucination)

| Design | `1c0af8ec` outcome (v2.max_con=0.66, judge_n=9) |
|---|---|
| **LOOSE AND-gate (current v2)** | **CLEARED — false negative.** NLI 0.66 < 0.70 → AND fails → bad summary slips through. |
| **OR-with-review (verdict)** | **REVIEW — caught.** Judge fired 9 → routed to human review. |

## Corrected-design routing on the 29 v1 hard-fails (T=0.70, atomic_facts NLI)

| Route | Rule | Count | Meaning |
|---|---|---:|---|
| **HARD_FAIL** | NLI≥.7 AND judge>0 | 2 | high-confidence real (88b63f46, fa2a34f6) |
| **REVIEW (judge-only)** | NLI<.7 AND judge>0 | 10 | judge caught, NLI threshold missed — incl. `1c0af8ec` |
| **REVIEW (NLI-only)** | NLI≥.7 AND judge=0 | 10 | NLI caught, judge lenient — but Agent A/E showed many are NLI FPs (verbatim-in-source) |
| **CLEAN** | neither | 7 | drop |

## Open questions (operator preferences — not resolvable from literature)

1. **Review-queue tolerance**: OR-with-review yields ~20 review items vs LOOSE-AND's 2. How many
   manual reviews are acceptable? This sets the threshold/routing aggressiveness.
2. **Calibration feasibility**: 81 items may be too few for held-out threshold tuning without
   overfitting — expert-labeled audit (~20-30 items) + fixed recall target may be better.
3. **Judge signal shape**: our judge emits a discrete `contradicted_sentences` list (not a [0,1]
   score), so soft/weighted combination is off the table — cascade/routing is the ceiling.

## Residual risk of the corrected design
- Larger review queue (the precision cost of recall-favoring). The 10 NLI-only items are
  likely mostly NLI false-positives (Agent A/E: verbatim-in-source, chunking-miss), so routing
  them to review wastes some annotator time — a calibrated threshold would trim this.
