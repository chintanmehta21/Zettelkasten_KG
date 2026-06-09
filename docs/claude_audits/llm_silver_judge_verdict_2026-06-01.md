# LLM-Silver Judge-Config Verdict (06) — 2026-06-01

**Status: SILVER — directional only. NOT a human-accuracy result.**

## What this is / is NOT

- The "human" annotations were produced by **LLM subagents** (7 parallel raters, identical anchored rubric, real sources fetched), not a human. 06 therefore measures **judge-config-vs-LLM-silver-annotator agreement**, *not* accuracy against human judgment.
- Use it as: a pipeline-mechanics proof + a directional reference for which judge config *might* align best with careful human scoring.
- Do NOT cite it as the accuracy verdict. The real verdict requires the operator to fill `annotation/round-1/responses.csv` (the human slot, deliberately left pristine) and re-run 06.

## Method

- Silver annotations: `annotation/round-1/responses_llm.csv` (81) — 4 axes (faithfulness/coverage/conciseness/coherence) 1–5, source-fetched, shared rubric. QA passed (completeness, range, construct validity, intra-rater faithfulness Δ=0.00, 2/2 adversarial defect confirmations).
- Ingested into an **isolated** annotation root (`analysis/_llm_silver/annot_root/`) so the human `responses.csv` slot is untouched.
- `06_run_stats.py --iter <it> --annotation-root <silver> --bootstrap-B 2000` per config. Pure stats, **$0, no API keys**. N=81 paired (0 backfilled-excluded) for every config.
- 06 axis map: faithfulness→`finesure_faithfulness`, coverage→`finesure_completeness`, conciseness→`finesure_conciseness`, coherence→`g_eval_coherence` (rescaled).

## Results — Spearman ρ [BCa 95% CI], n=81

| Config (iter) | faithfulness | coverage | conciseness | coherence |
|---|---|---|---|---|
| gemini-baseline (iter-001) | +0.152 [−0.048, +0.349] | +0.273 [+0.055, +0.458] | +0.028 [−0.197, +0.241] | +0.320 [+0.104, +0.517] |
| **claude** (iter-002) | **+0.311 [+0.109, +0.496]** | +0.259 [+0.032, +0.482] | **+0.437 [+0.226, +0.598]** | +0.364 [+0.154, +0.544] |
| gemini+nli (iter-003) | +0.152 [−0.048, +0.349] | +0.273 [+0.055, +0.458] | +0.028 [−0.197, +0.241] | +0.320 [+0.104, +0.517] |
| **jury-mean** (iter-004) | +0.219 [+0.023, +0.412] | **+0.300 [+0.090, +0.470]** | +0.336 [+0.095, +0.518] | **+0.404 [+0.192, +0.598]** |
| extract-swap (iter-005) | +0.111 [−0.102, +0.310] | +0.267 [+0.058, +0.460] | +0.178 [−0.022, +0.372] | +0.237 [+0.020, +0.434] |

Best per axis: faithfulness→**claude**, coverage→**jury-mean**, conciseness→**claude**, coherence→**jury-mean**.

## Findings

1. **claude is the front-runner.** Only config whose faithfulness ρ is significantly >0 (CI low +0.109), and it owns the single strongest cell (conciseness +0.437, CI low +0.226). Positive on all 4 axes.
2. **jury-mean (PoLL) a close second** — best on coverage + coherence, solid elsewhere. **claude vs jury-mean is NOT statistically separated** (CIs overlap on every axis).
3. **NLI (iter-003) ≡ baseline (iter-001), exactly** — 0/324 rubric-score-cell diffs across 81×4. NLI is a contradiction **gate** (changes hard-fail/review labels), not a scorer, so it cannot move the score-vs-silver correlation. Its value (hallucination flagging) is invisible to 06 by design.
4. **extract-swap (iter-005) is the weakest** — faithfulness (+0.111) and conciseness (+0.178) CIs both cross 0 (no reliable signal). The flash-lite extractor swap did **not** improve, and plausibly hurt, alignment.
5. **Magnitudes are modest (0.0–0.44) and CIs wide/overlapping.** Directional, not definitive.

## Caveats (read before quoting any number)

- **Silver ≠ human.** This is judge-vs-LLM-annotator agreement.
- **41% of the set (33/81) is YouTube**, scored metadata-only (spoken content unverifiable) → faithfulness/coverage signal is diluted on those.
- N=81 with wide CIs → per-axis "winners" are mostly not separated from the runner-up.
- The intra-rater faithfulness Δ=0.00 reflects LLM self-consistency, not a human test-retest bound.

## Bonus product bug surfaced by the silver pass

The **GitHub source summarizer fabricates a "Public API / Interfaces" section** with non-existent endpoints/flags — theiagen `/center --pathogen --Please` (verified absent from the live repo), Dendron `/sub`, Athens `@gmail.com //summary` — plus empty `''` pathogen-category placeholders and duplicated Overview blocks. 3/12 GitHub items affected → a systematic extraction artifact in the github summarizer, worth a real fix.

## Next step (the true verdict)

Operator fills `annotation/round-1/responses.csv` (human scores) → `05 --ingest --round 1` → re-run 06 (recommend B=10000) per config. Then this silver table becomes the comparison baseline ("did the human verdict agree with the silver one?").
