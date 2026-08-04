"""Regression tests for the 2026-08-02 worker-recycle zettel loss.

Incident: a gunicorn ``max_requests`` recycle cancelled an in-flight Add-Zettel
task 37.8 s in. The lifespan drained only infra tasks, so user work got no
grace; ``_run``'s ``CancelledError`` branch then finalized the row terminal
``cancelled`` with "The operation was cancelled by the client" — a message the
client had nothing to do with, which also hid the row from the stuck-running
reaper (it only reaps ``status='running'``) and fired no alert.

See docs/claude_audits/youtube_ingest_failure_2026-08-02.md.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from website.api import zettels_routes as zr

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Each case starts with the shutdown latch down and no live tasks."""
    zr._reset_shutdown_flag_for_tests()
    zr._LIVE_TASKS.clear()
    yield
    zr._reset_shutdown_flag_for_tests()
    zr._LIVE_TASKS.clear()


# --------------------------------------------------------------------------
# C1 — the config drift that made the recycle window 10x too tight
# --------------------------------------------------------------------------


def test_deploy_workflow_does_not_pin_max_requests():
    """deploy-droplet.yml must not re-pin GUNICORN_MAX_REQUESTS.

    Pinning 100/50 there silently overrode run.py's reasoned 1000/200 default
    (raised 2026-05-24 to stop exactly this class of mid-request recycle kill).
    run.py is the single source of truth.
    """
    workflow = (REPO_ROOT / ".github/workflows/deploy-droplet.yml").read_text(
        encoding="utf-8"
    )
    offenders = [
        line.strip()
        for line in workflow.splitlines()
        if "GUNICORN_MAX_REQUESTS" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, (
        "deploy-droplet.yml re-pins GUNICORN_MAX_REQUESTS, overriding run.py's "
        f"default and shrinking the recycle window: {offenders}"
    )


def test_drain_budget_fits_under_the_murder_clock():
    """The drain must finish before gunicorn's murder_workers SIGABRT.

    --graceful-timeout does NOT bound this path: on a max_requests recycle
    uvicorn self-exits with no signal, so graceful_timeout (an Arbiter.stop()
    concern) never applies. The binding limit is --timeout via murder_workers,
    and the heartbeat stops the moment shutdown begins — gunicorn heartbeats at
    timeout/2, so the worst-case remaining budget is timeout/2, not timeout.
    Overrunning earns SIGABRT, which UvicornWorker resets to SIG_DFL: instant
    death with no lifespan at all, i.e. worse than not draining.
    """
    gunicorn_timeout = 180.0  # run.py default; prod floor is also 180
    worst_case_budget = gunicorn_timeout / 2.0
    assert zr.LIVE_TASK_DRAIN_TIMEOUT_S < worst_case_budget, (
        f"drain budget {zr.LIVE_TASK_DRAIN_TIMEOUT_S}s exceeds the worst-case "
        f"{worst_case_budget}s before SIGABRT"
    )


def test_compose_stop_grace_exceeds_drain_budget():
    """Docker SIGKILLs at stop_grace_period, truncating the drain on deploys.

    A drain budget above this is silently a no-op for every blue/green cutover
    — the most frequent shutdown we do.
    """
    import re

    for color in ("blue", "green"):
        text = (REPO_ROOT / f"ops/docker-compose.{color}.yml").read_text(
            encoding="utf-8"
        )
        m = re.search(r"stop_grace_period:\s*(\d+)s", text)
        assert m, f"{color}: stop_grace_period not set — Docker defaults to 10s"
        assert int(m.group(1)) > zr.LIVE_TASK_DRAIN_TIMEOUT_S, (
            f"{color}: stop_grace_period {m.group(1)}s <= drain budget "
            f"{zr.LIVE_TASK_DRAIN_TIMEOUT_S}s; the drain is truncated on cutover"
        )


# --------------------------------------------------------------------------
# C2 — in-flight user work drains before the worker goes away
# --------------------------------------------------------------------------


async def test_drain_live_tasks_awaits_inflight_work():
    """A running op must be allowed to finish, not cancelled at shutdown."""
    finished: list[str] = []

    async def _slow_op():
        await asyncio.sleep(0.05)
        finished.append("persisted")

    task = asyncio.create_task(_slow_op())
    zr._LIVE_TASKS["op-1"] = task

    unfinished = await zr.drain_live_tasks(timeout=5.0)

    assert unfinished == 0
    assert task.done() and not task.cancelled()
    assert finished == ["persisted"], "in-flight work was not allowed to complete"


async def test_drain_live_tasks_reports_budget_overrun():
    """Work exceeding the budget is reported, not silently dropped."""

    async def _never_finishes():
        await asyncio.sleep(30)

    task = asyncio.create_task(_never_finishes())
    zr._LIVE_TASKS["op-2"] = task
    try:
        assert await zr.drain_live_tasks(timeout=0.05) == 1
        assert not task.done(), "drain must not cancel; loop teardown does that"
    finally:
        task.cancel()


async def test_drain_live_tasks_sets_shutdown_flag():
    """The latch is what lets _run tell a recycle from a client DELETE."""
    assert zr._SHUTTING_DOWN is False
    await zr.drain_live_tasks(timeout=0.01)
    assert zr._SHUTTING_DOWN is True


async def test_drain_live_tasks_noop_when_idle():
    assert await zr.drain_live_tasks(timeout=0.01) == 0


# --------------------------------------------------------------------------
# C3 — a recycle must not masquerade as a client cancel
# --------------------------------------------------------------------------


def test_worker_recycled_body_is_a_server_failure():
    body = zr._failed_response_for(
        asyncio.CancelledError(),
        operation_id="op-x",
        persist_requested=True,
        url="https://youtu.be/abc",
        worker_recycled=True,
    )
    err = body["error"]

    assert body["status"] == "failed"
    assert err["code"] == "worker_recycled"
    assert err["status"] == 503, "a server restart is not a 499 client cancel"
    assert err["retryable"] is True
    assert "client" not in err["detail"].lower()
    assert err["url"] == "https://youtu.be/abc", "URL must survive for forensics"


def test_client_cancel_body_is_unchanged():
    """Regression guard: the genuine DELETE path keeps its 499 contract."""
    body = zr._failed_response_for(
        asyncio.CancelledError(),
        operation_id="op-y",
        persist_requested=True,
        url="https://example.com",
    )
    err = body["error"]

    assert err["code"] == "operation_cancelled"
    assert err["status"] == 499
    assert err["detail"] == "The operation was cancelled by the client."
    assert "retryable" not in err


def test_non_cancel_exception_shape_unaffected():
    body = zr._failed_response_for(
        ValueError("boom"),
        operation_id="op-z",
        persist_requested=False,
        url=None,
    )
    assert body["status"] == "failed"
    assert body["error"]["code"] != "worker_recycled"


@pytest.mark.parametrize(
    ("shutting_down", "expected_target", "expected_code"),
    [
        (True, "failed", "worker_recycled"),
        (False, "cancelled", "operation_cancelled"),
    ],
)
async def test_run_finalize_target_follows_cancel_source(
    shutting_down, expected_target, expected_code
):
    """_run must route the finalize by *why* it was cancelled.

    'failed' keeps the incident visible as a server fault; 'cancelled' stays
    reserved for actual user intent.
    """
    calls: list[dict] = []

    async def _pipeline():
        raise asyncio.CancelledError()

    def _finalize(**kwargs):
        calls.append(kwargs)

    if shutting_down:
        zr._SHUTTING_DOWN = True

    with patch.object(zr.operations_repo, "start", lambda **_kw: None), patch.object(
        zr.operations_repo, "finalize", _finalize
    ), patch("website.features.web_monitor.maybe_fire_app_error", lambda **_kw: None):
        with pytest.raises(asyncio.CancelledError):
            await zr._run(
                user_id=zr.UUID(int=1),
                operation_id="op-run",
                pipeline=_pipeline,
                persist_requested=True,
                url="https://youtu.be/abc",
            )

    assert len(calls) == 1
    assert calls[0]["target"] == expected_target
    assert calls[0]["error"]["code"] == expected_code


# --------------------------------------------------------------------------
# C4 — the recycle path was silent; that is why this went unnoticed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shutting_down", "should_alert"), [(True, True), (False, False)]
)
async def test_alert_fires_only_for_recycle_not_client_cancel(
    shutting_down, should_alert
):
    fired: list[dict] = []

    async def _pipeline():
        raise asyncio.CancelledError()

    if shutting_down:
        zr._SHUTTING_DOWN = True

    with patch.object(zr.operations_repo, "start", lambda **_kw: None), patch.object(
        zr.operations_repo, "finalize", lambda **_kw: None
    ), patch(
        "website.features.web_monitor.maybe_fire_app_error",
        lambda **kw: fired.append(kw),
    ):
        with pytest.raises(asyncio.CancelledError):
            await zr._run(
                user_id=zr.UUID(int=2),
                operation_id="op-alert",
                pipeline=_pipeline,
                persist_requested=True,
                url=None,
            )

    assert bool(fired) is should_alert
    if should_alert:
        assert fired[0]["dedup_key"] == "add_zettel_worker_recycled"
        assert fired[0]["fields"]["stage"] == "shutdown_drain_timeout"


