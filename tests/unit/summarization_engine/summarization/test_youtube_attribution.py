# tests/unit/summarization_engine/summarization/test_youtube_attribution.py
"""Wave 1B: YouTube attribution gating, idempotent composer, format-verb map.

Pure deterministic string/threshold logic — NO model call, NO network.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.attribution import (
    reconcile_attribution_confidence,
)


def test_reconcile_all_real_names_is_high():
    assert reconcile_attribution_confidence(["Lex Fridman", "Andrej Karpathy"]) == "high"


def test_reconcile_mixed_real_and_placeholder_is_low():
    # one real + one placeholder/geographic survivor pattern -> "low"
    assert reconcile_attribution_confidence(["Lex Fridman", "the host"]) == "low"


def test_reconcile_all_placeholder_is_missing():
    assert reconcile_attribution_confidence(["the host", "narrator"]) == "missing"


def test_reconcile_sentinel_the_speaker_is_missing():
    assert reconcile_attribution_confidence(["The speaker"]) == "missing"


def test_reconcile_empty_is_missing():
    assert reconcile_attribution_confidence([]) == "missing"


# --- Task 2: canonical format label fold ----------------------------------
import pytest

from website.features.summarization_engine.summarization.youtube.attribution import (
    canonical_format,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lecture", "lecture"),
        ("talk", "lecture"),
        ("tutorial", "explainer"),
        ("walkthrough", "explainer"),
        ("demo", "explainer"),
        ("explainer", "explainer"),
        ("commentary", "commentary"),
        ("review", "commentary"),
        ("reaction", "commentary"),
        ("debate", "commentary"),
        ("vlog", "commentary"),
        ("documentary", "documentary"),   # classifier-leaked label, NOT in Literal
        ("news", "news"),
        ("recap", "news"),
        ("interview", "interview"),
        ("discussion", "interview"),
        ("other", "unknown"),
        ("", "unknown"),
        ("ASMR-something-weird", "unknown"),
        ("  Commentary  ", "commentary"),  # case + whitespace tolerant
    ],
)
def test_canonical_format_folds_both_vocabularies(raw, expected):
    assert canonical_format(raw) == expected


def test_canonical_format_covers_every_literal_and_classifier_label():
    # No label from either vocabulary may fall through to a verb-map miss.
    from website.features.summarization_engine.summarization.youtube.format_classifier import (
        FORMAT_LABELS,
    )
    literal = ("tutorial", "interview", "commentary", "lecture", "review",
               "debate", "walkthrough", "reaction", "vlog", "other")
    for label in (*FORMAT_LABELS, *literal):
        key = canonical_format(label)
        assert key in {"lecture", "explainer", "commentary", "documentary", "news", "interview", "unknown"}


# --- Task 3: format-conditional reporting-verb phrase ---------------------
from website.features.summarization_engine.summarization.youtube.attribution import (
    reporting_verb_phrase,
)


def test_verb_lecture_high_is_explains():
    assert reporting_verb_phrase("lecture", "high") == "explains that"


def test_verb_explainer_high_is_demonstrates():
    assert reporting_verb_phrase("explainer", "high") == "demonstrates how"


def test_verb_commentary_high_is_argues():
    assert reporting_verb_phrase("commentary", "high") == "argues that"


def test_verb_news_reports():
    assert reporting_verb_phrase("news", "high") == "reports that"


def test_verb_low_confidence_downgrades_strong_to_tentative():
    # commentary's strong "argues" softens to "suggests" at low confidence.
    assert reporting_verb_phrase("commentary", "low") == "suggests that"


def test_verb_missing_confidence_is_agentless_for_every_format():
    for key in ("lecture", "explainer", "commentary", "documentary", "news", "interview", "unknown"):
        assert reporting_verb_phrase(key, "missing") is None  # None == agentless


def test_verb_interview_and_documentary_are_agentless_even_at_high():
    assert reporting_verb_phrase("interview", "high") is None
    assert reporting_verb_phrase("documentary", "high") is None


def test_verb_unknown_format_is_agentless():
    assert reporting_verb_phrase("unknown", "high") is None


# --- Task 4: idempotent, confidence-gated compose_lead_sentence -----------
from website.features.summarization_engine.summarization.youtube.attribution import (
    compose_lead_sentence,
    has_leading_attribution,
    lift_leading_attribution,
)

# --- detector: anchored, only fires on a LEADING whole clause -------------
def test_detector_fires_on_leading_attribution_clause():
    assert has_leading_attribution("The host argues that inflation is structural.")
    assert has_leading_attribution("In this commentary, Jane Doe argues that X happens.")


def test_detector_does_not_fire_on_interior_argues():
    # "argues" appears, but NOT as a leading attribution clause -> must not fire.
    assert not has_leading_attribution("Inflation, she argues, is structural and persistent.")
    assert not has_leading_attribution("The paper that argues for rate cuts is flawed.")


def test_detector_does_not_fire_without_reporting_verb():
    assert not has_leading_attribution("The host of the show lives in Boston.")


# --- lifter: returns the thesis with the leading clause preserved verbatim --
def test_lift_returns_clause_plus_remainder_verbatim():
    text = "The host argues that inflation is structural."
    lifted = lift_leading_attribution(text)
    assert lifted == "The host argues that inflation is structural."  # already a full sentence


# --- IDEMPOTENCY PROPERTY (deterministic corpus loop; see FLAG-H) ----------
_THESIS_CORPUS = [
    "Inflation is structural, not transitory.",
    "The host argues that inflation is structural.",
    "the host argues that inflation is structural",          # lowercase, no period
    "In this commentary, Jane Doe argues that markets overreact.",
    "Dr. Rick Strassman explains that DMT binds serotonin receptors.",  # abbrev guard
    "She argues, in passing, that the model is wrong.",       # interior
    "",                                                       # empty
    "The narrator examines an untold story.",
    "THE HOST ARGUES THAT RATES STAY HIGH",                  # all caps
    "Jane Doe suggests that the data is noisy.",   # NBSP / Unicode drift
]


def _compose(thesis, fmt="commentary", conf="high", speakers=("Jane Doe",)):
    return compose_lead_sentence(
        format_name=fmt, canonical_key=fmt, thesis=thesis,
        speakers=list(speakers), attribution_confidence=conf,
    )


def test_compose_lead_sentence_is_idempotent_over_corpus():
    # f(f(x)) == f(x): feeding the composer its own output as the thesis must
    # not re-prepend / double the attribution clause. (Unicode UAX#15: NFC is
    # itself idempotent; we canonicalise before the anchored compare.)
    for thesis in _THESIS_CORPUS:
        once = _compose(thesis)
        # feed the produced sentence back in as the thesis
        twice = _compose(once)
        assert twice == once, f"not idempotent for {thesis!r}: once={once!r} twice={twice!r}"


def test_compose_does_not_double_when_thesis_already_attributed():
    out = _compose("The host argues that inflation is structural.",
                   fmt="commentary", conf="high", speakers=("the host",))
    low = out.lower()
    assert low.count("argues that") == 1, f"doubled attribution: {out!r}"


def test_compose_missing_confidence_is_speaker_free_and_no_the_speaker():
    out = _compose("Inflation is structural.", conf="missing", speakers=("The speaker",))
    low = out.lower()
    assert "the speaker" not in low, f"fabricated subject leaked: {out!r}"
    assert "argues that" not in low  # agentless on missing
    assert out.endswith((".", "!", "?")) and out


def test_compose_legitimate_repetition_not_mangled():
    # A thesis that merely repeats a content word is left intact (no clause to lift).
    out = _compose("Index funds beat index-tracking ETFs over index periods.",
                   conf="high", speakers=("Jane Doe",))
    assert "index" in out.lower()
    assert out.endswith((".", "!", "?"))


# --- ReDoS adversarial input must return fast -------------------------------
def test_detector_redos_adversarial_input_returns_quickly():
    import time
    # Degenerate: long run of spaces + word chars that would blow up an
    # unbounded/backtracking pattern. Anchored + bounded ranges -> linear.
    evil = ("In this commentary, " + ("a" * 5000) + " " * 5000 + "argues that " + "z" * 5000)
    start = time.perf_counter()
    has_leading_attribution(evil)
    lift_leading_attribution(evil)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"detector too slow on adversarial input: {elapsed:.3f}s"


# --- Task 4 WIRING: _compose_structured_brief actually USES compose_lead_sentence
# (these drive the real Path-5 composer end-to-end; they would FAIL against the
# pre-Wave-1B always-double / "The speaker" / fixed-"argues" code.)
from website.features.summarization_engine.summarization.youtube.schema import (
    _compose_structured_brief,
)


def _brief(thesis, *, fmt="commentary", conf="high", speakers=("Jane Doe",), entities=()):
    return _compose_structured_brief(
        format_name=fmt, thesis=thesis, speakers=list(speakers),
        entities=list(entities), chapter_titles=[], demonstrations=[],
        closing_takeaway="", attribution_confidence=conf,
    )


def test_structured_brief_wiring_no_doubling_when_thesis_attributed():
    out = _brief("The host argues that inflation is structural.",
                 fmt="commentary", conf="high", speakers=("the host",))
    assert out.lower().count("argues that") == 1, f"doubled in composer: {out!r}"


def test_structured_brief_wiring_missing_confidence_no_the_speaker():
    out = _brief("Inflation is structural.", conf="missing", speakers=("The speaker",))
    assert "the speaker" not in out.lower(), f"fabricated subject leaked: {out!r}"


def test_structured_brief_wiring_lecture_uses_explains_not_argues():
    out = _brief("Photosynthesis converts sunlight into chemical energy.",
                 fmt="lecture", conf="high", speakers=("Dr. Lee",))
    low = out.lower()
    assert "explains" in low and "argues that" not in low, f"verb not format-conditional: {out!r}"


def test_structured_brief_wiring_entity_sentence_abstains_when_missing():
    out = _brief("Inflation is structural.", conf="missing",
                 speakers=("The speaker",), entities=("CPI", "the Fed"))
    assert "the speaker" not in out.lower(), f"entity sentence fabricated speaker: {out!r}"
