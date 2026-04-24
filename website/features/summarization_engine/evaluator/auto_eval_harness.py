"""Auto-eval harness for held-out scoring.

Runs a rubric (`docs/summary_eval/_config/rubric_<source>.yaml`) against a
batch of summary payloads and emits a single composite-score JSON suitable
for CI gating. No Gemini calls — pure rubric arithmetic over inputs that
already carry per-criterion scores and anti-pattern flags.

Summary payload contract (per file)::

    {
      "url": "https://...",                 # optional, used in per-summary rows
      "criterion_scores": {                  # missing keys default to full credit
        "brief.thesis_capture": 5,
        "brief.format_identified": 3,
        ...
      },
      "anti_patterns_triggered": [           # rubric anti-pattern ids
        "speakers_absent"
      ],
      "fields_present": {                    # optional, used by anti-pattern
        "Closing remarks": false             # detection_field hooks (see below)
      }
    }

Anti-pattern firing rules:
  - Explicit ids in ``anti_patterns_triggered`` always fire.
  - If the rubric anti-pattern declares ``detection_field: <name>`` then a
    ``False`` value at ``fields_present[<name>]`` also fires it. This is the
    declarative bridge for "Closing remarks missing" style checks.

Scoring rules (per the rubric YAML schema):
  - Each component's score is the sum of its criteria scores, clamped to the
    component's ``max_points``.
  - Composite is the sum of component scores, then:
      1. ``penalty_points`` from every fired anti-pattern is subtracted.
      2. If any fired anti-pattern declares ``auto_cap``, composite is
         clamped to the **lowest** auto_cap among fired ones.
      3. Composite is clamped to ``[0, composite_max]``.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class AutoEvalSchemaError(ValueError):
    """Raised when a rubric YAML is missing required keys for auto-eval."""


class AutoEvalConfig(BaseModel):
    source_type: str
    rubric_path: Path
    summaries: list[Path]
    composite_max: int = 100
    pass_threshold: int = 85

    model_config = {"arbitrary_types_allowed": True}


_REQUIRED_TOP = ("version", "source_type", "composite_max_points", "components")
_REQUIRED_COMPONENT = ("id", "max_points", "criteria")
_REQUIRED_CRITERION = ("id", "max_points")


def load_rubric(path: Path) -> dict[str, Any]:
    """YAML loader with explicit error on schema mismatch.

    Validates top-level keys, every component, every criterion, and the
    optional ``anti_patterns`` list. Mirrors ``rubric_loader.load_rubric``
    but exposes a deterministic structure for the auto-scorer.
    """
    p = Path(path)
    if not p.exists():
        raise AutoEvalSchemaError(f"rubric file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise AutoEvalSchemaError(f"rubric {p}: top-level must be a mapping")

    for key in _REQUIRED_TOP:
        if key not in data:
            raise AutoEvalSchemaError(f"rubric {p}: missing required key '{key}'")

    components = data["components"]
    if not isinstance(components, list) or not components:
        raise AutoEvalSchemaError(f"rubric {p}: 'components' must be a non-empty list")

    for ci, comp in enumerate(components):
        if not isinstance(comp, dict):
            raise AutoEvalSchemaError(f"rubric {p}: component[{ci}] must be a mapping")
        for key in _REQUIRED_COMPONENT:
            if key not in comp:
                raise AutoEvalSchemaError(
                    f"rubric {p}: component[{ci}] missing key '{key}'"
                )
        criteria = comp["criteria"]
        if not isinstance(criteria, list) or not criteria:
            raise AutoEvalSchemaError(
                f"rubric {p}: component '{comp['id']}' has empty criteria list"
            )
        for cri, crit in enumerate(criteria):
            if not isinstance(crit, dict):
                raise AutoEvalSchemaError(
                    f"rubric {p}: criterion[{ci}][{cri}] must be a mapping"
                )
            for key in _REQUIRED_CRITERION:
                if key not in crit:
                    raise AutoEvalSchemaError(
                        f"rubric {p}: criterion in '{comp['id']}' missing key '{key}'"
                    )

    anti = data.get("anti_patterns", [])
    if anti is not None and not isinstance(anti, list):
        raise AutoEvalSchemaError(f"rubric {p}: 'anti_patterns' must be a list")
    for ai, ap in enumerate(anti or []):
        if not isinstance(ap, dict) or "id" not in ap:
            raise AutoEvalSchemaError(
                f"rubric {p}: anti_pattern[{ai}] missing 'id'"
            )

    return data


def _fired_anti_patterns(
    summary_payload: dict, anti_patterns: list[dict]
) -> list[dict]:
    explicit = set(summary_payload.get("anti_patterns_triggered") or [])
    fields_present = summary_payload.get("fields_present") or {}
    fired: list[dict] = []
    for ap in anti_patterns:
        ap_id = ap["id"]
        if ap_id in explicit:
            fired.append(ap)
            continue
        det_field = ap.get("detection_field")
        if det_field and fields_present.get(det_field) is False:
            fired.append(ap)
    return fired


def score_summary(summary_payload: dict, rubric: dict) -> dict:
    """Score one summary against a loaded rubric.

    Returns ``{"composite": int, "category_scores": {comp_id: int},
    "anti_patterns_triggered": [ids], "penalty_points": int,
    "auto_cap_applied": int|None}``.
    """
    composite_max = int(rubric.get("composite_max_points", 100))
    criterion_scores = summary_payload.get("criterion_scores") or {}

    category_scores: dict[str, int] = {}
    raw_total = 0
    for comp in rubric["components"]:
        comp_id = comp["id"]
        comp_max = int(comp["max_points"])
        comp_total = 0
        for crit in comp["criteria"]:
            crit_id = crit["id"]
            crit_max = int(crit["max_points"])
            # Default = full credit when not provided. Clamp to [0, max].
            score = criterion_scores.get(crit_id, crit_max)
            try:
                score = int(score)
            except (TypeError, ValueError):
                raise AutoEvalSchemaError(
                    f"summary criterion '{crit_id}' score must be numeric, got {score!r}"
                )
            score = max(0, min(score, crit_max))
            comp_total += score
        comp_total = min(comp_total, comp_max)
        category_scores[comp_id] = comp_total
        raw_total += comp_total

    fired = _fired_anti_patterns(summary_payload, rubric.get("anti_patterns") or [])
    penalty = sum(int(ap.get("penalty_points") or 0) for ap in fired)
    composite = raw_total - penalty

    auto_caps = [int(ap["auto_cap"]) for ap in fired if ap.get("auto_cap") is not None]
    auto_cap_applied: int | None = min(auto_caps) if auto_caps else None
    if auto_cap_applied is not None:
        composite = min(composite, auto_cap_applied)

    composite = max(0, min(composite, composite_max))

    return {
        "composite": int(composite),
        "category_scores": category_scores,
        "anti_patterns_triggered": [ap["id"] for ap in fired],
        "penalty_points": int(penalty),
        "auto_cap_applied": auto_cap_applied,
    }


def _percentile(values: list[int], pct: float) -> int:
    """Linear-interpolated percentile (statistics.quantiles is N+1 cuts)."""
    if not values:
        return 0
    if len(values) == 1:
        return int(values[0])
    s = sorted(values)
    rank = (pct / 100.0) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return int(round(s[lo] + (s[hi] - s[lo]) * frac))


def _load_summary(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def run_auto_eval(config: AutoEvalConfig) -> dict:
    """Iterate ``config.summaries``, score each, return aggregate."""
    rubric = load_rubric(config.rubric_path)

    per_summary: list[dict] = []
    composites: list[int] = []
    for summary_path in config.summaries:
        payload = _load_summary(summary_path)
        scored = score_summary(payload, rubric)
        row = {
            "path": str(summary_path),
            "url": payload.get("url"),
            **scored,
        }
        per_summary.append(row)
        composites.append(int(scored["composite"]))

    n = len(composites)
    mean_composite = float(statistics.fmean(composites)) if composites else 0.0
    p50 = _percentile(composites, 50.0)
    p10 = _percentile(composites, 10.0)
    passed = sum(1 for c in composites if c >= config.pass_threshold)

    # Aggregate optional provenance signals from the scored per-summary rows.
    # These fields are emitted only when present in any scored summary; absent
    # summaries do not zero-out the aggregate. Downstream JSON consumers should
    # check for key presence, not truthiness.
    provenance: dict[str, object] = {}
    pullpush_counts = [
        int(row.get("pullpush_fetched_count"))
        for row in per_summary
        if isinstance(row.get("pullpush_fetched_count"), int)
    ]
    if pullpush_counts:
        provenance["pullpush_fetched_count_total"] = sum(pullpush_counts)
    gh_quota = [
        int(row.get("gh_api_quota_used"))
        for row in per_summary
        if isinstance(row.get("gh_api_quota_used"), int)
    ]
    if gh_quota:
        provenance["gh_api_quota_used_total"] = sum(gh_quota)
    agreements = [
        float(row.get("inter_rater_agreement"))
        for row in per_summary
        if isinstance(row.get("inter_rater_agreement"), (int, float))
    ]
    if agreements:
        provenance["inter_rater_agreement_mean"] = round(
            statistics.fmean(agreements), 3
        )

    return {
        "source_type": config.source_type,
        "rubric_path": str(config.rubric_path),
        "summaries_scored": n,
        "mean_composite": round(mean_composite, 2),
        "p50": p50,
        "p10": p10,
        "passed_threshold": passed,
        "threshold": int(config.pass_threshold),
        "composite_max": int(config.composite_max),
        "per_summary": per_summary,
        **provenance,
    }


def emit_scorecard_json(result: dict, out_path: Path) -> Path:
    """Write the aggregate to JSON for CI consumption. Returns the path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    return out


__all__ = [
    "AutoEvalConfig",
    "AutoEvalSchemaError",
    "load_rubric",
    "score_summary",
    "run_auto_eval",
    "emit_scorecard_json",
]
