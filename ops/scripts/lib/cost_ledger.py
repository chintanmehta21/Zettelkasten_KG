"""Track Gemini token and call usage per iteration."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _tier(model: str) -> str:
    if model.endswith("pro"):
        return "pro"
    if "flash-lite" in model:
        return "flash_lite"
    return "flash"


class CostLedger:
    def __init__(self) -> None:
        self._phases: dict[str, Any] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        self._tokens_in: dict[str, int] = defaultdict(int)
        self._tokens_out: dict[str, int] = defaultdict(int)
        self._free_calls = 0
        self._billing_calls = 0
        self._quota_exhausted: list[dict] = []

    def record(
        self,
        phase: str,
        *,
        model: str,
        key: str,
        role: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        tier = _tier(model)
        self._phases[phase][tier][key] += 1
        self._tokens_in[phase] += tokens_in
        self._tokens_out[phase] += tokens_out
        if role == "billing":
            self._billing_calls += 1
        else:
            self._free_calls += 1

    def record_quota_exhausted(self, model: str, at_iso: str) -> None:
        self._quota_exhausted.append({"model": model, "at": at_iso})

    def to_dict(self) -> dict:
        return {
            **{phase: dict(inner) for phase, inner in self._phases.items()},
            "tokens_in_per_phase": dict(self._tokens_in),
            "tokens_out_per_phase": dict(self._tokens_out),
            "role_breakdown": {
                "free_tier_calls": self._free_calls,
                "billing_calls": self._billing_calls,
            },
            "quota_exhausted_events": self._quota_exhausted,
        }
