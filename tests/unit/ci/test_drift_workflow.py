"""Iter-03 §9: weekly drift workflow must:
- run on cron 0 2 * * 0 (Sun 02:00 UTC)
- run check_corpus_drift.py against Supabase
- if drift: run refresh_calibration_and_int8.py + open PR
- be gated to a single environment with Supabase secrets
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "check_calibration_drift.yml"


def test_workflow_exists():
    assert WORKFLOW.exists()


def test_workflow_has_weekly_cron():
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    schedule = (payload.get(True) or payload.get("on") or {}).get("schedule") or []
    crons = [s.get("cron") for s in schedule]
    assert "0 2 * * 0" in crons, "must run weekly on Sun 02:00 UTC"


def test_workflow_invokes_drift_check_and_refresh_and_pr():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ops/scripts/check_corpus_drift.py" in text
    assert "ops/scripts/refresh_calibration_and_int8.py" in text
    assert "peter-evans/create-pull-request" in text or "gh pr create" in text


def test_workflow_uses_lfs_checkout():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "lfs: true" in text, (
        "drift workflow must checkout with lfs: true so existing onnx/parquet are present."
    )
