from pathlib import Path
import pytest

from ops.scripts.lib.rag_eval_state import detect_state, IterState


def test_empty_dir_is_phase_a_required(tmp_path):
    assert detect_state(tmp_path) == IterState.PHASE_A_REQUIRED


def test_with_prompt_no_review_awaits_review(tmp_path):
    (tmp_path / "manual_review_prompt.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "eval.json").write_text("{}", encoding="utf-8")
    assert detect_state(tmp_path) == IterState.AWAITING_MANUAL_REVIEW


def test_with_review_no_diff_phase_b_required(tmp_path):
    (tmp_path / "manual_review_prompt.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "manual_review.md").write_text(
        'eval_json_hash_at_review: "NOT_CONSULTED"\nestimated_composite: 70',
        encoding="utf-8",
    )
    (tmp_path / "eval.json").write_text("{}", encoding="utf-8")
    assert detect_state(tmp_path) == IterState.PHASE_B_REQUIRED


def test_with_diff_committed(tmp_path):
    (tmp_path / "manual_review_prompt.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "manual_review.md").write_text("review", encoding="utf-8")
    (tmp_path / "diff.md").write_text("diff", encoding="utf-8")
    (tmp_path / "eval.json").write_text("{}", encoding="utf-8")
    assert detect_state(tmp_path) == IterState.ALREADY_COMMITTED
