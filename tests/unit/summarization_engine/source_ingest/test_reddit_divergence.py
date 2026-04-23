from website.features.summarization_engine.source_ingest.reddit.ingest import (
    _compute_divergence,
    _title_from_url_slug,
)


def test_divergence_zero_when_counts_equal():
    assert _compute_divergence(num_comments=50, rendered_count=50) == 0.0


def test_divergence_percent_correct():
    assert _compute_divergence(num_comments=50, rendered_count=40) == 20.0


def test_divergence_clamped_to_zero_when_rendered_exceeds_total():
    assert _compute_divergence(num_comments=10, rendered_count=12) == 0.0


def test_divergence_handles_zero_total():
    assert _compute_divergence(num_comments=0, rendered_count=0) == 0.0


def test_title_from_url_slug_capitalizes_and_caps_to_five_words():
    url = "https://www.reddit.com/r/changemyview/comments/1ssegtd/cmv_palantir_is_going_to_get_exactly_what_it_wants/"
    assert _title_from_url_slug(url) == "CMV Palantir Is Going To"


def test_title_from_url_slug_handles_experienceddevs():
    url = "https://www.reddit.com/r/ExperiencedDevs/comments/1bqc4gg/what_do_you_do_when_senior_engineers_keep/"
    assert _title_from_url_slug(url) == "What Do You Do When"


def test_title_from_url_slug_uppercases_known_acronyms():
    url = "https://www.reddit.com/r/AskReddit/comments/abc/til_python_is_fun/"
    assert _title_from_url_slug(url) == "TIL Python Is Fun"


def test_title_from_url_slug_returns_empty_when_no_slug():
    assert _title_from_url_slug("https://www.reddit.com/r/changemyview/") == ""
    assert _title_from_url_slug("https://example.com/not-reddit") == ""
