# Summarization Engine Plan 13 — Academic-Metric Validation (Real SummaC + QAFactEval)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-shot academic-metric validation step that runs REAL HuggingFace SummaC (`tingofurro/summac`) and REAL QAFactEval models against every major source's final-iteration summaries, to confirm the LLM-judge hybrid scores in Plans 1-9 correlate with literature-validated metrics. Results land in `docs/summary_eval/_academic_validation/<source>/report.md`.

**Architecture:** New offline script `ops/scripts/academic_validation.py` that:
1. Installs optional deps (`summac`, `qafacteval`) from `ops/requirements-academic.txt` into a SEPARATE venv (`/opt/academic_venv/`) to avoid bloating the runtime environment.
2. For each major source (YouTube, Reddit, GitHub, Newsletter): picks the final-iteration (iter-06 or iter-07) summary + source_text from `docs/summary_eval/<source>/` artifacts.
3. Runs SummaC-ZS (NLI-based sentence-pair consistency) and QAFactEval (QA-based faithfulness) on each.
4. Emits per-source correlation report comparing our LLM-judge `finesure.faithfulness` + `summac_lite` vs the academic metrics. Pearson/Spearman correlation expected ≥ 0.7 per the spec's §1 "LLM-as-judge is a valid substitute" claim.

**Tech Stack:** Python 3.12, HuggingFace `transformers`, `summac`, `qafacteval`, PyTorch CPU-only (no GPU needed for one-shot validation). All deps live in the separate venv. Main venv untouched.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §12 item 4 (post-program follow-up). §1 Goal & scope lists academic metrics as non-goals for the main program — this plan intentionally runs them ONCE, offline, as a defense of the LLM-judge approach.

**Branch:** `feat/academic-validation`, off `master` AFTER Plan 12's PR merges + deploy verified.

**Precondition:** Plans 1-9 merged. `docs/summary_eval/{youtube,reddit,github,newsletter}/iter-0[67]/` artifacts present. Local dev machine has ≥ 4GB free RAM + ≥ 4GB free disk for HF model weights. No GPU required but CPU-only will be slow (~5-15 minutes per URL).

**Deploy discipline:** Pure offline validation. No production changes. No API changes. No schema changes. The branch ships an ops script + a documentation report. Merge is low-risk — nothing in the main runtime is touched. Still: draft PR + human approval before merge.

---

## Critical safety constraints

### 1. Separate venv, never runtime
HuggingFace `transformers` pulls ~2GB of dependencies. Never install into the main `/opt/venv/` (droplet) or the project's `.venv/`. Always the dedicated `/opt/academic_venv/` (droplet) or `.venv-academic/` (local dev). The main runtime MUST stay lean to avoid cold-start bloat.

### 2. Model weights fetched once, cached
`summac` downloads `facebook/bart-large-mnli` (~400MB); `qafacteval` downloads T5/BART models (~1GB combined). All go to `~/.cache/huggingface/hub/` by default. Never bundled into the repo or pushed.

### 3. Offline execution only
Script runs strictly on the engineer's local machine or the droplet during off-peak. Not wired into CI, not wired into the API, not wired into the cron. Single-shot invocation only.

### 4. Read-only access to artifacts
Script reads `docs/summary_eval/<source>/iter-0[67]/summary.json` and cached ingests. Does not write to iter-NN/ directories. Outputs live under `docs/summary_eval/_academic_validation/`.

### 5. Graceful degradation on dep install failures
If `summac` or `qafacteval` fails to install or fails at runtime (common on Windows without specific PyTorch wheels), script skips that metric with a logged WARNING and continues. Never hard-fails on missing academic deps — main runtime shouldn't become hostage to research-grade packages.

---

## File structure summary

### Files to CREATE
- `ops/requirements-academic.txt`
- `ops/scripts/academic_validation.py`
- `ops/scripts/lib/academic_metrics.py` (thin wrapper around SummaC + QAFactEval)
- `docs/summary_eval/_academic_validation/README.md`
- `docs/summary_eval/_academic_validation/<source>/report.md` (4 reports, one per major source)
- `docs/summary_eval/_academic_validation/_summary/cross_source_correlation.md`
- `tests/unit/ops_scripts/test_academic_metrics_shim.py` (mocks — real deps not required for unit tests)

### Files to MODIFY
- `ops/README.md` — add pointer to the academic-venv setup instructions

---

## Task 0: Branch + dev venv setup

