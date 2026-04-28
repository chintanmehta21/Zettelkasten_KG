"""Iter-03 mem-bounded §2.4: RAG_FP32_VERIFY=off must be in the deploy
workflow's STATIC_BODY so apply_migrations + the running container both see
the env disabled. Re-enabling fp32 is a documented LAST-RESORT operation —
the steady-state default is OFF.
"""
from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-droplet.yml"


def test_static_body_contains_rag_fp32_verify_off():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"RAG_FP32_VERIFY=off"' in text, (
        "STATIC_BODY in deploy-droplet.yml must include RAG_FP32_VERIFY=off "
        "between REDDIT_OPTIONAL=1 and DEPLOY_GIT_SHA. See spec §2.4."
    )


def test_static_body_position_is_after_reddit_optional_before_deploy_git_sha():
    text = WORKFLOW.read_text(encoding="utf-8")
    fp32_idx = text.index('"RAG_FP32_VERIFY=off"')
    reddit_idx = text.index('"REDDIT_OPTIONAL=1"')
    deploy_sha_idx = text.index('"DEPLOY_GIT_SHA=${DEPLOY_GIT_SHA}"')
    assert reddit_idx < fp32_idx < deploy_sha_idx, (
        "RAG_FP32_VERIFY=off must sit between REDDIT_OPTIONAL=1 and "
        "DEPLOY_GIT_SHA=... so the STATIC_BODY block stays grouped."
    )
