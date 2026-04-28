"""Iter-03 §8: deploy.sh must verify _STAGE2_SESSION loaded after healthcheck
and BEFORE Caddy flip, exit 88 on failure, fail-loud-no-rollback per the
hot-fixed cgroup-assert pattern.
"""
from __future__ import annotations

from pathlib import Path

DEPLOY_SH = Path(__file__).resolve().parents[3] / "ops" / "deploy" / "deploy.sh"


def test_deploy_sh_has_stage2_assert_block():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "[stage2-assert]" in text, (
        "deploy.sh must include a [stage2-assert] log marker block."
    )
    assert "_STAGE2_SESSION" in text, (
        "deploy.sh must probe _STAGE2_SESSION via docker exec python -c."
    )
    assert "exit 88" in text, (
        "deploy.sh stage2-assert must exit 88 on mismatch (unique rc for triage)."
    )


def test_deploy_sh_stage2_assert_does_not_call_rollback():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    start = text.index("[stage2-assert]")
    end_marker = text.find("[stage2-assert] ", start + 1)
    if end_marker == -1:
        end_marker = text.index("Flipping Caddy upstream", start)
    block = text[start:end_marker]
    assert "rollback.sh" not in block, (
        "stage2-assert must NOT auto-invoke rollback.sh — operator triages."
    )


def test_deploy_sh_stage2_assert_runs_after_cgroup_before_flip():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    cgroup_idx = text.index("[cgroup-assert] ${IDLE} cgroup limits OK")
    stage2_idx = text.index("[stage2-assert]")
    flip_idx = text.index("Flipping Caddy upstream")
    assert cgroup_idx < stage2_idx < flip_idx, (
        "deploy.sh order: healthcheck → cgroup-assert → stage2-assert → rag-smoke → flip."
    )
