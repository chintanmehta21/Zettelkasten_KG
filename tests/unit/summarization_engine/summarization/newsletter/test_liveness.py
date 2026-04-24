from website.features.summarization_engine.summarization.newsletter.liveness import (
    is_live_newsletter,
    liveness_probe,
)


def test_alive_with_normal_html():
    alive, reason = is_live_newsletter(
        "https://example.substack.com/p/great-post",
        "<html><body>Real content here</body></html>",
    )
    assert alive is True
    assert reason == "ok"


def test_dead_when_html_contains_404():
    alive, reason = is_live_newsletter(
        "https://example.substack.com/p/x", "<h1>404 Not Found</h1>"
    )
    assert alive is False
    assert reason == "dead"


def test_dead_when_html_contains_page_not_found_case_insensitive():
    alive, reason = is_live_newsletter(
        "https://example.com/x", "<h1>Page Not Found</h1>"
    )
    assert alive is False


def test_dead_when_html_contains_410():
    alive, _ = is_live_newsletter("https://example.com/x", "Status: 410 Gone")
    assert alive is False


def test_dead_when_html_contains_gone_title():
    alive, _ = is_live_newsletter(
        "https://example.com/x", "<title>Gone</title><body></body>"
    )
    assert alive is False


def test_dead_when_html_empty_string():
    alive, reason = is_live_newsletter("https://example.com/x", "")
    assert alive is False
    assert reason == "dead"


def test_dead_when_html_whitespace_only():
    alive, _ = is_live_newsletter("https://example.com/x", "   \n\t  ")
    assert alive is False


def test_alive_when_html_none_and_url_clean():
    alive, reason = is_live_newsletter("https://example.substack.com/p/post", None)
    assert alive is True
    assert reason == "ok"


def test_dead_when_url_ends_with_unsubscribe():
    alive, reason = is_live_newsletter(
        "https://example.substack.com/unsubscribe", None
    )
    assert alive is False
    assert reason == "dead"


def test_dead_when_url_path_archive_deleted():
    alive, _ = is_live_newsletter(
        "https://example.com/archive/deleted", None
    )
    assert alive is False


def test_dead_when_url_path_p_deleted_post():
    alive, _ = is_live_newsletter(
        "https://example.substack.com/p/deleted-post", None
    )
    assert alive is False


def test_dead_when_url_unsubscribe_with_trailing_slash():
    alive, _ = is_live_newsletter(
        "https://example.com/unsubscribe/", None
    )
    assert alive is False


def test_liveness_probe_batch():
    urls = [
        "https://example.substack.com/p/alive",
        "https://example.substack.com/unsubscribe",
        "https://example.substack.com/p/deleted-post",
    ]
    out = liveness_probe(urls)
    assert out[urls[0]] == (True, "ok")
    assert out[urls[1]] == (False, "dead")
    assert out[urls[2]] == (False, "dead")


def test_liveness_probe_empty_list():
    assert liveness_probe([]) == {}
