# Methodology

This document specifies the evaluation methodology for the 47-zettel harness.
Every design choice cites a peer-reviewed paper or production-system writeup
from 2023-2026; see [CITATIONS.md](CITATIONS.md) for the full list.

## 1. Why a separate harness from `summary_eval_v2`

`summary_eval_v2` is a **source-iteration loop**: drive one source ingestor
(YouTube, GitHub, etc.) through iterations until composite gates pass. The
evaluator there is **uncalibrated against human judgement** — its threshold
(rho > 0.6, WARN-only) is permissive and single-annotator.

This harness is a **zettel-set audit**: take the 47 production summaries as
they exist today and (a) score them with a multi-judge + NLI panel and
(b) calibrate the composite scoring formula against a human pass. Output is
diagnostic, not gating.

## 2. The 47-zettel selection

Per the 2026-05-27 audit:
- Source: `content.workspace_zettels` joined to `content.canonical_zettels`,
  filtered to `deleted_at IS NULL` and `len(ai_summary) > 2000`.
- Total: 59 live summaries, of which 47 exceed the 2k char threshold.
- The 47 represent ~80% of the user-visible knowledge graph and are the
  zettels most likely to be opened, shared, and retrieved — the right set
  to invest annotation effort on.

## 3. Evaluation axes

We keep the existing 4 composite axes for run-001 baseline parity, but
**rename** the LLM-judged faithfulness signal currently mislabelled
`summac_lite` to `llm_entailment_check` to avoid confusion with the real
SummaC NLI baseline (Laban et al. TACL 2022). The proposed axes are:

| Axis | Definition | Current measurement | Planned addition |
|------|------------|---------------------|------------------|
| Faithfulness | No invented or contradicted claims | LLM `finesure.faithfulness` + `llm_entailment_check` | + MiniCheck-DeBERTa NLI score |
| Coverage | All key facts present | LLM `finesure.completeness` + rubric components | (none) |
| Conciseness | No redundancy / padding | LLM `finesure.conciseness` + rubric `length_*` | (none) |
| Coherence | Logical structure, clean prose | LLM `g_eval.coherence + fluency` (1-3 ordinal) | (none) |

Composite formula stays as `composite_score()` from [models.py](../../website/features/summarization_engine/evaluator/models.py)
during run-001 for parity; weights are revisited in run-005 after the
pairwise human pass.

## 4. Judges

| Role | Model | Why | Provider |
|------|-------|-----|----------|
| Primary | `gemini-2.5-flash` | Parity with prod summary path | Existing GEMINI_API_KEYS pool |
| Secondary | `claude-haiku-4-5-20251001` | Different-family judge addresses self-preference bias (Panickssery 2024; PoLL Verga 2024). Cheapest reliability lift. | New `ANTHROPIC_API_KEY` (eval-time only) |

We do NOT add a third judge (e.g. GPT-4o-mini) in v1 — PoLL's diversity
benefit plateaus quickly and the cost/operator-key-management burden grows
linearly. Three-judge jury is a v2 candidate, not v1.

**Atomic-fact extraction**: in v1 we keep Gemini Flash as the extractor for
cache parity with `summary_eval_v2`, but we add a `--swap-extractor` flag
(`gemini-2.5-flash-lite`) so the operator can run an experiment that
breaks the same-family extract-and-judge circularity (Tang 2024;
Wataoka 2024). Default is parity; the swap is opt-in for one run.

## 5. NLI scorer

**MiniCheck-DeBERTa-v3-Large** (Tang et al. EMNLP 2024).
- 435M params, ~1.7 GB RAM (fp32), ~1 GB disk.
- Best balanced accuracy on LLM-AggreFact (74-76%) among CPU-feasible
  models; matches GPT-4 at ~400× lower cost.
- Apache-2.0 / MIT licensed via `liyan06/MiniCheck` HF model.
- Runs **laptop-only**. Explicitly not on the prod droplet.

Each (summary_claim, source_paragraph) pair gets:
- `entailment_prob` ∈ [0, 1]
- `contradict_prob` ∈ [0, 1]
- Per-claim verdict in {`entailed`, `contradicted`, `neutral`}.

