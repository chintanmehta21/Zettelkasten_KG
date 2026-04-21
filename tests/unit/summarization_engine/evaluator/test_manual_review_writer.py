import json
from pathlib import Path

from website.features.summarization_engine.evaluator.manual_review_writer import (
    verify_manual_review,
    write_manual_review_prompt,
)


def test_write_manual_review_prompt_includes_eval_hash(tmp_path: Path):
    out = tmp_path / "manual_review_prompt.md"
    eval_json = tmp_path / "eval.json"
    eval_json.write_text(json.dumps({"score": 87}), encoding="utf-8")
    summary_json = {"mini_title": "t"}
    rubric = {"version": "rubric_youtube.v1"}

    hash_val = write_manual_review_prompt(
        out_path=out,
        rubric_yaml=rubric,
        summary=summary_json,
        atomic_facts=[],
        source_text="src",
        eval_json_path=eval_json,
    )

    assert out.exists()
    assert hash_val in out.read_text(encoding="utf-8")


def test_verify_manual_review_accepts_not_consulted(tmp_path: Path):
    mr = tmp_path / "manual_review.md"
    mr.write_text(
        'eval_json_hash_at_review: "NOT_CONSULTED"\n\n...prose...\n\nestimated_composite: 85.0\n',
        encoding="utf-8",
    )

    is_valid, composite = verify_manual_review(mr)

    assert is_valid
    assert composite == 85.0


def test_verify_manual_review_rejects_hash(tmp_path: Path):
    mr = tmp_path / "manual_review.md"
    mr.write_text(
        'eval_json_hash_at_review: "abcdef"\n\nestimated_composite: 85.0\n',
        encoding="utf-8",
    )

    is_valid, _ = verify_manual_review(mr)

    assert not is_valid
