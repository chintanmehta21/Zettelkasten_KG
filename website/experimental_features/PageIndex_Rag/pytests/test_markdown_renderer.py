from website.experimental_features.PageIndex_Rag.markdown_renderer import render_zettel_markdown
from website.experimental_features.PageIndex_Rag.types import ZettelRecord


def _zettel(**overrides):
    base = dict(
        user_id="u1",
        node_id="n1",
        title="My # Zettel",
        summary="# Accidental H1\nsummary",
        content="## Embedded\ncontent",
        source_type="web",
        url="https://example.com",
        tags=("zettelkasten", "tools"),
        metadata={},
    )
    base.update(overrides)
    return ZettelRecord(**base)


def test_renderer_emits_one_h1_and_demotes_embedded_headings():
    text, digest = render_zettel_markdown(_zettel())
    assert text.count("\n# ") == 0
    assert text.startswith("# My Zettel\n")
    assert "#### Accidental H1" in text
    assert "#### Embedded" in text
    assert len(digest) == 64


def test_renderer_is_deterministic():
    first = render_zettel_markdown(_zettel(tags=("b", "a")))
    second = render_zettel_markdown(_zettel(tags=("a", "b")))
    assert first == second
