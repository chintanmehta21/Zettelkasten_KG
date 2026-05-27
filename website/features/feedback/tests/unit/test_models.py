"""Tests for the request/response DTOs."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from website.features.feedback.intake.models import (
    FeedbackIntent,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
)


def _valid_request(**overrides) -> dict:
    base = {
        "intent": "issue",
        "subject": "Smoke test",
        "description": "Description of the issue with at least ten characters.",
        "follow_up_email": False,
    }
    base.update(overrides)
    return base


def test_intent_enum_accepts_known_values() -> None:
    assert FeedbackIntent("issue") == FeedbackIntent.ISSUE
    assert FeedbackIntent("suggestion") == FeedbackIntent.SUGGESTION


def test_intent_enum_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        FeedbackIntent("praise")


def test_subject_max_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(subject="x" * 121))


def test_subject_min_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(subject=""))


def test_description_min_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(description="too short"))


def test_description_max_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(description="a" * 4001))


def test_anon_email_validates_format_when_present() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(anon_email="not-an-email"))


def test_anon_email_optional_when_absent() -> None:
    req = FeedbackSubmitRequest(**_valid_request())
    assert req.anon_email is None


def test_anon_name_max_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(anon_name="x" * 81))


def test_response_serializes() -> None:
    resp = FeedbackSubmitResponse(feedback_id="FB-7K3Q", status="accepted")
    assert resp.model_dump() == {"feedback_id": "FB-7K3Q", "status": "accepted"}