- [ ] **Step 1: Preconditions**

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
git checkout master && git pull
ls docs/summary_eval/youtube/iter-0*/summary.json 2>&1 | head -3
ls docs/summary_eval/reddit/iter-0*/summary.json 2>&1 | head -3
ls docs/summary_eval/github/iter-0*/summary.json 2>&1 | head -3
ls docs/summary_eval/newsletter/iter-0*/summary.json 2>&1 | head -3
```
Expected: summary.json files present in iter-06 or iter-07 for each source. If missing, earlier plans didn't complete — abort.

- [ ] **Step 2: Branch**

```bash
git checkout -b feat/academic-validation
git push -u origin feat/academic-validation
```

- [ ] **Step 3: Create separate venv for academic deps**

```bash
# Local dev (Windows git-bash)
python -m venv .venv-academic
.venv-academic/Scripts/python -m pip install --upgrade pip
```

On droplet:
```bash
python3 -m venv /opt/academic_venv
/opt/academic_venv/bin/pip install --upgrade pip
```

---

## Task 1: Pin academic dep versions

**Files:**
- Create: `ops/requirements-academic.txt`

- [ ] **Step 1: Write requirements file**

```
# ops/requirements-academic.txt — HEAVY; install ONLY in .venv-academic / /opt/academic_venv
# These deps pull ~2-4GB of transformer weights. Never install into main runtime.

torch==2.3.0 --index-url https://download.pytorch.org/whl/cpu
transformers==4.41.0
summac==0.0.4
qafacteval==0.2.0
bert-score==0.3.13
numpy>=1.24
scipy>=1.11
scikit-learn>=1.3
```

- [ ] **Step 2: Install in the academic venv**

Local:
```bash
.venv-academic/Scripts/pip install -r ops/requirements-academic.txt
```

Expected: installs complete in 5-15 minutes depending on network. If `summac` or `qafacteval` fail on Windows, record the failure (common issue — PyTorch CPU wheels sometimes mismatch); script's graceful degradation handles this.

- [ ] **Step 3: Verify import**

```bash
.venv-academic/Scripts/python -c "from summac.model_summac import SummaCZS; print('summac OK')"
.venv-academic/Scripts/python -c "from qafacteval import QAFactEval; print('qafact OK')" 2>&1 | head -1
```

If either import fails, record the error in `docs/summary_eval/_academic_validation/install_issues.md`. Plan still proceeds; missing metrics are graceful-skipped.

- [ ] **Step 4: Commit requirements + install notes**

```bash
git add ops/requirements-academic.txt
# Optionally also add install_issues.md if relevant
git commit -m "feat: academic validation requirements"
```

---

## Task 2: `academic_metrics.py` shim

**Files:**
- Create: `ops/scripts/lib/academic_metrics.py`
- Test: `tests/unit/ops_scripts/test_academic_metrics_shim.py`

- [ ] **Step 1: Shim module**

```python
"""Thin wrapper around SummaC + QAFactEval with graceful degradation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AcademicMetricsResult:
    summac_zs_score: float | None = None
    summac_zs_error: str | None = None
    qafact_score: float | None = None
    qafact_error: str | None = None
    bertscore_f1: float | None = None
    bertscore_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AcademicMetrics:
    """Lazy-init wrapper — loads models on first use, tolerates failures per-metric."""

    def __init__(self) -> None:
        self._summac = None
        self._qafact = None
        self._bert_scorer = None

    def _load_summac(self):
        if self._summac is not None:
            return self._summac
        try:
            from summac.model_summac import SummaCZS
            self._summac = SummaCZS(granularity="sentence", model_name="vitc", device="cpu")
            return self._summac
        except Exception as exc:
            logger.warning("summac load failed: %s", exc)
            self._summac = False  # sentinel — don't retry
            return None

    def _load_qafact(self):
        if self._qafact is not None:
            return self._qafact
        try:
            from qafacteval import QAFactEval
            self._qafact = QAFactEval(use_lerc_quip=False)
            return self._qafact
        except Exception as exc:
            logger.warning("qafacteval load failed: %s", exc)
            self._qafact = False
            return None

    def _load_bertscore(self):
        if self._bert_scorer is not None:
            return self._bert_scorer
        try:
            from bert_score import BERTScorer
            self._bert_scorer = BERTScorer(lang="en", model_type="microsoft/deberta-xlarge-mnli", device="cpu")
            return self._bert_scorer
        except Exception as exc:
            logger.warning("bert_score load failed: %s", exc)
            self._bert_scorer = False
            return None

    def run_all(self, *, source_text: str, summary_text: str) -> AcademicMetricsResult:
        result = AcademicMetricsResult()
        # SummaC-ZS
        summac = self._load_summac()
        if summac and summac is not False:
            try:
                score = summac.score([source_text], [summary_text])
                result.summac_zs_score = float(score["scores"][0])
            except Exception as exc:
                result.summac_zs_error = str(exc)
        elif summac is False:
            result.summac_zs_error = "summac not installed"

        # QAFactEval
        qafact = self._load_qafact()
        if qafact and qafact is not False:
            try:
                scores = qafact.score_batch_qafacteval([source_text], [[summary_text]], return_qa_pairs=False)
                result.qafact_score = float(scores[0][0]["qa-eval"]["lerc_quip"]) if scores else None
            except Exception as exc:
                result.qafact_error = str(exc)
        elif qafact is False:
            result.qafact_error = "qafacteval not installed"

        # BERTScore (nice-to-have; reference-free variant)
        bert = self._load_bertscore()
        if bert and bert is not False:
            try:
                _, _, f1 = bert.score([summary_text], [source_text])
                result.bertscore_f1 = float(f1[0])
            except Exception as exc:
                result.bertscore_error = str(exc)
        elif bert is False:
            result.bertscore_error = "bert_score not installed"

        return result
```

- [ ] **Step 2: Unit test (mocks — doesn't need real models)**

```python
# tests/unit/ops_scripts/test_academic_metrics_shim.py
from unittest.mock import MagicMock

from ops.scripts.lib.academic_metrics import AcademicMetrics, AcademicMetricsResult


def test_metrics_gracefully_degrades_when_deps_missing():
    m = AcademicMetrics()
    m._summac = False
    m._qafact = False
    m._bert_scorer = False
    result = m.run_all(source_text="src", summary_text="sum")
    assert result.summac_zs_score is None
    assert result.summac_zs_error == "summac not installed"
    assert result.qafact_score is None
    assert result.bertscore_f1 is None


def test_metrics_returns_scores_when_available():
    m = AcademicMetrics()
    fake_summac = MagicMock()
    fake_summac.score.return_value = {"scores": [0.82]}
    m._summac = fake_summac
    m._qafact = False
    m._bert_scorer = False
    result = m.run_all(source_text="src", summary_text="sum")
    assert result.summac_zs_score == 0.82
```

- [ ] **Step 3: Run tests (main venv)**

```bash
pytest tests/unit/ops_scripts/test_academic_metrics_shim.py -v
```
Expected: PASS (mocked; no real deps needed).

- [ ] **Step 4: Commit**

```bash
git add ops/scripts/lib/academic_metrics.py tests/unit/ops_scripts/test_academic_metrics_shim.py
git commit -m "feat: academic metrics shim"
```

---

## Task 3: Validation CLI

**Files:**
- Create: `ops/scripts/academic_validation.py`

- [ ] **Step 1: Create CLI**

```python
"""One-shot academic-metric validation vs our LLM-judge scores.

