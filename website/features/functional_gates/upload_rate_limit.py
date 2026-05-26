"""Per-(user, ip) sliding-window rate limiter for upload routes.

Reuses the same in-memory token-list pattern as ``_check_rate_limit`` in
``zettels_routes.py``, but keyed on the (user_id, ip) tuple so:
  * Two distinct users sharing one IP (NAT, library wifi) don't share quota.
  * One user across multiple devices doesn't get a single-IP quota.

Per the functional_gates reuse rule: one implementation here, applied at
each upload endpoint via ``check_upload_rate_limit``. State is per-worker
(in-memory) — blue/green flip drops the window, which is fine: the window
itself is one-minute and ops accepts the small refresh on color flip.
"""

from __future__ import annotations

import time
from collections import defaultdict


class UploadRateLimiter:
    """Sliding-window per-(user, ip) limiter.

    Stateful — instantiate once per route (or once globally), call
    ``allow(user_id, ip)`` per request. Thread-safe within a single
    gunicorn worker via Python's GIL on dict mutation (no inter-worker
    coordination — by design; see module docstring).
    """

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window = window_seconds
        self._store: dict[tuple[str, str], list[float]] = defaultdict(list)

    def allow(self, user_id: str, ip: str) -> bool:
        key = (user_id, ip)
        now = time.monotonic()
        bucket = [t for t in self._store[key] if now - t < self._window]
        if len(bucket) >= self._limit:
            self._store[key] = bucket
            return False
        bucket.append(now)
        self._store[key] = bucket
        return True
