"""Typed models for the pricing catalog and entitlement responses."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Meter(StrEnum):
    ZETTEL = "zettel"
    KASTEN = "kasten"
    RAG_QUESTION = "rag_question"


class BillingPeriod(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class Money(BaseModel):
    currency: str = "INR"
    amount: int = Field(ge=0)
    display: str


class QuotaExhaustedDetail(BaseModel):
    code: Literal["quota_exhausted"] = "quota_exhausted"
    meter: Meter
    message: str
    recommended_products: list[str] = Field(default_factory=list)
    resume_token: str | None = None

