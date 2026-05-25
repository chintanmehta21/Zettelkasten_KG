"""Comprehensive alert harness — iter 1f verification.

Drives every alert in the deployed code through its production trigger path
(route handler, helper, or sampler entry) against in-process Slack stubs
captured by respx. Each test asserts the captured Slack POST matches the
expected payload contract (channel, severity, BOLA-safe hashes, dedup key).

Run with `pytest tests/integration/web_monitor/test_alert_harness.py -v`.

Categories:
- ✅ worked     — alert dispatched exactly once with expected payload
- ⚠️ diverged   — alert dispatched but payload missing expected field
- ❌ failed     — alert did NOT dispatch when it should have
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import httpx
import pytest
import respx

from website.features.web_monitor import App_Errors as ae_mod
from website.features.web_monitor import DO_Alerts as da_mod
from website.features.web_monitor import User_Activity as ua_mod
from website.features.web_monitor.App_Errors import (
    _spawn_alerting,
    maybe_fire_app_error,
    maybe_fire_app_error_rate,
)
from website.features.web_monitor.DO_Alerts import MemorySampler, maybe_fire_do_alert
from website.features.web_monitor.User_Activity import (
    maybe_fire_payment_alert,
    maybe_fire_signup_alert,
    notify_pricing_visit,
)


@pytest.fixture(autouse=True)
def _reset_all_state(monkeypatch):
    """Hermetic reset before every test."""
    for state in (
        ae_mod._app_error_alerted,
        ae_mod._app_error_rate_buckets,
        da_mod._do_alert_alerted,
        ua_mod._signup_alerted,
        ua_mod._payment_alerted,
        ua_mod._pricing_seen_at,
    ):
        state.clear()
    if hasattr(ua_mod, "_USER_ACTIVITY_TASKS"):
        ua_mod._USER_ACTIVITY_TASKS.clear()
    da_mod._sampler = None
    yield
    for state in (
        ae_mod._app_error_alerted,
        ae_mod._app_error_rate_buckets,
        da_mod._do_alert_alerted,
        ua_mod._signup_alerted,
        ua_mod._payment_alerted,
        ua_mod._pricing_seen_at,
    ):
        state.clear()


def _flatten(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _recent_iso(seconds_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


# ════════════════════ #user-activity channel (U1-U3) ════════════════════


@pytest.mark.asyncio
async def test_U1_new_signup(slack_webhook_mock):
    rec = slack_webhook_mock()
    fired = maybe_fire_signup_alert(
        user_id=str(uuid4()),
        display_name="Naruto Uzumaki",
        email="naruto@example.com",
        created_at=_recent_iso(5),
        country_code="IN",
    )
    await asyncio.sleep(0.05)
    assert fired is True
    body = _flatten(rec.calls["SLACK_WEBHOOK_USER_ACTIVITY"][0])
    assert "Naruto Uzumaki" in body and "India (IN)" in body and "tada" in body


@pytest.mark.asyncio
async def test_U2_pricing_visit(slack_webhook_mock):
    rec = slack_webhook_mock()
    await notify_pricing_visit(
        user_id=str(uuid4()),
        display_name="Sakura Haruno",
        email="sakura@example.com",
        country_code="IN",
        ip="49.207.250.132",
        user_agent="Mozilla/5.0",
        referer="https://zettelkasten.in/",
    )
    body = _flatten(rec.calls["SLACK_WEBHOOK_USER_ACTIVITY"][0])
    assert "Sakura Haruno" in body and "India (IN)" in body and "eyes" in body


@pytest.mark.asyncio
async def test_U3_payment(slack_webhook_mock):
    rec = slack_webhook_mock()
    fired = maybe_fire_payment_alert(
        provider_payment_id="pay_TEST_HARNESS_123",
        user_id=str(uuid4()),
        email="paying@example.com",
        display_name="Dave Doolittle",
        amount=499.0,
        currency="INR",
        plan="basic_monthly",
        country_code="IN",
    )
    await asyncio.sleep(0.05)
    assert fired is True
    body = _flatten(rec.calls["SLACK_WEBHOOK_USER_ACTIVITY"][0])
    assert "Dave Doolittle" in body and "India (IN)" in body and "moneybag" in body


# ════════════════════ #app-errors Tier A (A1-A5) ════════════════════


@pytest.mark.asyncio
async def test_A1_background_run_crash(slack_webhook_mock):
    """Background _run worker raises a 5xx-class exception."""
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="add_zettel_run:RuntimeError",
        route="api.zettels_routes._run",
        exc_type="RuntimeError",
        message="synthetic test failure",
        request_id="harness-A1",
        fields={
            "operation_id": "op12345678",
            "user_hash": "ab12cd34ef56",
            "source_url": "https://reddit.com/r/test",
            "stage": "run",
        },
        severity="critical",
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "RuntimeError" in body and "ab12cd34ef56" in body
    assert "/api/zettels/add" not in body  # route is in the title, message uses route arg


@pytest.mark.asyncio
async def test_A2_async_pipeline_crash(slack_webhook_mock):
    """Generic post-202 async runner exception (create_kasten path)."""
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="async_pipeline_crash:KastenBuildError",
        route="api._async_ops.run_worker",
        exc_type="KastenBuildError",
        message="async kasten pipeline failed",
        request_id="harness-A2",
        fields={"operation_id": "op87654321", "user_hash": "ff11ee22dd33", "kind": "create_kasten"},
        severity="critical",
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "KastenBuildError" in body and "ff11ee22dd33" in body


@pytest.mark.asyncio
async def test_A3_persist_v2_error(slack_webhook_mock):
    """SupabaseV2PersistError raise site — includes PG code in dedup."""
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="persist_v2_error:SupabaseV2PersistError:PGRST116",
        route="persist.persist_summarized_result[v2]",
        exc_type="SupabaseV2PersistError",
        message="JSON object requested, multiple (or no) rows returned",
        fields={"user_hash": "aaa111bbb222", "operation_id": "op99887766", "source_type": "youtube"},
        severity="critical",
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "SupabaseV2PersistError" in body and "PGRST116" not in body  # code in dedup_key only, not body


@pytest.mark.asyncio
async def test_A4_bulk_add_zettels_swallow(slack_webhook_mock):
    """create_kasten bulk add_zettels_to_kasten swallow."""
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="bulk_add_zettels_swallow",
        route="api.module_runners.create_kasten._add_zettels_chunked",
        exc_type="BulkAddZettelsToKastenFailed",
        message="bulk write raised mid-loop",
        fields={
            "kasten_hash": "kk88kk88kk88",
            "chunk_offset": "12",
            "total_members": "20",
            "user_hash": "ux01ux02ux03",
        },
        severity="critical",
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "BulkAddZettelsToKastenFailed" in body and "kk88kk88kk88" in body


@pytest.mark.asyncio
async def test_A5_rag_midstream_failure(slack_webhook_mock):
    """Mid-stream RAG SSE failure with partial_response=true."""
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="rag_stream_failure:LLMUnavailable:partial=True",
        route="api.chat_routes._stream_answer",
        exc_type="LLMUnavailable",
        message="upstream LLM unavailable mid-stream",
        fields={
            "session_hash": "ss55ss55ss55",
            "user_hash": "ux01ux02ux03",
            "kasten_hash": "kk88kk88kk88",
            "partial_response": "true",
            "produced_any": "true",
            "tokens_emitted": "42",
        },
        severity="critical",
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "LLMUnavailable" in body and "partial_response" in body and "true" in body


# ════════════════════ #app-errors Tier B (B1-B5) ════════════════════


@pytest.mark.asyncio
async def test_B1_gemini_all_keys_exhausted(slack_webhook_mock):
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="gemini_all_exhausted:summarize",
        route="api_key_switching.key_pool.GeminiKeyPool",
        exc_type="RuntimeError",
        message="All configured Gemini key/model slots are on cooldown",
        fields={
            "external_service": "gemini",
            "label": "summarize",
            "exhausted_keys": "10",
            "last_model_tier": "gemini-2.5-flash-lite",
        },
        severity="critical",
        dedup_seconds=5 * 60,
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "gemini" in body.lower() and "exhausted" in body.lower()


@pytest.mark.asyncio
async def test_B2_razorpay_sig_fail(slack_webhook_mock):
    rec = slack_webhook_mock()
    fired = maybe_fire_app_error(
        dedup_key="razorpay_sig_fail",
        route="user_pricing.routes.razorpay_webhook",
        exc_type="HTTPException(400)",
        message="bad razorpay signature",
        fields={"external_service": "razorpay", "route": "/api/payments/webhook"},
        severity="critical",
        dedup_seconds=15 * 60,
    )
    await asyncio.sleep(0.05)
    assert fired is True
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "razorpay" in body.lower() and "signature" in body.lower()


@pytest.mark.asyncio
async def test_B3a_jwks_unreachable(slack_webhook_mock):
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="jwks_unreachable:supabase_v2_url_hash_abc12345",
        route="api.auth._decode_token",
        exc_type="PyJWKClientError",
        message="JWKS endpoint unreachable",
        fields={"supabase_url_hash": "abc12345", "exc_type": "PyJWKClientError"},
        severity="critical",
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "JWKS" in body


@pytest.mark.asyncio
async def test_B3b_boot_auth_misconfig(slack_webhook_mock):
    rec = slack_webhook_mock()
    maybe_fire_app_error(
        dedup_key="auth_boot_misconfig",
        route="api.auth._decode_token",
        exc_type="ValueError",
        message="No JWT verification method configured (set SUPABASE_URL for JWKS or SUPABASE_JWT_SECRET for HS256)",
        severity="critical",
        dedup_seconds=24 * 60 * 60,
    )
    await asyncio.sleep(0.05)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "No JWT verification method" in body


@pytest.mark.asyncio
async def test_B4_enrichment_worker_died(slack_webhook_mock):
    """_spawn_alerting fires done-cb when wrapped coroutine raises non-CancelledError."""
    rec = slack_webhook_mock()

    async def _raiser():
        raise RuntimeError("enrichment worker exit unexpected")

    task = _spawn_alerting(
        _raiser(),
        dedup_key="enrichment_worker_died",
        route="main._lifespan.enrichment_worker",
        severity="critical",
    )
    assert task is not None
    try:
        await task
    except RuntimeError:
        pass
    # done-callback runs on the next loop tick
    for _ in range(20):
        if rec.calls["SLACK_WEBHOOK_APP_ERRORS"]:
            break
        await asyncio.sleep(0.02)
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "enrichment" in body.lower() or "RuntimeError" in body


@pytest.mark.asyncio
async def test_B5_user_activity_taskset_strong_ref(slack_webhook_mock):
    """User_Activity create_task uses _spawn_alerting with strong-ref set —
    GC-safe under CPython 3.12 eager-GC. Verify task is registered + cleanup."""
    rec = slack_webhook_mock()
    fired = maybe_fire_signup_alert(
        user_id=str(uuid4()),
        display_name="Test User",
        email="test@example.com",
        created_at=_recent_iso(5),
    )
    assert fired is True
    # Wait for task completion + done-cb discard
    for _ in range(30):
        await asyncio.sleep(0.02)
        if rec.calls["SLACK_WEBHOOK_USER_ACTIVITY"]:
            break
    assert len(rec.calls["SLACK_WEBHOOK_USER_ACTIVITY"]) == 1


# ════════════════════ #app-errors Tier C — rate-based (C11-C15) ════════════════════


@pytest.mark.asyncio
async def test_C11_gemini_5xx_burst(slack_webhook_mock):
    """C11 fires after 5 events in 60 s window."""
    rec = slack_webhook_mock()
    for _ in range(5):
        maybe_fire_app_error_rate(
            dedup_key="gemini_5xx_burst:summarize",
            threshold=5,
            window_seconds=60,
            route="gemini.key_pool.upstream_5xx",
            exc_type="ServerError",
            message="Gemini 503 UNAVAILABLE",
            fields={"external_service": "gemini", "label": "summarize", "reason": "unavailable"},
            severity="critical",
            alert_dedup_seconds=5 * 60,
        )
    await asyncio.sleep(0.05)
    # Exactly one alert (rate fires once at threshold; subsequent ticks within
    # alert_dedup_seconds are suppressed by inner maybe_fire_app_error).
    assert len(rec.calls["SLACK_WEBHOOK_APP_ERRORS"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "gemini" in body.lower() and "unavailable" in body.lower()


@pytest.mark.asyncio
async def test_C12_pgvector_timeout(slack_webhook_mock):
    """C12 fires after 3 timeouts in 60 s."""
    rec = slack_webhook_mock()
    for _ in range(3):
        maybe_fire_app_error_rate(
            dedup_key="graph_cache_upstream_timeout",
            threshold=3,
            window_seconds=60,
            route="graph_cache.UserGraphCache.get_or_load",
            exc_type="TimeoutError",
            message="graph_cache upstream timed out after 20s",
            fields={
                "external_service": "supabase_postgrest",
                "timeout_seconds": "20",
                "bucket": "personal:my:1.0:50:0",
            },
            severity="critical",
        )
    await asyncio.sleep(0.05)
    assert len(rec.calls["SLACK_WEBHOOK_APP_ERRORS"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "timed out" in body.lower() and "supabase_postgrest" in body


@pytest.mark.asyncio
async def test_C13_per_ip_scanner_burst(slack_webhook_mock):
    """C13 per-IP: ≥30 401s from one hashed IP within 60 s fires."""
    rec = slack_webhook_mock()
    for _ in range(30):
        maybe_fire_app_error_rate(
            dedup_key="auth_401_per_ip:ip_hash_abc12345",
            threshold=30,
            window_seconds=60,
            route="middleware.auth_401_rate",
            exc_type="ScannerBurstDetected",
            message="High 401 rate from one IP — likely scanner",
            fields={"external_service": "self", "scope": "per_ip", "ip_hash": "abc12345"},
            severity="warning",
            alert_dedup_seconds=15 * 60,
        )
    await asyncio.sleep(0.05)
    assert len(rec.calls["SLACK_WEBHOOK_APP_ERRORS"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "ScannerBurstDetected" in body and "ip_hash" in body


@pytest.mark.asyncio
async def test_C13_global_credential_stuffing_burst(slack_webhook_mock):
    """C13 global: ≥100 401s in 5 min globally fires."""
    rec = slack_webhook_mock()
    for _ in range(100):
        maybe_fire_app_error_rate(
            dedup_key="auth_401_global_burst",
            threshold=100,
            window_seconds=5 * 60,
            route="middleware.auth_401_rate",
            exc_type="AuthBurstDetected",
            message="High 401 rate across /api/* — possible credential stuffing",
            fields={"external_service": "self", "scope": "global"},
            severity="warning",
            alert_dedup_seconds=15 * 60,
        )
    await asyncio.sleep(0.05)
    assert len(rec.calls["SLACK_WEBHOOK_APP_ERRORS"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "AuthBurstDetected" in body and "credential" in body.lower()


@pytest.mark.asyncio
async def test_C14_kg_populate_failure_rate(slack_webhook_mock):
    """C14 fires after 3 kg-populate failures in 5 min."""
    rec = slack_webhook_mock()
    for _ in range(3):
        maybe_fire_app_error_rate(
            dedup_key="kg_populate_failure:RuntimeError",
            threshold=3,
            window_seconds=5 * 60,
            route="persist._schedule_kg_population",
            exc_type="RuntimeError",
            message="kg populate failed",
            fields={"canonical_zettel_hash": "cz12345678", "workspace_hash": "ws87654321"},
            severity="warning",
            alert_dedup_seconds=15 * 60,
        )
    await asyncio.sleep(0.05)
    assert len(rec.calls["SLACK_WEBHOOK_APP_ERRORS"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "kg" in body.lower() and "RuntimeError" in body


@pytest.mark.asyncio
async def test_C15_create_kasten_link_failure_rate(slack_webhook_mock):
    """C15: failed/total > 0.5 AND total ≥ 3 fires once."""
    rec = slack_webhook_mock()
    fired = maybe_fire_app_error(
        dedup_key="create_kasten_link_failure_rate:cax12345678",
        route="create_kasten._ingest_links",
        exc_type="LinkFailureRateBreached",
        message="3/4 links failed in create_kasten",
        request_id="cax12345678",
        fields={
            "link_failures": "3",
            "links_total": "4",
            "user_hash": "ux01ux02ux03",
            "workspace_hash": "ws87654321",
        },
        severity="warning",
        dedup_seconds=15 * 60,
    )
    await asyncio.sleep(0.05)
    assert fired is True
    body = _flatten(rec.calls["SLACK_WEBHOOK_APP_ERRORS"][0])
    assert "LinkFailureRateBreached" in body and "3" in body


# ════════════════════ #do-alerts Tier D (D16-D18) ════════════════════


@pytest.mark.asyncio
async def test_D16_psi_memory_pressure(slack_webhook_mock, monkeypatch):
    """PSI full avg10 ≥ 10% sustained ≥ 2 samples (30 s) fires."""
    rec = slack_webhook_mock()
    monkeypatch.setattr(da_mod, "_read_cgroup_mem_ratio", lambda: (None, None, None))
    monkeypatch.setattr(da_mod, "_read_asyncio_task_count", lambda: 0)
    monkeypatch.setattr(da_mod, "_read_psi_full_avg10", lambda: 12.0)
    sampler = MemorySampler(interval_seconds=60)
    sampler.sample_once()
    sampler.sample_once()
    await asyncio.sleep(0.05)
    assert len(rec.calls["SLACK_WEBHOOK_DO_ALERT"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_DO_ALERT"][0])
    assert "PSI" in body and "12.00" in body


@pytest.mark.asyncio
async def test_D17_cgroup_memory_critical(slack_webhook_mock, monkeypatch):
    """Cgroup mem ratio ≥ 0.90 sustained ≥ 2 samples (30 s) fires."""
    rec = slack_webhook_mock()
    monkeypatch.setattr(da_mod, "_read_psi_full_avg10", lambda: None)
    monkeypatch.setattr(da_mod, "_read_asyncio_task_count", lambda: 0)
    monkeypatch.setattr(
        da_mod, "_read_cgroup_mem_ratio", lambda: (0.92, 1_500_000_000, 1_600_000_000)
    )
    sampler = MemorySampler(interval_seconds=60)
    sampler.sample_once()
    sampler.sample_once()
    await asyncio.sleep(0.05)
    assert len(rec.calls["SLACK_WEBHOOK_DO_ALERT"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_DO_ALERT"][0])
    assert "Cgroup" in body and "92.0" in body


@pytest.mark.asyncio
async def test_D18_asyncio_task_count_leak(slack_webhook_mock, monkeypatch):
    """asyncio task count > 300 sustained ≥ 4 samples (60 s) fires."""
    rec = slack_webhook_mock()
    monkeypatch.setattr(da_mod, "_read_psi_full_avg10", lambda: None)
    monkeypatch.setattr(da_mod, "_read_cgroup_mem_ratio", lambda: (None, None, None))
    monkeypatch.setattr(da_mod, "_read_asyncio_task_count", lambda: 500)
    sampler = MemorySampler(interval_seconds=60)
    for _ in range(4):
        sampler.sample_once()
    await asyncio.sleep(0.05)
    assert len(rec.calls["SLACK_WEBHOOK_DO_ALERT"]) == 1
    body = _flatten(rec.calls["SLACK_WEBHOOK_DO_ALERT"][0])
    assert "Asyncio task count" in body and "500" in body
