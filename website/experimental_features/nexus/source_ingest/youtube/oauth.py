from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import urlencode

import httpx

from website.experimental_features.nexus.source_ingest.common.models import (
    NexusProvider,
    OAuthStartResponse,
    OAuthStateRecord,
    ProviderTokenSet,
)
from website.experimental_features.nexus.source_ingest.common.oauth_state import (
    consume_oauth_state,
    issue_oauth_state,
)
from website.experimental_features.nexus.source_ingest.common.oauth_utils import (
    build_code_challenge,
    generate_code_verifier,
    raise_for_oauth_status,
    require_env,
)

PROVIDER = NexusProvider.YOUTUBE
SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/youtube.readonly",)

CLIENT_ID_ENV = "NEXUS_YOUTUBE_CLIENT_ID"
CLIENT_SECRET_ENV = "NEXUS_YOUTUBE_CLIENT_SECRET"
REDIRECT_URI_ENV = "NEXUS_YOUTUBE_REDIRECT_URI"
ENV_CONFIG_NAMES: tuple[str, ...] = (
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    REDIRECT_URI_ENV,
)

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REQUEST_TIMEOUT = 20.0
FORCE_CONSENT_ENV = "NEXUS_YOUTUBE_FORCE_CONSENT"


@dataclass(frozen=True)
class YouTubeOAuthConfig:
    client_id: str
    client_secret: str | None
    redirect_uri: str


def get_oauth_config() -> YouTubeOAuthConfig:
    client_id = require_env(CLIENT_ID_ENV)
    _validate_client_id(client_id)
    redirect_uri = require_env(REDIRECT_URI_ENV)
    client_secret = os.environ.get(CLIENT_SECRET_ENV) or None
    return YouTubeOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )


def build_authorization_url(
    *,
    auth_user_sub: str,
    redirect_path: str | None = "/home/nexus",
    metadata: dict[str, Any] | None = None,
    scopes: Sequence[str] | None = None,
) -> OAuthStartResponse:
    config = get_oauth_config()
    code_verifier = generate_code_verifier()
    state_token, state_record = issue_oauth_state(
        provider=PROVIDER,
        auth_user_sub=auth_user_sub,
        redirect_path=redirect_path,
        code_verifier=code_verifier,
        metadata=metadata,
    )
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes or SCOPES),
        "state": state_token,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "code_challenge": build_code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    if _force_consent():
        params["prompt"] = "consent"
    return OAuthStartResponse(
        provider=PROVIDER,
        authorization_url=f"{AUTHORIZATION_URL}?{urlencode(params)}",
        expires_at=state_record.expires_at,
    )


async def exchange_code_for_tokens(
    *,
    code: str,
    state_token: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[OAuthStateRecord, ProviderTokenSet]:
    state_record = consume_oauth_state(PROVIDER, state_token)
    config = get_oauth_config()
    payload = {
        "code": code,
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": state_record.code_verifier or "",
    }
    if config.client_secret:
        payload["client_secret"] = config.client_secret
    token_set = await _request_token_set(payload, client=client)
    return state_record, token_set


async def refresh_access_token(
    refresh_token: str,
    *,
    scopes: Sequence[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> ProviderTokenSet:
    config = get_oauth_config()
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
    }
    if scopes:
        payload["scope"] = " ".join(scopes)
    if config.client_secret:
        payload["client_secret"] = config.client_secret
    return await _request_token_set(payload, client=client)


async def _request_token_set(
    payload: dict[str, str],
    *,
    client: httpx.AsyncClient | None = None,
) -> ProviderTokenSet:
    own_client = client is None
    http_client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        response = await http_client.post(
            TOKEN_URL,
            data=payload,
            headers={"Accept": "application/json"},
        )
        raise_for_oauth_status(
            response,
            provider_label="YouTube",
            action="token exchange",
            json_keys=("error.message", "error.status", "error"),
        )
        data = response.json()
    finally:
        if own_client:
            await http_client.aclose()

    token_set = ProviderTokenSet.from_token_payload(data)
    if not token_set.access_token:
        raise RuntimeError("YouTube OAuth token exchange did not return an access token.")
    return token_set

def _force_consent() -> bool:
    raw = (os.environ.get(FORCE_CONSENT_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}

def _validate_client_id(client_id: str) -> None:
    candidate = client_id.strip()
    if candidate.endswith(".apps.googleusercontent.com"):
        return
    raise RuntimeError(
        f"Invalid {CLIENT_ID_ENV} value. Expected a Google OAuth Client ID ending "
        "with '.apps.googleusercontent.com' (not an email, username, or project name)."
    )

__all__ = [
    "AUTHORIZATION_URL",
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "ENV_CONFIG_NAMES",
    "PROVIDER",
    "REDIRECT_URI_ENV",
    "SCOPES",
    "TOKEN_URL",
    "YouTubeOAuthConfig",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "get_oauth_config",
    "refresh_access_token",
]
