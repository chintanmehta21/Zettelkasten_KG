from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class PageIndexRagConfig:
    enabled: bool
    mode: str
    iter_id: str
    workspace: Path
    eval_dir: Path
    queries_path: Path
    login_details_path: Path
    kasten_slug: str
    kasten_name: str
    candidate_limit: int
    pageindex_api_mode: str
    pageindex_api_key: str | None
    enforce_answer_strength_gate: bool
    answer_strength_baseline_path: Path


def load_config() -> PageIndexRagConfig:
    iter_id = os.environ.get("PAGEINDEX_RAG_ITER_ID", "iter-01")
    return PageIndexRagConfig(
        enabled=os.environ.get("PAGEINDEX_RAG_ENABLED", "false").lower() == "true",
        mode=os.environ.get("PAGEINDEX_RAG_MODE", "local"),
        iter_id=iter_id,
        workspace=Path(os.environ.get("PAGEINDEX_RAG_WORKSPACE", str(REPO_ROOT / ".cache" / "pageindex_rag"))),
        eval_dir=Path(
            os.environ.get(
                "PAGEINDEX_RAG_EVAL_DIR",
                str(REPO_ROOT / "docs" / "rag_eval" / "PageIndex" / "knowledge-management" / iter_id),
            )
        ),
        queries_path=Path(
            os.environ.get(
                "PAGEINDEX_RAG_QUERIES_PATH",
                str(REPO_ROOT / "docs" / "rag_eval" / "common" / "knowledge-management" / "iter-03" / "queries.json"),
            )
        ),
        login_details_path=REPO_ROOT / "docs" / ("login_details" + ".txt"),
        kasten_slug="knowledge-management",
        kasten_name="Knowledge Management",
        candidate_limit=int(os.environ.get("PAGEINDEX_RAG_CANDIDATE_LIMIT", "7")),
        pageindex_api_mode=os.environ.get("PAGEINDEX_RAG_PAGEINDEX_API_MODE", "local"),
        pageindex_api_key=os.environ.get("PAGEINDEX_RAG_PAGEINDEX_API_KEY"),
        enforce_answer_strength_gate=os.environ.get("PAGEINDEX_RAG_ENFORCE_STRENGTH_GATE", "false").lower() == "true",
        answer_strength_baseline_path=Path(
            os.environ.get(
                "PAGEINDEX_RAG_ANSWER_STRENGTH_BASELINE",
                str(REPO_ROOT / "docs" / "rag_eval" / "PageIndex" / "knowledge-management" / "iter-03" / "answer_strength.json"),
            )
        ),
    )
