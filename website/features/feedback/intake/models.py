"""Pydantic DTOs for the feedback submission flow."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class FeedbackIntent(str, Enum):
    ISSUE = "issue"
    SUGGESTION = "suggestion"


class FeedbackSubmitRequest(BaseModel):
    intent: FeedbackIntent
    subject: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=10, max_length=4000)
    anon_name: str | None = Field(default=None, max_length=80)
    follow_up_email: bool = False
    anon_email: EmailStr | None = None


class FeedbackSubmitResponse(BaseModel):
    feedback_id: str
    status: Literal["accepted"] = "accepted"
