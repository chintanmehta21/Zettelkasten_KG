from pathlib import Path
import pytest

from ops.scripts.lib.rag_eval_review import (
    build_review_prompt,
    verify_review_stamp,
    BlindReviewError,
)


def test_build_review_prompt_excludes_eval_json():
    iter_dir = Path("/fake")
    prompt = build_review_prompt(iter_dir, source="youtube", iter_num=1)
    assert "eval.json" not in prompt
    assert "ablation_eval.json" not in prompt
    assert "NOT_CONSULTED" in prompt
    assert "queries.json" in prompt
    assert "answers.json" in prompt
    assert "kasten.json" in prompt


def test_verify_review_stamp_accepts_correct_stamp(tmp_path):
    review = tmp_path / "manual_review.md"
    review.write_text(
        """# review

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: 72.5
estimated_retrieval: 70
estimated_synthesis: 75
""",
        encoding="utf-8",
    )
    parsed = verify_review_stamp(review)
    assert parsed["estimated_composite"] == 72.5


def test_verify_review_stamp_rejects_missing(tmp_path):
    review = tmp_path / "manual_review.md"
    review.write_text("estimated_composite: 70", encoding="utf-8")
    with pytest.raises(BlindReviewError):
        verify_review_stamp(review)


def test_verify_review_stamp_rejects_wrong_stamp(tmp_path):
    review = tmp_path / "manual_review.md"
    review.write_text('eval_json_hash_at_review: "abc123"\nestimated_composite: 70', encoding="utf-8")
    with pytest.raises(BlindReviewError):
        verify_review_stamp(review)
