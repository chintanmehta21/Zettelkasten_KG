from __future__ import annotations

import base64
import hashlib
import os
import secrets

import httpx

_PLACEHOLDER_TOKENS = (
    "nexus-smoke",
    "example",
    "replace",
    "your-",
    "your_",
    "changeme",
    "test-",
)


def require_env(name: str, *, allow_placeholder: bool = False) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    if not allow_placeholder and is_placeholder_value(value):
        raise RuntimeError(
            f"Environment variable {name} is using a placeholder value. "
            "Set the real OAuth app credential."
        )
    return value


def is_placeholder_value(value: str) -> bool:
    probe = value.strip().lower()
    if not probe:
        return True
    return any(token in probe for token in _PLACEHOLDER_TOKENS)


def describe_oauth_error(response: httpx.Response, *json_keys: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "no response body").strip()[:500]

    for key in json_keys:
        value = payload
        for part in key.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value:
            return str(value)[:500]

    return str(payload)[:500]


def raise_for_oauth_status(
    response: httpx.Response,
    *,
    provider_label: str,
    action: str,
    json_keys: tuple[str, ...],
) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = describe_oauth_error(response, *json_keys)
        raise RuntimeError(
            f"{provider_label} OAuth {action} failed with status {response.status_code}: {detail}"
        ) from exc


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def build_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
