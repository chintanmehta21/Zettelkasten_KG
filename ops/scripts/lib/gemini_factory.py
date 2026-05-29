"""Instantiate a TieredGeminiClient from the same api_env the server uses."""
from __future__ import annotations

import os
from typing import Any

from website.features.api_key_switching.key_pool import (
    GeminiKeyPool,
    _load_keys_from_file,
    candidate_api_env_paths,
    filter_api_keys_by_role,
    parse_api_env_line,
)
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient


def _parse_csv_key_spec(raw: str) -> tuple[str, str] | None:
    """Parse one CSV element from GEMINI_API_KEYS into (key, role).

    Reuses ``parse_api_env_line`` so a bare ``AIza...`` defaults to ``free``
    and ``AIza... role=billing`` is honored — keeping the env-var path
    behaviorally identical to the api_env file path. Returns ``None`` for
    empty/whitespace-only entries so callers can skip them.
    """
    cleaned = raw.strip()
    if not cleaned:
        return None
    return parse_api_env_line(cleaned)


def make_client() -> TieredGeminiClient:
    keys: list[Any] = []
    env_keys: list[Any] = []
    # Legacy single-key vars: no role syntax supported here, treat as free.
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2"):
        value = os.environ.get(name)
        if value and value.strip():
            env_keys.append((value.strip(), "free"))
    env_key_csv = os.environ.get("GEMINI_API_KEYS")
    if env_key_csv:
        for raw in env_key_csv.split(","):
            spec = _parse_csv_key_spec(raw)
            if spec is not None:
                env_keys.append(spec)
    keys.extend(filter_api_keys_by_role(env_keys))
    if not keys:
        for candidate in candidate_api_env_paths():
            loaded = filter_api_keys_by_role(_load_keys_from_file(str(candidate)))
            if loaded:
                keys.extend(loaded)
                break
    if not keys:
        raise RuntimeError(
            "No Gemini API keys found — populate api_env or GEMINI_API_KEY(S)"
        )
    return TieredGeminiClient(GeminiKeyPool(keys), load_config())
