# zettel_eval_v1

End-to-end **evaluation harness** for our 47 strong production zettels (those whose
`workspace_zettels.ai_summary` length is > 2000 chars, as identified during the
2026-05-27 audit).

This is **orthogonal** to `docs/summary_eval_v2/`, which is a per-source
iteration loop (drive a source ingestor through iterations until composite
gates pass). This harness instead **takes the current production summaries
as-is** and meta-evaluates them against (1) the existing automated judge,
(2) a diverse-family secondary judge, (3) a real NLI factuality scorer, and
(4) a human-annotation pass — so we can answer:

1. How good are the 47 production summaries today, by axis?
2. How much of the automated score is real signal vs. judge bias?
3. Which axes need the most improvement, with what confidence?
4. Are the current composite weights (0.60/0.20/0.10/0.10) defensible?

## Scope guard

- **Read-only against prod Supabase**. No writes. No schema changes. No
  migrations.
- **NLI model and Claude Haiku judge run laptop-only**. The 2 GB / 1 vCPU
  DigitalOcean droplet is explicitly out of scope; iter-03 protected knobs
  (`GUNICORN_WORKERS=2`, `--preload`, BGE int8 cascade) MUST NOT be touched.
- **Eval-time Python deps live in `requirements.txt`** in this directory,
  separate from `ops/requirements.txt`. The runtime image does not change.
- **No prod LLM-call cost increase**. Eval-time calls are billed to the
  operator's local key pool, capped per run via `--max-zettels`.

## Methodology

See [METHODOLOGY.md](METHODOLOGY.md). Every design choice is grounded in
research streams documented in [CITATIONS.md](CITATIONS.md) (2024-2026
literature, prioritised by recency).

## Directory layout

```
zettel_eval_v1/
  _config/        frozen configs (manifest, rubric, judges, NLI, annotation template)
  _cache/         content-addressed cache (ingests, atomic_facts, judge & NLI outputs)
  _data/<uuid>/   per-zettel frozen input bundle (meta, source_text, summary, atomic_facts)
  runs/<run-id>/  per-run eval outputs (config snapshot, per_zettel/, manifest_results.csv)
  annotation/     human annotation rounds (1, 2-retest, pairwise)
  analysis/       statistical reports per run (Spearman/Kendall + BCa CI, Krippendorff, BT weights)
  scripts/        the seven runnable scripts (01..07)
```

## Quickstart (planned, not yet wired)

```powershell
# 0. Operator hand-curates _config/judge_calibration_set.json (>=2 per FRANK class)
# 1. Freeze the 47-zettel manifest from prod (READ-ONLY)
python docs/zettel_eval_v1/scripts/01_freeze_manifest.py

# 2. Calibration gate (per METHODOLOGY §18.7): judge must detect >=70% of seeded errors
python docs/zettel_eval_v1/scripts/10_judge_calibration.py --judge primary
python docs/zettel_eval_v1/scripts/10_judge_calibration.py --judge secondary

# 3. Canary baseline (per Sub-4): vendor-drift hash, save once
python docs/zettel_eval_v1/scripts/08_canary_drift.py --save-baseline

# 4. Run the five iters in order (each writes runs/iter-NNN-<label>/<source>/...)
python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-001-baseline
python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-002-claude
python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-003-nli
python docs/zettel_eval_v1/scripts/03_run_nli.py    --iter iter-003-nli
python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-004-jury
python docs/zettel_eval_v1/scripts/03_run_nli.py    --iter iter-004-jury
python docs/zettel_eval_v1/scripts/02_run_judge.py --iter iter-005-extract-swap
python docs/zettel_eval_v1/scripts/03_run_nli.py    --iter iter-005-extract-swap

# 5. Compute per-source composites + REPORT.md per iter
python docs/zettel_eval_v1/scripts/04_compute_composite.py --iter iter-001-baseline
# ...repeat for all 5 iters...

# 6. Annotation kit + human round-1 + retest + pairwise
python docs/zettel_eval_v1/scripts/05_annotation_kit.py --emit
# ...annotator fills annotation/round-1/responses.csv...
python docs/zettel_eval_v1/scripts/05_annotation_kit.py --ingest

# 7. Stats: per-axis Spearman/Kendall + BCa CI per source (Tier A) + per mode (Tier B)
python docs/zettel_eval_v1/scripts/06_run_stats.py --iter iter-001-baseline

# 8. Diff iters per source (the surgical "where does X regress for github?" surface)
python docs/zettel_eval_v1/scripts/07_diff_runs.py --base iter-001-baseline --candidate iter-004-jury

# 9. Pick best iter per axis per source (lesson-8: NEVER auto-select latest)
python docs/zettel_eval_v1/scripts/11_select_best.py

# 10. Local SQLite registry for queryable history
python docs/zettel_eval_v1/scripts/09_run_registry.py init
python docs/zettel_eval_v1/scripts/09_run_registry.py ingest-iter iter-001-baseline
```