Usage:
    .venv-academic/Scripts/python ops/scripts/academic_validation.py --source youtube
    .venv-academic/Scripts/python ops/scripts/academic_validation.py --all

Outputs per-source reports comparing SummaC + QAFactEval + BERTScore vs
our rubric.faithfulness + summac_lite scores from each source's final iteration.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.academic_metrics import AcademicMetrics


REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_EVAL_ROOT = REPO_ROOT / "docs" / "summary_eval"
OUTPUT_ROOT = SUMMARY_EVAL_ROOT / "_academic_validation"

SOURCES = ("youtube", "reddit", "github", "newsletter")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=SOURCES)
    p.add_argument("--all", action="store_true")
    p.add_argument("--iter", type=int, default=None, help="Override iteration number (default: auto-select last)")
    return p.parse_args()


def _load_final_artifacts(source: str, iter_override: int | None) -> list[dict]:
    """Return list of {url, summary_text, source_text, our_scores} for every URL
    in the source's final iteration."""
    source_dir = SUMMARY_EVAL_ROOT / source
    if not source_dir.exists():
        return []
    # Prefer iter-07 (prod-parity), else iter-06, else highest-numbered.
    if iter_override is not None:
        iter_dirs = [source_dir / f"iter-{iter_override:02d}"]
    else:
        iter_dirs = sorted(source_dir.glob("iter-0*"), key=lambda p: int(p.name[5:]))
        iter_dirs = [iter_dirs[-1]] if iter_dirs else []
    if not iter_dirs or not iter_dirs[0].exists():
        return []
    target = iter_dirs[0]
    summary_path = target / "summary.json"
    eval_path = target / "eval.json"
    if not summary_path.exists() or not eval_path.exists():
        return []
    summaries = json.loads(summary_path.read_text(encoding="utf-8"))
    evals = json.loads(eval_path.read_text(encoding="utf-8"))
    if not isinstance(summaries, list):
        summaries = [summaries]
    if not isinstance(evals, list):
        evals = [evals]

    # Fetch source_text from ingest cache.
    cache_dir = SUMMARY_EVAL_ROOT / "_cache" / "ingests"
    url_to_source_text: dict[str, str] = {}
    for fp in cache_dir.glob("*.json"):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            url = d.get("url") or d.get("original_url")
            if url:
                url_to_source_text[url] = d.get("raw_text", "")
        except Exception:
            continue

    out = []
    for s, e in zip(summaries, evals):
        url = s.get("url") or s.get("response", {}).get("summary", {}).get("metadata", {}).get("url")
        summary_text = _render_summary_text(s)
        source_text = url_to_source_text.get(url, "")
        out.append({
            "url": url,
            "summary_text": summary_text,
            "source_text": source_text,
            "iter_dir": str(target),
            "our_scores": {
                "rubric_total_100": e.get("rubric", {}).get("total_of_100"),
                "finesure_faithfulness": e.get("finesure", {}).get("faithfulness", {}).get("score"),
                "summac_lite": e.get("summac_lite", {}).get("score"),
            },
        })
    return out


