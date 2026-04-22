"""Nitter instance pool with health caching.

Mirrors the Piped/Invidious pattern used for YouTube. Nitter instances churn —
caching health lets us skip known-bad instances for a TTL window instead of
re-probing every request.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable

import httpx


@dataclass
class _HealthEntry:
    healthy: bool
    checked_at: float
    reason: str = ""


@dataclass
class NitterPool:
    """Health-cached pool of Nitter instance base URLs.

    - `get_healthy_instances()` returns cached-healthy instances first,
      falling back to unchecked/expired ones.
    - `mark_failure(instance, reason)` records a negative health entry.
    - `mark_success(instance)` records a positive health entry.
    - Entries expire after `ttl_seconds`; expired entries get re-probed
      lazily (via `probe_if_stale`).
    """

    instances: tuple[str, ...]
    ttl_seconds: float = 300.0
    probe_timeout_sec: float = 5.0
    _cache: dict[str, _HealthEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.instances:
            raise ValueError("NitterPool requires at least one instance")
        seen: set[str] = set()
        deduped: list[str] = []
        for inst in self.instances:
            normalized = inst.rstrip("/")
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        self.instances = tuple(deduped)

    def _is_fresh(self, entry: _HealthEntry) -> bool:
        return (time.monotonic() - entry.checked_at) < self.ttl_seconds

    def get_healthy_instances(self) -> list[str]:
        """Return instances ordered: fresh-healthy > unknown/stale > fresh-unhealthy."""
        fresh_healthy: list[str] = []
        unknown_or_stale: list[str] = []
        fresh_unhealthy: list[str] = []
        for inst in self.instances:
            entry = self._cache.get(inst)
            if entry is None or not self._is_fresh(entry):
                unknown_or_stale.append(inst)
            elif entry.healthy:
                fresh_healthy.append(inst)
            else:
                fresh_unhealthy.append(inst)
        return fresh_healthy + unknown_or_stale + fresh_unhealthy

    def mark_success(self, instance: str) -> None:
        instance = instance.rstrip("/")
        self._cache[instance] = _HealthEntry(
            healthy=True, checked_at=time.monotonic()
        )

    def mark_failure(self, instance: str, reason: str = "") -> None:
        instance = instance.rstrip("/")
        self._cache[instance] = _HealthEntry(
            healthy=False, checked_at=time.monotonic(), reason=reason
        )

    def health_snapshot(self) -> dict[str, dict[str, object]]:
        """Inspection helper — returns {instance: {healthy, age_sec, reason}}."""
        now = time.monotonic()
        return {
            inst: {
                "healthy": entry.healthy,
                "age_sec": round(now - entry.checked_at, 1),
                "reason": entry.reason,
                "fresh": self._is_fresh(entry),
            }
            for inst, entry in self._cache.items()
        }

    async def probe(self, instance: str, *, client: httpx.AsyncClient | None = None) -> bool:
        """Best-effort HEAD probe. On any exception or non-2xx/3xx, mark unhealthy."""
        instance = instance.rstrip("/")
        owned_client = client is None
        if owned_client:
            client = httpx.AsyncClient(timeout=self.probe_timeout_sec, follow_redirects=True)
        try:
            resp = await client.get(instance + "/", timeout=self.probe_timeout_sec)
            if 200 <= resp.status_code < 400:
                self.mark_success(instance)
                return True
            self.mark_failure(instance, reason=f"status={resp.status_code}")
            return False
        except Exception as exc:  # noqa: BLE001 — any network error is an unhealthy signal
            self.mark_failure(instance, reason=f"{type(exc).__name__}: {exc}")
            return False
        finally:
            if owned_client and client is not None:
                await client.aclose()


def build_pool_from_config(
    config: dict, *, default_ttl: float = 300.0
) -> NitterPool | None:
    """Construct a NitterPool from a `sources.twitter` config dict.

    Returns None when `use_nitter_fallback` is false or no instances configured.
    """
    if not config.get("use_nitter_fallback", True):
        return None
    raw_instances: Iterable[str] = config.get("nitter_instances") or []
    instances = tuple(str(i) for i in raw_instances if i)
    if not instances:
        return None
    timeout = float(config.get("nitter_health_check_timeout_sec", 5.0))
    ttl = float(config.get("nitter_health_cache_ttl_sec", default_ttl))
    return NitterPool(
        instances=instances,
        ttl_seconds=ttl,
        probe_timeout_sec=timeout,
    )
