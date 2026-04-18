"""In-process cascade reranker built from FlashRank and BGE ONNX."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from flashrank import Ranker, RerankRequest
from tokenizers import Tokenizer

from website.features.rag_pipeline.rerank.degradation_log import DegradationLogger
from website.features.rag_pipeline.rerank.model_manager import FLASHRANK_MODEL_NAME, ModelManager
from website.features.rag_pipeline.types import RetrievalCandidate


@dataclass(slots=True)
class _ScoredCandidate:
    candidate: RetrievalCandidate
    score: float


# Per-node diversity penalty applied greedily after scoring. A candidate whose
# node is already represented in the selected set pays this much against its
# final_score before competing for the next slot. Keeps top_k from being
# dominated by one chatty node while still letting clearly-stronger siblings
# win — a sibling only loses out if a different node is within _MMR_LAMBDA of
# its score.
_MMR_LAMBDA = 0.10


class CascadeReranker:
    """Rerank candidates with a fast shortlist stage and a deeper ONNX stage."""

    def __init__(self, model_dir: str | Path, stage1_k: int = 15, max_length: int = 512) -> None:
        self._model_manager = ModelManager(model_dir)
        self._degradation_logger = DegradationLogger(model_dir)
        self._stage1_k = max(stage1_k, 1)
        self._max_length = max_length
        self._stage1: Ranker | None = None
        self._stage2_session: ort.InferenceSession | None = None
        self._stage2_tokenizer: Tokenizer | None = None
        self._stage1_lock = threading.Lock()
        self._stage2_lock = threading.Lock()

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 8,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        try:
            stage1_ranked = await self._stage1_rank(query, candidates)
        except Exception as exc:
            self._log_degradation(query, candidates, "both", exc)
            return self._fallback_to_rrf(candidates, top_k)

        shortlisted = [item.candidate for item in stage1_ranked[: self._stage1_k]]
        if not shortlisted:
            return []

        try:
            stage2_scores = await self._stage2_rank(query, shortlisted)
        except Exception as exc:
            self._log_degradation(query, shortlisted, "stage2", exc)
            return self._apply_scores(stage1_ranked[: self._stage1_k], top_k)

        scored_candidates = [
            _ScoredCandidate(candidate=candidate, score=float(score))
            for candidate, score in zip(shortlisted, stage2_scores, strict=False)
        ]
        return self._apply_scores(scored_candidates, top_k)

    async def _stage1_rank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> list[_ScoredCandidate]:
        stage1 = self._get_stage1_ranker()
        passages = [
            {"id": index, "text": _passage_text(candidate), "meta": {"index": index}}
            for index, candidate in enumerate(candidates)
        ]
        request = RerankRequest(query=query, passages=passages)
        results = await asyncio.to_thread(self._run_stage1_sync, stage1, request)

        scored = []
        for item in results:
            candidate = candidates[item["meta"]["index"]]
            scored.append(_ScoredCandidate(candidate=candidate, score=float(item["score"])))
        return scored

    async def _stage2_rank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> list[float]:
        tokenizer = self._get_stage2_tokenizer()
        session = self._get_stage2_session()
        encoded = await asyncio.to_thread(self._encode_pairs_sync, tokenizer, query, candidates)
        outputs = await asyncio.to_thread(self._run_stage2_sync, session, encoded)
        return self._extract_scores(outputs)

    def _apply_scores(
        self,
        scored_candidates: list[_ScoredCandidate],
        top_k: int,
    ) -> list[RetrievalCandidate]:
        for item in scored_candidates:
            item.candidate.rerank_score = item.score
            item.candidate.final_score = self._fused_score(item.candidate, item.score)

        ranked = sorted(
            [item.candidate for item in scored_candidates],
            key=lambda candidate: candidate.final_score or 0.0,
            reverse=True,
        )
        return _mmr_select(ranked, top_k, _MMR_LAMBDA)

    def _fallback_to_rrf(
        self,
        candidates: list[RetrievalCandidate],
        top_k: int,
    ) -> list[RetrievalCandidate]:
        for candidate in candidates:
            candidate.rerank_score = None
            candidate.final_score = candidate.rrf_score or 0.0
        return sorted(candidates, key=lambda candidate: candidate.rrf_score or 0.0, reverse=True)[:top_k]

    def _fused_score(self, candidate: RetrievalCandidate, rerank_score: float) -> float:
        quality = _content_quality_factor(candidate.content or "")
        return (
            0.60 * rerank_score * quality
            + 0.25 * (candidate.graph_score or 0.0)
            + 0.15 * (candidate.rrf_score or 0.0)
        )

    def _build_degradation_context(self, candidates: list[RetrievalCandidate]) -> dict[str, list]:
        return {
            "content_lengths": [len(candidate.content) for candidate in candidates],
            "source_types": [candidate.source_type.value for candidate in candidates],
        }

    def _log_degradation(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        failed_stage: str,
        exception: BaseException,
    ) -> None:
        context = self._build_degradation_context(candidates)
        self._degradation_logger.log_event(
            query=query,
            candidate_count=len(candidates),
            failed_stage=failed_stage,
            exception=exception,
            content_lengths=context["content_lengths"],
            source_types=context["source_types"],
        )

    def _get_stage1_ranker(self) -> Ranker:
        if self._stage1 is None:
            self._model_manager.ensure_flashrank_model()
            self._stage1 = Ranker(
                model_name=FLASHRANK_MODEL_NAME,
                cache_dir=str(self._model_manager.model_dir),
            )
        return self._stage1

    def _get_stage2_session(self) -> ort.InferenceSession:
        if self._stage2_session is None:
            bge_dir = self._model_manager.ensure_bge_onnx_model()
            self._stage2_session = ort.InferenceSession(str(bge_dir / "onnx" / "model.onnx"))
        return self._stage2_session

    def _get_stage2_tokenizer(self) -> Tokenizer:
        if self._stage2_tokenizer is None:
            bge_dir = self._model_manager.ensure_bge_onnx_model()
            self._stage2_tokenizer = Tokenizer.from_file(str(bge_dir / "tokenizer.json"))
        return self._stage2_tokenizer

    def _run_stage1_sync(self, stage1: Ranker, request: RerankRequest) -> list[dict]:
        with self._stage1_lock:
            return stage1.rerank(request)

    def _encode_pairs_sync(
        self,
        tokenizer: Tokenizer,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> dict[str, np.ndarray]:
        with self._stage2_lock:
            tokenizer.enable_truncation(max_length=self._max_length)
            tokenizer.enable_padding(length=self._max_length)
            encodings = tokenizer.encode_batch([(query, _passage_text(candidate)) for candidate in candidates])

        input_ids = np.array([encoding.ids for encoding in encodings], dtype=np.int64)
        attention_mask = np.array([encoding.attention_mask for encoding in encodings], dtype=np.int64)
        encoded = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        type_ids = [encoding.type_ids for encoding in encodings]
        if any(type_ids):
            encoded["token_type_ids"] = np.array(type_ids, dtype=np.int64)
        return encoded

    def _run_stage2_sync(
        self,
        session: ort.InferenceSession,
        encoded: dict[str, np.ndarray],
    ) -> list[np.ndarray]:
        inputs = {
            input_meta.name: encoded[input_meta.name]
            for input_meta in session.get_inputs()
            if input_meta.name in encoded
        }
        return session.run(None, inputs)

    def _extract_scores(self, outputs: list[np.ndarray]) -> list[float]:
        if not outputs:
            return []

        logits = np.asarray(outputs[0])
        if logits.ndim == 1:
            raw = logits
        elif logits.ndim == 2 and logits.shape[1] == 1:
            raw = logits[:, 0]
        elif logits.ndim == 2 and logits.shape[1] >= 2:
            raw = logits[:, -1]
        else:
            raw = logits.reshape(logits.shape[0], -1)[:, 0]

        # BGE cross-encoder emits raw logits that can sit in the ~[-5, +5]
        # range. Fused scoring multiplies rerank_score by 0.60 against RRF
        # (0-1) and graph (0-1); un-normalised logits would dominate by an
        # order of magnitude and make the fusion weights meaningless. Squash
        # via sigmoid so all three components live in [0, 1].
        squashed = _sigmoid(raw)
        return [float(value) for value in squashed]


def _content_quality_factor(content: str) -> float:
    """Return a 0.35–1.0 factor that damps the rerank contribution for very
    short (stub) candidates. A 200-char body saturates at 1.0; a 40-char stub
    lands around 0.50. The floor of 0.35 keeps useful-but-terse nodes in the
    mix (e.g. a one-line GitHub issue that actually answers the query)."""
    length = len(content.strip())
    if length <= 0:
        return 0.35
    saturated = min(1.0, length / 200.0)
    return 0.35 + 0.65 * saturated


def _sigmoid(values: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid — avoids overflow for large negative logits
    by splitting positives and negatives."""
    arr = np.asarray(values, dtype=np.float64)
    out = np.empty_like(arr)
    positive = arr >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-arr[positive]))
    exp_neg = np.exp(arr[~positive])
    out[~positive] = exp_neg / (1.0 + exp_neg)
    return out


