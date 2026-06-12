"""Wave 1A: coverage-aware Reddit consensus phrasing.

Locks that no Reddit brief asserts thread-wide consensus when coverage is
unknown or below the calibrated floors. Pure string/threshold logic — no
LLM calls.
"""
from __future__ import annotations

from datetime import datetime, timezone

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.reddit.summarizer import (
    _build_minimum_safe_payload,
)

_BANNED_REPRESENTATIVE = ("consensus", "most agree", "the thread agreed", "dissent centered")


def _ingest(metadata: dict) -> IngestResult:
    return IngestResult(
        source_type=SourceType.REDDIT,
        url="https://www.reddit.com/r/test/comments/abc/x/",
        original_url="https://www.reddit.com/r/test/comments/abc/x/",
        raw_text="",
        sections={},
        metadata=metadata,
        extraction_confidence="low",
        confidence_reason="test",
        fetched_at=datetime.now(timezone.utc),
    )


def test_min_safe_fallback_makes_no_consensus_claim():
    ingest = _ingest({"subreddit": "test", "title": "Some thread"})
    payload = _build_minimum_safe_payload("", ingest)
    brief_lower = payload.brief_summary.lower()
    for banned in _BANNED_REPRESENTATIVE:
        assert banned not in brief_lower, f"min-safe brief must not assert {banned!r}: {payload.brief_summary!r}"


def test_min_safe_fallback_stays_within_char_bound():
    ingest = _ingest({"subreddit": "test", "title": "x" * 300})
    payload = _build_minimum_safe_payload("", ingest)
    assert len(payload.brief_summary) <= 400


from website.features.summarization_engine.summarization.reddit.layout import (
    compose_reddit_detailed,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)


def _payload_no_questions_no_counters() -> RedditStructuredPayload:
    detailed = RedditDetailedPayload(
        op_intent="OP shares a workflow tip.",
        reply_clusters=[RedditCluster(theme="Agreement", reasoning="Replies echoed the tip.")],
        counterarguments=[],
        unresolved_questions=[],
        moderation_context=None,
    )
    return RedditStructuredPayload(
        mini_title="r/test workflow tip shared",
        brief_summary=(
            "OP shares a workflow tip. Replies broadly echo it. "
            "A few add variants. Tooling is mentioned. No major dispute. "
            "Thread is short."
        ),
        tags=["test", "workflow", "tips", "tooling", "reddit-test", "productivity", "reddit"],
        detailed_summary=detailed,
    )


def test_layout_closing_remarks_makes_no_thread_wide_consensus_claim():
    payload = _payload_no_questions_no_counters()
    sections = compose_reddit_detailed(payload)
    closing = next(s for s in sections if s.heading == "Closing remarks")
    text = " ".join(closing.bullets).lower()
    assert "consensus" not in text, f"closing remarks must not assert consensus: {closing.bullets!r}"
    assert closing.bullets and closing.bullets[0].strip(), "closing remarks must stay non-empty"


from website.features.summarization_engine.summarization.reddit.coverage import (
    CoverageContext,
    compute_coverage,
    coverage_stance_sentence,
    reset_coverage_config_cache,
)


def _md(**kw) -> dict:
    return dict(kw)


def test_tier_consensus_requires_high_coverage_and_n_at_least_25():
    ctx = compute_coverage(_md(num_comments=50, fetched_comment_count=30))  # cov=0.60, n=30
    assert ctx.tier == "consensus"
    assert ctx.fetched == 30 and ctx.total == 50


def test_tier_plurality_band():
    ctx = compute_coverage(_md(num_comments=50, fetched_comment_count=20))  # cov=0.40, n=20
    assert ctx.tier == "plurality"


def test_tier_sample_scoped_when_below_plurality_gate_but_n_at_least_10():
    ctx = compute_coverage(_md(num_comments=500, fetched_comment_count=12))  # cov=0.024, n=12
    assert ctx.tier == "sample_scoped"


def test_tier_anecdote_when_fetched_below_10():
    ctx = compute_coverage(_md(num_comments=500, fetched_comment_count=4))
    assert ctx.tier == "anecdote"


def test_unknown_when_num_comments_zero():
    ctx = compute_coverage(_md(num_comments=0, fetched_comment_count=40))
    assert ctx.tier == "unknown"
    assert ctx.coverage is None


def test_unknown_when_fetched_count_missing():
    # HTML-scrape path never sets fetched_comment_count.
    ctx = compute_coverage(_md(num_comments=120))
    assert ctx.tier == "unknown"


def test_clamp_when_fetched_exceeds_total_but_floor_still_applies():
    # Stale num_comments: fetched 30 > total 10. Coverage clamps to 1.0,
    # n=30 >= 25 -> consensus allowed (absolute floor satisfied).
    ctx = compute_coverage(_md(num_comments=10, fetched_comment_count=30))
    assert ctx.coverage == 1.0
    assert ctx.tier == "consensus"


def test_clamp_high_coverage_but_tiny_n_is_not_consensus():
    # fetched 8 > total 5 -> clamp cov 1.0, but n=8 < 10 -> anecdote (floor wins).
    ctx = compute_coverage(_md(num_comments=5, fetched_comment_count=8))
    assert ctx.coverage == 1.0
    assert ctx.tier == "anecdote"


def test_stance_sentence_consensus_states_n_of_m_and_scopes_to_fetched():
    ctx = CoverageContext(tier="consensus", fetched=30, total=50, coverage=0.6)
    sent = coverage_stance_sentence(ctx, dominant="index funds beat stock-picking")
    low = sent.lower()
    assert "30 of 50" in sent
    assert "most-visible" in low or "most visible" in low
    assert "index funds beat stock-picking" in low
    assert sent.endswith((".", "!", "?"))


def test_stance_sentence_unknown_never_asserts_consensus():
    ctx = CoverageContext(tier="unknown", fetched=0, total=0, coverage=None)
    sent = coverage_stance_sentence(ctx, dominant="anything")
    low = sent.lower()
    assert "consensus" not in low and "most agree" not in low
    assert sent  # non-empty hedge


def test_stance_sentence_anecdote_is_dropped_or_anecdotal():
    ctx = CoverageContext(tier="anecdote", fetched=4, total=200, coverage=0.02)
    sent = coverage_stance_sentence(ctx, dominant="x")
    # spec: anecdote may DROP the sentence entirely -> empty string is valid.
    if sent:
        assert "consensus" not in sent.lower()


def test_missing_yaml_falls_back_to_baked_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("REDDIT_COVERAGE_YAML", str(tmp_path / "nope.yaml"))
    reset_coverage_config_cache()
    ctx = compute_coverage(_md(num_comments=50, fetched_comment_count=30))
    assert ctx.tier == "consensus"  # baked defaults still gate correctly
    reset_coverage_config_cache()
