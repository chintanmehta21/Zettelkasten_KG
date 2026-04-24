"""Inverted FactScore self-check phase."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.summarization.common.json_utils import parse_json_object
from website.features.summarization_engine.summarization.common.prompts import SYSTEM_PROMPT

try:
    from google.api_core import exceptions as _gapi_exc  # type: ignore
except Exception:  # pragma: no cover - google-api-core is a runtime dep
    _gapi_exc = None  # type: ignore

logger = logging.getLogger(__name__)

# Retry up to this many times on transient upstream failures before failing
# open. Two retries with 2s then 5s delays ≈ 7s added latency worst-case.
_SELF_CHECK_MAX_RETRIES = 2
_SELF_CHECK_RETRY_DELAYS_SEC = (2.0, 5.0)

_IMPORTANCE_MAP = {"low": 1, "medium": 2, "mid": 2, "high": 3, "very high": 4, "critical": 5}


class MissingClaim(BaseModel):
    claim: str
    importance: int = Field(default=1, ge=1, le=5)

    @field_validator("importance", mode="before")
    @classmethod
    def coerce_importance(cls, v):
        if isinstance(v, int):
            return max(1, min(v, 5))
        if isinstance(v, str):
            s = v.strip().lower().split(".")[0].split(",")[0].strip()
            try:
                return max(1, min(int(s), 5))
            except ValueError:
                return _IMPORTANCE_MAP.get(s, 3)
        return 1


@dataclass
class SelfCheckResult:
    missing: list[MissingClaim] = field(default_factory=list)
    pro_tokens: int = 0

    @property
    def missing_count(self) -> int:
        return len(self.missing)


def _is_transient_error(exc: BaseException) -> bool:
    """Return True for errors that merit a retry.

    Transient = 5xx from Gemini, DeadlineExceeded, ServiceUnavailable,
    or asyncio/builtin TimeoutError. 4xx (client errors / invalid args)
    are NOT retried — those are bugs, not transient.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    if _gapi_exc is not None:
        # DeadlineExceeded and ServiceUnavailable are ServerError subclasses.
        if isinstance(exc, _gapi_exc.ServerError):
            return True
        if isinstance(exc, _gapi_exc.ClientError):
            return False
        if isinstance(exc, _gapi_exc.GoogleAPICallError):
            # Fallback: treat >=500 codes as transient, <500 as permanent.
            code = getattr(exc, "code", None)
            try:
                code_int = int(code) if code is not None else None
            except Exception:  # noqa: BLE001
                code_int = None
            if code_int is not None and code_int >= 500:
                return True
            return False
    # Fallback pattern match for environments without google-api-core
    # exception classes wired (tests, key-pool-wrapped errors).
    msg = str(exc).lower()
    if "504" in msg or "503" in msg or "502" in msg or "500" in msg:
        return True
    if "timeout" in msg or "deadline" in msg or "unavailable" in msg:
        return True
    return False


class InvertedFactScoreSelfCheck:
    def __init__(self, client: TieredGeminiClient, config: EngineConfig):
        self._client = client
        self._config = config

    async def check(self, source_text: str, summary_text: str) -> SelfCheckResult:
        if not self._config.self_check.enabled:
            return SelfCheckResult()
        prompt = (
            "Compare SOURCE to SUMMARY. Return JSON with key missing, a list of "
            "important source claims absent from summary. Each item: claim, importance.\n\n"
            f"SOURCE:\n{source_text}\n\nSUMMARY:\n{summary_text}"
        )

        result = None
        last_exc: BaseException | None = None
        for attempt in range(_SELF_CHECK_MAX_RETRIES + 1):
            try:
                result = await self._client.generate(
                    prompt,
                    tier="pro",
                    system_instruction=SYSTEM_PROMPT,
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= _SELF_CHECK_MAX_RETRIES or not _is_transient_error(exc):
                    # Give up: fail open with empty result (preserves summary).
                    logger.info(
                        "self_check.fail_open attempt=%d error_class=%s transient=%s",
                        attempt + 1,
                        exc.__class__.__name__,
                        _is_transient_error(exc),
                    )
                    return SelfCheckResult()
                delay = _SELF_CHECK_RETRY_DELAYS_SEC[
                    min(attempt, len(_SELF_CHECK_RETRY_DELAYS_SEC) - 1)
                ]
                logger.info(
                    "self_check.retry attempt=%d next_attempt=%d error_class=%s delay_sec=%.1f",
                    attempt + 1,
                    attempt + 2,
                    exc.__class__.__name__,
                    delay,
                )
                await asyncio.sleep(delay)

        if result is None:
            # Defensive: loop always either returns or sets result.
            logger.info(
                "self_check.fail_open_exhausted last_error_class=%s",
                last_exc.__class__.__name__ if last_exc else "unknown",
            )
            return SelfCheckResult()
        tokens = result.input_tokens + result.output_tokens
        try:
            payload = parse_json_object(result.text)
        except Exception:
            return SelfCheckResult(pro_tokens=tokens)
        missing = []
        for item in payload.get("missing", [])[: self._config.self_check.max_atomic_claims]:
            try:
                missing.append(MissingClaim(**item))
            except Exception:
                continue
        return SelfCheckResult(missing=missing, pro_tokens=tokens)
