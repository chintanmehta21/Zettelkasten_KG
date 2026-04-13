"""Manage local model bootstrap and freshness checks for cascade reranking."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flashrank import Ranker
from huggingface_hub import model_info

from website.features.rag_pipeline.errors import RerankerUnavailable

logger = logging.getLogger(__name__)

FLASHRANK_MODEL_NAME = "ms-marco-MiniLM-L-12-v2"
BGE_REPO_ID = "BAAI/bge-reranker-base"
BGE_DIR_NAME = "BAAI--bge-reranker-base"


class ModelManager:
    """Ensure cascade reranker assets exist on disk before inference."""

    def __init__(self, model_dir: str | Path) -> None:
        self._model_dir = Path(model_dir)
        self._model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_dir(self) -> Path:
        return self._model_dir

    @property
    def flashrank_dir(self) -> Path:
        return self._model_dir / FLASHRANK_MODEL_NAME

    @property
    def bge_dir(self) -> Path:
        return self._model_dir / BGE_DIR_NAME

    @property
    def bge_model_path(self) -> Path:
        return self.bge_dir / "onnx" / "model.onnx"

    @property
    def bge_metadata_path(self) -> Path:
        return self.bge_dir / "export_metadata.json"

    def models_exist(self) -> bool:
        return self.flashrank_dir.exists() and self.bge_model_path.exists()

    def _read_local_bge_sha(self) -> str | None:
        if not self.bge_metadata_path.exists():
            return None

        try:
            data = json.loads(self.bge_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        value = data.get("source_sha")
        return value if isinstance(value, str) and value else None

    def _fetch_remote_bge_sha(self) -> str:
        info = model_info(BGE_REPO_ID)
        if not info.sha:
            raise OSError(f"No upstream revision available for {BGE_REPO_ID}")
        return info.sha

    def is_bge_stale(self) -> bool:
        local_sha = self._read_local_bge_sha()

        try:
            remote_sha = self._fetch_remote_bge_sha()
        except OSError:
            if self.bge_model_path.exists():
                logger.warning("Hugging Face Hub unreachable; using cached BGE export")
                return False
            raise

        if local_sha is None:
            return True
        return local_sha != remote_sha

    def ensure_flashrank_model(self) -> Path:
        if not self.flashrank_dir.exists():
            Ranker(model_name=FLASHRANK_MODEL_NAME, cache_dir=str(self._model_dir))
        return self.flashrank_dir

    def ensure_bge_onnx_model(self) -> Path:
        if not self.bge_model_path.exists():
            raise RerankerUnavailable(
                "BGE ONNX export missing; run ops/scripts/export_bge_onnx.py first.",
            )
        return self.bge_dir
