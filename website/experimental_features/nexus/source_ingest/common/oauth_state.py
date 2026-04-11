from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from website.core.supabase_kg import get_supabase_client
from website.experimental_features.nexus.source_ingest.common.models import (
    NexusProvider,
    OAuthStateRecord,
)

_STATE_TTL = timedelta(minutes=10)


def issue_oauth_state(
    *,
    provider: NexusProvider,
    auth_user_sub: str,
    redirect_path: str | None = "/home/nexus",
    code_verifier: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, OAuthStateRecord]:
    state_token = secrets.token_urlsafe(32)
    expires_at = _utcnow() + _STATE_TTL
    payload = {
        "state_digest": _digest(state_token),
        "provider": provider.value,
        "auth_user_sub": auth_user_sub,
        "redirect_path": redirect_path,
        "code_verifier": code_verifier,
        "metadata": metadata or {},
        "expires_at": expires_at.isoformat(),
    }
    client = get_supabase_client()
    response = client.table("nexus_oauth_states").insert(payload).execute()
    row = response.data[0]
    return state_token, OAuthStateRecord(**row)


def consume_oauth_state(provider: NexusProvider, state_token: str) -> OAuthStateRecord:
    client = get_supabase_client()
    select_response = (
        client.table("nexus_oauth_states")
        .select("*")
        .eq("state_digest", _digest(state_token))
        .eq("provider", provider.value)
        .limit(1)
        .execute()
    )
    if not select_response.data:
        raise ValueError("Invalid OAuth state")

    consumed_at = _utcnow()
    updated = (
        client.table("nexus_oauth_states")
        .update({"consumed_at": consumed_at.isoformat()})
        .eq("state_digest", _digest(state_token))
        .eq("provider", provider.value)
        .is_("consumed_at", "null")
        .gt("expires_at", consumed_at.isoformat())
        .execute()
    )
    if updated.data:
        return OAuthStateRecord(**updated.data[0])

    record = OAuthStateRecord(**select_response.data[0])
    if record.consumed_at is not None:
        raise ValueError("OAuth state has already been used")
    if record.expires_at <= consumed_at:
        raise ValueError("OAuth state has expired")
    raise ValueError("OAuth state could not be consumed safely")


def _digest(state_token: str) -> str:
    return hashlib.sha256(state_token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
