"""Unit tests for the YouTube format classifier."""
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.youtube.format_classifier import (
    FORMAT_LABELS,
    classify_format,
)


def test_documentary_signals_win():
    label, conf = classify_format(
        title="The Untold Chronicle of the Moon Landing",
        description="A narrator guides us through archival footage of the space race.",
        chapter_titles=["Introduction", "The race begins"],
        speakers=["Narrator"],
    )
    assert label == "documentary"
    assert 0.2 <= conf <= 1.0


def test_commentary_signals_win():
    label, conf = classify_format(
        title="My hot take on the new iPhone",
        description="Opinion and reaction to Apple's latest keynote. My thoughts on the pricing.",
        chapter_titles=[],
        speakers=["MKBHD"],
    )
    assert label == "commentary"
    assert conf >= 0.2


def test_lecture_signals_win():
    label, conf = classify_format(
        title="Linear Algebra - Lecture 3",
        description="Professor covers eigenvalues with slides from the course syllabus.",
        chapter_titles=["Chapter 1: Setup", "Chapter 2: Eigenvalues", "Chapter 3: Wrap"],
        speakers=["Prof. Strang"],
    )
    assert label == "lecture"
    assert conf >= 0.2


def test_explainer_signals_win():
    label, conf = classify_format(
        title="How it works: transformers explained",
        description="A step-by-step tutorial that shows how attention works in practice.",
        chapter_titles=["Intro", "Attention", "Demo"],
        speakers=["3Blue1Brown"],
    )
    assert label == "explainer"
    assert conf >= 0.2


def test_interview_signals_win():
    label, conf = classify_format(
        title="In conversation with Satya Nadella",
        description="A Q&A interview with our guest Satya on the future of AI.",
        chapter_titles=["Intro", "Career", "AI"],
        speakers=["Host", "Satya Nadella"],
    )
    assert label == "interview"
    assert conf >= 0.2


def test_empty_metadata_falls_back_to_commentary_with_floor():
    label, conf = classify_format(
        title="",
        description="",
        chapter_titles=[],
        speakers=[],
    )
    assert label == "commentary"
    assert conf == pytest.approx(0.2)


def test_all_noise_returns_floor_confidence():
    label, conf = classify_format(
        title="video 12345",
        description="some words with no strong signal at all",
        chapter_titles=["part one"],
        speakers=["Jane"],
    )
    assert label in FORMAT_LABELS
    assert conf == pytest.approx(0.2)


def test_multi_signal_tie_is_deterministic_by_label_order():
    # Score 4 for documentary (keyword "documentary") and 4 for interview (keyword "q&a").
    # FORMAT_LABELS orders documentary before interview, so documentary wins.
    label, conf = classify_format(
        title="documentary Q&A",
        description="",
        chapter_titles=[],
        speakers=[],
    )
    assert label == "documentary"
    assert conf >= 0.2


def test_two_distinct_speakers_boost_interview():
    # No lexical interview keywords; rely on metadata boost from two speakers.
    label, conf = classify_format(
        title="A chat",
        description="Two folks talk.",
        chapter_titles=[],
        speakers=["Alice Smith", "Bob Jones"],
    )
    assert label == "interview"
    assert conf >= 0.2


def test_confidence_never_exceeds_one_and_never_below_floor():
    # Many strong keywords — confidence should cap at 1.0.
    label, conf = classify_format(
        title="documentary narrator archival footage",
        description="documentary narration b-roll archival investigation chronicle",
        chapter_titles=["documentary"],
        speakers=["Narrator"],
    )
    assert label == "documentary"
    assert 0.2 <= conf <= 1.0


def test_label_set_matches_public_tuple():
    assert set(FORMAT_LABELS) == {
        "documentary",
        "commentary",
        "lecture",
        "explainer",
        "interview",
    }
