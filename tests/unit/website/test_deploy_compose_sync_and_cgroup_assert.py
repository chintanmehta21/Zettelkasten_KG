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
    assert "EXPECTED_MEM_MAX=1677721600" in text, (
        "deploy.sh must hard-code expected memory.max=1677721600 (1600m). "
        "Bumped from 1300m on 2026-04-28 after q1 OOM-killed workers; stage-2 "
        "BGE rerank temp tensors push peak RSS to ~1.19 GB (profiled 16:49 UTC)."
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
    # Must exit non-zero with the unique rc 87 so callers can distinguish
    # cgroup-mismatch failure from generic deploy failure
    assert "exit 87" in text


def test_deploy_sh_restores_service_on_cgroup_mismatch():
    """SUPERSEDES ``test_deploy_sh_does_NOT_auto_rollback_on_cgroup_mismatch``.

    That guard (2026-04-28) required the cgroup assert to exit WITHOUT
    restoring service. It gave two reasons, and by 2026-08-01 both had ceased
    to hold — the original author anticipated this and wrote the precondition
    into the docstring: "DO NOT re-add rollback.sh invocation here without
    first fixing rollback.sh to preserve the iter-03 transport block".

    Reason (a) — "the assert fires BEFORE the Caddy flip so the failed
    container isn't serving traffic; there's nothing live to roll back from."
    FALSIFIED by the sequential-deploy rewrite. deploy.sh now stops AND
    ``docker rm``s the previously-active container before starting the idle
    one (the 2 GB droplet cannot hold both). By the time this assert runs, the
    thing that was serving is gone, so a bare exit leaves Caddy pointed at a
    dead upstream — raw 502s until a human intervenes. That is precisely the
    shape of the 2026-07-31 outage (~10h dark).

    Reason (b) — "rollback.sh rewrites upstream.snippet WITHOUT the iter-03
    transport block, silently regressing Strong-mode RAG to 30s timeouts."
    FIXED on 2026-08-01: rollback.sh now swaps only the colour token in place,
    preserving the transport block (and the inode, which the Caddy single-file
    bind mount tracks). See test_deploy_sh_faildark_guards.py.

    Failing loudly is preserved — the deploy still exits 87 and still logs
    FATAL. What changed is that it no longer fails *dark*.
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    cgroup_block_start = text.index("EXPECTED_MEM_MAX=")
    cgroup_block_end = text.index('log "[cgroup-assert] ${IDLE} cgroup limits OK"')
    cgroup_block = text[cgroup_block_start:cgroup_block_end]

    assert 'restore_previous_color "cgroup-assert"' in cgroup_block, (
        "cgroup-assert runs after the serving container was removed, so it "
        "must restore the previous colour before exiting."
    )
    # Still fails loudly — restoring service must not become silent success.
    assert "exit 87" in cgroup_block
    assert "FATAL" in cgroup_block
    # The precondition from the original guard: rollback must preserve the
    # protected Caddy transport block rather than flattening the snippet.
    rollback = (DEPLOY_SH.parent / "rollback.sh").read_text(encoding="utf-8")
    assert "transport http" in rollback, (
        "rollback.sh must guard the protected transport block before deploy.sh "
        "is allowed to call it automatically."
    )


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
