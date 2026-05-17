"""Phase B P2-2 — pseudo-tag derivation unit coverage.

Conservative, high-confidence-only: correct cases emit the right tag;
low-confidence / ambiguous signals emit NOTHING (never a guess); the
result is cardinality-bounded.
"""
from __future__ import annotations

from website.features.kg_features.pseudo_tags import (
    _MAX_PSEUDO_TAGS,
    derive_pseudo_tags,
)


def test_source_domain_is_registrable_etld1_only():
    tags = derive_pseudo_tags(
        url="https://www.youtube.com/watch?v=abc&t=10s",
        source_type="youtube",
        metadata=None,
    )
    assert "source_domain:youtube.com" in tags
    # deep path / query never leaks into a tag (cardinality bound)
    assert not any("watch" in t or "abc" in t for t in tags)


def test_multi_part_public_suffix_handled():
    tags = derive_pseudo_tags(
        url="https://news.example.co.uk/2026/05/post", source_type="web"
    )
    assert "source_domain:example.co.uk" in tags


def test_modality_from_source_type_only():
    assert "modality:video" in derive_pseudo_tags(
        url="https://x.com/v", source_type="youtube"
    )
    assert "modality:post" in derive_pseudo_tags(
        url="https://reddit.com/r/p", source_type="reddit"
    )
    assert "modality:article" in derive_pseudo_tags(
        url="https://blog.example.com/p", source_type="newsletter"
    )


def test_unknown_source_type_emits_no_modality():
    tags = derive_pseudo_tags(url="https://example.com/p", source_type="weird")
    assert not any(t.startswith("modality:") for t in tags)


def test_speaker_only_from_explicit_structured_signal():
    tags = derive_pseudo_tags(
        url="https://youtube.com/watch?v=1",
        source_type="youtube",
        metadata={"channel_name": "Lex Fridman"},
    )
    assert "speaker:lex-fridman" in tags


def test_speaker_emits_none_when_no_explicit_signal():
    # title/summary prose is NOT a speaker signal; absence -> no tag
    tags = derive_pseudo_tags(
        url="https://youtube.com/watch?v=1",
        source_type="youtube",
        metadata={"description": "An interview with someone famous"},
    )
    assert not any(t.startswith("speaker:") for t in tags)


def test_no_url_yields_no_domain_tag():
    tags = derive_pseudo_tags(url=None, source_type="web")
    assert not any(t.startswith("source_domain:") for t in tags)


def test_bare_host_and_malformed_url_safe():
    assert derive_pseudo_tags(url="localhost", source_type="web") == [
        "modality:article"
    ]
    # never raises on garbage
    derive_pseudo_tags(url="http://", source_type=None, metadata={"x": object()})


def test_cardinality_hard_capped():
    tags = derive_pseudo_tags(
        url="https://youtube.com/watch?v=1",
        source_type="youtube",
        metadata={"channel": "Some Channel"},
    )
    assert len(tags) <= _MAX_PSEUDO_TAGS
    assert len(set(tags)) == len(tags)  # deduped
