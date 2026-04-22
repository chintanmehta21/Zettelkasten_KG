from website.features.summarization_engine.source_ingest.reddit.ingest import (
    _compute_divergence,
)


def test_divergence_zero_when_counts_equal():
    assert _compute_divergence(num_comments=50, rendered_count=50) == 0.0


def test_divergence_percent_correct():
    assert _compute_divergence(num_comments=50, rendered_count=40) == 20.0


def test_divergence_clamped_to_zero_when_rendered_exceeds_total():
    assert _compute_divergence(num_comments=10, rendered_count=12) == 0.0


def test_divergence_handles_zero_total():
    assert _compute_divergence(num_comments=0, rendered_count=0) == 0.0