Combination rule (per Tang 2024 + the SemEval-2025 ensemble work):
- **Hard-fail (gate)**: `contradict_prob > 0.7 AND llm_judge_label == "contradicted"`.
- **Ranking signal**: `nli_faithfulness = mean(entailment_prob across claims)`.
- **Combined faithfulness for composite (run-003+)**: `min(llm_faithfulness, nli_faithfulness)` — conservative; either-or-both unfaithful sinks the score.

## 6. Human annotation protocol

### Round 1 (full pass, 47 zettels, ~3-4 hours)

- Randomised order, blind to automated scores.
- 4 axes scored on 1-5 Likert (faithfulness, coverage, conciseness, coherence).
- Optional 1-line comment per zettel for qualitative drift signal.

### Round 2 (intra-rater retest, random 10 zettels, ~1 hour)

- Run ≥ 1 week after round 1.
- Blind to round-1 scores (script enforces shuffle).
- Used to compute **intra-rater Krippendorff α** (ordinal weighting).
  Target ≥ 0.67 ("tentative reliability"), ideal ≥ 0.80 (Krippendorff 2018).

### Pairwise round (30 random pairs, ~1.5 hours)

- For each pair `(A, B)` drawn from the 47, annotator picks preferred summary
  (or "tie"). 30 pairs ≈ 1/36 of C(47, 2) = 1081 possible pairs — sufficient
  for fitting 4-7 weights via logistic regression (Chatbot Arena pattern,
  Chiang et al. 2024).

## 7. Statistics

All correlations are **rank-based** (Spearman ρ + Kendall τ) — composite
scores are NOT interval-scaled and have ceiling/floor effects (cite Ruscio
2008 / Deutsch et al. NAACL 2022).

Confidence intervals: **BCa bootstrap with B=10000 resamples** via
`scipy.stats.bootstrap` (since SciPy 1.7). At N=47, the 95% CI on ρ=0.6 is
roughly [0.37, 0.76] — Bonett & Wright (2000). We report CIs, never bare ρ.

**Inter / intra-rater**: `krippendorff` package (PyPI, ~5 KB) with ordinal
weighting. Cohen's κ and Fleiss κ are deliberately NOT used (wrong for
ordinal/continuous data per Krippendorff 2018).

**Composite weight refit**: pairwise logistic regression
`P(A ≻ B) = σ(w · (score_A − score_B))` via `sklearn.linear_model.LogisticRegression`
(no penalty, fit_intercept=False, constrained to weights ≥ 0 in
post-processing). This is exactly the Bradley-Terry MLE Chatbot Arena uses.

**Iteration ranking** (for v2+ runs comparing models or rubrics): Bradley-Terry
with bootstrapped rank CIs. Pointwise composite is fine for triage; BT is
correct when distinguishing close iterations (86% vs 59% accuracy at
distinguishing iteration quality — Judge-Aware Ranking 2025).

## 8. What we deliberately DO NOT do in v1

- **No Patronus Lynx / Vectara HHEM API integration** — vendor egress,
  $20/1k calls, not justified at N=47.
- **No splitting the consolidated Gemini prompt into 3 calls** — listed as
  rank-6 improvement; cost is 3× current; deferred to v2 once we know
  what the human ground truth says about run-001 baseline.
- **No RAGAS bridge resurrection** — the stub returns 0.90. We delete the
  RAGAS branch in run-001 to stop the constant from masquerading as
  signal, but we do NOT integrate real `ragas.metrics.Faithfulness` in
  v1 (it's an extra LLM call that doesn't add information vs our existing
  `finesure.faithfulness` + new MiniCheck NLI signal).
- **No multi-annotator pass** — single-operator with intra-rater
  Krippendorff retest is sufficient for an internal calibration baseline
  per Liu et al. RoSE (ACL 2023) and the COLING 2025 consistency paper.
  External-claim publishing would require ≥ 2 annotators.

## 9. Reproducibility

- `_data/<uuid>/source_text.md` is frozen at manifest-freeze time. Re-ingest
  is disabled to avoid link-rot / API drift; the eval run is reproducible
  off the frozen bundle.
