from website.features.summarization_engine.summarization.youtube.schema import (
    YouTubeStructuredPayload,
)


def _build_payload(timestamp_a, timestamp_b):
    return {
        "mini_title": "DMT research overview",
        "brief_summary": "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five.",
        "tags": [
            "dmt",
            "psychedelics",
            "neuroscience",
            "lecture",
            "ayahuasca",
            "rick-strassman",
            "consciousness",
        ],
        "speakers": ["Fern"],
        "guests": None,
        "entities_discussed": ["DMT", "Ayahuasca"],
        "detailed_summary": {
            "thesis": "DMT has a long research history and unresolved scientific questions.",
            "format": "lecture",
            "chapters_or_segments": [
                {
                    "timestamp": timestamp_a,
                    "title": "Origins",
                    "bullets": ["The video opens with early historical context."],
                },
                {
                    "timestamp": timestamp_b,
                    "title": "Effects",
                    "bullets": ["The video later covers subjective and neural effects."],
                },
            ],
            "demonstrations": [],
            "closing_takeaway": "More research is still needed.",
        },
    }


def test_youtube_schema_drops_all_placeholder_timestamps():
    payload = YouTubeStructuredPayload(**_build_payload("00:00", "00:00"))

    assert [segment.timestamp for segment in payload.detailed_summary.chapters_or_segments] == [
        None,
        None,
    ]


def test_youtube_schema_preserves_real_timestamps():
    payload = YouTubeStructuredPayload(**_build_payload("00:00", "12:34"))

    assert [segment.timestamp for segment in payload.detailed_summary.chapters_or_segments] == [
        "00:00",
        "12:34",
    ]
