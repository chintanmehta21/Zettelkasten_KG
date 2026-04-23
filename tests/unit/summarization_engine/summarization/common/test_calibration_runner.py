from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.common.calibration import (
    CalibrationHarness,
    CalibrationResult,
    CalibrationShape,
    CalibrationVerdict,
)


class _FakeRunner:
    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.calls = 0

    async def score(self, url: str) -> float:
        self.calls += 1
        return self.scores[url]


@pytest.mark.asyncio
async def test_calibration_passes_when_all_shapes_meet_floor():
    shapes = [
        CalibrationShape(name="lecture", url="https://x/l"),
        CalibrationShape(name="interview", url="https://x/i"),
        CalibrationShape(name="tutorial", url="https://x/t"),
        CalibrationShape(name="review", url="https://x/r"),
        CalibrationShape(name="short", url="https://x/s"),
    ]
    runner = _FakeRunner({s.url: 90.0 for s in shapes})
    harness = CalibrationHarness(shapes=shapes, floor=85.0, regression_tolerance=3.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.verdict is CalibrationVerdict.PASS
    assert runner.calls == 5
    assert result.mean == pytest.approx(90.0)
    assert set(result.per_shape) == {"lecture", "interview", "tutorial", "review", "short"}


@pytest.mark.asyncio
async def test_calibration_blocks_on_any_shape_below_floor():
    shapes = [
        CalibrationShape(name="lecture", url="https://x/l"),
        CalibrationShape(name="interview", url="https://x/i"),
    ]
    runner = _FakeRunner({"https://x/l": 90.0, "https://x/i": 70.0})
    harness = CalibrationHarness(shapes=shapes, floor=85.0, regression_tolerance=3.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.verdict is CalibrationVerdict.BLOCK
    assert "interview" in result.reason
    assert "70" in result.reason


@pytest.mark.asyncio
async def test_calibration_blocks_on_mean_regression_beyond_tolerance():
    shapes = [CalibrationShape(name=f"s{i}", url=f"https://x/{i}") for i in range(5)]
    runner = _FakeRunner({s.url: 85.0 for s in shapes})  # mean 85, all at floor
    harness = CalibrationHarness(shapes=shapes, floor=80.0, regression_tolerance=3.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.verdict is CalibrationVerdict.BLOCK
    assert "regression" in result.reason.lower()


@pytest.mark.asyncio
async def test_calibration_passes_when_regression_within_tolerance():
    shapes = [CalibrationShape(name=f"s{i}", url=f"https://x/{i}") for i in range(5)]
    runner = _FakeRunner({s.url: 88.0 for s in shapes})  # mean 88, baseline 90 → -2, tol 3
    harness = CalibrationHarness(shapes=shapes, floor=80.0, regression_tolerance=3.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.verdict is CalibrationVerdict.PASS


@pytest.mark.asyncio
async def test_calibration_result_reports_per_shape_scores():
    shapes = [
        CalibrationShape(name="a", url="https://x/a"),
        CalibrationShape(name="b", url="https://x/b"),
    ]
    runner = _FakeRunner({"https://x/a": 92.0, "https://x/b": 88.0})
    harness = CalibrationHarness(shapes=shapes, floor=80.0, regression_tolerance=10.0)
    result = await harness.run(runner, baseline=90.0)
    assert result.per_shape == {"a": 92.0, "b": 88.0}
    assert result.mean == pytest.approx(90.0)
