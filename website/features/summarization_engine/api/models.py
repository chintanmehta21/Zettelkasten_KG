"""API request and response models for summarization engine v2."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
    urls: list[str] = Field(..., min_length=1, max_length=500)
    write_to_supabase: bool = False

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        for url in cleaned:
            if not url.startswith(("http://", "https://")):
                raise ValueError("Each URL must start with http:// or https://")
        return cleaned


class SummarizeV2Response(BaseModel):
    summary: dict
    writers: list[dict] = Field(default_factory=list)
