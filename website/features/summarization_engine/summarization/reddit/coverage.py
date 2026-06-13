"""Coverage-aware stance phrasing for Reddit summaries (Wave 1A).

Turns ingest comment counts into a tiered representativeness verdict and the
exact stance sentence to use. Pure + deterministic — NO model call.

Why tiers, not a boolean: Reddit "top/best" sort is a position-biased
non-probability sample (~4x interaction bias top vs 10th — Glenski et al.
2017, arXiv:1703.05267), so "consensus among fetched" != "consensus of
thread". A threshold only narrows variance around a biased point; it cannot
remove the bias. Therefore every representativeness claim is SCOPED to the
fetched frame and assertiveness tracks coverage (plurality < majority <
consensus). Floors (n>=25 for consensus) follow proportion sample-size norms
(PSU STAT 200; MeasuringU FPC): at n=10 a 50/50 split has a ~+/-31pp 95% CI.

Config: docs/summary_eval/_config/reddit_coverage.yaml (env override
REDDIT_COVERAGE_YAML). Missing file -> baked defaults below. Thresholds are
CALIBRATION DEFAULTS pending operator confirmation on the 15-thread set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from website.features.summarization_engine.summarization.common.brief_repair import (
    as_sentence as _as_sentence,
)

_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[5]
    / "docs"
    / "summary_eval"
    / "_config"
    / "reddit_coverage.yaml"
)

# Baked calibration defaults (used when YAML missing). MUST match the YAML.
_BAKED_DEFAULTS: dict[str, Any] = {
    "consensus": {"min_coverage": 0.60, "min_fetched": 25},
    "plurality": {"min_coverage": 0.40, "min_fetched": 10},
    "sample_scoped": {"min_fetched": 10},
    # below sample_scoped.min_fetched -> anecdote
}


@dataclass(frozen=True)
class CoverageContext:
    tier: str  # consensus | plurality | sample_scoped | anecdote | unknown
    fetched: int
    total: int
    coverage: float | None  # None when total unknown


def _config_path() -> Path:
    override = os.environ.get("REDDIT_COVERAGE_YAML")
    return Path(override) if override else _DEFAULT_CONFIG_PATH


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return {k: dict(v) for k, v in _BAKED_DEFAULTS.items()}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ValueError(f"reddit_coverage.yaml is not valid YAML: {exc}") from exc
    if data is None:
        return {k: dict(v) for k, v in _BAKED_DEFAULTS.items()}
    if not isinstance(data, dict):
        raise ValueError(
            "reddit_coverage.yaml must deserialise to a mapping at the top "
            f"level (got {type(data).__name__})."
        )
    tiers = data.get("tiers", data)
    _validate_shape(tiers)
    return tiers


def _validate_shape(tiers: dict[str, Any]) -> None:
    for key in ("consensus", "plurality", "sample_scoped"):
        node = tiers.get(key)
        if not isinstance(node, dict):
            raise ValueError(f"reddit_coverage.yaml: '{key}' must be a mapping.")
    for key in ("consensus", "plurality"):
        cov = tiers[key].get("min_coverage")
        if not isinstance(cov, (int, float)) or not (0.0 <= float(cov) <= 1.0):
            raise ValueError(
                f"reddit_coverage.yaml: '{key}.min_coverage' must be in [0, 1]."
            )
    for key in ("consensus", "plurality", "sample_scoped"):
        n = tiers[key].get("min_fetched")
        if not isinstance(n, int) or n < 1:
            raise ValueError(
                f"reddit_coverage.yaml: '{key}.min_fetched' must be a positive int."
            )


def _tiers() -> dict[str, Any]:
    return _load_cached(str(_config_path()))


def reset_coverage_config_cache() -> None:
    """Test helper: drop the lru_cache so a new YAML path takes effect."""
    _load_cached.cache_clear()


def _safe_int(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def compute_coverage(metadata: dict[str, Any]) -> CoverageContext:
    """Derive the coverage tier from ingest metadata. Never raises.

    Fail-safe: total<=0 or missing fetched_comment_count -> 'unknown' (hedge).
    fetched>total (stale num_comments / nested mismatch) -> clamp coverage to
    1.0 but keep the absolute fetched floor (a clamp does not manufacture a
    larger sample).
    """
    total = _safe_int(metadata.get("num_comments"))
    has_fetched = metadata.get("fetched_comment_count") is not None
    fetched = _safe_int(metadata.get("fetched_comment_count"))

    if total <= 0 or not has_fetched:
        return CoverageContext(tier="unknown", fetched=fetched, total=max(total, 0), coverage=None)

    # Stale num_comments can report fewer comments than we fetched. Clamp the
    # displayed denominator to max(fetched, total) so the rendered "N of M"
    # never reads "30 of 10"; this also keeps coverage == fetched/total = 1.0.
    total = max(fetched, total)
    coverage = fetched / total
    if coverage > 1.0:
        coverage = 1.0  # clamp; floor still governs the tier

    tiers = _tiers()
    cons, plur, samp = tiers["consensus"], tiers["plurality"], tiers["sample_scoped"]

    if coverage >= float(cons["min_coverage"]) and fetched >= int(cons["min_fetched"]):
        tier = "consensus"
    elif coverage >= float(plur["min_coverage"]) and fetched >= int(plur["min_fetched"]):
        tier = "plurality"
    elif fetched >= int(samp["min_fetched"]):
        tier = "sample_scoped"
    else:
        tier = "anecdote"

    return CoverageContext(tier=tier, fetched=fetched, total=total, coverage=round(coverage, 4))


def coverage_stance_sentence(ctx: CoverageContext, *, dominant: str) -> str:
    """Return the stance sentence for this coverage tier, scoped to the fetched
    frame. Assertiveness tracks coverage; counts (N of M) are always stated at
    consensus/plurality. Anecdote MAY drop the sentence (returns "").

    ``dominant`` is the already-trimmed dominant-cluster phrase (lower-case
    fragment) the caller wants represented.
    """
    dominant = (dominant or "").strip().rstrip(".")
    if ctx.tier == "consensus":
        return _as_sentence(
            f"Among the {ctx.fetched} of {ctx.total} most-visible comments, "
            f"most converged on {dominant}"
        )
    if ctx.tier == "plurality":
        return _as_sentence(
            f"Among the {ctx.fetched} of {ctx.total} most-visible comments, "
            f"many leaned toward {dominant}"
        )
    if ctx.tier == "sample_scoped":
        return _as_sentence(
            f"In the {ctx.fetched} comments reviewed (of {ctx.total}), a recurring "
            f"thread was {dominant}"
        )
    if ctx.tier == "anecdote":
        # Too few to characterise distribution -> drop the stance sentence.
        return ""
    # unknown -> hedge, never assert representativeness.
    return _as_sentence(
        f"Within the visible replies, one recurring point was {dominant}"
    )
