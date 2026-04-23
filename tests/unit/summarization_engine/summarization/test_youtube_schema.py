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
    assert "Key voices and figures include Chris Timmermann and Dr. Rick Strassman." in payload.brief_summary
    assert payload.brief_summary.endswith(".")
    assert "..." not in payload.brief_summary
    assert len(payload.brief_summary) <= 400
    assert "commentary" in payload.tags
    assert len(payload.tags) == 10


def test_youtube_payload_upgrades_other_format_and_preserves_speaker_sentence():
    payload = YouTubeStructuredPayload(
        mini_title="DMT Chemistry Experience Research",
        brief_summary=(
            "This other video explains DMT's unique neurochemical action induces profound "
            "subjective experiences, including entity encounters, and offers a unique lens "
            "for understanding consciousness and potential therapeutic applications. "
            "It moves through sections on Historical Timeline and Chemistry and Brain Effects. "
            "It also covers N,N-DMT and 5-MeO-DMT. Featured voices include Dr."
        ),
        tags=[
            "dmt",
            "psychedelics",
            "neuroscience",
            "consciousness",
            "ayahuasca",
            "near-death-experiences",
            "mental-health",
            "psychopharmacology",
            "richard-strassman",
            "other",
        ],
        speakers=[
            "Dr. Rick Strassman",
            "Chris Timmermann",
            "Andrew Gallimore",
        ],
        guests=None,
        entities_discussed=["N,N-DMT", "5-MeO-DMT", "Consciousness"],
        detailed_summary={
            "thesis": (
                "DMT's unique neurochemical action induces profound subjective experiences "
                "and offers a lens for understanding consciousness."
            ),
            "format": "other",
            "chapters_or_segments": [
                {
                    "timestamp": "00:00",
                    "title": "Historical Timeline",
                    "bullets": ["Richard Spruce documents ayahuasca use."],
                },
                {
                    "timestamp": "N/A",
                    "title": "Chemistry and Brain Effects",
                    "bullets": ["Researchers connect DMT to serotonin signaling."],
                },
            ],
            "demonstrations": [],
            "closing_takeaway": (
                "Modern research studies DMT as a tool for understanding consciousness "
                "and therapeutic potential."
            ),
        },
    )

    assert payload.detailed_summary.format == "commentary"
    assert "commentary" in payload.tags
    assert "Key voices and figures include Chris Timmermann and Andrew Gallimore." in payload.brief_summary
    assert "..." not in payload.brief_summary
    assert len(payload.brief_summary) <= 400
