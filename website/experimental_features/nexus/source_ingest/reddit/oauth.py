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

PROVIDER = NexusProvider.REDDIT
SCOPES: tuple[str, ...] = ("identity", "history", "read")

CLIENT_ID_ENV = "NEXUS_REDDIT_CLIENT_ID"
CLIENT_SECRET_ENV = "NEXUS_REDDIT_CLIENT_SECRET"
REDIRECT_URI_ENV = "NEXUS_REDDIT_REDIRECT_URI"
USER_AGENT_ENV = "NEXUS_REDDIT_USER_AGENT"
ENV_CONFIG_NAMES: tuple[str, ...] = (
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    REDIRECT_URI_ENV,
    USER_AGENT_ENV,
)

AUTHORIZATION_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REQUEST_TIMEOUT = 20.0
DEFAULT_USER_AGENT = "nexus-ingest/1.0"


@dataclass(frozen=True)
class RedditOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    user_agent: str


def get_oauth_config() -> RedditOAuthConfig:
    return RedditOAuthConfig(
        client_id=_require_env(CLIENT_ID_ENV),
        client_secret=os.environ.get(CLIENT_SECRET_ENV, ""),
        redirect_uri=_require_env(REDIRECT_URI_ENV),
        user_agent=(os.environ.get(USER_AGENT_ENV) or DEFAULT_USER_AGENT).strip(),
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
        "response_type": "code",
        "state": state_token,
        "redirect_uri": config.redirect_uri,
        "duration": "permanent",
        "scope": " ".join(scopes or SCOPES),
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
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
    }
    token_set = await _request_token_set(payload, config=config, client=client)
    return state_record, token_set


async def refresh_access_token(
    refresh_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> ProviderTokenSet:
    config = get_oauth_config()
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    return await _request_token_set(payload, config=config, client=client)


async def _request_token_set(
    payload: dict[str, str],
    *,
    config: RedditOAuthConfig,
    client: httpx.AsyncClient | None = None,
) -> ProviderTokenSet:
    own_client = client is None
    http_client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        response = await http_client.post(
            TOKEN_URL,
            data=payload,
            auth=httpx.BasicAuth(config.client_id, config.client_secret),
            headers={
                "Accept": "application/json",
                "User-Agent": config.user_agent,
            },
        )
        _raise_for_status(response, "token exchange")
        data = response.json()
    finally:
        if own_client:
            await http_client.aclose()

    token_set = ProviderTokenSet.from_token_payload(data)
    if not token_set.access_token:
        raise RuntimeError("Reddit OAuth token exchange did not return an access token.")
    return token_set


def _raise_for_status(response: httpx.Response, action: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = _response_detail(response)
        raise RuntimeError(
            f"Reddit OAuth {action} failed with status {response.status_code}: {detail}"
        ) from exc


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "no response body").strip()[:500]
    return str(payload.get("error") or payload)[:500]


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    if _is_placeholder(value):
        raise RuntimeError(
            f"Environment variable {name} is using a placeholder value. "
            "Set the real OAuth app credential."
        )
    return value


def _is_placeholder(value: str) -> bool:
    probe = value.strip().lower()
    if not probe:
        return True
    placeholder_tokens = (
        "nexus-smoke",
        "example",
        "replace",
        "your-",
        "your_",
        "changeme",
        "test-",
    )
    return any(token in probe for token in placeholder_tokens)


__all__ = [
    "AUTHORIZATION_URL",
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "ENV_CONFIG_NAMES",
    "PROVIDER",
    "REDIRECT_URI_ENV",
    "SCOPES",
    "TOKEN_URL",
    "USER_AGENT_ENV",
    "RedditOAuthConfig",
    "build_authorization_url",
    "exchange_code_for_tokens",
    "get_oauth_config",
    "refresh_access_token",
]
