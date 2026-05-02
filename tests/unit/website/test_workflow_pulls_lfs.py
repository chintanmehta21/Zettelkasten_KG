"""2026-05-03: int8 BGE was migrated from Git LFS to a private HF Hub
repo (Zettelkasten/bge-reranker). The build-and-push checkout must NOT
enable LFS (saves ~30s per build, sidesteps LFS quota), and the docker
build must mount the HF_TOKEN secret so the Dockerfile builder stage
can pull the model.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-droplet.yml"


def test_build_checkout_does_not_enable_lfs():
    """The docker-build checkout must not enable LFS — model now comes from HF Hub."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "lfs: true" not in text, (
        "deploy-droplet.yml must NOT use 'lfs: true' anywhere — the int8 BGE "
        "reranker was migrated to HF Hub on 2026-05-03 and is fetched at "
        "docker build time via huggingface_hub. See ops/Dockerfile."
    )


def test_build_passes_hf_token_secret():
    """build-push action must forward HF_TOKEN as a docker build secret."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "hf_token=${{ secrets.HF_TOKEN }}" in text, (
        "deploy-droplet.yml must forward HF_TOKEN as a build secret named "
        "'hf_token' so ops/Dockerfile can `RUN --mount=type=secret,id=hf_token` "
        "to fetch the int8 BGE reranker from HF Hub."
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