## Status

| File | Status |
|------|--------|
| README.md, METHODOLOGY.md (17 sections), CITATIONS.md (11 sections, ~80 sources) | drafted |
| `_config/manifest.json` | schema-only; populated by `01_freeze_manifest.py` |
| `_config/rubric_v3.yaml` | drafted; references failure_taxonomy + per_source + tier_grouping |
| `_config/judges.yaml` | drafted; DATED model pins per Sub-4 mandate |
| `_config/nli_config.yaml` | drafted |
| `_config/annotation_template.csv` | drafted |
| `_config/failure_taxonomy.yaml` | drafted; FRANK-7 + FineSurE + source-specific extensions (sweep-2) |
| `_config/per_source_criteria.yaml` | drafted; per-source incremental criteria for all 10 sources (sweep-2) |
| `_config/tier_grouping.yaml` | drafted; Tier A/B/C statistical reporting + 4-mode grouping (sweep-2) |
| `_config/canary_set.json` | drafted; 7 deterministic prompts for daily drift hash (sweep-2) |
| `_config/cache_keys.md` | drafted; canonical cache-key composition with response_model field (sweep-2) |
| `_config/run_registry_schema.sql` | drafted; SQLite DDL (sweep-2) |
| `_config/run_telemetry_schema.json` | drafted; OpenTelemetry GenAI semconv (sweep-2) |
| `_config/adversarial_seed.json` | drafted placeholder; v2 work (sweep-2) |
| `_config/judge_calibration_set.json` | drafted schema + 2 worked examples; 14 slots pending hand-curation (orchestration sweep) |
| `_config/post_judge_filter_v2.yaml` | drafted spec; full FRANK-7 deterministic detector chains (orchestration sweep) |
| `_config/iter_001_p1_checks.yaml` | drafted spec; 5 P1 checks (ACR / ESS / PCS+CMS / smoke / KCR-lite) for iter-001 (FRANK improvements report) |
| `scripts/01_freeze_manifest.py` | **working** (read-only Supabase pull) |
| `scripts/02_run_judge.py` ... `07_diff_runs.py` | argparse skeleton + planned data flow |
| `scripts/08_canary_drift.py` | argparse skeleton (sweep-2) |
| `scripts/09_run_registry.py` | argparse skeleton (sweep-2) |
| `scripts/10_judge_calibration.py` | argparse skeleton (orchestration sweep, lesson-5) |
| `scripts/11_select_best.py` | argparse skeleton (orchestration sweep, lesson-8) |

Scripts 02-11 are deliberately scaffolds — their wiring is the next iteration
once the operator approves the methodology in METHODOLOGY.md.

## Pre-flight gate sequence (orchestration sweep §18.7)

Before any of run-001 ... run-005 is permitted to consume the 47-zettel manifest:

1. `01_freeze_manifest.py` populates `_data/<uuid>/`.
2. Operator hand-curates `_config/judge_calibration_set.json` to >= 2 items per FRANK class.
3. `10_judge_calibration.py --judge <id>` confirms `overall_pass == true` for the judge.
4. `08_canary_drift.py --save-baseline` establishes the vendor-model drift baseline.
5. ONLY THEN `02_run_judge.py --run-id <NNN>` proceeds.
6. After all runs complete, `11_select_best.py` picks the production candidate via paired BCa bootstrap.
