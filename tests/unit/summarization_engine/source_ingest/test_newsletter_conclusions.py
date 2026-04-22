from website.features.summarization_engine.source_ingest.newsletter.conclusions import (
    extract_conclusions,
)


def test_detects_prefixed_sentences_in_tail():
    text = (
        ("Opening background. " * 20)
        + "I recommend switching to FastAPI. "
        + "The key takeaway is that async matters."
    )
    conclusions = extract_conclusions(
        text,
        tail_fraction=0.3,
        prefixes=["i recommend", "the key takeaway"],
        max_count=6,
    )
    assert len(conclusions) == 2
    assert any("FastAPI" in c for c in conclusions)


def test_detects_action_items_list_headers():
    text = ("Background. " * 30) + "## Takeaways\n- Do X\n- Track Y\n"
    conclusions = extract_conclusions(
        text,
        tail_fraction=0.3,
        prefixes=["i recommend"],
        max_count=6,
    )
    assert any("Do X" in c or "Track Y" in c for c in conclusions)


def test_empty_when_no_conclusions():
    text = "Just a normal paragraph with no action items."
    conclusions = extract_conclusions(
        text,
        tail_fraction=0.3,
        prefixes=["i recommend"],
        max_count=6,
    )
    assert conclusions == []
