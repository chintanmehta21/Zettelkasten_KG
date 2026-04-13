"""Append-only JSONL logger for cascade reranker degradation events."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class DegradationLogger:
    """Log structured events when the cascade reranker falls back."""

    def __init__(self, log_dir: str | Path) -> None:
        self._log_path = Path(log_dir) / "degradation_events.jsonl"

    def log_event(
        self,
        *,
        query: str,
        candidate_count: int,
        failed_stage: str,
        exception: BaseException,
        content_lengths: list[int],
        source_types: list[str],
    ) -> None:
        if content_lengths:
            mean = round(sum(content_lengths) / len(content_lengths))
            content_length_stats = {
                "min": min(content_lengths),
                "max": max(content_lengths),
                "mean": mean,
            }
        else:
            content_length_stats = {"min": 0, "max": 0, "mean": 0}

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query_hash": f"sha256:{hashlib.sha256(query.encode('utf-8')).hexdigest()}",
            "candidate_count": candidate_count,
            "failed_stage": failed_stage,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "content_length_stats": content_length_stats,
            "source_types": list(dict.fromkeys(source_types)),
        }

        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            logger.warning("Failed to write degradation event", exc_info=True)
