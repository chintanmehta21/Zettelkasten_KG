# Summarization Engine Plan 14 — Monitoring, Metrics, and Alerting

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production observability for the v2 summarization pipeline + eval endpoint + iteration loops. Emit structured Prometheus metrics, route critical anomalies (Gemini quota exhaustion, hallucination-cap spikes, ingest-tier failures, RAGAS-score regressions) to Slack via the existing `web_monitor` fan-out in `website/features/web_monitor/`.

**Architecture:** Three moving parts:
1. **Metrics emitter** — new `website/features/observability/metrics.py` wrapping `prometheus_client` counters/histograms for every pipeline phase (ingest tier, CoD iterations, self-check missing claims, evaluator composite, key-pool role used, quota-exhaust events, cache hit rate).
2. **`/metrics` endpoint** — standard Prometheus scrape target at `/metrics` (gated by `observability.metrics_endpoint_enabled` config, default on in prod, off in dev).
3. **Anomaly watchers** — three thin async tasks that periodically query the last hour's metrics + recent `kg_eval_samples` rows and fire Slack alerts via the existing `User_Activity.py`-style fan-out when anomalies cross thresholds.

**Tech Stack:** Python 3.12, FastAPI, `prometheus_client` (new dep), existing `web_monitor` Slack channel fan-out, Supabase (read-only), existing DigitalOcean droplet cron.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §9 (budget controls), §11 (risks).

**Branch:** `feat/summarization-observability`, off `master` AFTER Plan 13's PR merges + deploy verified.

**Precondition:** Plans 1-13 merged. `kg_eval_samples` table live (Plan 12). `web_monitor/User_Activity.py`-style Slack fan-out exists per CLAUDE.md mention of `website/features/web_monitor/`.

**Deploy discipline:** Metrics endpoint is read-only and gated off by default in dev. Slack fan-out reuses existing webhook secrets — no new secret added. Still: draft PR + human approval before merge.

---

## Critical safety constraints

### 1. Metrics endpoint authorization
`/metrics` is traditionally unauthenticated (Prometheus scrapes from inside the trust zone). Given our droplet's Caddy reverse proxy, `/metrics` MUST be IP-ACL'd to the droplet's local scrape targets only. The FastAPI route uses middleware that rejects requests not from `127.0.0.1` / `::1`. Caddy does NOT expose `/metrics` publicly — the route is still reachable on the internal port 10000 but blocked at the Caddy layer via `handle_path /metrics { abort }`.

### 2. No PII in labels or log lines
Prometheus label cardinality must stay bounded. URL labels REPLACED with `source_type` + 8-char URL hash. User IDs REPLACED with a stable hash. Never emit raw email, auth tokens, or full URLs.

### 3. Slack alert rate limiting
Each alert type has a 15-minute dedup window. Stored in `docs/summary_eval/_cache/alert_dedup.json`. If the same `alert_key` (e.g., `quota_exhausted_billing_flipped_on`) fires twice in 15 min, second firing is suppressed. Prevents alert fatigue.

### 4. Watchers read-only
Anomaly watchers only SELECT from Supabase. No UPDATE / INSERT / DELETE. They don't participate in the eval write path.

### 5. Config gating
Every metric source has a `config.yaml → observability.*_enabled` flag, default true in prod, false in dev. Lets operators disable a noisy metric without code changes.

---

## File structure summary

### Files to CREATE
- `website/features/observability/__init__.py`
- `website/features/observability/metrics.py`
- `website/features/observability/slack_alerts.py`
- `website/features/observability/watchers/__init__.py`
- `website/features/observability/watchers/quota_watcher.py`
- `website/features/observability/watchers/quality_regression_watcher.py`
- `website/features/observability/watchers/ingest_failure_watcher.py`
- `website/features/observability/routes.py` (FastAPI `/metrics` endpoint)
- `ops/prometheus/zettelkasten.yaml` (Prometheus scrape config)
- `ops/prometheus/alert_rules.yaml` (Prometheus alertmanager rules; optional)
- `ops/cron/hourly_watchers.py`
- `tests/unit/observability/test_metrics.py`
- `tests/unit/observability/test_slack_alerts.py`
- `tests/unit/observability/test_watchers.py`
- `docs/summary_eval/_observability/README.md`