- All script outputs are content-addressed in `_cache/` per the canonical
  spec in [`_config/cache_keys.md`](_config/cache_keys.md). The cascade
  rule (input-chain invalidation: atomic_facts re-run -> judges invalidate
  -> composite invalidates) is non-negotiable. Caches that share all keys
  except `response_model` flag a Gemini silent-model-routing event.
- Each `runs/<run-id>/config.json` snapshots the full judge / NLI / rubric
  versions plus a git rev-parse HEAD so the run is bisectable.

## 10. Failure-mode taxonomy (Sub-2 sweep)

Canonical 2026 taxonomy = **FRANK-7 + FineSurE refresh** (Pagnoni 2021;
Song 2024). Per [`_config/failure_taxonomy.yaml`](_config/failure_taxonomy.yaml):

| Class | Definition |
|---|---|
| EntE  | Entity error — wrong subject/object/attribute |
| PredE | Predicate error — verb/relation inconsistent |
| CircE | Circumstance error — wrong location/time/manner/modality |
| CorefE | Coreference error — pronoun bound to wrong antecedent |
| LinkE | Discourse link error — causal/temporal/contrastive flip |
| GramE | Grammatical error — meaning destroyed by syntax |
| OutE  | Out-of-article / extrinsic — claim not in source |

Plus orthogonal axes: `completeness` (missing keyfacts) and `conciseness`
(redundant bullets). FaithBench meta-overlay {`consistent`,
`questionable`, `benign`} downgrades flagged claims that are true-but-
unsupported (less operator triage noise).

Every judge call returns a per-class count vector (single structured
output, +150-300 output tokens vs the current composite-only judge — Sub-2
quantification). Per-zettel report includes `top_3_error_classes`;
aggregate dashboards use `histogram_by_class`, NOT a confusion matrix
(industry pattern is FineSurE / Lynx / Phoenix; confusion matrix is research-only).

Source-type-specific class extensions (additive) live in the same file
under `source_type_extensions:` and are triggered by source_type match.

## 11. Per-source-type surgical evaluation (Sub-1 sweep)

Industry pattern in 2026 (Patronus Glider, Vectara FaithJudge, AdaRubric):
**single judge + variable rubric**, not 10 separate prompts. We adopt
this. The shape-aware overrides already in `evaluator.v7` route the per-
source criteria from [`_config/per_source_criteria.yaml`](_config/per_source_criteria.yaml)
into one prompt at judge time. Cost delta: ~0 LLM calls — added prompt
tokens (~500/source-extension) are dominated by output tokens (Sub-1
citation: arXiv 2501.17178, "Tuning LLM Judge Design Decisions for 1/1000 of the Cost").

Per source type:
- **github**: code-block hallucination, false API names, stale versions
  (CodeXGLUE summarization + SentenceBERT scoring)
- **newsletter**: shape-respecting editorialization penalty, thesis
  capture (FacetSum facet labels)
- **reddit**: OP/comment separation, consensus signal, attribution NLI
- **youtube**: speaker self-attribution loop regex, M3-SLU speaker-attributed
  reasoning, chronological order
- **hackernews**: two-source NLI (article vs comment), news/opinion divide
- **arxiv**: contributions vs prior work, experimental caveats, novelty
  under academic_roundup shape
- **podcast**: speaker diarization, sponsor segment drop, time-code refs
- **twitter**: thread root anchor, retweet endorsement separation, sarcasm
- **linkedin**: promotional pattern detection
- **web**: boilerplate removal at INGEST time (Trafilatura/jusText), not eval

Statistical reporting: see §12.

## 12. Tiered statistical reporting at N=47 (Sub-3 sweep)

N=47 distributed across 10 source types is a directional dev set, **not** a
per-source statistical benchmark (Bonett & Wright 2000; Deutsch et al. 2022).
Per [`_config/tier_grouping.yaml`](_config/tier_grouping.yaml):

