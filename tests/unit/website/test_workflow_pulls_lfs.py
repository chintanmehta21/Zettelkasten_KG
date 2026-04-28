"""Iter-03 §5: the deploy workflow must checkout with lfs: true so the
runner pulls models/bge-reranker-base-int8.onnx + bge_calibration_pairs.parquet
before docker build runs. Without lfs:true, COPY models/ in the Dockerfile
copies pointer files instead of real binaries.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-droplet.yml"


def test_main_app_checkout_has_lfs_true():
    """The primary checkout (the one used by docker build) must pull LFS."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "lfs: true" in text, (
        "deploy-droplet.yml must add 'lfs: true' to the docker-build checkout "
        "so models/*.onnx + *.parquet are pulled. See spec §5."
    )


def test_static_body_has_rag_smoke_env_vars():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"RAG_SMOKE_KASTEN_ID=' in text, (
        "STATIC_BODY must include RAG_SMOKE_KASTEN_ID so deploy.sh can fire the "
        "pre-flip RAG smoke probe. See spec §8."
    )
    assert '"NARUTO_SMOKE_PASSWORD=' in text and '"SUPABASE_ANON_KEY_LEGACY_JWT=' in text, (
        "STATIC_BODY must include NARUTO_SMOKE_PASSWORD + SUPABASE_ANON_KEY_LEGACY_JWT "
        "so deploy.sh can mint a fresh JWT every deploy. (Replaced the static "
        "RAG_SMOKE_TOKEN secret which expired after 1h and silently blocked deploys.)"
    )
    assert '"RAG_DEGRADATION_LOG_DIR=/app/runtime"' in text, (
        "STATIC_BODY must declare RAG_DEGRADATION_LOG_DIR=/app/runtime so the "
        "DegradationLogger writes to the new mount. See spec §6."
    )
