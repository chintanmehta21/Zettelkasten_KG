"""Alerting on cgroup v2 ``memory.events oom_kill`` (step 1).

Under cgroup v2 the kernel OOM-kills a process *inside* the cgroup, not
necessarily PID 1. A gunicorn worker dies, the arbiter respawns it, the
container stays up with ``restarts=0``, and Docker's ``State.OOMKilled`` never
surfaces it. Two such kills happened on the production droplet before the
2026-08-02 incident and nothing fired.

PSI and mem_ratio are leading indicators; ``oom_kill`` is the confirmed-damage
counter, so it alerts on every increment with no hysteresis.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from website.features.web_monitor import DO_Alerts


@pytest.fixture
def sampler():
    return DO_Alerts.MemorySampler(interval_seconds=0.01)


def _fire_capture():
    fired: list[dict] = []
    return fired, patch.object(
        DO_Alerts, "maybe_fire_do_alert", lambda **kw: fired.append(kw)
    )


def test_first_sample_only_baselines(sampler):
    """A container with historical kills must not page us at boot."""
    fired, patcher = _fire_capture()
    with patcher:
        sampler._evaluate_oom_kill(7)
    assert fired == []
    assert sampler.state.oom_kill_last == 7


def test_increment_fires_critical(sampler):
    fired, patcher = _fire_capture()
    with patcher:
        sampler._evaluate_oom_kill(2)   # baseline
        sampler._evaluate_oom_kill(3)   # a kill happened

    assert len(fired) == 1
    assert fired[0]["dedup_key"] == "cgroup_oom_kill"
    assert fired[0]["severity"] == "critical"
    assert fired[0]["fields"]["oom_kill_delta"] == "1"
    assert fired[0]["fields"]["oom_kill_total"] == "3"


def test_steady_counter_is_silent(sampler):
    """Historical kills must not re-alert on every 15s sample."""
    fired, patcher = _fire_capture()
    with patcher:
        for _ in range(5):
            sampler._evaluate_oom_kill(2)
    assert fired == []


def test_counter_reset_rebaselines_without_alerting(sampler):
    """Container restart recreates the cgroup and zeroes the counter."""
    fired, patcher = _fire_capture()
    with patcher:
        sampler._evaluate_oom_kill(9)
        sampler._evaluate_oom_kill(0)   # cgroup recreated
    assert fired == [], "a counter reset is not a kill"
    assert sampler.state.oom_kill_last == 0

    # ...and a genuine kill after the reset still fires.
    with patcher:
        sampler._evaluate_oom_kill(1)
    assert len(fired) == 1


def test_unreadable_events_file_is_silent(sampler):
    """Local dev / non-cgroup hosts must not generate false alarms."""
    fired, patcher = _fire_capture()
    with patcher:
        sampler._evaluate_oom_kill(None)
    assert fired == []


def test_multi_kill_burst_reports_true_delta(sampler):
    fired, patcher = _fire_capture()
    with patcher:
        sampler._evaluate_oom_kill(0)
        sampler._evaluate_oom_kill(3)   # 3 kills between samples
    assert fired[0]["fields"]["oom_kill_delta"] == "3"
    assert sampler.state.oom_kill_total_seen == 3


# --- the parser -----------------------------------------------------------


def test_parser_reads_oom_kill_not_oom_group_kill(tmp_path):
    """'oom_kill' and 'oom_group_kill' both prefix-match 'oom' — exact key only."""
    events = tmp_path / "memory.events"
    events.write_text(
        "low 0\nhigh 0\nmax 1150\noom 2\noom_kill 2\noom_group_kill 0\n",
        encoding="utf-8",
    )
    with patch.object(DO_Alerts, "_CGROUP_MEM_EVENTS", events):
        assert DO_Alerts._read_cgroup_oom_kill() == 2


def test_parser_returns_none_when_absent(tmp_path):
    events = tmp_path / "memory.events"
    events.write_text("low 0\nhigh 0\nmax 0\n", encoding="utf-8")
    with patch.object(DO_Alerts, "_CGROUP_MEM_EVENTS", events):
        assert DO_Alerts._read_cgroup_oom_kill() is None


def test_parser_returns_none_when_missing_file(tmp_path):
    with patch.object(DO_Alerts, "_CGROUP_MEM_EVENTS", tmp_path / "nope"):
        assert DO_Alerts._read_cgroup_oom_kill() is None


def test_sample_once_exposes_oom_kill(sampler, tmp_path):
    events = tmp_path / "memory.events"
    events.write_text("oom_kill 4\n", encoding="utf-8")
    _fired, patcher = _fire_capture()
    with patch.object(DO_Alerts, "_CGROUP_MEM_EVENTS", events), patcher:
        snap = sampler.sample_once()
    assert snap["oom_kill_total"] == 4
    assert snap["state"]["oom_kill_last"] == 4
