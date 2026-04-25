# tests/unit/rag_pipeline/ops/test_rag_eval_kasten.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from ops.scripts.lib.rag_eval_kasten import (
    build_kasten,
    load_naruto_zettels_for_source,
    parse_chintan_testing,
    select_similar_zettel,
    KastenBuildError,
)


def test_parse_chintan_testing(tmp_path):
    md = tmp_path / "Chintan_Testing.md"
    md.write_text("""**CHINTAN TESTING**

1. [Title One](https://www.youtube.com/watch?v=aaa) (5m)
2. [Title Two](https://www.reddit.com/r/foo/) [R]
3. [Title Three](https://github.com/x/y) (gh)
""", encoding="utf-8")
    entries = parse_chintan_testing(md)
    assert len(entries) == 3
    assert entries[0]["url"].startswith("https://www.youtube.com")
    assert entries[1]["url"].startswith("https://www.reddit.com")


def test_select_similar_zettel_picks_above_threshold():
    candidates = [
        {"node_id": "yt-a", "embedding": [1.0, 0.0]},
        {"node_id": "yt-b", "embedding": [0.0, 1.0]},
        {"node_id": "yt-c", "embedding": [0.95, 0.05]},
    ]
    centroid = [1.0, 0.0]
    result = select_similar_zettel(candidates=candidates, centroid=centroid, min_cosine=0.65, exclude_ids={"yt-a"})
    assert result["node_id"] == "yt-c"


def test_select_similar_zettel_returns_none_below_threshold():
    candidates = [{"node_id": "yt-x", "embedding": [0.0, 1.0]}]
    centroid = [1.0, 0.0]
    assert select_similar_zettel(candidates=candidates, centroid=centroid, min_cosine=0.65, exclude_ids=set()) is None
