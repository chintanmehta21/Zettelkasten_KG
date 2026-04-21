"""Centralized Gemini API key pool with multi-key rotation and model fallback.

Manages N API keys (from separate GCP projects) with per-(key, model) cooldown
tracking.  Provides two entry points:

  - generate_content() — for summarization, NL query, entity extraction
  - embed_content()    — for embedding generation (single model, key rotation)

Traversal order: last-successful key first (fast path), then key-first
across model tiers.  Cooldowns are short (10s) since Gemini rate limits
reset per-minute.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time

import httpx
from google import genai
from google.genai.errors import ClientError

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_MAX_KEYS = 10
_MAX_RETRIES = 3  # Cap transient-error retries (across the attempt chain)
_RATE_LIMIT_COOLDOWN_SECS = 10  # Short cooldown; Gemini resets per-minute

_GENERATIVE_MODEL_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

_EMBEDDING_MODEL = "gemini-embedding-001"


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_api_env_line(line: str) -> tuple[str, str]:
    """Parse one api_env line into ``(key, role)``."""
    parts = line.strip().split()
    if not parts:
        raise ValueError("empty api_env line")

    key = parts[0]
    role = "free"
    for token in parts[1:]:
        if token.startswith("role="):
            role = token.split("=", 1)[1].strip().lower()
            if role not in {"free", "billing"}:
                raise ValueError(f"invalid role '{role}' on api_env line")
    return key, role


def _is_rate_limited(exc: Exception) -> bool:
    """Return True if *exc* is a Gemini 429 rate-limit error."""
    if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
        return True
    return "429" in str(exc) and "RESOURCE_EXHAUSTED" in str(exc)


def _is_retryable(exc: Exception) -> bool:
    """Return True if *exc* is a transient error worth retrying on next key.

    Covers 429 rate-limits, 503 UNAVAILABLE, and 504 DEADLINE_EXCEEDED.
    """
    if _is_rate_limited(exc):
        return True
    if isinstance(exc, ClientError) and getattr(exc, "code", None) in (503, 504):
        return True
    exc_str = str(exc)
    if "DEADLINE_EXCEEDED" in exc_str or "504" in exc_str:
        return True
    if "UNAVAILABLE" in exc_str or "503" in exc_str:
        return True
    return False


def _send_slack_alert(message: str) -> None:
    """Fire-and-forget Slack webhook alert.  Silent no-op if not configured."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        return
    try:
        httpx.post(webhook_url, json={"text": message}, timeout=5.0)
    except Exception:
        logger.debug("Slack alert failed (non-critical)", exc_info=True)


def _load_keys_from_file(path: str) -> list[str | tuple[str, str]]:
    """Read API keys from an api_env file.

    Plain one-key lines stay as strings for backward compatibility, while
    ``role=...`` tagged lines return ``(key, role)`` tuples.
    """
    try:
        with open(path, encoding="utf-8") as f:
            keys: list[str | tuple[str, str]] = []
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                key, role = parse_api_env_line(stripped)
                if "role=" in stripped:
                    keys.append((key, role))
                else:
                    keys.append(key)
            return keys
    except FileNotFoundError:
        return []


@dataclass(frozen=True)
class Attempt:
    key: str
    role: str
    model: str


# ── GeminiKeyPool ────────────────────────────────────────────────────────────

