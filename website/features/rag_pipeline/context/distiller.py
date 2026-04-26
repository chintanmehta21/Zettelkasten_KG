"""EvidenceCompressor: bi-encoder cascade for sentence-level passage compression.

Producer half of the context distillation pipeline (T15). The companion wiring
into ContextAssembler is T16. Pure module: no model loading at import time, no
global state — all dependencies are injected via the constructor.

Cascade:
  1. Bi-encoder cosine scoring of every sentence vs the query.
  2. Optional cross-encoder escalation when bi-encoder confidence is low or
     scores are clustered too tightly to discriminate.
  3. Top-K selection plus scaffold neighbours to preserve local discourse
     coherence.
"""

from __future__ import annotations

import re

import numpy as np

from website.features.rag_pipeline.types import RetrievalCandidate

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TOP_K = 5
_SCAFFOLD_NEIGHBOURS = 1
_LOW_CONFIDENCE_FLOOR = 0.55
_TIE_CLUSTER_DELTA = 0.05


class EvidenceCompressor:
    """Compress retrieval candidates to the most query-relevant sentences."""

    def __init__(self, *, embedder, cross_encoder=None) -> None:
        self._embedder = embedder
        self._ce = cross_encoder  # optional fallback; may be None

    async def compress(
        self,
        *,
        user_query: str,
        grouped: list[list[RetrievalCandidate]],
        target_budget_tokens: int,
    ) -> list[list[RetrievalCandidate]]:
        if not grouped:
            return grouped

        q_vec = await self._embedder.embed_query_with_cache(user_query)
        q_arr = np.array(q_vec, dtype=np.float32)
        q_norm = q_arr / (np.linalg.norm(q_arr) + 1e-9)

        out: list[list[RetrievalCandidate]] = []
        for group in grouped:
            new_group: list[RetrievalCandidate] = []
            for cand in group:
                body = cand.content or ""
                sentences = [s.strip() for s in _SENTENCE_RE.split(body) if s.strip()]

                # Short passage: nothing to compress.
                if len(sentences) <= _TOP_K:
                    new_group.append(cand)
                    continue

                vecs = await self._embedder.embed_texts(sentences)
                arr = np.array(vecs, dtype=np.float32)
                arr_n = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
                cosines = (arr_n @ q_norm).tolist()
                ranked = sorted(enumerate(cosines), key=lambda x: x[1], reverse=True)

                top3_scores = [s for _, s in ranked[:3]]
                escalate = (
                    all(s < _LOW_CONFIDENCE_FLOOR for s in top3_scores)
                    or (
                        max(top3_scores) - min(top3_scores) <= _TIE_CLUSTER_DELTA
                        and len(top3_scores) >= 3
                    )
                )

                if escalate and self._ce is not None:
                    ce_scores = await self._ce.score_pairs(user_query, sentences)
                    ranked = sorted(enumerate(ce_scores), key=lambda x: x[1], reverse=True)

                top_idx = sorted({i for i, _ in ranked[:_TOP_K]})

                # Add scaffold neighbours to preserve local coherence.
                kept: set[int] = set(top_idx)
                for i in top_idx:
                    lo = max(0, i - _SCAFFOLD_NEIGHBOURS)
                    hi = min(len(sentences), i + _SCAFFOLD_NEIGHBOURS + 1)
                    for j in range(lo, hi):
                        kept.add(j)

                kept_sorted = sorted(kept)
                new_content = " ".join(sentences[k] for k in kept_sorted)
                new_group.append(cand.model_copy(update={"content": new_content}))

            out.append(new_group)
        return out


__all__ = ["EvidenceCompressor"]
