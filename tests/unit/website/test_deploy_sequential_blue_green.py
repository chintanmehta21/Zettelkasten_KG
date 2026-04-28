"""Iter-03 (2026-04-28): SEQUENTIAL blue/green - deploy.sh must stop ACTIVE
container BEFORE starting IDLE on this 2 GB droplet.

Concurrent blue+green ran the system into OOM during the smoke probe q1
query because each container holds ~280 MB resident + spikes +684 MB
during stage-2 BGE rerank. 2 containers x peak ~1.2 GB > 1.9 GB physical
RAM, even with the 1.6 GB cgroup ceiling per container. Stopping ACTIVE
first frees the RAM for IDLE's smoke probe.

Trade-off: ~30-60s of 502s while Caddy points at the now-stopped color
until the post-assert flip. Acceptable for single-droplet 2 GB target.

iter-04 can revisit this (larger droplet, smaller stage1_k, batched
rerank encoding, or moving stage2 to a separate worker process).
"""
from __future__ import annotations

from pathlib import Path

DEPLOY_SH = Path(__file__).resolve().parents[3] / "ops" / "deploy" / "deploy.sh"


def test_deploy_sh_stops_active_before_starting_idle():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    stop_idx = text.index("[seq-deploy] Stopping ACTIVE color")
    start_idx = text.index('Starting $IDLE container with new image')
    assert stop_idx < start_idx, (
        "deploy.sh must stop ACTIVE BEFORE starting IDLE (sequential blue/green). "
        "Concurrent containers OOM the 2 GB droplet during smoke probe."
    )


def test_deploy_sh_uses_docker_stop_with_grace_period():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    seq_block_start = text.index("[seq-deploy] Stopping ACTIVE color")
    seq_block_end = text.index('Starting $IDLE container with new image')
    block = text[seq_block_start:seq_block_end]
    assert "docker stop" in block, "must use docker stop for graceful shutdown"
    assert "--time" in block, "must specify graceful timeout (matches stop_grace_period in compose)"


def test_deploy_sh_does_not_call_retire_color_after_sequential_stop():
    """retire_color.sh drains an ALIVE container; if we already stopped
    ACTIVE pre-flight, calling it would error or no-op. Skip it explicitly."""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    # The legacy `nohup .../retire_color.sh` invocation must be gone or
    # commented out. The seq-deploy log marker confirms the intent.
    assert "nohup \"$ROOT/deploy/retire_color.sh\"" not in text, (
        "retire_color.sh must NOT be invoked after sequential pre-flight stop "
        "(ACTIVE is already stopped; retire_color.sh would race or error)."
    )
    assert "[seq-deploy] ACTIVE color ${ACTIVE} already stopped pre-flight" in text, (
        "deploy.sh must log a clear 'no retire needed' marker for audit."
    )


def test_deploy_sh_stop_runs_before_caddy_flip():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    stop_idx = text.index("[seq-deploy] Stopping ACTIVE color")
    flip_idx = text.index("Flipping Caddy upstream")
    assert stop_idx < flip_idx
