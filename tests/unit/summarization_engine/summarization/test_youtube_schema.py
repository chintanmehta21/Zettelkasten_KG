from website.features.summarization_engine.summarization.youtube.schema import (
    YouTubeStructuredPayload,
)


def test_youtube_payload_repairs_brief_and_adds_format_tag():
    payload = YouTubeStructuredPayload(
        mini_title="DMT: Identity, History, Effects, and Theories",
        brief_summary=(
            "DMT is an endogenous psychedelic compound with a rich history. "
            "It binds to serotonin receptors. "
            "Theories suggest it disrupt"
        ),
        tags=[
            "dmt",
            "psychedelics",
            "neuroscience",
            "ayahuasca",
            "serotonin-receptors",
            "consciousness",
            "mental-health",
            "pharmacology",
            "history-of-psychedelics",
            "therapeutic-potential",
        ],
        speakers=["Chris Timmermann", "Dr. Rick Strassman"],
        guests=None,
        entities_discussed=["DMT", "Ayahuasca"],
        detailed_summary={
            "thesis": (
                "DMT is an endogenous psychedelic compound with a documented history, "
                "distinct administration modes, and unresolved theories about consciousness."
            ),
            "format": "commentary",
            "chapters_or_segments": [
                {
                    "timestamp": "1852",
                    "title": "Richard Spruce documents capi",
                    "bullets": ["Spruce records ayahuasca use in Brazil."],
                },
                {
                    "timestamp": "1990s",
                    "title": "Rick Strassman study",
                    "bullets": ["Modern human DMT research resumes."],
                },
            ],
            "demonstrations": [],
            "closing_takeaway": (
                "Use without professional guidance is not recommended."
            ),
        },
    )

    assert payload.mini_title == "DMT Identity History Effects Theories"
    assert payload.brief_summary.startswith("This commentary video explains DMT")
    assert "Chris Timmermann" in payload.brief_summary
    assert payload.brief_summary.endswith(".")
    assert len(payload.brief_summary) <= 400
    assert "commentary" in payload.tags
    assert len(payload.tags) == 10