# --------------------------------------------------------------------------
# C5 — YouTube tier 3 must actually be able to impersonate
# --------------------------------------------------------------------------


def test_ytdlp_impersonate_chrome_is_available():
    """yt-dlp[default] omits curl-cffi, which silently killed all 5 clients."""
    from website.features.summarization_engine.source_ingest.youtube import tiers

    tiers.impersonate_target_available.cache_clear()
    assert tiers.impersonate_target_available("chrome"), (
        "curl-cffi impersonation backend missing — ops/requirements.in must "
        "pin yt-dlp[default,curl-cffi]"
    )


def test_requirements_pins_curl_cffi_extra():
    src = (REPO_ROOT / "ops/requirements.in").read_text(encoding="utf-8")
    assert "yt-dlp[default,curl-cffi]" in src
    lock = (REPO_ROOT / "ops/requirements.txt").read_text(encoding="utf-8")
    assert any(
        line.startswith("curl-cffi==") for line in lock.splitlines()
    ), "curl-cffi absent from the compiled lockfile — recompile with uv"


async def test_tier3_fails_once_when_impersonation_unavailable(tmp_path):
    """One clear error, not five identical per-client failures."""
    from website.features.summarization_engine.source_ingest.youtube import tiers

    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# netscape cookie file", encoding="utf-8")

    with patch.dict("os.environ", {"YT_COOKIES_PATH": str(cookies)}), patch.object(
        tiers, "impersonate_target_available", lambda *_a, **_kw: False
    ):
        result = await tiers.tier_ytdlp_cookies_impersonate("vid123", {})

    assert result.success is False
    assert "impersonate backend missing" in result.error
