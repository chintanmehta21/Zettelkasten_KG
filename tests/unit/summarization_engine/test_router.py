from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.core.router import detect_source_type


def test_detects_known_newsletter_platform_url():
    assert (
        detect_source_type("https://organicsynthesis.beehiiv.com/p/organic-synthesis-beehiiv")
        == SourceType.NEWSLETTER
    )


def test_detects_custom_domain_newsletter_post():
    assert (
        detect_source_type("https://www.platformer.news/substack-nazi-push-notification/")
        == SourceType.NEWSLETTER
    )
