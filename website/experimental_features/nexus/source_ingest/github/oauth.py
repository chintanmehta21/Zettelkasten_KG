from __future__ import annotations

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
    raise_for_oauth_status,
    require_env,
)

PROVIDER = NexusProvider.GITHUB
SCOPES: tuple[str, ...] = ("repo", "read:user")

CLIENT_ID_ENV = "NEXUS_GITHUB_CLIENT_ID"
CLIENT_SECRET_ENV = "NEXUS_GITHUB_CLIENT_SECRET"
REDIRECT_URI_ENV = "NEXUS_GITHUB_REDIRECT_URI"
ENV_CONFIG_NAMES: tuple[str, ...] = (
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    REDIRECT_URI_ENV,
)

AUTHORIZATION_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
REQUEST_TIMEOUT = 20.0


@dataclass(frozen=True)
class GitHubOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


def get_oauth_config() -> GitHubOAuthConfig:
    return GitHubOAuthConfig(
        client_id=require_env(CLIENT_ID_ENV),
        client_secret=require_env(CLIENT_SECRET_ENV),
        redirect_uri=require_env(REDIRECT_URI_ENV),
    )


def build_authorization_url(
    *,
    auth_user_sub: str,
    redirect_path: str | None = "/home/nexus",
    metadata: dict[str, Any] | None = None,
    scopes: Sequence[str] | None = None,
) -> OAuthStartResponse:
    config = get_oauth_config()
    state_token, state_record = issue_oauth_state(
        provider=PROVIDER,
        auth_user_sub=auth_user_sub,
        redirect_path=redirect_path,
        metadata=metadata,
    )
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(scopes or SCOPES),
        "state": state_token,
    }
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
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": code,
        "redirect_uri": config.redirect_uri,
    }
    token_set = await _request_token_set(payload, client=client)
    return state_record, token_set


async def refresh_access_token(
    refresh_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> ProviderTokenSet:
    config = get_oauth_config()
    payload = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
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
            headers={
                "Accept": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        raise_for_oauth_status(
            response,
            provider_label="GitHub",
            action="token exchange",
            json_keys=("error_description", "error"),
        )
        data = response.json()
    finally:
        if own_client:
            await http_client.aclose()

    token_set = ProviderTokenSet.from_token_payload(data)
    if not token_set.access_token:
        raise RuntimeError("GitHub OAuth token exchange did not return an access token.")
    return token_set

__all__ = [
    "AUTHORIZATION_URL",
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "ENV_CONFIG_NAMES",
    "GitHubOAuthConfig",
    "PROVIDER",
    "REDIRECT_URI_ENV",
    "SCOPES",
    "TOKEN_URL",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "get_oauth_config",
    "refresh_access_token",
]