class GeminiKeyPool:
    """Pool of Gemini API clients with automatic key/model rotation."""

    def __init__(self, api_keys: list[str] | list[tuple[str, str]]) -> None:
        if not api_keys:
            raise ValueError("GeminiKeyPool requires at least one API key")
        if len(api_keys) > _MAX_KEYS:
            raise ValueError(f"GeminiKeyPool supports a maximum of {_MAX_KEYS} keys")

        normalized: list[tuple[str, str]] = []
        for entry in api_keys:
            if isinstance(entry, tuple):
                key, role = entry
            else:
                key, role = entry, "free"

            key = key.strip()
            role = role.strip().lower()
            if not key:
                raise ValueError("Gemini API keys cannot be empty")
            if role not in {"free", "billing"}:
                raise ValueError(f"invalid Gemini key role '{role}'")
            normalized.append((key, role))

        normalized.sort(key=lambda item: item[1] != "free")

        self._keys = [key for key, _role in normalized]
        self._key_roles = [role for _key, role in normalized]
        self._clients: dict[int, genai.Client] = {}
        # (key_index, model_name) → cooldown expiry (monotonic timestamp)
        self._cooldowns: dict[tuple[int, str], float] = {}
        # Round-robin counters — spread load across all keys evenly
        self._next_gen_key: int = 0
        self._next_emb_key: int = 0

    # ── Client management ────────────────────────────────────────────

    def _get_client(self, key_index: int) -> genai.Client:
        """Return (lazily create) the genai.Client for key at *key_index*."""
        if key_index not in self._clients:
            self._clients[key_index] = genai.Client(
                api_key=self._keys[key_index],
                http_options={"timeout": 60_000},  # 60s in ms
            )
        return self._clients[key_index]

    # ── Cooldown management ──────────────────────────────────────────

    def _mark_cooldown(self, key_index: int, model: str) -> None:
        """Put (key_index, model) on cooldown."""
        self._cooldowns[(key_index, model)] = (
            time.monotonic() + _RATE_LIMIT_COOLDOWN_SECS
        )

    def _is_on_cooldown(self, key_index: int, model: str) -> bool:
        """Check if a slot is on cooldown without full purge."""
        exp = self._cooldowns.get((key_index, model))
        if exp is None:
            return False
        if exp <= time.monotonic():
            del self._cooldowns[(key_index, model)]
            return False
        return True

    def _purge_expired(self) -> None:
        """Remove expired cooldown entries."""
        now = time.monotonic()
        self._cooldowns = {
            slot: exp for slot, exp in self._cooldowns.items() if exp > now
        }

    def _role_for_key(self, key_index: int) -> str:
        return self._key_roles[key_index]

    def _ordered_key_indices(self, start_index: int) -> list[int]:
        """Return rotated key order while keeping free keys ahead of billing."""
        n = len(self._keys)
        rotated = [(start_index + i) % n for i in range(n)]
        free = [index for index in rotated if self._role_for_key(index) == "free"]
        billing = [
            index for index in rotated if self._role_for_key(index) == "billing"
        ]
        return free + billing

    def next_attempt(self, model: str) -> Attempt:
        """Return the next available attempt for *model* with role metadata."""
        key_index, attempt_model = self._build_attempt_chain(starting_model=model)[0]
        return Attempt(
            key=self._keys[key_index],
            role=self._role_for_key(key_index),
            model=attempt_model,
        )

    def _log_quota_exhausted(
        self,
        *,
        model: str,
        current_key_role: str,
        next_key_role: str | None,
    ) -> None:
        if current_key_role == "free" and next_key_role == "billing":
            logger.warning(
                "quota_exhausted_event model=%s escalating_to=billing",
                model,
            )

    # ── Chain building ───────────────────────────────────────────────

    def _build_attempt_chain(
        self,
        starting_model: str | None = None,
    ) -> list[tuple[int, str]]:
        """Build the (key_index, model) attempt chain.

        Round-robin: starts from the next key in rotation so load is
        spread evenly across all keys (prevents pinning to one paid key).
        Key-first traversal: all keys tried per model before fallback.
        """
        self._purge_expired()
        n = len(self._keys)

        if starting_model:
            models = [starting_model] + [
                m for m in _GENERATIVE_MODEL_CHAIN if m != starting_model
            ]
        else:
            models = list(_GENERATIVE_MODEL_CHAIN)

        # Rotate key order starting from _next_gen_key, but always try free
        # keys before billing keys so quota escalation happens last.
        key_indices = self._ordered_key_indices(self._next_gen_key)

        full_chain = [
            (ki, model) for model in models for ki in key_indices
        ]

        filtered = [
            slot for slot in full_chain if slot not in self._cooldowns
        ]

        if not filtered:
            logger.warning("All key/model slots on cooldown — retrying full chain")
            return full_chain

        return filtered

    def _build_embedding_chain(self) -> list[tuple[int, str]]:
        """Build the embedding attempt chain with round-robin key rotation."""
        self._purge_expired()
        n = len(self._keys)

        key_indices = self._ordered_key_indices(self._next_emb_key)
        full_chain = [(ki, _EMBEDDING_MODEL) for ki in key_indices]

        filtered = [
            slot for slot in full_chain if slot not in self._cooldowns
        ]

        if not filtered:
            logger.warning("All embedding key slots on cooldown — retrying full chain")
            return full_chain

        return filtered

    # ── Generative API ───────────────────────────────────────────────

    async def generate_content(
        self,
        contents,
        *,
        config: dict | None = None,
        starting_model: str | None = None,
        label: str = "",
    ):
        """Generate content with automatic key/model fallback.

        Retries up to ``_MAX_RETRIES`` times on transient errors (429 rate-
        limit, 504 DEADLINE_EXCEEDED).  On exhaustion, fires a Slack alert
        and raises the last exception.

        Returns (response, model_used, key_index) on success.
        """
        chain = self._build_attempt_chain(starting_model=starting_model)
        last_exc: Exception | None = None
        retries = 0

        for position, (key_index, model) in enumerate(chain):
            try:
                client = self._get_client(key_index)
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config or {},
                )
                # Advance round-robin so next call starts from a different key
                self._next_gen_key = (key_index + 1) % len(self._keys)
                return response, model, key_index
            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc):
                    retries += 1
                    self._mark_cooldown(key_index, model)
                    next_key_role = None
                    if position + 1 < len(chain):
                        next_key_role = self._role_for_key(chain[position + 1][0])
                    self._log_quota_exhausted(
                        model=model,
                        current_key_role=self._role_for_key(key_index),
                        next_key_role=next_key_role,
                    )
                    if _is_rate_limited(exc):
                        reason = "rate-limited"
                    elif "503" in str(exc) or "UNAVAILABLE" in str(exc):
                        reason = "unavailable"
                    else:
                        reason = "timeout"
                    logger.warning(
                        "%s %s on key[%d]/%s — retry %d/%d, cooldown %ds",
                        label or "Gemini",
                        reason,
                        key_index,
                        model,
                        retries,
                        _MAX_RETRIES,
                        _RATE_LIMIT_COOLDOWN_SECS,
                    )
                    if retries >= _MAX_RETRIES:
                        logger.error(
                            "%s exhausted %d retries — giving up",
                            label or "Gemini",
                            _MAX_RETRIES,
                        )
                        _send_slack_alert(
                            f":warning: *Gemini API failure* — `{label or 'generate_content'}` "
                            f"exhausted {_MAX_RETRIES} retries. "
                            f"Last error: `{reason}` on key[{key_index}]/{model}. "
                            f"Exception: `{exc}`"
                        )
                        raise
                    continue
                raise

        # Entire chain exhausted without hitting _MAX_RETRIES (e.g. all on cooldown)
        _send_slack_alert(
            f":warning: *Gemini API failure* — `{label or 'generate_content'}` "
            f"all key/model slots exhausted after {retries} retries. "
            f"Last error: `{last_exc}`"
        )
        raise last_exc  # type: ignore[misc]

    # ── Embedding API ────────────────────────────────────────────────

    def embed_content(self, contents, *, config: dict | None = None):
        """Embed content with automatic key rotation.

        Tries all keys for gemini-embedding-001.  Returns the response
        on first success.  Raises the last exception on total failure.
        """
        chain = self._build_embedding_chain()
        last_exc: Exception | None = None

        for position, (key_index, model) in enumerate(chain):
            try:
                client = self._get_client(key_index)
                response = client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=config or {},
                )
                self._next_emb_key = (key_index + 1) % len(self._keys)
                return response
            except Exception as exc:
                last_exc = exc
                if _is_rate_limited(exc):
                    self._mark_cooldown(key_index, model)
                    next_key_role = None
                    if position + 1 < len(chain):
                        next_key_role = self._role_for_key(chain[position + 1][0])
                    self._log_quota_exhausted(
                        model=model,
                        current_key_role=self._role_for_key(key_index),
                        next_key_role=next_key_role,
                    )
                    logger.warning(
                        "Embedding rate-limited on key[%d] — cooldown %ds, trying next",
                        key_index,
                        _RATE_LIMIT_COOLDOWN_SECS,
                    )
                    continue
                raise

        raise last_exc  # type: ignore[misc]

    def embed_content_safe(self, contents, *, config: dict | None = None):
        """Like embed_content, but returns None instead of raising.

        Preserves existing behavior where embeddings fail silently.
        """
        try:
            return self.embed_content(contents, config=config)
        except Exception as exc:
            logger.error("All embedding keys exhausted: %s", exc)
            return None
