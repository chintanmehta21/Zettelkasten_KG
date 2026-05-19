from __future__ import annotations

from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.post_summary_transformation import (
    registry as reg,
)
from website.features.summarization_engine.post_summary_transformation.rules import (
    sections as S,  # noqa: F401  (import registers the arxiv section rule)
)


# Sections on the real generic detailed-summary path are DetailedSummarySection
# Pydantic objects (NOT dicts); stub matches the real type.
def _s(h, b): return DetailedSummarySection(heading=h, bullets=b, sub_sections={})


def test_arxiv_drops_placeholder_limitations_and_citations():
    secs = [
        _s("Research Question", ["To determine X."]),
        _s("Limitations", ["No specific limitations were mentioned in the provided summary."]),
        _s("Citations", ["No citations were provided in the provided summary."]),
    ]
    out = reg.apply_sections(secs, source_type="arxiv")
    assert [s.heading for s in out] == ["Research Question"]


def test_non_arxiv_source_keeps_everything():
    secs = [_s("Limitations", ["No specific limitations were mentioned in the provided summary."])]
    assert reg.apply_sections(secs, source_type="youtube") == secs


def test_arxiv_keeps_real_and_multibullet():
    secs = [
        _s("Limitations", ["Sample size was small (n=12)."]),
        _s("Citations", ["Erdos & Gallai 1959.", "No citations were provided in the provided summary."]),
        _s("Methodology", ["No specific limitations were mentioned in the provided summary."]),
    ]
    out = reg.apply_sections(secs, source_type="arxiv")
    assert [s.heading for s in out] == ["Limitations", "Citations", "Methodology"]
