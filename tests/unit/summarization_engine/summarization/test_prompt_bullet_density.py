"""Lock the 5-7 nested-bullets prompt guidance for reddit/github/newsletter.

YouTube already ships this language via its chapter-bullet schema constraint;
the three non-YouTube prompts explicitly instruct the model to emit 5-7
bullets per nested section so density stays consistent across sources.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.prompts import (
    STRUCTURED_EXTRACT_INSTRUCTION as GITHUB_PROMPT,
)
from website.features.summarization_engine.summarization.newsletter.prompts import (
    STRUCTURED_EXTRACT_INSTRUCTION as NEWSLETTER_PROMPT,
)
from website.features.summarization_engine.summarization.reddit.prompts import (
    STRUCTURED_EXTRACT_INSTRUCTION as REDDIT_PROMPT,
)


def test_reddit_prompt_requires_5_to_7_bullets_per_cluster():
    assert "5-7" in REDDIT_PROMPT
    # The guidance is attached to examples[] within reply_clusters.
    assert "examples[]" in REDDIT_PROMPT


def test_github_prompt_requires_5_to_7_bullets_per_section():
    assert "5-7" in GITHUB_PROMPT
    assert "bullets[]" in GITHUB_PROMPT


def test_newsletter_prompt_requires_5_to_7_bullets_per_section():
    assert "5-7" in NEWSLETTER_PROMPT
    assert "bullets[]" in NEWSLETTER_PROMPT
