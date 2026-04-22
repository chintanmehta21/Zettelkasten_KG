"""Auto-resume state detection for eval_loop.py."""
from __future__ import annotations

from enum import Enum
from pathlib import Path


class IterationState(str, Enum):
    PHASE_A_REQUIRED = "phase_a_required"
    AWAITING_MANUAL_REVIEW = "awaiting_manual_review"
    PHASE_B_REQUIRED = "phase_b_required"
    ALREADY_COMMITTED = "already_committed"


def detect_iteration_state(iter_dir: Path) -> IterationState:
    has = lambda name: (iter_dir / name).exists()

    if has("diff.md"):
        return IterationState.ALREADY_COMMITTED
    if has("manual_review.md") and has("summary.json") and has("eval.json"):
        return IterationState.PHASE_B_REQUIRED
    if has("summary.json") and has("eval.json") and has("manual_review_prompt.md"):
        return IterationState.AWAITING_MANUAL_REVIEW
    return IterationState.PHASE_A_REQUIRED
