"""Pure-Python SSE parser used to unit-test the iter-09 harness reader.

The in-page Playwright reader uses `r.body.getReader()` and `performance.now()`
for true wall-clock; this module replicates the framing logic so behaviour can
be validated without a browser.
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterable


_FRAME_END = b"\n\n"
_EVENT_RE = re.compile(rb"event:\s*(\S+)")
_DATA_RE = re.compile(rb"data:\s*(.*)", re.DOTALL)


def parse_sse_stream(chunks: Iterable[bytes]) -> dict:
    t0 = time.monotonic_ns()
    buf = b""
    first_token_ns: int | None = None
    last_token_ns: int | None = None
    done_ns: int | None = None
    error: dict | None = None

    for chunk in chunks:
        buf += chunk
        while True:
            idx = buf.find(_FRAME_END)
            if idx < 0:
                break
            frame, buf = buf[:idx], buf[idx + len(_FRAME_END):]
            if frame.startswith(b":"):
                continue
            ev_match = _EVENT_RE.search(frame)
            data_match = _DATA_RE.search(frame)
            if ev_match is None:
                continue
            ev = ev_match.group(1).decode("utf-8")
            now_ns = time.monotonic_ns()
            if ev == "token":
                if first_token_ns is None:
                    first_token_ns = now_ns
                last_token_ns = now_ns
            elif ev == "done":
                done_ns = now_ns
                break
            elif ev == "error" and data_match:
                try:
                    error = json.loads(data_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    error = {"raw": data_match.group(1).decode("utf-8", "replace")}
                break

    def _to_ms(ns: int | None) -> float | None:
        return None if ns is None else (ns - t0) / 1_000_000

    return {
        "p_user_first_token_ms": _to_ms(first_token_ns),
        "p_user_last_token_ms": _to_ms(last_token_ns),
        "p_user_complete_ms": _to_ms(done_ns),
        "error": error,
    }
