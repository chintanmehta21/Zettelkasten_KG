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


def test_title_from_url_slug_truncates_at_word_boundary_within_budget():
    url = "https://www.reddit.com/r/changemyview/comments/1ssegtd/cmv_palantir_is_going_to_get_exactly_what_it_wants/"
    title = _title_from_url_slug(url)
    # Fits 44-char budget, stops at word boundary, doesn't end on stopword.
    assert title == "CMV Palantir Is Going To Get Exactly What"
    assert len(title) <= 44
    assert not title.endswith(("to", "is", "the", "a", "an", "of", "for"))


def test_title_from_url_slug_drops_trailing_stopwords_even_when_short():
    url = "https://www.reddit.com/r/ExperiencedDevs/comments/1bqc4gg/what_do_you_do_when_senior_engineers_keep/"
    title = _title_from_url_slug(url)
    # Full slug is "What Do You Do When Senior Engineers Keep" (42 chars) —
    # fits the 44-char budget so all words survive, and "Keep" is content, not stopword.
    assert title == "What Do You Do When Senior Engineers Keep"


def test_title_from_url_slug_uppercases_known_acronyms():
    url = "https://www.reddit.com/r/AskReddit/comments/abc/til_python_is_fun/"
    assert _title_from_url_slug(url) == "TIL Python Is Fun"


def test_title_from_url_slug_drops_trailing_preposition_after_truncation():
    # Manufactured slug where word-boundary truncation would leave a
    # trailing "to" — the stopword pass must drop it.
    url = "https://www.reddit.com/r/test/comments/xyz/why_we_decided_to_migrate_to/"
    title = _title_from_url_slug(url, max_chars=28)
    assert title == "Why We Decided To Migrate"
    assert not title.endswith(" To")


def test_title_from_url_slug_honours_max_chars():
    url = "https://www.reddit.com/r/test/comments/xyz/one_two_three_four_five_six_seven/"
    title = _title_from_url_slug(url, max_chars=15)
    assert len(title) <= 15
    assert title == "One Two Three"


def test_title_from_url_slug_returns_empty_when_no_slug():
    assert _title_from_url_slug("https://www.reddit.com/r/changemyview/") == ""
    assert _title_from_url_slug("https://example.com/not-reddit") == ""
