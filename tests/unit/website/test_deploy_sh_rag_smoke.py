"""Iter-03 §8: deploy.sh must fire one canonical RAG probe (the iter-03 q1
zk-org/zk two-fact gold) against the new color, expect 200 + correct
primary citation, exit 89 on failure. Fail-loud, no auto-rollback.
"""
from __future__ import annotations

from pathlib import Path

DEPLOY_SH = Path(__file__).resolve().parents[3] / "ops" / "deploy" / "deploy.sh"


def test_deploy_sh_has_rag_smoke_block():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "[rag-smoke]" in text
    assert "/api/rag/adhoc" in text
    assert "exit 89" in text
    assert "gh-zk-org-zk" in text, (
        "rag-smoke must assert the q1 gold primary_citation == 'gh-zk-org-zk'."
    )


def test_deploy_sh_rag_smoke_does_not_call_rollback():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    start = text.index("[rag-smoke]")
    end_marker = text.index("Flipping Caddy upstream", start)
    block = text[start:end_marker]
    assert "rollback.sh" not in block


def test_deploy_sh_rag_smoke_runs_after_stage2_before_flip():
    text = DEPLOY_SH.read_text(encoding="utf-8")
    stage2_idx = text.index("[stage2-assert] ${IDLE} stage2 session OK")
    smoke_idx = text.index("[rag-smoke]")
    flip_idx = text.index("Flipping Caddy upstream")
    assert stage2_idx < smoke_idx < flip_idx
