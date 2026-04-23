"""Spearman-rho calibration between auto-eval and manual-review composites.

This module is a thin wrapper around ``scipy.stats.spearmanr`` with a pure-Python
fallback so the eval harness can run without scipy installed (the hermetic CI
sandbox sometimes lacks the wheel). It is a **calibration aid, not a gate**:
the caller WARNs when rho drops below the configured threshold but never
raises — missing or thin manual-review data would otherwise fail CI on days
when no reviewer has caught up.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)

DEFAULT_WARN_THRESHOLD = 0.6


@dataclass(frozen=True)
class SpearmanResult:
    rho: float
    n: int
    used_scipy: bool


class InsufficientCalibrationData(ValueError):
    """Raised when there are not enough paired scores to compute rho.

    Spearman requires >= 2 pairs and at least one pair where ranks differ.
    """


def _rankdata(values: Sequence[float]) -> list[float]:
    """Average-rank tie handling, matching scipy.stats.rankdata default."""
    indexed = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while (
            j + 1 < len(indexed)
            and values[indexed[j + 1]] == values[indexed[i]]
        ):
            j += 1
        average = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            ranks[indexed[k]] = average
        i = j + 1
    return ranks


def _manual_spearman(
    auto_scores: Sequence[float], manual_scores: Sequence[float]
) -> float:
    ra = _rankdata(auto_scores)
    rm = _rankdata(manual_scores)
    n = len(ra)
    mean_a = sum(ra) / n
    mean_m = sum(rm) / n
    cov = sum((ra[i] - mean_a) * (rm[i] - mean_m) for i in range(n))
    var_a = sum((r - mean_a) ** 2 for r in ra)
    var_m = sum((r - mean_m) ** 2 for r in rm)
    denom = math.sqrt(var_a * var_m)
    if denom == 0.0:
        raise InsufficientCalibrationData(
            "Cannot compute Spearman rho: all ranks tied on one side (zero variance)."
        )
    return cov / denom


def compute_spearman(
    auto_scores: Iterable[float], manual_scores: Iterable[float]
) -> SpearmanResult:
    """Return the Spearman rank correlation between automated and manual scores.

    Uses ``scipy.stats.spearmanr`` when available (identical semantics to the
    pure-Python fallback on the supported range: average ranks for ties,
    n >= 2 required). Raises ``InsufficientCalibrationData`` when fewer than
    two paired scores are supplied or when variance is zero on either axis.
    """
    auto_list = list(auto_scores)
    manual_list = list(manual_scores)
    if len(auto_list) != len(manual_list):
        raise ValueError(
            f"auto_scores and manual_scores must align: "
            f"len(auto)={len(auto_list)} vs len(manual)={len(manual_list)}"
        )
    if len(auto_list) < 2:
        raise InsufficientCalibrationData(
            f"Spearman requires >= 2 paired scores; got {len(auto_list)}."
        )

    try:
        from scipy.stats import spearmanr  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - exercised only when scipy missing
        rho = _manual_spearman(auto_list, manual_list)
        return SpearmanResult(rho=float(rho), n=len(auto_list), used_scipy=False)

    result = spearmanr(auto_list, manual_list)
    # scipy >=1.9 returns SignificanceResult; older returns tuple. Both expose
    # the correlation at index 0 / attribute ``correlation`` / ``statistic``.
    rho = getattr(result, "statistic", None)
    if rho is None:
        rho = getattr(result, "correlation", None)
    if rho is None:
        rho = result[0]  # type: ignore[index]
    if rho is None or (isinstance(rho, float) and math.isnan(rho)):
        raise InsufficientCalibrationData(
            "scipy.spearmanr returned NaN; variance is zero on at least one axis."
        )
    return SpearmanResult(rho=float(rho), n=len(auto_list), used_scipy=True)


def check_calibration(
    auto_scores: Iterable[float],
    manual_scores: Iterable[float],
    *,
    source: str,
    threshold: float = DEFAULT_WARN_THRESHOLD,
) -> SpearmanResult | None:
    """WARN-level calibration probe for the eval scorecard.

    Returns the ``SpearmanResult`` (including rho). When rho is below
    ``threshold``, logs a WARNING with the source label so the scorecard and
    CI output surface the calibration gap without failing. Returns ``None``
    when there is not enough data to compute rho (treated as "no signal" —
    still WARNs once at debug level so the scorecard can explain the absence).
    """
    try:
        result = compute_spearman(auto_scores, manual_scores)
    except InsufficientCalibrationData as exc:
        logger.warning(
            "calibration_spearman source=%s insufficient_data reason=%s",
            source, exc,
        )
        return None

    if result.rho < threshold:
        logger.warning(
            "calibration_spearman source=%s rho=%.3f n=%d below threshold=%.2f "
            "(auto-eval vs manual-review drift)",
            source, result.rho, result.n, threshold,
        )
    else:
        logger.info(
            "calibration_spearman source=%s rho=%.3f n=%d threshold=%.2f",
            source, result.rho, result.n, threshold,
        )
    return result
