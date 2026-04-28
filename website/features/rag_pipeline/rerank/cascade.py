"""In-process cascade reranker built from FlashRank and BGE ONNX.

The stage-2 path is now int8-aware: when ``models/bge-reranker-base-int8.onnx``
exists at process start, an int8 session is loaded eagerly at module import so
gunicorn ``--preload`` can share the resident pages across worker forks. A
calibration regression (``_int8_score_cal.json``) and per-class margin file
(``_int8_thresholds.json``) live next to this module. An optional fp32 verify
session re-scores the top-K to absorb int8 outliers (Layer 5) and ``score_batch``
supports test-time augmentation (Layer 7) when ``mode='high'``.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from flashrank import Ranker, RerankRequest
from tokenizers import Tokenizer

from website.features.rag_pipeline.rerank.degradation_log import DegradationLogger
from website.features.rag_pipeline.rerank.model_manager import FLASHRANK_MODEL_NAME, ModelManager
from website.features.rag_pipeline.types import QueryClass, RetrievalCandidate

_logger = logging.getLogger(__name__)


def _log_rss(label: str, **fields: object) -> None:
    """Log current process RSS at a named profiling point.

    iter-03 (2026-04-29): emits one line per phase boundary so we can grep the
    container logs to compute per-stage memory deltas during q1. Pure-stdlib
    /proc/self/status read - no psutil dependency, no measurable overhead.
    """
    try:
        with open("/proc/self/status", "r", encoding="ascii") as f:
            rss_kb = next(
                (int(line.split()[1]) for line in f if line.startswith("VmRSS:")),
                0,
            )
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        _logger.info("[mem-trace] %s rss_kb=%d %s", label, rss_kb, extra)
    except OSError:
        pass  # /proc not available (Windows tests etc.)

# ---------------------------------------------------------------------------
# Module-level int8 wiring (spec 3.15 layers 1-7)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[4]
INT8_MODEL_PATH = _REPO_ROOT / "models" / "bge-reranker-base-int8.onnx"
FP32_MODEL_PATH = _REPO_ROOT / "models" / "bge-reranker-base.onnx"
SCORE_CAL_PATH = Path(__file__).parent / "_int8_score_cal.json"
THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "retrieval" / "_int8_thresholds.json"
FP32_VERIFY_ENABLED = os.environ.get("RAG_FP32_VERIFY", "on").lower() == "on"


def _build_ort_session(path: Path) -> ort.InferenceSession | None:
    """Eagerly load an ONNX session if the file exists, else return None.

    Single-threaded CPU session: gunicorn ``--preload`` will fork workers after
    this completes, so each worker inherits the resident model via copy-on-write
    rather than each loading its own ~110 MB int8 weights.
    """
    if not path.exists():
        return None
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # iter-03 mem-bounded §2.3: cap arena at per-call working set instead of
    # holding the high-water mark for the session lifetime. Both flags off
    # because mem_pattern only helps when arena is on AND shapes are static.
    # Latency cost: +10-30 ms per BGE call (Gemini-bound p50 ~20s ⇒ invisible).
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False
    try:
        return ort.InferenceSession(
            str(path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
    except Exception as exc:  # pragma: no cover - load-time fault is logged
        _logger.warning("failed to eager-load %s: %s", path, exc)
        return None


_STAGE2_SESSION: ort.InferenceSession | None = _build_ort_session(INT8_MODEL_PATH)
_FP32_VERIFY_SESSION: ort.InferenceSession | None = (
    _build_ort_session(FP32_MODEL_PATH) if FP32_VERIFY_ENABLED else None
)


# iter-03 mem-bounded §2.5: hoist FlashRank to module-level so gunicorn
# --preload shares it via COW. The lazy per-instance path stays as a fallback
# for tests where the model file is absent.
_DEFAULT_FLASHRANK_DIR = _REPO_ROOT / "models"


def _build_flashrank_ranker(model_dir: Path) -> Ranker | None:
    """Build the FlashRank stage-1 ranker eagerly so it COW-shares post-fork.

    Filesystem side effects (model download into ``model_dir``) MUST happen
    pre-fork — we trigger them via ``ModelManager.ensure_flashrank_model()``
    here at import time so the cache directory is populated and forked
    workers do not race for the file.

    Returns ``None`` on any failure so import-time problems degrade to the
    legacy lazy path rather than crashing the whole app.
    """
    try:
        ModelManager(str(model_dir)).ensure_flashrank_model()
        return Ranker(model_name=FLASHRANK_MODEL_NAME, cache_dir=str(model_dir))
    except Exception as exc:  # pragma: no cover - bootstrap fault is logged
        _logger.warning("failed to preload FlashRank ranker: %s", exc)
        return None


_STAGE1_RANKER: Ranker | None = _build_flashrank_ranker(_DEFAULT_FLASHRANK_DIR)


# iter-03 §7: BGE tokenizer also baked into the image. Eager-load at module
# import so workers COW-share the parsed tokenizer state instead of each
# parsing the 700 KB tokenizer.json post-fork. cascade._score_one's existing
# int8-path tokenizer handling reads the same file at models/tokenizer.json.
_TOKENIZER_PATH = INT8_MODEL_PATH.parent / "tokenizer.json"
_STAGE2_TOKENIZER: Tokenizer | None = (
    Tokenizer.from_file(str(_TOKENIZER_PATH)) if _TOKENIZER_PATH.exists() else None
)


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - config fault
        _logger.warning("failed to load %s, using defaults: %s", path, exc)
        return default


_SCORE_CAL = _load_json(SCORE_CAL_PATH, {"a": 1.0, "b": 0.0})
_THRESHOLDS = _load_json(THRESHOLDS_PATH, {"default": 0.50})


def _score_one(session: ort.InferenceSession, query: str, chunk: str) -> float:
    """Single (query, chunk) pair scoring helper used by the int8 path.

    Loads/caches a tokenizer next to the model and returns the sigmoid-squashed
    score. Heavy: callers should batch where possible.
    """
    tok = _score_one._tokenizer  # type: ignore[attr-defined]
    if tok is None:
        # Resolve a tokenizer.json sitting next to the int8 model. If none is
        # present, fall back to a sentinel that lets the caller skip scoring
        # gracefully -- typical only in tests where the model is absent.
        candidates = [
            INT8_MODEL_PATH.parent / "tokenizer.json",
            FP32_MODEL_PATH.parent / "tokenizer.json",
        ]
        for cand in candidates:
            if cand.exists():
                tok = Tokenizer.from_file(str(cand))
                break
        if tok is None:
            raise FileNotFoundError("BGE tokenizer.json not found alongside model files")
        tok.enable_truncation(max_length=512)
        tok.enable_padding(length=512)
        _score_one._tokenizer = tok  # type: ignore[attr-defined]

    enc = tok.encode(query, chunk)
    input_ids = np.asarray([enc.ids], dtype=np.int64)
    attention_mask = np.asarray([enc.attention_mask], dtype=np.int64)
    feeds = {"input_ids": input_ids, "attention_mask": attention_mask}
    if any(enc.type_ids):
        feeds["token_type_ids"] = np.asarray([enc.type_ids], dtype=np.int64)
    feeds = {meta.name: feeds[meta.name] for meta in session.get_inputs() if meta.name in feeds}
    out = session.run(None, feeds)
    logits = np.asarray(out[0])
    raw = logits.reshape(-1)[0] if logits.ndim >= 1 else float(logits)
    return float(_sigmoid(np.asarray([raw]))[0])


_score_one._tokenizer = None  # type: ignore[attr-defined]


# Query-class-aware (rerank, graph, rrf) fusion weights — different signals
# matter for different query intents. Weights per class sum to 1.0 so score
# magnitudes stay comparable across classes for downstream logic.
# iter-04 retune: probe iter introduces yt-effective-public-speakin (Patrick
# Winston / MIT lecture) as a similar-tag distractor against the AI/ML cluster.
# To prevent the probe from dragging into top-K via shared 'lecture' tag, lift
# rerank weight back to 0.55 and trim graph to 0.30 for THEMATIC. The KG
# signal stays strong enough to surface true gold (per iter-02's +28.8 lift)
# while reducing the probability that the probe's tag-overlap edges win.
_FUSION_WEIGHTS: dict[QueryClass, tuple[float, float, float]] = {
    QueryClass.LOOKUP: (0.70, 0.15, 0.15),
    QueryClass.VAGUE: (0.55, 0.25, 0.20),
    QueryClass.THEMATIC: (0.55, 0.30, 0.15),  # iter-04: rebalance for probe
    QueryClass.MULTI_HOP: (0.40, 0.45, 0.15),
    QueryClass.STEP_BACK: (0.45, 0.40, 0.15),
}
_DEFAULT_FUSION_WEIGHTS: tuple[float, float, float] = (0.60, 0.25, 0.15)


def _resolve_fusion_weights(
    query_class: QueryClass | None,
    graph_weight_override: float | None = None,
) -> tuple[float, float, float]:
    """Resolve (rerank_w, graph_w, rrf_w) for a query class with optional graph override.

    When graph_weight_override is set (e.g. 0.0 for KG ablation), the graph weight
    is replaced and the remaining (1 - graph_w) is redistributed across rerank/rrf
    while preserving their original ratio.
    """
    rerank_w, graph_w, rrf_w = _FUSION_WEIGHTS.get(query_class, _DEFAULT_FUSION_WEIGHTS)
    if graph_weight_override is not None:
        graph_w = graph_weight_override
        denom = (rerank_w + rrf_w) if hasattr(_FUSION_WEIGHTS, "get") else 0
        # Use original (rerank_w, rrf_w) ratio from the class table to redistribute.
        orig_rerank, _, orig_rrf = _FUSION_WEIGHTS.get(query_class, _DEFAULT_FUSION_WEIGHTS)
        denom = orig_rerank + orig_rrf
        if denom > 0:
            scale = (1.0 - graph_w) / denom
            return orig_rerank * scale, graph_w, orig_rrf * scale
        return rerank_w, graph_w, rrf_w
    return rerank_w, graph_w, rrf_w


@dataclass(slots=True)
class _ScoredCandidate:
    candidate: RetrievalCandidate
    score: float


# iter-02 retune: drop MMR lambda from 0.10 → 0.05 to reduce diversity penalty.
# iter-01 reranking P@3 was 0.83 — the gold Zettel was always rank #1 but #2/#3
# slots sometimes carried distractors that beat near-tied gold-cluster siblings
# only because of the diversity push. Cutting the penalty in half lets stronger
# in-cluster candidates retain their slots; precision should rise without
# sacrificing the per-query Hit@5 (still 1.0 on iter-01).
_MMR_LAMBDA = 0.05


class CascadeReranker:
    """Rerank candidates with a fast shortlist stage and a deeper ONNX stage."""

    def __init__(
        self,
        model_dir: str | Path | None = None,
        stage1_k: int = 10,
        max_length: int = 512,
        stage2_sub_batch: int | None = None,
    ) -> None:
        # ``model_dir`` is optional now -- the int8 path is wired through the
        # eager module-level session and doesn't depend on FlashRank's cache dir.
        # Existing callers continue to pass it for stage-1 (FlashRank).
        effective_model_dir = model_dir if model_dir is not None else str(_REPO_ROOT / "models")
        self._model_manager = ModelManager(effective_model_dir)
        # iter-03 §7: write degradation events to a separate writable mount,
        # not to model_dir. /app/models is read-only post-bake. Override via
        # RAG_DEGRADATION_LOG_DIR env (default /app/runtime).
        log_dir = os.environ.get("RAG_DEGRADATION_LOG_DIR", "/app/runtime")
        self._degradation_logger = DegradationLogger(log_dir)
        self._stage1_k = max(stage1_k, 1)
        self._max_length = max_length
        # iter-03 §B (2026-04-29): bound the ONNX forward-pass peak by
        # processing candidates in sub-batches. Halving from 10 to 5 cuts the
        # activation tensor allocation roughly in half so the worker fits
        # under the 1.6 GB cgroup ceiling on the 2 GB droplet. Override via
        # RAG_STAGE2_SUB_BATCH env var for tuning.
        if stage2_sub_batch is None:
            stage2_sub_batch = int(os.environ.get("RAG_STAGE2_SUB_BATCH", "5"))
        self._stage2_sub_batch = max(stage2_sub_batch, 1)
        self._stage1: Ranker | None = None
        self._stage1_lock = threading.Lock()
        self._stage2_lock = threading.Lock()

        # int8 wiring (spec 3.15)
        self.stage2_model_path = str(INT8_MODEL_PATH)
        self._calibration_a = float(_SCORE_CAL.get("a", 1.0))
        self._calibration_b = float(_SCORE_CAL.get("b", 0.0))
        self._fp32_verify_enabled = FP32_VERIFY_ENABLED and _FP32_VERIFY_SESSION is not None
        self._tta_call_count_for_last_query = 0

    # ------------------------------------------------------------------
    # int8 helpers (spec 3.15 layers 4-7)
    # ------------------------------------------------------------------
    def _apply_score_calibration(self, raw: float) -> float:
        """Recover fp32 scale: fp32 ~= a * int8 + b (Layer 4)."""
        return self._calibration_a * raw + self._calibration_b

    def _threshold_for_class(self, query_class: str) -> float:
        """Per-class margin threshold from the tuned table (Layer 6)."""
        return float(_THRESHOLDS.get(query_class, _THRESHOLDS.get("default", 0.50)))

    def _fp32_verify_top_k(
        self, query: str, top_docs: list[dict], k: int = 3
    ) -> list[dict]:
        """Layer 5: re-score the top-k with the fp32 model and re-sort."""
        if not self._fp32_verify_enabled or _FP32_VERIFY_SESSION is None:
            return top_docs
        sub = list(top_docs[:k])
        for doc in sub:
            doc["score"] = _score_one(_FP32_VERIFY_SESSION, query, doc["text"])
        sub.sort(key=lambda d: d["score"], reverse=True)
        return sub + list(top_docs[k:])

    def score_batch(
        self, query: str, docs: list[dict], *, mode: str = "fast"
    ) -> list[dict]:
        """Score every doc with the int8 session. ``mode='high'`` enables TTA.

        Test-time augmentation (Layer 7) re-scores once with the doc list
        reversed and averages the two passes, dampening positional bias.
        """
        if _STAGE2_SESSION is None:
            raise RuntimeError(
                "int8 stage-2 session is not loaded - "
                f"missing {INT8_MODEL_PATH}. Run ops/scripts/quantize_bge_int8.py."
            )
        self._tta_call_count_for_last_query = 0

        def _score_pass(doc_order: list[dict]) -> list[float]:
            self._tta_call_count_for_last_query += 1
            with self._stage2_lock:
                return [_score_one(_STAGE2_SESSION, query, d["text"]) for d in doc_order]

        raw_scores = _score_pass(docs)
        if mode == "high":
            rev_scores = _score_pass(list(reversed(docs)))
            rev_scores_aligned = list(reversed(rev_scores))
            raw_scores = [(a + b) / 2.0 for a, b in zip(raw_scores, rev_scores_aligned)]

        for doc, raw in zip(docs, raw_scores):
            doc["score"] = self._apply_score_calibration(raw)

        docs.sort(key=lambda d: d["score"], reverse=True)
        if mode == "high":
            docs = self._fp32_verify_top_k(query, docs, k=3)
        return docs

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int = 8,
        query_class: QueryClass | None = None,
        graph_weight_override: float | None = None,
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

        # iter-03 §B (2026-04-29): explicitly free retrieval and stage-1
        # working set before the stage-2 forward pass. HTTPx response buffers
        # from Gemini rewriter calls and Supabase RPCs can hold ~100-200 MB
        # of decoded JSON until refcounts naturally drop; running gc here
        # returns that memory to the allocator right before the largest
        # spike, buying cgroup headroom. Cost: ~30-50 ms (Gemini-bound p50
        # is ~20s so invisible in p95). pre_gc/post_gc mem-trace lines let
        # us measure the actual delta in prod.
        _log_rss("stage2.pre_gc")
        gc.collect()
        _log_rss("stage2.post_gc")

        try:
            stage2_scores = await self._stage2_rank(query, shortlisted)
        except Exception as exc:
            self._log_degradation(query, shortlisted, "stage2", exc)
            return self._apply_scores(
                stage1_ranked[: self._stage1_k],
                top_k,
                query_class,
                graph_weight_override=graph_weight_override,
            )

        scored_candidates = [
            _ScoredCandidate(candidate=candidate, score=float(score))
            for candidate, score in zip(shortlisted, stage2_scores, strict=False)
        ]
        return self._apply_scores(
            scored_candidates,
            top_k,
            query_class,
            graph_weight_override=graph_weight_override,
        )

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
        # iter-03 §B (2026-04-29): split the stage-2 batch into sub-batches
        # of self._stage2_sub_batch (default 5) and process them sequentially.
        # The ONNX forward pass on a full batch=10 was the +684 MB spike that
        # SIGKILLed the worker; a 5-wide sub-batch halves the activation
        # tensors and keeps peak RSS under the 1.6 GB cgroup. Encoded buffers
        # and outputs are released between sub-batches to bound peak.
        _log_rss("stage2.enter", count=len(candidates))
        if not candidates:
            _log_rss("stage2.scored", count=0)
            return []

        tokenizer = self._get_stage2_tokenizer()
        session = self._get_stage2_session()

        sub_batch = self._stage2_sub_batch
        all_scores: list[float] = []
        for chunk_start in range(0, len(candidates), sub_batch):
            chunk = candidates[chunk_start : chunk_start + sub_batch]
            encoded = await asyncio.to_thread(
                self._encode_pairs_sync, tokenizer, query, chunk
            )
            _log_rss("stage2.encoded", chunk_start=chunk_start, chunk_size=len(chunk))
            outputs = await asyncio.to_thread(self._run_stage2_sync, session, encoded)
            _log_rss("stage2.ran", chunk_start=chunk_start, chunk_size=len(chunk))
            del encoded
            chunk_scores = self._extract_scores(outputs)
            del outputs
            all_scores.extend(chunk_scores)

        _log_rss("stage2.scored", count=len(all_scores))
        return all_scores

    def _apply_scores(
        self,
        scored_candidates: list[_ScoredCandidate],
        top_k: int,
        query_class: QueryClass | None = None,
        graph_weight_override: float | None = None,
    ) -> list[RetrievalCandidate]:
        for item in scored_candidates:
            item.candidate.rerank_score = item.score
            item.candidate.final_score = self._fused_score(
                item.candidate, item.score, query_class, graph_weight_override
            )

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

    def _fused_score(
        self,
        candidate: RetrievalCandidate,
        rerank_score: float,
        query_class: QueryClass | None = None,
        graph_weight_override: float | None = None,
    ) -> float:
        quality = _content_quality_factor(candidate.content or "")
        rerank_w, graph_w, rrf_w = _resolve_fusion_weights(query_class, graph_weight_override)
        return (
            rerank_w * rerank_score * quality
            + graph_w * (candidate.graph_score or 0.0)
            + rrf_w * (candidate.rrf_score or 0.0)
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
        # Production path: the module-level singleton was preloaded in master
        # under gunicorn --preload, so workers inherit it via COW. Return it
        # directly without locking — the singleton is read-only after import.
        if _STAGE1_RANKER is not None:
            return _STAGE1_RANKER
        # Test / smoke fallback: legacy per-instance lazy build retained so
        # tests that patch model_dir keep working. Preserve the existing
        # ensure_flashrank_model() download trigger so the file is on disk.
        with self._stage1_lock:
            if self._stage1 is None:
                self._model_manager.ensure_flashrank_model()
                self._stage1 = Ranker(
                    model_name=FLASHRANK_MODEL_NAME,
                    cache_dir=str(self._model_manager.model_dir),
                )
            return self._stage1

    def _get_stage2_session(self) -> ort.InferenceSession:
        # iter-03 §7: int8 BGE is baked into the image at module import. There
        # is no lazy fp32 fallback - if _STAGE2_SESSION is None, the image is
        # broken and we fail loudly so deploy.sh [stage2-assert] catches it
        # before Caddy flip. The previous lazy path ate 1 GB RSS per worker
        # in iter-03-stale.
        if _STAGE2_SESSION is None:
            raise RuntimeError(
                "int8 BGE session not loaded - image is missing "
                "models/bge-reranker-base-int8.onnx or it failed to import"
            )
        return _STAGE2_SESSION

    def _get_stage2_tokenizer(self) -> Tokenizer:
        # iter-03 §7: tokenizer also eager-loaded at module level (see
        # _STAGE2_TOKENIZER). No lazy fallback.
        if _STAGE2_TOKENIZER is None:
            raise RuntimeError(
                "BGE tokenizer not loaded - image is missing "
                "models/tokenizer.json or it failed to import"
            )
        return _STAGE2_TOKENIZER

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
    """Build the text passed to both rerank stages.

    Prepends a compact bracketed metadata header (source / author / date /
    tags) so the cross-encoder gets richer signal for the same compute
    budget. The header is followed by the candidate name (unless content
    already restates it) and finally the body. Missing metadata fields are
    silently omitted — no `None`-stringified noise leaks into the input."""
    content = (candidate.content or "")[:4000]
    name = (candidate.name or "").strip()
    parts: list[str] = []

    meta_pieces: list[str] = []
    src = getattr(candidate.source_type, "value", str(candidate.source_type or "unknown"))
    meta_pieces.append(f"source={src}")
    md = candidate.metadata or {}
    author = md.get("author") or md.get("channel")
    if author:
        meta_pieces.append(f"author={author}")
    ts = md.get("timestamp")
    if not ts:
        time_span = md.get("time_span")
        if isinstance(time_span, dict):
            ts = time_span.get("end")
    if ts:
        meta_pieces.append(f"date={str(ts)[:10]}")
    if candidate.tags:
        meta_pieces.append("tags=" + ",".join(candidate.tags[:5]))
    parts.append("[" + "; ".join(meta_pieces) + "]")

    if name:
        head = content.lstrip()[:120].lower()
        if name.lower() not in head:
            parts.append(name)
    parts.append(content)
    return "\n\n".join(parts)


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