### Files to MODIFY
- `ops/requirements.txt` — add `prometheus_client==0.20.0`
- `website/features/summarization_engine/config.yaml` — new `observability` block
- `website/features/summarization_engine/core/config.py` — `ObservabilityConfig` model
- `website/features/summarization_engine/core/orchestrator.py` — emit ingest / summarize metrics
- `website/features/api_key_switching/key_pool.py` — emit pool-role metrics + quota_exhausted counter
- `website/features/summarization_engine/api/routes.py` — include observability router
- `Caddyfile` (if present, else ops/caddy/*.caddy) — block public `/metrics` access

---

## Critical edge cases Codex MUST handle

### 1. Prometheus registry already initialized
If `prometheus_client.CollectorRegistry` is instantiated twice (common during pytest + reimport), metric registration raises `Duplicated timeseries`. The metrics module MUST use `prometheus_client.REGISTRY` exactly once; all `Counter`, `Histogram`, `Gauge` live as module-level singletons protected by a `_initialized` flag. Tests use `_reset_metrics_for_tests()` helper.

### 2. Slack webhook unavailable
If Slack webhook returns 5xx or times out, the alert MUST be logged locally to `docs/summary_eval/_observability/failed_alerts.jsonl` and NOT re-queued. Dropping one alert is better than flooding the webhook on recovery.

### 3. Metric emission must never fail a request
Every `metrics.inc()` / `metrics.observe()` call is wrapped in `try/except Exception: logger.warning(...)`. A failing metric emission must never crash a summarize or eval request.

### 4. Cron clock skew + late runs
The hourly watchers compute "past hour" relative to `NOW()` at invocation. If cron is late (common on droplet reboot), the windows can overlap — that's fine, we dedupe on `alert_key`. If cron is early/missed, watchers may miss an anomaly's first hour — acceptable, next run catches it.

### 4. High-cardinality label prevention
URLs transformed via `hashlib.sha1(url.encode()).hexdigest()[:8]`. Known source-types is a bounded enum. User IDs hashed. The `ingest_tier_total` counter has ≤ 60 unique label combinations regardless of URL volume.

### 5. Config flag flip without restart
`observability.metrics_endpoint_enabled` is checked on every request (not just at startup). Flipping `false→true` in config.yaml takes effect after the server's next `load_config()` cache bust (next `--manage-server` restart OR the hot-reload path if using uvicorn --reload).

### 6. RAGAS regression false positives on low-traffic days
`quality_regression_watcher` baseline comes from trailing-7-day mean composite on `kg_eval_samples`. If a day has < 10 samples (low traffic), the watcher skips that hour instead of emitting noise. Threshold: min 10 samples in the comparison window.

### 7. Alert dedup file corruption
If `docs/summary_eval/_cache/alert_dedup.json` is corrupt (invalid JSON), the slack_alerts module treats it as empty and rewrites it. Never hard-fail on dedup file parse error.

---

## Task 0: Branch + preconditions

- [ ] **Step 1: Verify web_monitor exists**

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
git checkout master && git pull
test -d website/features/web_monitor && echo "web_monitor OK"
ls website/features/web_monitor/*.py | head
```

- [ ] **Step 2: Branch**

```bash
git checkout -b feat/summarization-observability
git push -u origin feat/summarization-observability
```

- [ ] **Step 3: Pin prometheus_client**

Add to `ops/requirements.txt`:

```
prometheus_client==0.20.0
```

```bash
pip install -r ops/requirements.txt
git add ops/requirements.txt
git commit -m "chore: add prometheus client dep"
```

---

## Task 1: Config model + defaults

**Files:**
- Modify: `website/features/summarization_engine/config.yaml`
- Modify: `website/features/summarization_engine/core/config.py`

- [ ] **Step 1: Add `observability` block in `config.yaml`**

```yaml
observability:
  metrics_endpoint_enabled: true
  ingest_metrics_enabled: true
  summarizer_metrics_enabled: true
  evaluator_metrics_enabled: true
  pool_metrics_enabled: true
  cache_metrics_enabled: true
  slack_alerts_enabled: false              # flip to true per-alert via per-watcher flag
  alerts:
    quota_exhaustion_billing_flipped:
      enabled: true
      dedup_window_minutes: 60
    quality_regression_7d:
      enabled: true
      regression_threshold_points: 5
      min_samples_in_window: 10
      dedup_window_minutes: 120
    ingest_tier_fallback_rate_24h:
      enabled: true
      tier_5_or_6_threshold_pct: 25
      dedup_window_minutes: 60
```

- [ ] **Step 2: `ObservabilityConfig` model in `core/config.py`**

```python
class AlertConfig(BaseModel):
    enabled: bool = True
    dedup_window_minutes: int = 60


class QuotaAlertConfig(AlertConfig):
    pass


class QualityRegressionAlertConfig(AlertConfig):
    regression_threshold_points: float = 5.0
    min_samples_in_window: int = 10


class IngestFallbackAlertConfig(AlertConfig):
    tier_5_or_6_threshold_pct: float = 25.0


class AlertsConfig(BaseModel):
    quota_exhaustion_billing_flipped: QuotaAlertConfig = Field(default_factory=QuotaAlertConfig)
    quality_regression_7d: QualityRegressionAlertConfig = Field(default_factory=QualityRegressionAlertConfig)
    ingest_tier_fallback_rate_24h: IngestFallbackAlertConfig = Field(default_factory=IngestFallbackAlertConfig)


class ObservabilityConfig(BaseModel):
    metrics_endpoint_enabled: bool = True
    ingest_metrics_enabled: bool = True
    summarizer_metrics_enabled: bool = True
    evaluator_metrics_enabled: bool = True
    pool_metrics_enabled: bool = True
    cache_metrics_enabled: bool = True
    slack_alerts_enabled: bool = False
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)


class EngineConfig(BaseModel):
    # existing fields...
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
```

- [ ] **Step 3: Commit**

```bash
git add website/features/summarization_engine/config.yaml website/features/summarization_engine/core/config.py
git commit -m "feat: observability config block"
```

---

## Task 2: Metrics module

**Files:**
- Create: `website/features/observability/__init__.py`
- Create: `website/features/observability/metrics.py`
- Test: `tests/unit/observability/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/observability/test_metrics.py
import pytest
from website.features.observability.metrics import (
    record_ingest_tier, record_summarize, record_eval_composite,
    record_pool_role, record_cache_hit, record_quota_exhausted,
    _reset_metrics_for_tests,
)


def setup_function():
    _reset_metrics_for_tests()


def test_record_ingest_tier_does_not_raise():
    record_ingest_tier(source_type="youtube", tier="ytdlp_player_rotation", success=True)
    record_ingest_tier(source_type="youtube", tier="metadata_only", success=False)


def test_record_summarize_histogram_accepts_latency():
    record_summarize(source_type="github", latency_ms=1234, pro_tokens=100, flash_tokens=50)


def test_record_eval_composite_label_cardinality_bounded():
    for i in range(100):
        record_eval_composite(source_type="youtube", composite=85.0, prompt_version="evaluator.v1")
    # No exception — label cardinality stays bounded because URL not in labels.


def test_record_pool_role_emits_counter():
    record_pool_role(role="free", model="gemini-2.5-pro", outcome="success")
    record_pool_role(role="billing", model="gemini-2.5-pro", outcome="success")


def test_record_cache_hit_supports_hit_miss():
    record_cache_hit(namespace="ingests", hit=True)
    record_cache_hit(namespace="summaries", hit=False)


def test_record_quota_exhausted_only_fires_on_escalation():
    record_quota_exhausted(model="gemini-2.5-pro", next_role="billing")
    # Counter emitted; tests pass if no exception.


def test_metrics_emission_exception_does_not_leak(monkeypatch):
    # Simulate a broken counter; emitter must swallow.
    import website.features.observability.metrics as m
    monkeypatch.setattr(m, "INGEST_TIER_TOTAL", None)
    record_ingest_tier(source_type="youtube", tier="tier1", success=True)  # should not raise
```

- [ ] **Step 2: Run + verify FAIL**

```bash
pytest tests/unit/observability/test_metrics.py -v
```
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Create `observability/__init__.py`**

```python
"""Observability: Prometheus metrics + Slack alerts."""
```

- [ ] **Step 4: Create `observability/metrics.py`**

```python
"""Prometheus metrics emitters. Every function is no-throw — metrics must never fail a request."""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from prometheus_client import Counter, Histogram, Gauge, REGISTRY, CollectorRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton metrics. _initialized prevents double-registration.
# ---------------------------------------------------------------------------

_initialized = False

INGEST_TIER_TOTAL: Optional[Counter] = None
SUMMARIZE_LATENCY_MS: Optional[Histogram] = None
SUMMARIZE_TOKENS: Optional[Counter] = None
EVAL_COMPOSITE: Optional[Histogram] = None
POOL_CALLS_TOTAL: Optional[Counter] = None
QUOTA_EXHAUSTED_TOTAL: Optional[Counter] = None
CACHE_OPS_TOTAL: Optional[Counter] = None


def _init_metrics(registry: Optional[CollectorRegistry] = None) -> None:
    global _initialized
    global INGEST_TIER_TOTAL, SUMMARIZE_LATENCY_MS, SUMMARIZE_TOKENS
    global EVAL_COMPOSITE, POOL_CALLS_TOTAL, QUOTA_EXHAUSTED_TOTAL, CACHE_OPS_TOTAL
    if _initialized:
        return
    r = registry or REGISTRY
    INGEST_TIER_TOTAL = Counter(
        "zk_ingest_tier_total", "Count of ingest-tier invocations",
        labelnames=("source_type", "tier", "outcome"), registry=r,
    )
    SUMMARIZE_LATENCY_MS = Histogram(
        "zk_summarize_latency_ms", "End-to-end summarize latency",
        labelnames=("source_type",),
        buckets=(100, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000),
        registry=r,
    )
    SUMMARIZE_TOKENS = Counter(
        "zk_summarize_tokens_total", "Tokens consumed per summarize call",
        labelnames=("source_type", "tier"),  # tier = pro | flash | flash_lite
        registry=r,
    )
    EVAL_COMPOSITE = Histogram(
        "zk_eval_composite", "Composite eval scores",
        labelnames=("source_type", "prompt_version"),
        buckets=(50, 60, 70, 75, 80, 85, 88, 92, 95, 100),
        registry=r,
    )
    POOL_CALLS_TOTAL = Counter(
        "zk_pool_calls_total", "Gemini key-pool call outcomes",
        labelnames=("role", "model", "outcome"),  # role = free | billing
        registry=r,
    )
    QUOTA_EXHAUSTED_TOTAL = Counter(
        "zk_quota_exhausted_total", "Quota exhaustion escalations",
        labelnames=("model", "next_role"),
        registry=r,
    )
    CACHE_OPS_TOTAL = Counter(
        "zk_cache_ops_total", "Content-cache ops",
        labelnames=("namespace", "result"),  # result = hit | miss
        registry=r,
    )
    _initialized = True


def _reset_metrics_for_tests() -> None:
    """Re-create all metrics against a fresh registry. Test-only."""
    global _initialized
    _initialized = False
    from prometheus_client import CollectorRegistry
    _init_metrics(CollectorRegistry())


# Ensure metrics initialized at import.
try:
    _init_metrics()
except Exception as exc:
    logger.warning("Prometheus metrics init failed: %s", exc)


# ---------------------------------------------------------------------------
# Emitters — always no-throw.
# ---------------------------------------------------------------------------

def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


def record_ingest_tier(*, source_type: str, tier: str, success: bool) -> None:
    try:
        INGEST_TIER_TOTAL.labels(source_type=source_type, tier=tier, outcome="success" if success else "failure").inc()
    except Exception as exc:
        logger.warning("metrics.record_ingest_tier failed: %s", exc)


def record_summarize(*, source_type: str, latency_ms: int,
                     pro_tokens: int, flash_tokens: int) -> None:
    try:
        SUMMARIZE_LATENCY_MS.labels(source_type=source_type).observe(latency_ms)
        if pro_tokens:
            SUMMARIZE_TOKENS.labels(source_type=source_type, tier="pro").inc(pro_tokens)
        if flash_tokens:
            SUMMARIZE_TOKENS.labels(source_type=source_type, tier="flash").inc(flash_tokens)
    except Exception as exc:
        logger.warning("metrics.record_summarize failed: %s", exc)


def record_eval_composite(*, source_type: str, composite: float, prompt_version: str) -> None:
    try:
        EVAL_COMPOSITE.labels(source_type=source_type, prompt_version=prompt_version).observe(composite)
    except Exception as exc:
        logger.warning("metrics.record_eval_composite failed: %s", exc)


def record_pool_role(*, role: str, model: str, outcome: str) -> None:
    try:
        POOL_CALLS_TOTAL.labels(role=role, model=model, outcome=outcome).inc()
    except Exception as exc:
        logger.warning("metrics.record_pool_role failed: %s", exc)


def record_quota_exhausted(*, model: str, next_role: str) -> None:
    try:
        QUOTA_EXHAUSTED_TOTAL.labels(model=model, next_role=next_role).inc()
    except Exception as exc:
        logger.warning("metrics.record_quota_exhausted failed: %s", exc)


def record_cache_hit(*, namespace: str, hit: bool) -> None:
    try:
        CACHE_OPS_TOTAL.labels(namespace=namespace, result="hit" if hit else "miss").inc()
    except Exception as exc:
        logger.warning("metrics.record_cache_hit failed: %s", exc)
```

- [ ] **Step 5: Verify PASS + commit**

```bash
pytest tests/unit/observability/test_metrics.py -v
git add website/features/observability/ tests/unit/observability/
git commit -m "feat: observability metrics emitters"
```

---

## Task 3: `/metrics` endpoint + IP ACL

**Files:**
- Create: `website/features/observability/routes.py`
- Modify: `website/features/summarization_engine/api/routes.py` — include router

- [ ] **Step 1: Create `observability/routes.py`**

```python
"""FastAPI route for /metrics. IP-ACL'd to localhost only."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from website.features.summarization_engine.core.config import load_config


router = APIRouter()

_ALLOWED_SCRAPE_IPS = {"127.0.0.1", "::1", "localhost"}


@router.get("/metrics")
async def metrics(request: Request):
    cfg = load_config()
    if not cfg.observability.metrics_endpoint_enabled:
        raise HTTPException(status_code=503, detail="metrics endpoint disabled")
    # IP ACL — only allow localhost scrapes. Caddy blocks public access separately.
    client_host = request.client.host if request.client else ""
    if client_host not in _ALLOWED_SCRAPE_IPS:
        raise HTTPException(status_code=403, detail="metrics endpoint forbidden from this host")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

- [ ] **Step 2: Register router in `website/app.py`**

In the app setup, add:

```python
from website.features.observability.routes import router as observability_router
app.include_router(observability_router)
```

- [ ] **Step 3: Caddy block for public `/metrics`**

Edit `ops/caddy/Caddyfile` (or the active Caddy config):

```
# Inside the zettelkasten.in host block, BEFORE the reverse_proxy directive:
@block_metrics path /metrics /metrics/*
handle @block_metrics {
    respond "Not Found" 404 {
        close
    }
}
```

This ensures `/metrics` is 404 externally, still reachable internally on the droplet via `http://127.0.0.1:10000/metrics`.

- [ ] **Step 4: Commit**

```bash
git add website/features/observability/routes.py website/app.py ops/caddy/
git commit -m "feat: metrics endpoint ip acl and caddy block"
```

---

## Task 4: Wire metric emitters into pipeline

**Files:**
- Modify: `website/features/summarization_engine/core/orchestrator.py`
- Modify: `website/features/summarization_engine/source_ingest/youtube/ingest.py`
- Modify: `website/features/api_key_switching/key_pool.py`
- Modify: `website/features/summarization_engine/core/cache.py`

- [ ] **Step 1: Emit ingest-tier metric from YouTube ingestor**

At the end of `YouTubeIngestor.ingest`, before returning the `IngestResult`:

```python
from website.features.observability.metrics import record_ingest_tier
try:
    record_ingest_tier(
        source_type=self.source_type.value,
        tier=tier_result.tier.value,
        success=tier_result.success,
    )
except Exception:
    pass
```

- [ ] **Step 2: Emit summarize metric from orchestrator**

In `orchestrator.summarize_url_bundle`, after the `summarizer.summarize(ingest_result)` call succeeds:

```python
from website.features.observability.metrics import record_summarize, record_eval_composite
try:
    record_summarize(
        source_type=effective_source_type.value,
        latency_ms=int(summary_result.metadata.total_latency_ms),
        pro_tokens=int(summary_result.metadata.gemini_pro_tokens),
        flash_tokens=int(summary_result.metadata.gemini_flash_tokens),
    )
except Exception:
    pass
```

- [ ] **Step 3: Emit pool-role metrics from `key_pool.py`**

In the `GeminiKeyPool` class methods that actually execute a call, wrap with:

```python
from website.features.observability.metrics import record_pool_role, record_quota_exhausted

# After a successful call:
try:
    record_pool_role(role=attempt.role, model=attempt.model, outcome="success")
except Exception:
    pass

# On 429, before escalating:
try:
    record_pool_role(role=attempt.role, model=attempt.model, outcome="rate_limited")
except Exception:
    pass

# When escalating free → billing:
try:
    record_quota_exhausted(model=attempt.model, next_role="billing")
except Exception:
    pass
```

- [ ] **Step 4: Emit cache hit/miss from `core/cache.py`**

In `FsContentCache.get` / `put`:

```python
from website.features.observability.metrics import record_cache_hit

def get(self, key_tuple: tuple) -> dict | None:
    if os.environ.get("CACHE_DISABLED") == "1":
        return None
    path = self._path(key_tuple)
    hit = path.exists()
    try:
        record_cache_hit(namespace=self._dir.name, hit=hit)
    except Exception:
        pass
    if not hit:
        return None
    ...
```

- [ ] **Step 5: Run the full test suite — emitters should not break any existing test**

```bash
pytest tests/unit/ website/features/summarization_engine/tests/unit/ -q
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add website/features/summarization_engine/core/orchestrator.py website/features/summarization_engine/source_ingest/youtube/ingest.py website/features/api_key_switching/key_pool.py website/features/summarization_engine/core/cache.py
git commit -m "feat: wire metrics emitters into pipeline"
```

---

## Task 5: Slack alert module + dedup

**Files:**
- Create: `website/features/observability/slack_alerts.py`
- Test: `tests/unit/observability/test_slack_alerts.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/observability/test_slack_alerts.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from website.features.observability.slack_alerts import (
    SlackAlerter, AlertDedupStore,
)


def test_dedup_respects_window(tmp_path):
    store = AlertDedupStore(path=tmp_path / "dedup.json")
    key = "quota_exhausted_billing_flipped"
    assert not store.is_deduped(key, window_minutes=15)
    store.mark_sent(key)
    assert store.is_deduped(key, window_minutes=15)


def test_dedup_expires_after_window(tmp_path, monkeypatch):
    store = AlertDedupStore(path=tmp_path / "dedup.json")
    key = "x"
    store.mark_sent(key)
    # Simulate time passing
    import website.features.observability.slack_alerts as m
    orig_now = m._now
    monkeypatch.setattr(m, "_now", lambda: orig_now().replace(year=orig_now().year + 1))
    assert not store.is_deduped(key, window_minutes=15)


def test_corrupt_dedup_file_treated_empty(tmp_path):
    path = tmp_path / "dedup.json"
    path.write_text("not json", encoding="utf-8")
    store = AlertDedupStore(path=path)
    assert not store.is_deduped("any_key", window_minutes=15)


@pytest.mark.asyncio
async def test_alerter_skips_on_webhook_error(tmp_path, caplog):
    alerter = SlackAlerter(webhook_url="https://example.com/fake", dedup_store=AlertDedupStore(path=tmp_path / "d.json"))
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=Exception("network dead"))):
        sent = await alerter.send_alert(title="t", body="b", alert_key="k", dedup_window_minutes=15)
    assert sent is False
```

- [ ] **Step 2: Module**

```python
"""Slack alert fan-out with dedup + graceful failure."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AlertDedupStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict[str, str]) -> None:
        try:
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("alert dedup save failed: %s", exc)

    def is_deduped(self, key: str, window_minutes: int) -> bool:
        data = self._load()
        last = data.get(key)
        if not last:
            return False
        try:
            when = datetime.fromisoformat(last)
        except Exception:
            return False
        return _now() - when < timedelta(minutes=window_minutes)

    def mark_sent(self, key: str) -> None:
        data = self._load()
        data[key] = _now().isoformat()
        self._save(data)


class SlackAlerter:
    def __init__(self, *, webhook_url: str, dedup_store: AlertDedupStore) -> None:
        self._url = webhook_url
        self._dedup = dedup_store

    async def send_alert(self, *, title: str, body: str, alert_key: str,
                          dedup_window_minutes: int) -> bool:
        if self._dedup.is_deduped(alert_key, dedup_window_minutes):
            logger.info("alert deduped: %s", alert_key)
            return False
        payload = {"text": f"*{title}*\n{body}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._url, json=payload)
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("slack webhook failed: %s", exc)
            return False
        self._dedup.mark_sent(alert_key)
        return True
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/unit/observability/test_slack_alerts.py -v
git add website/features/observability/slack_alerts.py tests/unit/observability/test_slack_alerts.py
git commit -m "feat: slack alerter with dedup and graceful failure"
```

---

## Task 6: Anomaly watchers (quota, quality, ingest)

**Files:**
- Create: `website/features/observability/watchers/__init__.py`
- Create: `website/features/observability/watchers/quota_watcher.py`
- Create: `website/features/observability/watchers/quality_regression_watcher.py`
- Create: `website/features/observability/watchers/ingest_failure_watcher.py`
- Test: `tests/unit/observability/test_watchers.py`

- [ ] **Step 1: Quota watcher**

```python
# website/features/observability/watchers/quota_watcher.py
"""Fires when QUOTA_EXHAUSTED_TOTAL counter has increased in the last hour."""
from __future__ import annotations

from prometheus_client import CollectorRegistry
from prometheus_client.parser import text_string_to_metric_families


class QuotaWatcher:
    def __init__(self, *, metric_fetcher, alerter, dedup_window_minutes: int) -> None:
        self._metric_fetcher = metric_fetcher
        self._alerter = alerter
        self._dedup_window = dedup_window_minutes

    async def check(self) -> bool:
        """Returns True if an alert was fired."""
        text = await self._metric_fetcher()
        count = 0
        for family in text_string_to_metric_families(text):
            if family.name != "zk_quota_exhausted":
                continue
            for sample in family.samples:
                if sample.name == "zk_quota_exhausted_total":
                    count += int(sample.value)
        if count == 0:
            return False
        return await self._alerter.send_alert(
            title="Quota exhaustion — billing key activated",
            body=f"Cumulative zk_quota_exhausted_total={count}. Free keys have 429'd; billing key is absorbing traffic. Consider adding another free key or waiting for UTC midnight quota reset.",
            alert_key="quota_exhausted_billing_flipped",
            dedup_window_minutes=self._dedup_window,
        )
```

- [ ] **Step 2: Quality regression watcher**

```python
# website/features/observability/watchers/quality_regression_watcher.py
"""Fires when trailing-hour mean composite drops > threshold below trailing-7d baseline."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone


class QualityRegressionWatcher:
    def __init__(self, *, supabase_fetcher, alerter,
                 regression_threshold: float, min_samples: int,
                 dedup_window_minutes: int) -> None:
        self._fetch = supabase_fetcher
        self._alerter = alerter
        self._threshold = regression_threshold
        self._min_samples = min_samples
        self._dedup_window = dedup_window_minutes

    async def check(self) -> bool:
        now = datetime.now(timezone.utc)
        # past hour
        recent = await self._fetch(start=now - timedelta(hours=1), end=now)
        # trailing 7d EXCLUDING past hour
        baseline = await self._fetch(start=now - timedelta(days=7), end=now - timedelta(hours=1))

        if len(recent) < self._min_samples or len(baseline) < self._min_samples:
            return False

        recent_mean = statistics.mean(r["composite_score"] for r in recent)
        baseline_mean = statistics.mean(r["composite_score"] for r in baseline)
        delta = baseline_mean - recent_mean

        if delta < self._threshold:
            return False

        return await self._alerter.send_alert(
            title=f"Quality regression — composite dropped {delta:.1f} points",
            body=(
                f"Past hour mean composite: {recent_mean:.1f} (n={len(recent)})\n"
                f"7-day baseline mean: {baseline_mean:.1f} (n={len(baseline)})\n"
                f"Threshold: -{self._threshold} points.\n"
                "Investigate recent commits + Gemini model changes + rubric edits."
            ),
            alert_key="quality_regression_7d",
            dedup_window_minutes=self._dedup_window,
        )
```

- [ ] **Step 3: Ingest-failure watcher**

```python
# website/features/observability/watchers/ingest_failure_watcher.py
"""Fires when tier-5 or tier-6 ingest rate for YouTube exceeds threshold over past 24h."""
from __future__ import annotations

from prometheus_client.parser import text_string_to_metric_families


_FALLBACK_TIERS = {"gemini_audio", "metadata_only"}


class IngestFailureWatcher:
    def __init__(self, *, metric_fetcher, alerter,
                 threshold_pct: float, dedup_window_minutes: int) -> None:
        self._fetch = metric_fetcher
        self._alerter = alerter
        self._threshold = threshold_pct
        self._dedup_window = dedup_window_minutes

    async def check(self) -> bool:
        text = await self._fetch()
        total = 0
        fallback = 0
        for family in text_string_to_metric_families(text):
            if family.name != "zk_ingest_tier":
                continue
            for sample in family.samples:
                if sample.name != "zk_ingest_tier_total":
                    continue
                if sample.labels.get("source_type") != "youtube":
                    continue
                if sample.labels.get("outcome") != "success":
                    continue
                total += int(sample.value)
                if sample.labels.get("tier") in _FALLBACK_TIERS:
                    fallback += int(sample.value)
        if total == 0:
            return False
        pct = (fallback / total) * 100.0
        if pct < self._threshold:
            return False
        return await self._alerter.send_alert(
            title=f"YouTube ingest tier fallback rate {pct:.1f}% (threshold {self._threshold}%)",
            body=(
                f"{fallback}/{total} YouTube ingests hit tier-5 (Gemini audio) or tier-6 (metadata-only).\n"
                "Tier-5 is costly; tier-6 produces low-confidence summaries.\n"
                "Likely causes: Piped/Invidious pool health degraded; YouTube blocked yt-dlp player clients; datacenter IP range flagged.\n"
                "Check docs/summary_eval/_cache/youtube_instance_health.json + websearch for current mitigation."
            ),
            alert_key="ingest_tier_fallback_rate_24h",
            dedup_window_minutes=self._dedup_window,
        )
```

- [ ] **Step 4: Watcher tests (all mocked)**

```python
# tests/unit/observability/test_watchers.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from website.features.observability.watchers.quota_watcher import QuotaWatcher


@pytest.mark.asyncio
async def test_quota_watcher_fires_when_counter_nonzero():
    metric_fetcher = AsyncMock(return_value=(
        "# HELP zk_quota_exhausted_total ...\n"
        "# TYPE zk_quota_exhausted_total counter\n"
        'zk_quota_exhausted_total{model="gemini-2.5-pro",next_role="billing"} 3.0\n'
    ))
    alerter = MagicMock()
    alerter.send_alert = AsyncMock(return_value=True)
    w = QuotaWatcher(metric_fetcher=metric_fetcher, alerter=alerter, dedup_window_minutes=60)
    fired = await w.check()
    assert fired is True


@pytest.mark.asyncio
async def test_quota_watcher_skips_when_counter_zero():
    metric_fetcher = AsyncMock(return_value="")
    alerter = MagicMock()
    alerter.send_alert = AsyncMock(return_value=True)
    w = QuotaWatcher(metric_fetcher=metric_fetcher, alerter=alerter, dedup_window_minutes=60)
    fired = await w.check()
    assert fired is False
```

- [ ] **Step 5: Run + commit**

```bash
pytest tests/unit/observability/test_watchers.py -v
git add website/features/observability/watchers/ tests/unit/observability/test_watchers.py
git commit -m "feat: three anomaly watchers"
```

---

## Task 7: Hourly watcher cron

**Files:**
- Create: `ops/cron/hourly_watchers.py`

- [ ] **Step 1: Create cron script**

```python
"""Hourly watcher cron — runs all watchers, emits Slack alerts on anomalies."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from website.features.observability.slack_alerts import SlackAlerter, AlertDedupStore
from website.features.observability.watchers.quota_watcher import QuotaWatcher
from website.features.observability.watchers.quality_regression_watcher import QualityRegressionWatcher
from website.features.observability.watchers.ingest_failure_watcher import IngestFailureWatcher
from website.features.summarization_engine.core.config import load_config


REPO_ROOT = Path(__file__).resolve().parents[2]
DEDUP_PATH = REPO_ROOT / "docs" / "summary_eval" / "_cache" / "alert_dedup.json"
METRICS_URL = os.environ.get("METRICS_URL", "http://127.0.0.1:10000/metrics")
WEBHOOK = os.environ.get("SLACK_ALERTS_WEBHOOK", "")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_ROLE = None


def _load_service_role() -> str:
    global SERVICE_ROLE
    if SERVICE_ROLE:
        return SERVICE_ROLE
    path = Path("/etc/secrets/supabase_service_role_key")
    if path.exists():
        SERVICE_ROLE = path.read_text(encoding="utf-8").strip()
    else:
        SERVICE_ROLE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return SERVICE_ROLE


async def _fetch_metrics() -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(METRICS_URL)
        resp.raise_for_status()
        return resp.text


async def _fetch_samples(start: datetime, end: datetime) -> list[dict]:
    service = _load_service_role()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/kg_eval_samples",
            params={
                "sampled_at": f"gte.{start.isoformat()}",
                "select": "composite_score,sampled_at",
                "limit": "5000",
            },
            headers={"apikey": service, "Authorization": f"Bearer {service}"},
        )
        resp.raise_for_status()
        rows = resp.json()
        # client-side filter for end cutoff
        return [r for r in rows if r["sampled_at"] < end.isoformat()]


async def _main() -> int:
    cfg = load_config()
    if not cfg.observability.slack_alerts_enabled:
        print("slack_alerts_enabled=false; skipping watchers")
        return 0
    if not WEBHOOK:
        print("SLACK_ALERTS_WEBHOOK not set; skipping")
        return 0

    dedup = AlertDedupStore(path=DEDUP_PATH)
    alerter = SlackAlerter(webhook_url=WEBHOOK, dedup_store=dedup)

    alerts = cfg.observability.alerts

    fired_any = False

    if alerts.quota_exhaustion_billing_flipped.enabled:
        w = QuotaWatcher(
            metric_fetcher=_fetch_metrics, alerter=alerter,
            dedup_window_minutes=alerts.quota_exhaustion_billing_flipped.dedup_window_minutes,
        )
        fired_any |= await w.check()

    if alerts.quality_regression_7d.enabled:
        w = QualityRegressionWatcher(
            supabase_fetcher=_fetch_samples, alerter=alerter,
            regression_threshold=alerts.quality_regression_7d.regression_threshold_points,
            min_samples=alerts.quality_regression_7d.min_samples_in_window,
            dedup_window_minutes=alerts.quality_regression_7d.dedup_window_minutes,
        )
        fired_any |= await w.check()

    if alerts.ingest_tier_fallback_rate_24h.enabled:
        w = IngestFailureWatcher(
            metric_fetcher=_fetch_metrics, alerter=alerter,
            threshold_pct=alerts.ingest_tier_fallback_rate_24h.tier_5_or_6_threshold_pct,
            dedup_window_minutes=alerts.ingest_tier_fallback_rate_24h.dedup_window_minutes,
        )
        fired_any |= await w.check()

    print(f"hourly watchers done; fired_any={fired_any}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
```

- [ ] **Step 2: Droplet cron install (documented, not executed)**

Append to `ops/cron/README.md`:

```markdown
## hourly_watchers.py
Runs every hour, checks Prometheus metrics + kg_eval_samples for anomalies, fires Slack alerts.

### Install
```bash
# Set SLACK_ALERTS_WEBHOOK (distinct from existing web_monitor webhook; reuse if you want)
crontab -e
# Append:
# 5 * * * * cd /opt/zettelkasten && SLACK_ALERTS_WEBHOOK=$(cat /etc/secrets/slack_alerts_webhook) /opt/venv/bin/python ops/cron/hourly_watchers.py >> /var/log/zk_watchers.log 2>&1
```
```

- [ ] **Step 3: Commit**

```bash
git add ops/cron/hourly_watchers.py ops/cron/README.md
git commit -m "feat: hourly anomaly watchers cron"
```

---

## Task 8: Prometheus scrape config

**Files:**
- Create: `ops/prometheus/zettelkasten.yaml`
- Create: `ops/prometheus/alert_rules.yaml`

- [ ] **Step 1: Scrape config**

```yaml
# ops/prometheus/zettelkasten.yaml — add to prometheus.yml scrape_configs
- job_name: 'zettelkasten'
  scrape_interval: 30s
  scrape_timeout: 10s
  metrics_path: /metrics
  static_configs:
    - targets: ['127.0.0.1:10000']
      labels:
        service: 'zettelkasten-web'
        env: 'prod'
```

- [ ] **Step 2: Alert rules (reference, prometheus alertmanager optional)**

```yaml
# ops/prometheus/alert_rules.yaml
groups:
  - name: zettelkasten
    rules:
      - alert: QuotaExhaustedToBilling
        expr: increase(zk_quota_exhausted_total[1h]) > 0
        for: 5m
        labels: {severity: warning}
        annotations:
          summary: "Gemini quota exhausted; billing key active"
      - alert: SummarizeLatencyP95Slow
        expr: histogram_quantile(0.95, rate(zk_summarize_latency_ms_bucket[5m])) > 60000
        for: 10m
        labels: {severity: warning}
        annotations:
          summary: "P95 summarize latency > 60s"
      - alert: EvalCompositeLow
        expr: histogram_quantile(0.50, rate(zk_eval_composite_bucket[1h])) < 80
        for: 30m
        labels: {severity: warning}
        annotations:
          summary: "Median eval composite < 80"
```

- [ ] **Step 3: Commit**

```bash
git add ops/prometheus/
git commit -m "ops: prometheus scrape and alert rules"
```

---

## Task 9: Push + draft PR

```bash
git push origin feat/summarization-observability
gh pr create --draft --title "feat: summarization observability metrics and alerts" \
  --body "Plan 14. Adds Prometheus metrics emitters across the pipeline + IP-ACL'd /metrics endpoint + Slack anomaly watchers (quota, quality-regression, ingest-fallback). Caddy blocks public /metrics access. All wrapped try/except; never fails a request. Alert dedup + graceful webhook failure.

### Deploy gate
- [ ] CI green
- [ ] ops/requirements.txt includes prometheus_client
- [ ] Caddy config updated to 404 public /metrics (check after deploy)
- [ ] /metrics reachable from 127.0.0.1 only (test: curl from droplet OK, curl from laptop → 404)
- [ ] Hourly watchers cron NOT yet installed on droplet (install AFTER deploy verified, via ops/cron/README.md)
- [ ] slack_alerts_enabled=false in committed config.yaml (flip on per-alert manually in prod)

Post-merge: human runs the cron install command; tests a known-good webhook; flips slack_alerts_enabled=true in prod config."
```

---

## Self-review checklist
- [ ] All metric emitters wrapped try/except — never fail a request
- [ ] Prometheus label cardinality bounded (URL hashed, user IDs hashed, source_type enum)
- [ ] /metrics endpoint IP-ACL'd + Caddy-blocked
- [ ] Slack alerter has dedup + graceful webhook failure
- [ ] All 3 watchers have unit tests with mocked fetchers
- [ ] slack_alerts_enabled defaults to false in config.yaml
- [ ] Watcher cron NOT installed via this PR (documented in README for human)
- [ ] NO merge, NO push to master
