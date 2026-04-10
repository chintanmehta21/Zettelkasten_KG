"""API request and response models for summarization engine v2."""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class SummarizeV2Request(BaseModel):
    url: str
    write_to_supabase: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return value


class BatchV2Request(BaseModel):
    urls: list[str]
    write_to_supabase: bool = False


class SummarizeV2Response(BaseModel):
    summary: dict
    writers: list[dict] = []