- **Tier A (N >= 10)**: full per-source Spearman/Kendall + BCa CI.
- **Tier B (3-9)**: descriptive per-source only; correlation reported at 4-mode bucket level.
- **Tier C (<3)**: adversarial probe pass/fail only; no correlation.

4-mode buckets (per Sub-1 grouping rationale):
- `code_structured` = github
- `long_form_text` = newsletter + arxiv + linkedin + web
- `social_threaded` = reddit + hackernews + twitter
- `transcript_multi_speaker` = youtube + podcast

Multiple-comparisons: **Holm-Bonferroni** at family-wise alpha=0.05
across the 10 per-source p-values (Sub-3 cite: uniformly more powerful
than Bonferroni at k=10).

Graduation: when `N(source_type) >= 10` for ALL source types, reporting
collapses back to per-source-type granularity and the 4-mode grouping
becomes a sanity-check view rather than the primary surface.

## 13. Paired-run drift detection (Sub-4 sweep)

For comparing two runs against the SAME frozen 47-zettel manifest, the
2026-standard test is **per-zettel paired BCa bootstrap + sign-flip
permutation** (arXiv 2511.19794, *When +1% Is Not Enough*). NOT
PSI/KS — PSI/KS are for unpaired feature distributions and are
explicitly flagged as "less effective for generative AI use cases" for
textual outputs.

Decision rule:
- declare significance only if the BCa interval lies entirely above/below
  zero AND the permutation p-value < threshold (default 0.05).
- block-deploy threshold: median delta > 5% with CI not crossing 0
- rollback threshold: median delta > 10%

PSI/KS are retained ONLY for input-side drift (e.g. raw token-length
distribution drifting), not for output scores.

## 14. Silent vendor-model-update detection (Sub-4 + Sub-5)

Three layers, all required:

1. **Pin DATED model aliases** in `judges.yaml` (`gemini-2.5-flash-002`,
   `claude-haiku-4-5-20251001`). Never floating aliases.
2. **Daily canary set** ([`_config/canary_set.json`](_config/canary_set.json),
   driven by `scripts/08_canary_drift.py`): 7 deterministic prompts at
   temperature 0.0; sha256 the responses; alert on hash change. Catches
   silent backend updates even when version string is pinned.
