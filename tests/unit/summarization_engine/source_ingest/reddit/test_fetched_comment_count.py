"""Wave 1A: corrected fetched_comment_count = rendered + nested at ingest."""
from __future__ import annotations

import pytest

from website.features.summarization_engine.source_ingest.reddit import ingest as reddit_ingest
from website.features.summarization_engine.source_ingest.reddit.ingest import RedditIngestor


def _listing(num_comments: int, comment_children: list[dict]) -> list[dict]:
    post = {
        "data": {
            "children": [
                {"data": {"title": "T", "selftext": "B", "url": "", "subreddit": "test",
                          "author": "op", "score": 1, "num_comments": num_comments,
                          "id": "abc", "permalink": "/r/test/comments/abc/x/"}}
            ]
        }
    }
    comments = {"data": {"children": comment_children}}
    return [post, comments]


def _t1(author: str, body: str, replies: list[dict] | None = None) -> dict:
    data = {"author": author, "body": body}
    if replies:
        data["replies"] = {"data": {"children": replies}}
    return {"kind": "t1", "data": data}


@pytest.mark.asyncio
async def test_fetched_comment_count_sums_rendered_and_nested(monkeypatch):
    # 2 top-level comments; first has 1 nested reply -> rendered=2, nested=1, fetched=3.
    children = [
        _t1("a", "top one", replies=[_t1("b", "nested reply")]),
        _t1("c", "top two"),
    ]
    listing = _listing(num_comments=10, comment_children=children)

    async def _fake_fetch_json(url, headers=None):
        return listing, url

    monkeypatch.setattr(reddit_ingest, "fetch_json", _fake_fetch_json)
    # Keep pullpush dormant regardless of divergence.
    result = await RedditIngestor()._ingest_json(
        "https://www.reddit.com/r/test/comments/abc/x/",
        {"max_comments": 50, "comment_depth": 3, "pullpush_enabled": False},
    )
    md = result.metadata
    assert md["rendered_comment_count"] == 2
    assert md["nested_reply_count"] == 1
    assert md["fetched_comment_count"] == 3
    # Existing divergence key preserved (harness reads it), still rendered-based.
    assert md["comment_divergence_pct"] == pytest.approx(80.0)
