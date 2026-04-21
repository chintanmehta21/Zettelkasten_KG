from pathlib import Path

import pytest

from website.features.summarization_engine.evaluator.rubric_loader import (
    RubricSchemaError,
    load_rubric,
)


def test_load_rubric_rejects_missing_version(tmp_path: Path):
    bad = tmp_path / "rubric_youtube.yaml"
    bad.write_text(
        "source_type: youtube\ncomposite_max_points: 100\ncomponents: []\n",
        encoding="utf-8",
    )

    with pytest.raises(RubricSchemaError):
        load_rubric(bad)
