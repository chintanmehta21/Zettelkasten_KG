"""4-state machine for the rag_eval iter directory."""
from __future__ import annotations

from enum import Enum
from pathlib import Path


class IterState(str, Enum):
    PHASE_A_REQUIRED = "PHASE_A_REQUIRED"
    AWAITING_MANUAL_REVIEW = "AWAITING_MANUAL_REVIEW"
    PHASE_B_REQUIRED = "PHASE_B_REQUIRED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"


def detect_state(iter_dir: Path) -> IterState:
    if (iter_dir / "diff.md").exists():
        return IterState.ALREADY_COMMITTED
    if (iter_dir / "manual_review.md").exists():
        return IterState.PHASE_B_REQUIRED
    if (iter_dir / "manual_review_prompt.md").exists() and (iter_dir / "eval.json").exists():
        return IterState.AWAITING_MANUAL_REVIEW
    return IterState.PHASE_A_REQUIRED