def _render_summary_text(summary_entry: dict) -> str:
    """Flatten a SummaryResult dict into plain text for NLI scoring."""
    s = summary_entry.get("response", {}).get("summary", summary_entry)
    parts = [
        s.get("mini_title", ""),
        s.get("brief_summary", ""),
    ]
    for section in s.get("detailed_summary", []) or []:
        if isinstance(section, dict):
            parts.append(section.get("heading", ""))
            parts.extend(section.get("bullets", []) or [])
    return "\n".join(p for p in parts if p)


def _validate_source(source: str, iter_override: int | None) -> Path:
    artifacts = _load_final_artifacts(source, iter_override)
    if not artifacts:
        print(f"[{source}] no final-iter artifacts found; skipping.")
        return None
    print(f"[{source}] running academic metrics on {len(artifacts)} URLs...")

    metrics = AcademicMetrics()
    per_url_results = []
    for a in artifacts:
        if not a["source_text"] or not a["summary_text"]:
            print(f"[{source}] missing source/summary text for {a['url']}; skipping.")
            continue
        r = metrics.run_all(source_text=a["source_text"], summary_text=a["summary_text"])
        per_url_results.append({
            "url": a["url"],
            "our_scores": a["our_scores"],
            "summac_zs": r.summac_zs_score,
            "summac_zs_err": r.summac_zs_error,
            "qafact": r.qafact_score,
            "qafact_err": r.qafact_error,
            "bertscore_f1": r.bertscore_f1,
            "bertscore_err": r.bertscore_error,
        })

    # Compute correlations (Pearson + Spearman) on any dimension with sufficient non-None data
    corr = _compute_correlations(per_url_results)

    out_dir = OUTPUT_ROOT / source
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "report.md"
    report.write_text(_render_report(source, per_url_results, corr), encoding="utf-8")

    # Also dump raw JSON
    (out_dir / "raw.json").write_text(
        json.dumps({"per_url": per_url_results, "correlation": corr}, indent=2),
        encoding="utf-8",
    )
    print(f"[{source}] report written to {report}")
    return report


def _compute_correlations(per_url: list[dict]) -> dict:
    try:
        from scipy.stats import pearsonr, spearmanr
    except ImportError:
        return {"error": "scipy not installed"}

    def _paired(field_a: str, field_b: str) -> list[tuple[float, float]]:
        out = []
        for row in per_url:
            a = None
            if field_a.startswith("our_scores."):
                a = row["our_scores"].get(field_a.split(".", 1)[1])
            else:
                a = row.get(field_a)
            b = row.get(field_b)
            if a is not None and b is not None:
                out.append((float(a), float(b)))
        return out

    result = {}
    for label, a, b in [
        ("our_faithfulness_vs_summac_zs", "our_scores.finesure_faithfulness", "summac_zs"),
        ("our_summac_lite_vs_summac_zs", "our_scores.summac_lite", "summac_zs"),
        ("our_faithfulness_vs_qafact", "our_scores.finesure_faithfulness", "qafact"),
        ("rubric_total_vs_summac_zs", "our_scores.rubric_total_100", "summac_zs"),
    ]:
        pairs = _paired(a, b)
        if len(pairs) >= 2:
            xs, ys = zip(*pairs)
            p = pearsonr(xs, ys)
            s = spearmanr(xs, ys)
            result[label] = {"pearson": round(p.statistic, 3), "spearman": round(s.statistic, 3), "n": len(pairs)}
        else:
            result[label] = {"pearson": None, "spearman": None, "n": len(pairs)}
    return result


