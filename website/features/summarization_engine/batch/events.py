"""SSE progress events for batch runs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProgressEvent:
    event: str
    data: dict[str, Any]

    def as_sse(self) -> dict[str, Any]:
        return {"event": self.event, "data": self.data}