def _passage_text(candidate: RetrievalCandidate) -> str:
    """Build the text passed to both rerank stages. Prepending the candidate's
    name (unless the content already starts with it) gives the cross-encoder
    strong title signal for non-first chunks and summary rows whose body may
    not repeat the zettel title verbatim."""
    content = (candidate.content or "")[:4000]
    name = (candidate.name or "").strip()
    if not name:
        return content
    head = content.lstrip()[:120].lower()
    if name.lower() in head:
        return content
    return f"{name}\n\n{content}"


def _mmr_select(
    ranked: list[RetrievalCandidate],
    top_k: int,
    node_penalty: float,
) -> list[RetrievalCandidate]:
    """Greedy MMR pick that penalises repeated node_ids. Stable when all
    candidates come from distinct nodes: the penalty never fires and ordering
    matches the input (score-desc) exactly."""
    if top_k <= 0 or not ranked:
        return ranked[:top_k]

    selected: list[RetrievalCandidate] = []
    remaining = list(ranked)
    selected_nodes: set[str] = set()
    while remaining and len(selected) < top_k:
        best_index = 0
        best_adjusted = float("-inf")
        for index, candidate in enumerate(remaining):
            base = candidate.final_score or 0.0
            penalty = node_penalty if candidate.node_id in selected_nodes else 0.0
            adjusted = base - penalty
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        picked = remaining.pop(best_index)
        selected.append(picked)
        selected_nodes.add(picked.node_id)
    return selected