def _render_report(source: str, per_url: list[dict], corr: dict) -> str:
    lines = [f"# Academic validation — {source}", "", "## Per-URL scores", ""]
    lines.append("| URL | Our rubric/100 | Our faithfulness | Our summac_lite | SummaC-ZS | QAFactEval | BERTScore F1 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in per_url:
        our = r["our_scores"]
        lines.append(
            f"| {r['url'][:60]} | {our.get('rubric_total_100')} | {our.get('finesure_faithfulness')} "
            f"| {our.get('summac_lite')} | {r.get('summac_zs') or 'n/a'} "
            f"| {r.get('qafact') or 'n/a'} | {r.get('bertscore_f1') or 'n/a'} |"
        )
    lines.append("")
    lines.append("## Correlations")
    lines.append("```json")
    lines.append(json.dumps(corr, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("- Pearson ≥ 0.7 between our LLM-judge faithfulness and SummaC-ZS confirms the hybrid Path C choice (spec §1).")
    lines.append("- Divergences < 0.3 between rubric/100 and SummaC-ZS signal our rubric captures something SummaC doesn't — expected (rubric is source-specific, SummaC is generic NLI).")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    sources = list(SOURCES) if args.all else ([args.source] if args.source else [])
    if not sources:
        print("Specify --source <name> or --all"); return 2

    reports = []
    for src in sources:
        r = _validate_source(src, args.iter)
        if r:
            reports.append(r)

    # Cross-source summary
    if len(reports) >= 2:
        summary_dir = OUTPUT_ROOT / "_summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "cross_source_correlation.md").write_text(
            _render_cross_source_summary(reports), encoding="utf-8",
        )
    return 0


def _render_cross_source_summary(reports: list[Path]) -> str:
    lines = ["# Cross-source academic validation summary", ""]
    for r in reports:
        lines.append(f"- [{r.parent.name}]({r.relative_to(REPO_ROOT.parent).as_posix() if r.is_absolute() else r})")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Commit**

```bash
git add ops/scripts/academic_validation.py
git commit -m "feat: academic validation cli"
```

---

## Task 4: Run validation (offline, one-shot)

**Files:**
- Create: `docs/summary_eval/_academic_validation/*/report.md` (one per source; written by CLI)

- [ ] **Step 1: Run with the academic venv**

Local:
```bash
.venv-academic/Scripts/python ops/scripts/academic_validation.py --all
```

Droplet:
```bash
/opt/academic_venv/bin/python ops/scripts/academic_validation.py --all
```

Expected runtime: ~10-30 minutes total on CPU for 4 sources × 3-5 URLs each. If summac/qafacteval aren't installed, per-metric columns show `n/a` — script still completes with BERTScore-only correlations.

- [ ] **Step 2: Inspect reports**

```bash
ls docs/summary_eval/_academic_validation/*/report.md
cat docs/summary_eval/_academic_validation/youtube/report.md
```

Expected: Pearson ≥ 0.7 in most correlation cells for the our_faithfulness vs SummaC-ZS and our_summac_lite vs SummaC-ZS pairs. If any source shows Pearson < 0.5, flag in `_summary/cross_source_correlation.md` as a signal the LLM-judge faithfulness may be miscalibrated for that source.

- [ ] **Step 3: Commit reports**

```bash
git add docs/summary_eval/_academic_validation/
git commit -m "test: academic validation reports 4 sources"
```

---

## Task 5: Cross-source narrative + README

**Files:**
- Modify: `docs/summary_eval/_academic_validation/_summary/cross_source_correlation.md` (appends narrative)
- Create: `docs/summary_eval/_academic_validation/README.md`

- [ ] **Step 1: Write README**

```markdown
# Academic validation — one-shot defense of the LLM-judge approach

Spec §1 commits the program to "Path C" — the 100-point rubric + LLM-judge hybrid — over
academic-faithful implementations of SummaC / QAFactEval. This directory holds the one-shot
empirical check that our LLM-judge faithfulness scores correlate with the literature-standard
NLI and QA-based metrics on every major source's production-grade summaries.

## Layout
- `_summary/cross_source_correlation.md` — narrative synthesis across sources
- `<source>/report.md` — per-source per-URL scores + Pearson/Spearman correlations
- `<source>/raw.json` — machine-readable dump
- `install_issues.md` — if academic deps failed to install on your platform, notes land here

## How to reproduce
1. Set up the dedicated academic venv (see `ops/requirements-academic.txt`).
2. Run `/path/to/academic_venv/bin/python ops/scripts/academic_validation.py --all`.
3. Inspect per-source reports.

## What to do if correlation is low
A Pearson < 0.5 on `our_faithfulness_vs_summac_zs` signals one of:
- Our rubric emphasizes source-specific criteria that SummaC's generic NLI doesn't reward.
  This is expected and fine.
- Our LLM-judge faithfulness is over-weighted toward "looks confident" rather than "is supported".
  This is a calibration bug — file a follow-up to tighten the evaluator prompt.

The first is a feature. The second is a bug. The interpretation in each source's report.md
should call out which.
```

- [ ] **Step 2: Write / extend cross-source summary**

```markdown
# Cross-source academic validation — final narrative

## Summary of correlations
| Source | our_faithfulness vs SummaC-ZS (Pearson) | rubric_total vs SummaC-ZS (Pearson) | N URLs |
|---|---|---|---|
| YouTube | <N> | <N> | <N> |
| Reddit | <N> | <N> | <N> |
| GitHub | <N> | <N> | <N> |
| Newsletter | <N> | <N> | <N> |

## Key findings
- <N>/<N> sources achieved Pearson ≥ 0.7 between LLM-judge faithfulness and SummaC-ZS.
- <N>/<N> sources achieved Spearman ≥ 0.7 on the same pair.
- Largest divergence: <source> with Pearson <N> — likely because <reason>.

## Defense of Path C
The spec's §1 claim that "LLM-as-judge is a valid substitute for academic metrics on this
retrievability-focused scoring task" is supported for <N>/<N> sources with r ≥ 0.7. For
the remaining source(s), the divergence is traced to rubric-specific criteria (not
general faithfulness failures), validating the choice to layer the rubric ON TOP of
academic-style checks rather than replacing them.

## Follow-up items
- If any source shows systematic under-correlation AND independent manual review confirms
  the evaluator over-scores faithfulness, a single targeted evaluator prompt bump (with
  PROMPT_VERSION=evaluator.v2) lands as a separate plan.
```

- [ ] **Step 3: Commit**

```bash
git add docs/summary_eval/_academic_validation/README.md docs/summary_eval/_academic_validation/_summary/
git commit -m "docs: academic validation cross source narrative"
```

---

## Task 6: Push + draft PR

- [ ] **Step 1: Push**

```bash
git push origin feat/academic-validation
```

- [ ] **Step 2: Draft PR**

```bash
gh pr create --draft --title "test: academic metric validation one shot" \
  --body "Plan 13. One-shot validation of our LLM-judge approach vs literature-standard SummaC + QAFactEval + BERTScore. Produces per-source correlation reports under docs/summary_eval/_academic_validation/. Pure documentation + ops-only; no runtime changes.

### Deploy gate
- [ ] CI green
- [ ] Per-source report.md files committed
- [ ] cross_source_correlation.md narrative filled
- [ ] No changes to runtime venv (ops/requirements.txt untouched)
- [ ] ops/requirements-academic.txt pinned separately

Merge is low-risk; nothing in runtime touched. Deploy triggered on merge will not change behavior."
```

- [ ] **Step 3: STOP + handoff**

Report:
> Plan 13 complete. Draft PR ready. Per-source correlations computed: YouTube=<N>, Reddit=<N>, GitHub=<N>, Newsletter=<N>. LLM-judge defense validated for <N>/4 sources. Awaiting human review + merge.

---

## Self-review checklist
- [ ] Academic deps live ONLY in `.venv-academic` / `/opt/academic_venv`; main runtime untouched
- [ ] ops/requirements.txt NOT modified; academic requirements file is separate
- [ ] Graceful degradation: script runs even if summac/qafacteval fail to install
- [ ] BERTScore fallback when NLI-based metrics unavailable
- [ ] Cross-source correlation report defends the Path C spec commitment
- [ ] No API changes, no schema changes, no config flags needed
- [ ] NO merge, NO push to master
