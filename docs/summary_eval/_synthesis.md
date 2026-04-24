# Summary-Eval Iteration Analysis — Cross-Source Synthesis

## Prioritized improvements (P1–P8)

| # | Title | Status | Code marker |
|---|---|---|---|
| P1 | Sentinel-tag stripping | shipped | website/features/summarization_engine/summarization/common/structured.py:744 (`_SENTINEL_TAG_RE`) |
| P2 | Faithful-fallback payload | shipped | website/features/summarization_engine/summarization/common/structured.py:687 (`_fallback_payload`) |
| P3 | Brief-repair primitives wired | shipped | website/features/summarization_engine/summarization/common/brief_repair.py + per-source schema.py |
| P4 | Archetype/format routing | shipped | website/features/summarization_engine/core/router.py + youtube/prompts.py + github/prompts.py |
| P5 | Reserved-tag slots | shipped | website/features/summarization_engine/summarization/common/structured.py:763 (`_normalize_tags(..., reserved=)`) |
| P6 | Thesis cornerstone | shipped | per-source layout.py `sub_sections["Thesis"]` (youtube/layout.py:63 and sibling layouts) |
| P7 | Mid-phase gate (Phase A → Phase B) | shipped | ops/scripts/lib/phases.py + ops/scripts/eval_loop.py |
| P8 | Numeric-grounding validator | shipped + wired | website/features/summarization_engine/evaluator/numeric_grounding.py + evaluator/consolidated.py (`compute_numeric_grounding_signal`) |

## Per-source improvements

- **YouTube**: confidence-scored format classifier wired to prompt selection (5 labels: `documentary` / `commentary` / `lecture` / `explainer` / `interview`) at `summarization/youtube/format_classifier.py` (`FORMAT_LABELS`); `yt-<channel-slug>` + format reserved-tag pair plumbed through `summarization/youtube/summarizer.py` (lines 104–108, 169).
- **Reddit**: cluster-rebalance config (`summarization/reddit/cluster_rebalance.py`, driven by `docs/summary_eval/_config/reddit_cluster_rebalance.yaml`); brief scorecard via shared brief-repair primitives; reserved `subreddit` + `thread-type` tag slots enforced in `summarization/reddit/schema.py:141` (`_normalize_tags(..., subreddit=, thread_type=)`).
- **GitHub**: archetype router with 5 labels (`library_thin` / `framework_api` / `cli_tool` / `docs_heavy` / `app_example`) at `summarization/github/archetype.py`; exposed via `core/router.py:133` (`classify_github_archetype`) and consumed by `github/prompts.py` for focus-block selection; symbol-aware evaluator config.
- **Newsletter**: branded-source registry (11 sources — Stratechery, Platformer, Lenny's, Not Boring, The Dispatch, Beehiiv, Organic Synthesis, Pragmatic Engineer, Benedict Evans, One Useful Thing, Astral Codex Ten) loaded from `docs/summary_eval/_config/branded_newsletter_sources.yaml` via `summarization/newsletter/schema.py:19` (`load_branded_newsletter_sources`); reserved brand-slug tag; liveness probe wired to eval-loop pre-flight at `ops/scripts/eval_loop.py` (`_filter_live_urls`); numeric-grounding validator now drives the consolidated evaluator faithfulness sub-signal.

## Cross-source utilities

- **Auto-eval harness** (Cross#9): `website/features/summarization_engine/evaluator/auto_eval_harness.py` + `ops/scripts/eval_loop.py --auto-eval <source>` (rubric-only scoring over the most recent iteration's summaries, emits JSON scorecard to `docs/summary_eval/auto_eval/`).
- **Liveness pre-flight**: shared across all 4 sources via `_filter_live_urls` in `ops/scripts/eval_loop.py`; extended HTML-marker list in `summarization/newsletter/liveness.py` now covers YouTube (`video unavailable`), GitHub (`404 - page not found`), Reddit (`[deleted]` / `[removed]` / banned-community) in addition to the original newsletter markers. `EVAL_SKIP_LIVENESS=1` bypasses the pre-flight for CI. Dead URLs are logged to `docs/summary_eval/_dead_urls/<source>_iter<NN>_<utc-ts>.json` so they never disappear silently.
- **Numeric-grounding sub-signal**: `compute_numeric_grounding_signal` in `website/features/summarization_engine/evaluator/consolidated.py` writes `numeric_grounding_score` (float 0.0–1.0) and `unsupported_numeric_claims` (list, capped at 5 entries) into `EvalResult.evaluator_metadata`. Backward compatible — no schema additions to `EvalResult`.

## Verification approach

After any code change in `website/features/summarization_engine/`, re-run the 31-task progress bar to confirm no regression. Targeted verification for this iteration:

- `pytest tests/unit/summarization_engine/evaluator/test_consolidated_numeric.py` (P8 wiring — 10 tests)
- `pytest tests/unit/summarization_engine/ops/test_eval_loop_liveness.py` (liveness pre-flight — 15 tests)
- `pytest tests/unit/summarization_engine/summarization/newsletter/test_liveness.py` (unchanged behavior after marker extension — 14 tests)
- `pytest tests/unit/summarization_engine/evaluator/test_consolidated.py tests/unit/summarization_engine/evaluator/test_numeric_grounding.py` (no-regression on existing evaluator coverage — 20 tests)
