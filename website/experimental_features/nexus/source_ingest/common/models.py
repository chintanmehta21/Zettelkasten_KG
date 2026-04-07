from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class NexusProvider(str, Enum):
    YOUTUBE = "youtube"
    GITHUB = "github"
    REDDIT = "reddit"
    TWITTER = "twitter"


PROVIDER_LABELS: dict[NexusProvider, str] = {
    NexusProvider.YOUTUBE: "YouTube",
    NexusProvider.GITHUB: "GitHub",
    NexusProvider.REDDIT: "Reddit",
    NexusProvider.TWITTER: "Twitter/X",
}


class OAuthStartResponse(BaseModel):
    provider: NexusProvider
    authorization_url: str
    expires_at: datetime


class ProviderTokenSet(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_token_payload(cls, payload: dict[str, Any]) -> "ProviderTokenSet":
        expires_at = None
        expires_in = payload.get("expires_in")
        if expires_in is not None:
            try:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            except (TypeError, ValueError):
                expires_at = None

        raw_scopes = payload.get("scope") or payload.get("scopes") or []
        scopes = _normalize_scopes(raw_scopes)
        token_type = str(payload.get("token_type") or "Bearer")
        return cls(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=payload.get("refresh_token"),
            token_type=token_type,
            scopes=scopes,
            expires_at=expires_at,
            raw=payload,
        )


class StoredProviderAccount(BaseModel):
    id: UUID | None = None
    user_id: UUID
    provider: NexusProvider
    account_id: str | None = None
    account_username: str | None = None
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_imported_at: datetime | None = None


class OAuthStateRecord(BaseModel):
    id: UUID | None = None
    provider: NexusProvider
    auth_user_sub: str
    redirect_path: str | None = "/home/nexus"
    code_verifier: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime
    consumed_at: datetime | None = None
    created_at: datetime | None = None


class ProviderArtifact(BaseModel):
    provider: NexusProvider
    external_id: str
    url: str
    title: str = ""
    description: str = ""
    source_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderDescriptor(BaseModel):
    provider: NexusProvider
    label: str
    connected: bool
    available: bool
    can_refresh: bool
    scopes: list[str] = Field(default_factory=list)
    account_username: str | None = None
    last_imported_at: datetime | None = None


class ImportRequest(BaseModel):
    limit: int = 25
    force: bool = False
    remember_connection: bool = True

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("limit must be at least 1")
        if value > 100:
            raise ValueError("limit must be 100 or less")
        return value


class ImportRun(BaseModel):
    id: UUID
    provider: NexusProvider
    status: str
    total_artifacts: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _normalize_scopes(raw_scopes: Any) -> list[str]:
    if isinstance(raw_scopes, str):
        return [part for part in raw_scopes.replace(",", " ").split() if part]
    if isinstance(raw_scopes, list):
        return [str(part) for part in raw_scopes if str(part).strip()]
    return []
