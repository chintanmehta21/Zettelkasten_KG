# NLI Threshold Calibration — Verdict: Do NOT Calibrate Now (keep fixed 0.70)

**Date:** 2026-05-31
**Decision:** The NLI `HARD_FAIL_CONTRADICT_THRESHOLD` stays a **fixed 0.70**, deliberately
NOT data-calibrated. Formal calibration is **deferred** until the labeled set reaches the
hundreds and can be built cleanly. Operator-approved after a verify-first research pass.

## How we got here
The deep-research verdict (`nli_judge_combination_strategy_2026-05-30.md`) said "recalibrate
the threshold." We attempted it via the `13_threshold_calibration.py` kit. A subagent emulating
the operator labeled a 25-row, score-stratified sample by reading source — and it came back
**25 supported / 0 contradicted** (degenerate, recall undefined). It correctly STOPPED rather
than wire a meaningless threshold. The operator then asked to verify the *next* idea (enrich
positives via judge flags, then F-β) before building it. Three dedicated web-search agents ran.

## Three-agent research verdict (all cited, <5yr-prioritized)

### A — rare-positive calibration
Enrich-by-oversampling-candidate-positives → F-β is the textbook active/weak-supervision pattern,
BUT **F-β is prevalence-dependent** (contains precision); a cut chosen on a positive-heavy enriched
set **over-fires** in production unless prevalence-corrected. Mandatory fix: King–Zeng prior
correction or inverse-probability weighting (Google "upweight by sampling factor"). Recall is
prevalence-invariant; the F-β-optimal *cut* is not.
- King & Zeng (rare-events logistic); PMC10283136 (label-selection bias, IPW); Google MLCC imbalance.

### B — tiny-n overfitting (the decisive one)
At **n~25-50** any data-driven threshold **overfits** — operating-point CIs are wide at n≤100,
and the cut cannot be cross-validated (sklearn: never tune a threshold without CV). For a
**high-recall human-review gate** (exactly ours), the standard is a **fixed operating point**
(model-author default / coverage-recall target) + monitor; defer F-β until labels reach the
**hundreds**.
- Hanczar 2010 (Bioinformatics); Steinberg 2022 (PLOS One); scikit-learn 1.8 threshold docs;
  HALT-RAG 2025; Manokhin 2021; Vectara HHEM ("start at 0.5").

### C — correlated-detector selection bias
Enriching NLI's calibration set via the **judge's** flags = classic **verification/workup bias**;
because judge & NLI are both faithfulness detectors with **correlated errors**, it is only
**partially correctable** (IPW needs per-item selection probabilities + overlap), and it
systematically hides the correlated false-negatives we most need to catch. Clean enrichment uses
**NLI's own near-boundary uncertainty + a random/stratified base layer**, NOT judge flags.
- Verification-bias (arXiv 2509.12217; Catalog of Bias; Begg–Greenes); LLM-judge calibration
  independence (arXiv 2511.21140); Active Testing / IPW (Kossen 2021); spectrum bias.

## Synthesis
All three independently reject "enrich-via-judge → F-β at n~25-50": it is **biased (C)**,
**needs a prevalence correction the kit lacks (A)**, and **overfits regardless (B)**. Under
**OR-with-review**, the threshold only sizes the low-priority `nli_only` review queue —
**correctness is owned by the `judge_only` route** — so a fixed default is the safe, standard choice.

## Actions taken
- Threshold left at **0.70**, documented as a fixed/deferred operating point in `03_run_nli.py`.
- `13_threshold_calibration.py` hardened: header now states the do-not-calibrate-at-small-n verdict
  + the clean future recipe; `--calibrate` warns when `n < 200` (MIN_CALIBRATION_N) and when the
  set is single-class. The F-β sweep is retained but flagged EXPLORATORY-until-IPW-and-scale.
- Degenerate probe artifacts (`labels.csv` all-supported + provenance sidecar) discarded.

## When to revisit
Labels in the **hundreds**, enriched by **NLI's own uncertainty + random-stratified** (not judge),
F-β selected with **IPW prevalence correction** (then add IPW to `--calibrate`). Until then: 0.70 fixed.
