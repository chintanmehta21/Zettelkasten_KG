from pathlib import Path

from ops.scripts.lib.state_detector import IterationState, detect_iteration_state


def test_empty_iter_dir_returns_phase_a(tmp_path: Path):
    iter_dir = tmp_path / "iter-01"
    iter_dir.mkdir()

    assert detect_iteration_state(iter_dir) == IterationState.PHASE_A_REQUIRED


def test_only_summary_eval_returns_waiting_for_review(tmp_path: Path):
    iter_dir = tmp_path / "iter-01"
    iter_dir.mkdir()
    (iter_dir / "summary.json").write_text("{}", encoding="utf-8")
    (iter_dir / "eval.json").write_text("{}", encoding="utf-8")
    (iter_dir / "manual_review_prompt.md").write_text("", encoding="utf-8")

    assert detect_iteration_state(iter_dir) == IterationState.AWAITING_MANUAL_REVIEW


def test_all_present_including_manual_review_returns_phase_b(tmp_path: Path):
    iter_dir = tmp_path / "iter-01"
    iter_dir.mkdir()
    for name in ("summary.json", "eval.json", "manual_review_prompt.md", "manual_review.md"):
        (iter_dir / name).write_text("{}" if name.endswith("json") else "", encoding="utf-8")

    assert detect_iteration_state(iter_dir) == IterationState.PHASE_B_REQUIRED


def test_diff_present_returns_already_committed(tmp_path: Path):
    iter_dir = tmp_path / "iter-01"
    iter_dir.mkdir()
    for name in ("summary.json", "eval.json", "manual_review_prompt.md", "manual_review.md", "diff.md"):
        (iter_dir / name).write_text("{}" if name.endswith("json") else "", encoding="utf-8")

    assert detect_iteration_state(iter_dir) == IterationState.ALREADY_COMMITTED
