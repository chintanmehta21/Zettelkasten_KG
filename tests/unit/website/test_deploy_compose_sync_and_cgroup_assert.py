"""Iter-03 mem-bounded §2.10 (post-mortem): two regression guards against
the silent-no-op failure mode where compose ceiling changes never reach the
droplet.

(1) The deploy workflow MUST scp ops/docker-compose.{blue,green}.yml to
    /opt/zettelkasten/compose/ — without this, mem_limit/memswap_limit edits
    in the repo never propagate to the running cgroup.

(2) deploy.sh MUST assert the running container's cgroup memory.max +
    memory.swap.max match the expected values, and fail the deploy if not.
    This guards against compose drift, mount issues, or kernel-version
    issues silently producing the wrong cgroup config.

If either guard is removed, the next mem_limit edit could silently no-op
production again. Do not delete these guards without writing a replacement.
"""
from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-droplet.yml"
DEPLOY_SH = Path(__file__).resolve().parents[3] / "ops" / "deploy" / "deploy.sh"


def test_workflow_scps_compose_files_to_droplet():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Sync compose files to droplet" in text, (
        "Deploy workflow must include a 'Sync compose files to droplet' step "
        "so ops/docker-compose.{blue,green}.yml edits propagate. See spec §2.10."
    )
    assert "ops/docker-compose.blue.yml" in text and "ops/docker-compose.green.yml" in text, (
        "The compose-sync scp step must list both blue + green compose files."
    )
    assert "/opt/zettelkasten/compose/" in text, (
        "Compose files must land at /opt/zettelkasten/compose/ on the droplet."
    )


def test_workflow_sparse_checkout_includes_compose_files():
    """The sparse-checkout block must include the compose files, otherwise
    the scp source path won't exist in the runner's checkout."""
    text = WORKFLOW.read_text(encoding="utf-8")
    # Sparse checkout block lists files; both must be present
    assert "ops/docker-compose.blue.yml" in text
    assert "ops/docker-compose.green.yml" in text


def test_deploy_sh_asserts_cgroup_memory_max():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "EXPECTED_MEM_MAX=1363148800" in text, (
        "deploy.sh must hard-code expected memory.max=1363148800 (1300m)."
    )
    assert "EXPECTED_SWAP_MAX=1048576000" in text, (
        "deploy.sh must hard-code expected memory.swap.max=1048576000 (1000m)."
    )


def test_deploy_sh_fails_loudly_on_cgroup_mismatch():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    # Must fetch actuals from /sys/fs/cgroup
    assert "/sys/fs/cgroup/memory.max" in text
    assert "/sys/fs/cgroup/memory.swap.max" in text
    # Must compare against expected and exit non-zero on mismatch
    assert 'if [[ "$ACTUAL_MEM_MAX" != "$EXPECTED_MEM_MAX" ]]' in text or \
           'if [[ "$ACTUAL_MEM_MAX" != "$EXPECTED_MEM_MAX" ]] || [[ "$ACTUAL_SWAP_MAX" != "$EXPECTED_SWAP_MAX" ]]' in text
    # Must log [cgroup-assert] markers so log-greppers can track this
    assert "[cgroup-assert]" in text
    # Must trigger a rollback path on mismatch
    assert "rollback.sh" in text and "exit 87" in text


def test_deploy_sh_runs_assert_after_healthcheck_before_caddy_flip():
    """Order matters: healthcheck → cgroup-assert → caddy-flip. If we flip
    caddy first and THEN find a cgroup mismatch, traffic is already on the
    bad container."""
    text = DEPLOY_SH.read_text(encoding="utf-8")
    healthcheck_idx = text.index('"$ROOT/deploy/healthcheck.sh" "$IDLE_PORT"')
    assert_idx = text.index("[cgroup-assert]")
    flip_idx = text.index("Flipping Caddy upstream")
    assert healthcheck_idx < assert_idx < flip_idx, (
        "deploy.sh must run cgroup-assert AFTER healthcheck but BEFORE Caddy flip."
    )