3. **Log `response_model`** field on EVERY LLM call (Gemini SDK's
   `GenerateContentResponse.modelVersion`, Anthropic's `response.model`).
   Reject runs where this is null or differs from the request.

## 15. Run registry & observability (Sub-5 sweep)

OpenTelemetry GenAI Semantic Conventions (stable since 2025) is the canonical
contract. Per-run telemetry schema lives in [`_config/run_telemetry_schema.json`](_config/run_telemetry_schema.json).

Storage: local SQLite at `_data/eval_history.sqlite` (DDL in
[`_config/run_registry_schema.sql`](_config/run_registry_schema.sql))
companion to git-tracked JSON snapshots under `runs/<run-id>/`. Pattern is
Simon Willison's `llm` CLI / Datasette / MLflow 3.0 — zero SaaS, zero
droplet impact, queryable via `09_run_registry.py query "<SQL>"`.

Three required spans per run:
- **Identity / pinning**: run_id, git_sha, dataset_sha256, config_sha256
- **Per-LLM-call**: provider, request_model, **response_model**, tokens,
  cost_usd, latency_ms, ttft_ms, cache_hit
- **Per-evaluator**: evaluator.name, prompt_version, rubric_sha256,
  implementation_fingerprint, score, parent_trace_id

Provenance / bisectability: when a metric regresses between run N and N+1,
diff their (git_sha, config_sha, dataset_sha, response_model) tuples; first
non-equal field is the culprit. If all equal, it's provider drift — which
the `response_model` log will prove.

## 16. Eval-set growth path (Sub-3 sweep)

v1 ships with the natural 47-zettel set frozen as `eval-v1.0`. Per Sub-3,
the 2026 best practice is **hybrid**: a frozen release-gate set + a rolling
drift slice continuously fed by production failures.

Growth sources, in priority order (see [`_config/adversarial_seed.json`](_config/adversarial_seed.json)):
1. **Production-failure mining** — operator-flagged "bad summary" zettels.
2. **NanoFlux dual-LLM adversarial synthesis** (arxiv 2509.23252).
3. **EvalAssist synthetic-with-bias-guards** (IBM EMNLP 2025).

These are v2 work. v1 ships with N=47 + explicit "directional only" framing.

## 17. What v1 deliberately STILL doesn't do (after Sub-2 sweep)

- **No automated keyfact-extraction-then-bipartite-match for omission** —
  FineSurE proper requires a 2nd LLM call for keyfact extraction. We rely
  on the rubric's `completeness` component + atomic_facts coverage proxy.
  Deferred to v2 once the run-001 baseline is calibrated.
- **No QAGS / QuestEval / QAFactEval QA-based omission detector** — same
  reason. Adds ~2x LLM calls per zettel; out of v1 budget.
- **No real-time CI integration** — `08_canary_drift.py` runs manually in
  v1. GitHub Actions cron wiring is v2.

## 18. Orchestration-pattern adaptations (operator pointers, 2026-05-27)

Re-cast lessons from a multi-agent product-build harness article. The article
is fundamentally about BUILDING products; we EVALUATE them. The role map
is not 1:1, so each adopted lesson is re-cast:

### 18.1 Separate "doing" from "judging" (article lesson-1)
The article warns agents are weak at judging their own work. For us, the
LLM judge is the "doer". We add a **deterministic post-judge filter** — the
judge-of-the-judge — covering all FRANK-7 classes (today's filter covers only
2 of 7). Spec: [`_config/post_judge_filter_v2.yaml`](_config/post_judge_filter_v2.yaml).
**Isolation rule**: implementation lives only inside `docs/zettel_eval_v1/`;
the prod `ops/scripts/lib/phases.py::filter_judge_false_positives` is NOT
modified to avoid regressing summary_eval_v2's calibration baseline.

### 18.2 Test behavior, not claims (article lesson-5)
Without ground truth on judge competence, every per-class count is just an
LLM assertion. We add a **judge calibration set**
([`_config/judge_calibration_set.json`](_config/judge_calibration_set.json)):
15–20 operator-hand-curated zettels with known errors of each FRANK class.
`scripts/10_judge_calibration.py` runs the judge against these BEFORE the
47-zettel pass and reports per-class detection rate. A judge that misses
seeded errors fails calibration; `02_run_judge.py` then refuses to run the
47-zettel pass unless `--override-calibration` is passed.

### 18.3 Iterate, but know when scores plateau (article lesson-8)
We MUST NOT auto-select the latest run (e.g. run-005 jury+NLI) as the
winner; later iterations sometimes regress. `scripts/11_select_best.py`
picks the best run per-axis-per-source via paired BCa bootstrap +
sign-flip permutation, with explicit `is_significant`, `is_regression`,
and promotion-rule logic.

### 18.4 Penalize "AI slop" — judge edition (article lesson-7)
The judge MUST cite a specific source span for every error class flagged;
vague "general faithfulness concern" is itself a failure mode and gets
filtered out. Operationalised inside the post-judge filter as a structural
requirement on the judge's per-class output, not as a separate detector.

### 18.5 Cost / duration as first-class metrics (article lesson-14)
Already captured in [`_config/run_telemetry_schema.json`](_config/run_telemetry_schema.json)
(OpenTelemetry GenAI semconv). `11_select_best.py` reads this and surfaces
the cost/latency tradeoff per winning run so the operator can answer:
"was the deeper harness worth it for this axis × source-type cell?"

### 18.6 What the article suggests but we deliberately REJECT

- **Planner agent at runtime** — `METHODOLOGY.md` IS the planner output;
  not a live agent.
- **Playwright UI testing** — no UI in the eval pipeline. The analog is the
  canary set (§14) + judge calibration set (§18.2).
- **Context resets** — every judge call is per-zettel, no context bloat.
- **Per-zettel sprint contracts** — superseded by `rubric_v3.yaml +
  per_source_criteria.yaml + failure_taxonomy.yaml`, which already encode
  pass criteria; a runtime contract doc would be ceremony without signal.
- **Few-shot calibration examples in the judge prompt (lesson-11)** —
  deferred per operator decision 2026-05-27. Will revisit only after run-001
  baseline shows which source types under-perform; targeted few-shot lift
  is more efficient than blanket source-type-specific few-shot.

### 18.7 Pre-flight gate sequence (the order of operations the harness enforces)

Before any of run-001 through run-005 is permitted to consume the 47-zettel manifest:

1. `01_freeze_manifest.py` populates `_data/<uuid>/` (idempotent).
2. Operator hand-curates `_config/judge_calibration_set.json` to ≥ 2 items
   per FRANK class.
3. `10_judge_calibration.py --judge <id>` confirms `overall_pass == true`
   (per-class detection rate ≥ 0.7) for that judge config.
4. `08_canary_drift.py --save-baseline` establishes the vendor-model drift
   baseline for the judge.
5. ONLY THEN does `02_run_judge.py --run-id <NNN>` proceed.
6. After all runs complete, `11_select_best.py` selects the production
   candidate, with explicit promotion-rule output.

## 19. Iter-set design — anchor + rotation (sweep-3 verdict, 2026-05-28)

Three independent research subagents (sweep-3) converged on a clear-cut
verdict — full sources cited in [CITATIONS.md §12](CITATIONS.md).

### 19.1 Design verdict: **Design A (frozen anchor across all iters)**

Every meta-eval benchmark from FRANK (2021) through JudgeBench (ICLR 2025)
and FACTS Grounding (DeepMind 2025) uses a frozen anchor scored identically
by every judge configuration. Per "When +1% Is Not Enough"
([arXiv 2511.19794](https://arxiv.org/abs/2511.19794)), unpaired tests
produce false positives at p≈0.003 on noise at our N; paired BCa on a
frozen set is the **only** design that survives. Design B (rotation) is
statistically indefensible at N=47-85; Design C (anchor + rotation hybrid)
is acceptable only if the anchor cell is large enough for per-source
histograms — which at 2-3 per source it isn't. **We collapse to pure Design
A and grow the anchor.**

### 19.2 Anchor-selection strategy: hybrid 60 / 20 / 20

- **60% top-discrimination items** — IRT 2-PL *a*-parameter from a pilot
  run (tinyBenchmarks; MetaEval AAAI 2026), spread across difficulty
  buckets (~25 % easy / 50 % medium / 25 % hard per Easy2Hard-Bench
  NeurIPS 2024).
- **20% production-failure mining** — operator-flagged "this summary is
  wrong" zettels.
- **20% adversarial / hardest-case** — lowest mean judge agreement in
  pilot.
- **Floor:** ≥ 3 anchors per retained stratum.
- **Refresh quarterly** — replace bottom-quartile-discrimination anchors
  with new production failures.

### 19.3 Sizing for our actual cell counts — operator-overridden (2026-05-28-evening)

**Operator override on sweep-3-budget verdict:** restore 1 rotation per
source per iter + restore iter-005. Rationale: thorough deep-check
analysis matters more than the marginal $1-2 of savings from rotation
elimination; iter-005's extractor-swap is needed to isolate
extractor-judge circularity even if it's a lower-info-gain knob.
Budget figures below are citation-grounded; **no vibes estimates.**

VERDICT — **40 anchors + 1 rotation per source per iter, 5 active iters:**

| Source | Total available | Anchor (every iter) | Rotation per iter |
|---|---:|---:|---:|
| youtube | 32 | 14 | 1 |
| reddit | ~15 | 6 | 1 |
| web | ~15 | 6 | 1 |
| github | ~12 | 6 | 1 |
| newsletter | ~13 | 6 | 1 |
| arxiv | 2 | 2 | 0 (no pool) |
| hackernews / podcast / twitter / linkedin | 0 each | — | — |
| **TOTAL** | **~88** | **40** | **5** (one per viable source) |

- Anchor set: **40 zettels** present in EVERY iter (paired BCa preserved
  across all C(5,2)=10 pairwise iter comparisons; Chatbot Arena anchor-
  reuse pattern per [Chiang et al. 2024](https://arxiv.org/pdf/2406.12319)).
  All viable sources clear the n=6 per-source minimum (Bonett-Wright
  [2000](https://link.springer.com/article/10.1007/BF02294183)
  directional-signal floor) except arxiv at n=2 (Tier-C descriptive only).
- Rotation: **5 fresh zettels per iter** (one per viable source, drawn
  from a 25-item pool that rotates so the same rotation zettel never
  reappears across iters). Per [tinyBenchmarks](https://arxiv.org/pdf/2402.14992)
  the anchor alone gives <2% estimation error, but the operator wants
  the rotation breadth for failure-class discovery and per-source novelty
  signal; the marginal cost (see §19.3.1) is trivial.
- Across 5 iters: 40 anchor × 5 + 5 rotation × 5 = **225 evaluator runs**
  plus 45 atomic-facts × 5 iters = **225 atomic-facts calls**, plus 18
  calibration items × 2 judges = **36 calibration calls**.
- Statistical power: per [Steiger paired formula](https://powerandsamplesize.com/calculator/pwrss-power-z-steiger/),
  n=40 anchors at r_judges≈0.85 gives ~78% power at Δρ=0.20 per iter
  pair. Rotation does not contribute to paired power (different zettels
  per iter); it contributes only to breadth coverage.

### 19.3.1 USD breakdown — every number cited

**Price inputs** (all from primary sources, 2026-05):

- Gemini 2.5 Flash: **$0.30 / M input tokens, $2.50 / M output tokens**
  ([ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)).
- Claude Haiku 4.5: **$1.00 / M input, $5.00 / M output**
  (Anthropic pricing page 2026-05).
- Typical evaluator call: ~30 k input tokens + ~2 k output (consolidated
  evaluator prompt + per-source rubric extension + atomic-facts JSON).
- Per-call unit cost derivations:
  - **Gemini eval ≈ $0.014** (30 k × $0.30/M + 2 k × $2.50/M = $0.009 + $0.005).
  - **Claude eval ≈ $0.040** (30 k × $1.00/M + 2 k × $5.00/M = $0.030 + $0.010).
  - **Atomic-facts call ≈ $0.005** (10 k input + 1 k output on Gemini Flash).
  - iter-005 atomic-facts swaps the extractor to gemini-2.5-flash-lite
    which is cheaper; using flash pricing here as a conservative upper
    bound.

**Per-iter call counts** (each iter sees 40 anchor + 5 rotation = 45 zettels):

| Iter | Gemini eval calls | Claude eval calls | Atomic-facts calls |
|---|---:|---:|---:|
| iter-001-baseline    | 45 | 0  | 45 |
| iter-002-claude      | 0  | 45 | 45 |
| iter-003-nli         | 45 | 0  | 45 |
| iter-004-jury        | 45 | 45 | 45 |
| iter-005-extract-swap| 45 | 0  | 45 |
| **5-iter totals**    | **180** | **90** | **225** |

**Calibration smoke gate** (18 items × 2 judges, runs once per judge
per session, not per iter):

| Stage | Calls | Unit cost | Subtotal |
|---|---:|---:|---:|
| Calibration Gemini | 18 | $0.014 | $0.25 |
| Calibration Claude | 18 | $0.040 | $0.72 |

**Final cost table:**

| Stage | Calls | Unit cost | Subtotal |
|---|---:|---:|---:|
| Gemini eval (anchor + rotation × 4 Gemini-using iters) | 180 | $0.014 | $2.52 |
| Claude eval (anchor + rotation × 2 Claude-using iters) | 90 | $0.040 | $3.60 |
| Atomic facts × 5 iters | 225 | $0.005 | $1.13 |
| Calibration smoke | 36 | mixed | $0.97 |
| **TOTAL** | **531** | | **~$8.22** |

**NLI** runs on the operator's laptop (CPU-local MiniCheck-DeBERTa-v3-Large
per [Tang et al. EMNLP 2024](https://arxiv.org/abs/2404.10774)) — zero
USD, ~1 s/claim CPU time.

**No vibes-estimate in this budget.** Every dollar figure derives from a
cited unit price and an explicit call-count derivation. If the operator
disputes any line item, the chain of citation is one click away.

### 19.4 Source-cell limits we are accepting explicitly

- **arxiv at N=1** → 2 anchors after Naruto top-up; Tier-C reporting only.
- **hn / podcast / twitter / linkedin at N=0** → excluded from iter-001
  through iter-004. Naruto top-up 2.0 is the remediation path.
- **No equal stratification** per Sub-3 ([Metritocracy](https://arxiv.org/pdf/2506.09813)):
  natural distribution after top-up, with floor.

### 19.5 Files this verdict produces

- `_config/anchor_set.v1.json` — content-hashed list of 40 anchor wz_uuids
  (frozen after the iter-001 pilot's 88-zettel scoring; quarterly refresh
  per [§19.2](#192-anchor-selection-strategy-hybrid-60--20--20)).
- `_config/rotation_pool.v1.json` — content-hashed list of 25 rotation
  wz_uuids partitioned by iter index (5 iters × 5 rotation each).
- `01_freeze_manifest.py` extended to emit both lists once the pilot
  has produced per-zettel IRT-discrimination signal.

### 19.4 Source-cell limits we are accepting explicitly

- **arxiv at N=1** → 1 anchor, no rotation, Tier-C reporting (descriptive
  only; no rho claim per `tier_grouping.yaml`).
- **hn / podcast / twitter / linkedin at N=0** → excluded from iter-001
  through iter-005 entirely; the harness skips their per-source folders
  for these iters. A Naruto top-up 2.0 pass (out of scope here) is the
  remediation path.
- **No equal stratification** per Sub-3 (Metritocracy arXiv 2506.09813):
  forcing equal cell sizes when natural cell is < floor wastes annotation
  budget; collapse low-volume cells instead.

### 19.5 Files this verdict produces

- `_config/anchor_set.v1.json` — content-hashed list of 21 anchor wz_uuids
  (frozen at iter-001 pilot completion; refreshed quarterly per §19.2).
- `_config/rotation_pool.v1.json` — content-hashed list of 25 rotation
  wz_uuids partitioned by iter index.
- `01_freeze_manifest.py` upgraded to emit BOTH anchor and rotation pool
  alongside the legacy manifest after the pilot run; pilot is
  iter-001-baseline with anchor=ALL 88 zettels, then trim.

## 20. P1 checks landing in iter-001 (FRANK improvements report, 2026-05-28)

Operator-provided improvements report at
[docs/research/zettel-eval-v1_improvements.md](../research/zettel-eval-v1_improvements.md)
defines 13 prioritised checks. iter-001-baseline implements the **5 P1
checks** as first-class outputs alongside the existing rubric_v3 composite:

| P1 check | Metric | iter-001 implementation |
|---|---|---|
| **Claim Attribution Gate** | ACR (Attributed Claim Rate) | Verbatim substring + judge.finesure.faithfulness; iter-003+ adds MiniCheck NLI |
| **Entity / Number / Date / Unit consistency** | ESS (Entity Slot Support) | spaCy NER + existing `compute_numeric_grounding_signal` + DATE-normalisation |
| **Predicate / Polarity / Modality** | PCS + CMS | Lexicon detectors (negation, modal verbs) + LLM-judge sub-call |
| **Per-class smoke bank** | calibration_pass | Pre-flight gate via `10_judge_calibration.py` (already wired) |
| **Completeness audit** | KCR (Key-Fact Coverage Recall) | iter-001: "lite" version reusing `rubric.completeness` (no extra LLM call); iter-002+ adds keyfact extraction + bipartite match |

Full spec: [`_config/iter_001_p1_checks.yaml`](_config/iter_001_p1_checks.yaml).

Per-zettel output adds a `p1_block` with `acr_score`, `ess_score`,
`pcs_score`, `cms_score`, `kcr_lite_score`, plus `decision`
(pass | warn | fail) and `fail_reasons[]`. iter-001 surfaces these
alongside the composite; later iters tighten thresholds and add NLI/jury
backstops per the `iter_progression` map in the YAML.
