"""Pydantic models + avatar-URL validation."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_AVATAR_URL_RE = re.compile(r"^/artifacts/avatars/avatar_(0[0-9]|[1-5][0-9])\.svg$")


def is_valid_avatar_url(url: Optional[str]) -> bool:
    if not url or not isinstance(url, str):
        return False
    return bool(_AVATAR_URL_RE.match(url))


class UserProfile(BaseModel):
    user_id: str
    email: Optional[str] = None
    avatar_url: str
    display_name: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    avatar_url: str = Field(..., description="One of /artifacts/avatars/avatar_NN.svg")

    @field_validator("avatar_url")
    @classmethod
    def _check(cls, v: str) -> str:
        if not is_valid_avatar_url(v):
            raise ValueError("avatar_url must be /artifacts/avatars/avatar_NN.svg with NN in 00..59")
        return v
