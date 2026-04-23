"""Held-out shape calibration gate for the summarization tune loop.

Motivation: single-URL tune loops over-fit to one source shape (iter-06 of
docs/summary_eval/youtube regressed the held-out mean to 44.55 despite
passing on the training URL). CalibrationHarness runs a fixed 5-shape
URL set at the end of each tune iteration and blocks advance when either
(a) any shape score falls below a hard floor or (b) the shape-mean
regresses more than ``regression_tolerance`` points below the baseline.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class CalibrationVerdict(str, Enum):
    PASS = "pass"
    BLOCK = "block"


@dataclass(frozen=True)
class CalibrationShape:
    name: str
    url: str


@dataclass(frozen=True)
class CalibrationResult:
    verdict: CalibrationVerdict
    reason: str
    per_shape: dict[str, float]
    mean: float


class _Runner(Protocol):
    async def score(self, url: str) -> float: ...


@dataclass
class CalibrationHarness:
    shapes: list[CalibrationShape]
    floor: float
    regression_tolerance: float

    async def run(self, runner: _Runner, *, baseline: float) -> CalibrationResult:
        per_shape: dict[str, float] = {}
        for shape in self.shapes:
            per_shape[shape.name] = await runner.score(shape.url)

        mean = sum(per_shape.values()) / len(per_shape) if per_shape else 0.0

        below_floor = [(n, s) for n, s in per_shape.items() if s < self.floor]
        if below_floor:
            failing = ", ".join(f"{n}={s:.2f}" for n, s in below_floor)
            return CalibrationResult(
                verdict=CalibrationVerdict.BLOCK,
                reason=f"shape(s) below floor {self.floor:.2f}: {failing}",
                per_shape=per_shape,
                mean=mean,
            )

        if baseline - mean > self.regression_tolerance:
            return CalibrationResult(
                verdict=CalibrationVerdict.BLOCK,
                reason=(
                    f"held-out regression {baseline - mean:.2f} > tolerance "
                    f"{self.regression_tolerance:.2f} (mean {mean:.2f} vs baseline {baseline:.2f})"
                ),
                per_shape=per_shape,
                mean=mean,
            )

        return CalibrationResult(
            verdict=CalibrationVerdict.PASS,
            reason=f"all shapes >= floor {self.floor:.2f}; mean {mean:.2f}",
            per_shape=per_shape,
            mean=mean,
        )
