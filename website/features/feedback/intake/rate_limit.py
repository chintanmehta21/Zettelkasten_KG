"""Sliding-window rate limiter for the feedback endpoint.

Keys are scoped (user_id / cookie / IP) so the same daily budget can be
applied independently to each axis. In-process counters per gunicorn worker
— acceptable for the modest limits operators chose. Container restart resets
state, which is also acceptable (operator's intent is "stop abuse" not
"enforce a precise cap").
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitKey:
    scope: str   # "user" | "cookie" | "ip"
    value: str


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"rate limit hit; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class FeedbackRateLimiter:
    """Thread-safe sliding window.

    Each call to consume(key) appends `time.monotonic()` to that key's deque
    and rejects when len(deque) > daily_cap (after pruning expired entries).
    """

    def __init__(self, *, daily_cap: int, window_seconds: int) -> None:
        self._cap = int(daily_cap)
        self._window = float(window_seconds)
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def consume(self, key: RateLimitKey) -> None:
        """Record one hit for `key`. Raises RateLimitExceeded when over cap."""
        now = time.monotonic()
        cutoff = now - self._window
        dkey = (key.scope, key.value)
        with self._lock:
            q = self._hits[dkey]
            # Prune expired entries
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self._cap:
                # Seconds until the oldest entry exits the window — ceil so we
                # never return 0 (sub-second remainder still means "wait").
                retry_after = math.ceil(q[0] + self._window - now)
                raise RateLimitExceeded(max(1, retry_after))
            q.append(now)
