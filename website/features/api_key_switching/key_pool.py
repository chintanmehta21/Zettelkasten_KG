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

import logging
import time

import httpx
from google import genai
from google.genai.errors import ClientError

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_MAX_KEYS = 10
_RATE_LIMIT_COOLDOWN_SECS = 10  # Short cooldown; Gemini resets per-minute

_GENERATIVE_MODEL_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

_EMBEDDING_MODEL = "gemini-embedding-001"

# Connection/read timeouts to prevent hanging on slow Gemini responses
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=25.0, write=5.0, pool=5.0)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_rate_limited(exc: Exception) -> bool:
    """Return True if *exc* is a Gemini 429 rate-limit error."""
    if isinstance(exc, ClientError) and getattr(exc, "code", None) == 429:
        return True
    return "429" in str(exc) and "RESOURCE_EXHAUSTED" in str(exc)


def _load_keys_from_file(path: str) -> list[str]:
    """Read API keys from an api_env file.  One key per line, # comments ignored."""
    try:
        with open(path) as f:
            keys = []
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                keys.append(line)
            return keys
    except FileNotFoundError:
        return []


# ── GeminiKeyPool ────────────────────────────────────────────────────────────

class GeminiKeyPool:
    """Pool of Gemini API clients with automatic key/model rotation."""

    def __init__(self, api_keys: list[str]) -> None:
        if not api_keys:
            raise ValueError("GeminiKeyPool requires at least one API key")
        if len(api_keys) > _MAX_KEYS:
            raise ValueError(f"GeminiKeyPool supports a maximum of {_MAX_KEYS} keys")

        self._keys = list(api_keys)
        self._clients: dict[int, genai.Client] = {}
        # (key_index, model_name) → cooldown expiry (monotonic timestamp)
        self._cooldowns: dict[tuple[int, str], float] = {}
        # Track last successful (key_index, model) for fast-path
        self._last_success_gen: tuple[int, str] | None = None
        self._last_success_emb: int | None = None

    # ── Client management ────────────────────────────────────────────

    def _get_client(self, key_index: int) -> genai.Client:
        """Return (lazily create) the genai.Client for key at *key_index*."""
        if key_index not in self._clients:
            http_client = httpx.Client(timeout=_HTTP_TIMEOUT)
            async_http_client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
            self._clients[key_index] = genai.Client(
                api_key=self._keys[key_index],
                http_options={"timeout": 25_000},  # 25s in ms
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

    # ── Chain building ───────────────────────────────────────────────

    def _build_attempt_chain(
        self,
        starting_model: str | None = None,
    ) -> list[tuple[int, str]]:
        """Build the (key_index, model) attempt chain.

        Fast path: if the last successful slot is still available, put it first.
        Then key-first traversal for remaining slots.
        """
        self._purge_expired()

        # Build model order: starting model first, then remaining.
        if starting_model and starting_model in _GENERATIVE_MODEL_CHAIN:
            models = [starting_model] + [
                m for m in _GENERATIVE_MODEL_CHAIN if m != starting_model
            ]
        else:
            models = list(_GENERATIVE_MODEL_CHAIN)

        key_indices = list(range(len(self._keys)))

        # Key-first: for each model, try all keys.
        full_chain = [
            (ki, model) for model in models for ki in key_indices
        ]

        filtered = [
            slot for slot in full_chain if slot not in self._cooldowns
        ]

        if not filtered:
            logger.warning("All key/model slots on cooldown — retrying full chain")
            return full_chain

        # Fast path: promote last-successful slot to front
        if self._last_success_gen and self._last_success_gen in filtered:
            filtered.remove(self._last_success_gen)
            filtered.insert(0, self._last_success_gen)

        return filtered

    def _build_embedding_chain(self) -> list[tuple[int, str]]:
        """Build the embedding attempt chain (key rotation only, single model)."""
        self._purge_expired()

        key_indices = list(range(len(self._keys)))
        full_chain = [(ki, _EMBEDDING_MODEL) for ki in key_indices]

        filtered = [
            slot for slot in full_chain if slot not in self._cooldowns
        ]

        if not filtered:
            logger.warning("All embedding key slots on cooldown — retrying full chain")
            return full_chain

        # Fast path: promote last-successful key to front
        if self._last_success_emb is not None:
            target = (self._last_success_emb, _EMBEDDING_MODEL)
            if target in filtered:
                filtered.remove(target)
                filtered.insert(0, target)

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

        Returns (response, model_used, key_index) on success.
        Raises the last exception if ALL (key, model) combinations fail.
        """
        chain = self._build_attempt_chain(starting_model=starting_model)
        last_exc: Exception | None = None

        for key_index, model in chain:
            try:
                client = self._get_client(key_index)
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config or {},
                )
                self._last_success_gen = (key_index, model)
                return response, model, key_index
            except Exception as exc:
                last_exc = exc
                if _is_rate_limited(exc):
                    self._mark_cooldown(key_index, model)
                    logger.warning(
                        "%s rate-limited on key[%d]/%s — cooldown %ds, trying next",
                        label or "Gemini",
                        key_index,
                        model,
                        _RATE_LIMIT_COOLDOWN_SECS,
                    )
                    continue
                raise

        raise last_exc  # type: ignore[misc]

    # ── Embedding API ────────────────────────────────────────────────

    def embed_content(self, contents, *, config: dict | None = None):
        """Embed content with automatic key rotation.

        Tries all keys for gemini-embedding-001.  Returns the response
        on first success.  Raises the last exception on total failure.
        """
        chain = self._build_embedding_chain()
        last_exc: Exception | None = None

        for key_index, model in chain:
            try:
                client = self._get_client(key_index)
                response = client.models.embed_content(
                    model=model,
                    contents=contents,
                    config=config or {},
                )
                self._last_success_emb = key_index
                return response
            except Exception as exc:
                last_exc = exc
                if _is_rate_limited(exc):
                    self._mark_cooldown(key_index, model)
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
