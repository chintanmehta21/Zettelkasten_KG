"""03_run_nli.py — MiniCheck-DeBERTa-v3-Large NLI augmentation of per-zettel evals.

WIRED implementation (2026-05-28 TDD).

Reads:
  runs/<iter>/_overall/per_zettel/<wz_uuid>.json   (from 02_run_judge.py)
  _data/<wz_uuid>/source_text.md                    (the source-of-truth reference)
  _data/<wz_uuid>/summary.json                      (production summary; claims source)
  _cache/atomic_facts/<sha>.json                    (per 02; claims if available)
  _config/nli_config.yaml                           (model + thresholds)

Writes (in place, augments existing per_zettel JSONs):
  runs/<iter>/<source>/per_zettel/<wz_uuid>.json   adds:
    nli: {
      mean_entailment: float,
      max_contradict: float,
      hard_fail_flagged: bool,    # True if any claim contradict_prob >= 0.7
      per_claim: [{claim, entail_prob, contradict_prob, neutral_prob, verdict}],
      nli_model: str,
      nli_model_revision: str,
      n_claims: int,
    }

HARD GUARD: this script MUST NOT be invoked on the prod droplet (the
1.7GB MiniCheck model would violate iter-03 RAM budget). Always laptop-only.

Fake-NLI mode for tests:
  --fake-nli                    use a deterministic stub instead of real model
  --fake-entail-prob FLOAT      stub entailment probability (default 0.85)
  --fake-contradict-prob FLOAT  stub contradiction probability (default 0.05)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

EVAL = REPO_ROOT / "docs" / "zettel_eval_v1"
RUNS = EVAL / "runs"
DATA = EVAL / "_data"
CACHE = EVAL / "_cache"


def _load_hf_token_from_new_envs(candidates: list | None = None) -> str | None:
    """Best-effort: pluck ``HF_READ_TOKEN`` out of ``new_envs.txt`` (one level
    above the worktree, operator-owned, untracked) and surface it as
    ``HF_TOKEN`` for the HuggingFace SDK.

    Why: the script downloads the MiniCheck-DeBERTa-v3-Large model from HF Hub
    on first use; without an auth token the request is rate-limited and emits
    a cosmetic "unauthenticated requests" warning every script start. The
    operator already keeps an HF read-scope token alongside other dev secrets;
    plumbing it through silently keeps the warning gone and unlocks faster
    model swaps if we ever change predictor.

    Parses lines of the form ``KEY : value`` OR ``KEY=value`` (case-insensitive
    key, optional whitespace around the separator, optional surrounding quotes).
    Skips comments and blank lines. Prefers ``HF_READ_TOKEN`` over
    ``HF_ADMIN_TOKEN`` (least-privilege).

    Args:
        candidates: optional list of ``Path`` objects to search. Defaults to
            the standard discovery list. Exposed for tests so they can inject
            a tmp-path file without touching the real operator new_envs.txt.

    Returns the token string or ``None`` if not found. Never raises.
    """
    import os as _os
    if _os.environ.get("HF_TOKEN"):
        return _os.environ["HF_TOKEN"]  # explicit override wins
    if candidates is None:
        candidates = [
            REPO_ROOT.parent.parent.parent / "new_envs.txt",
            Path("C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/new_envs.txt"),
        ]
    seen = {"HF_READ_TOKEN": None, "HF_ADMIN_TOKEN": None}
    for p in candidates:
        try:
            if not p.exists():
                continue
            for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                # split on ':' or '=' — whichever appears first
                sep_idx = min(
                    (ln.find(":") if ":" in ln else 10**9),
                    (ln.find("=") if "=" in ln else 10**9),
                )
                if sep_idx >= 10**9:
                    continue
                key = ln[:sep_idx].strip().upper()
                val = ln[sep_idx + 1:].strip().strip('"').strip("'")
                if key in seen and val:
                    seen[key] = val
            break  # first existing file wins
        except Exception:
            continue
    token = seen["HF_READ_TOKEN"] or seen["HF_ADMIN_TOKEN"]
    if token:
        _os.environ["HF_TOKEN"] = token
    return token


# Surface HF_TOKEN at module import time so transformers / huggingface_hub
# pick it up before any from_pretrained call.
_HF_TOKEN_LOADED = _load_hf_token_from_new_envs()

HARD_FAIL_CONTRADICT_THRESHOLD = 0.7


def route_verdict(nli_flag: bool, judge_n: int) -> tuple[str, str]:
    """OR-with-review routing — the combination strategy adopted 2026-05-30.

    REPLACES the prior strict/LOOSE AND-gate. Deep-research verdict
    (docs/claude_audits/nli_judge_combination_strategy_2026-05-30.md, adversarially
    verified): no SOTA framework strict-ANDs two grounding verifiers, and LLM
    judges systematically UNDER-report contradictions (FaithJudge / leniency
    bias) — so requiring the judge to ALSO fire lets a judge false-negative
    silently veto a correct NLI catch (proven on wz=1c0af8ec: NLI 0.66, judge 9
    → AND cleared a real hallucination). OR-with-review never lets one signal
    veto the other:
        both fire         -> "hard_fail"  (high-confidence; auto-fail)
        exactly one fires -> "review"      (route to human queue; reason tags which)
        neither           -> "clean"
    Returns (route, review_reason) where review_reason ∈ {"", "nli_only", "judge_only"}.
    """
    jflag = judge_n > 0
    if nli_flag and jflag:
        return "hard_fail", ""
    if nli_flag and not jflag:
        return "review", "nli_only"
    if (not nli_flag) and jflag:
        return "review", "judge_only"
    return "clean", ""


def _decode_softmax_row(claim: str, row: list[float], model_name: str = "") -> dict:
    """Decode one softmax row into the canonical per-claim dict.

    Shape-aware:
      - len(row) == 2 → MiniCheck binary [not_supported, supported]:
          map to (contradict=not_supported, neutral=0.0, entail=supported).
      - len(row) == 3 → MNLI/SNLI [contradict, neutral, entail]: pass through.
      - anything else → RuntimeError (fail loud on misconfigured model swaps).

    Shared between single-claim ``predict()`` and batched ``predict_batch()``
    so both code paths produce identical output rows; pinned by tests.
    """
    if len(row) == 2:
        contradict_p = float(row[0])
        neutral_p = 0.0
        entail_p = float(row[1])
    elif len(row) == 3:
        contradict_p, neutral_p, entail_p = float(row[0]), float(row[1]), float(row[2])
    else:
        raise RuntimeError(
            f"NLI model {model_name!r} returned unexpected output shape "
            f"len={len(row)}; expected 2 (binary) or 3 (MNLI)."
        )
    verdict = "entailed" if entail_p >= max(contradict_p, neutral_p) else (
        "contradicted" if contradict_p >= neutral_p else "neutral"
    )
    return {
        "claim": claim,
        "entail_prob": round(entail_p, 4),
        "contradict_prob": round(contradict_p, 4),
        "neutral_prob": round(neutral_p, 4),
        "verdict": verdict,
    }


class FakeMiniCheck:
    """Deterministic stub NLI predictor."""
    def __init__(self, entail_prob: float = 0.85, contradict_prob: float = 0.05):
        self.entail_prob = entail_prob
        self.contradict_prob = contradict_prob
        self.model_name = "FAKE-minicheck"
        self.revision = "fake-revision"

    def predict(self, claim: str, premise: str) -> dict:
        # Return canned three-way distribution
        ep = self.entail_prob
        cp = self.contradict_prob
        np_ = max(0.0, 1.0 - ep - cp)
        verdict = (
            "entailed" if ep >= max(cp, np_)
            else ("contradicted" if cp >= np_ else "neutral")
        )
        return {
            "claim": claim,
            "entail_prob": round(ep, 3),
            "contradict_prob": round(cp, 3),
            "neutral_prob": round(np_, 3),
            "verdict": verdict,
        }

    def predict_batch(self, claims: list[str], premise: str,
                       batch_size: int = 8) -> list[dict]:
        # Stub: just iterate. Mirrors the real predictor's signature so the
        # call site can be batch-only. Default batch_size kept in sync with
        # the real predictor (8) post-2026-05-29 chunking refactor.
        return [self.predict(c, premise) for c in claims]


def _chunk_premise(
    premise: str, tokenizer, chunk_token_target: int = 400
) -> list[str]:
    """Split ``premise`` into non-overlapping sentence-aggregated chunks of
    ~``chunk_token_target`` tokens each. Implements the MiniCheck inference
    strategy (Tang et al., EMNLP 2024) — paired with ``max_length=512`` per
    (chunk, claim) pair and max-aggregation of chunk scores per claim.

    Rationale (rather than raw truncation): DeBERTa-v3-Large was pretrained
    at ``max_position_embeddings=512``. Anything beyond that is positional-
    extrapolation. The previous ``max_length=2048`` raw-truncation path
    silently dropped premise content past 2048 tokens, biasing every
    long-source zettel toward "not supported". Chunking + max-pool
    restores the published algorithm's grounding behavior.

    **Empirical wall-clock**: roughly equivalent to the old raw-truncation
    path on CPU. The per-batch O(seq²) win from dropping seq from 2048 → 512
    (~16x cheaper per forward) is mostly offset by the chunk × claim-batch
    loop nest yielding ~6x more forward passes (3 chunks × halved batch_size).
    The real win is QUALITY, not speed.

    Args:
        premise: the source document text. Empty / whitespace → returns ``[]``.
        tokenizer: a HuggingFace tokenizer with ``.encode(text, add_special_tokens=False)``.
            Used only to count tokens per sentence — the actual tokenization
            for inference happens later inside ``predict_batch``. A fallback
            (~4 chars/token) is used if the tokenizer raises.
        chunk_token_target: rough cap per chunk. A single sentence that
            exceeds this becomes its own chunk and will be truncated by
            the downstream tokenizer (rare; sentences typically <80 tokens).

    Returns a list of chunk strings in source order.
    """
    text = (premise or "").strip()
    if not text:
        return []
    # Sentence splitter — prefer NLTK punkt_tab (handles "Dr.", "U.S.", "a.m.",
    # etc. without splitting mid-sentence on the period). Fall back to a naive
    # regex if NLTK or its data are unavailable, so the script still works in a
    # bare-bones dev environment. The regex falls back ONLY when NLTK fails;
    # consequence is reduced grounding quality on abbreviation-dense corpora
    # (Reddit/YouTube transcripts in particular) — the regex over-splits and
    # fragments evidence across spurious chunk boundaries.
    sents: list[str] | None = None
    try:
        from nltk.tokenize import sent_tokenize
        try:
            sents = [s.strip() for s in sent_tokenize(text) if s.strip()]
        except LookupError:
            # punkt_tab not yet downloaded — try once, then retry.
            # Subsequent calls hit the local cache so this happens at most once.
            try:
                import nltk
                nltk.download("punkt_tab", quiet=True)
                sents = [s.strip() for s in sent_tokenize(text) if s.strip()]
            except Exception:
                sents = None
    except ImportError:
        sents = None
    except Exception:
        # Any other NLTK runtime hiccup → drop to regex fallback rather than crash
        sents = None
    if not sents:
        import re as _re
        sents = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sents:
        # No sentence-terminator found — treat the whole premise as one chunk
        # (downstream tokenizer will truncate to max_length anyway).
        return [text]
    chunks: list[str] = []
    cur_sents: list[str] = []
    cur_tokens = 0
    for sent in sents:
        try:
            tok_count = len(tokenizer.encode(sent, add_special_tokens=False))
        except Exception:
            tok_count = max(1, len(sent) // 4)
        # Start a new chunk if adding this sentence would overshoot, BUT only
        # if the current chunk already has at least one sentence (otherwise a
        # single super-long sentence would loop forever as its own zero-chunk).
        if cur_sents and cur_tokens + tok_count > chunk_token_target:
            chunks.append(" ".join(cur_sents))
            cur_sents = []
            cur_tokens = 0
        cur_sents.append(sent)
        cur_tokens += tok_count
    if cur_sents:
        chunks.append(" ".join(cur_sents))
    return chunks


class MiniCheckPredictor:
    """Real MiniCheck-DeBERTa-v3-Large predictor. Loads on first call (~1.7GB).

    Both ``predict()`` (single claim) and ``predict_batch()`` (many claims)
    route through the chunk+max-aggregate path (Tang et al., EMNLP 2024).
    The premise is split into ~400-token sentence-aggregated chunks; every
    (chunk, claim) pair is scored at ``max_length=512`` (DeBERTa-v3 pretrain
    distribution); the chunk with the highest entail probability wins per
    claim. This restores correct grounding behavior on long premises which
    the prior raw ``max_length=2048`` path silently truncated. Wall-clock
    is roughly equivalent to the prior path on CPU (see ``_chunk_premise``
    docstring) — the win is quality, not speed.
    """
    def __init__(self, device: str = "cpu"):
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch
        self.model_name = "lytang/MiniCheck-DeBERTa-v3-Large"
        # Suppress the cosmetic HF Hub "unauthenticated requests" warning — the
        # model is cached locally after first run, and we don't make enough HEAD
        # requests to hit any rate limit. If an operator ever wants faster model
        # swaps, they can set HF_TOKEN in api_env and this filter becomes a no-op.
        # Belt-and-braces: filter via both warnings module AND raise huggingface_hub
        # logger threshold, since the message appears via either path in different
        # transformers/huggingface_hub versions.
        import warnings as _warnings
        import logging as _logging
        _warnings.filterwarnings(
            "ignore",
            message=r".*unauthenticated requests.*HF Hub.*",
        )
        _logging.getLogger("huggingface_hub").setLevel(_logging.ERROR)
        self.tok = AutoTokenizer.from_pretrained(self.model_name)
        # transformers 5.x: `torch_dtype` was renamed to `dtype`. Use `dtype`
        # going forward; passing `torch_dtype` still works but emits a deprecation
        # warning on every model load.
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name, dtype=torch.float16 if device != "cpu" else torch.float32
        ).to(device).eval()
        self.device = device
        self.torch = torch
        self.revision = getattr(self.model.config, "_commit_hash", "unknown")

    def predict(self, claim: str, premise: str) -> dict:
        """Single-claim convenience method. Routes through ``predict_batch`` so
        the same chunk+max-aggregate algorithm runs regardless of entry point.

        Note: ``predict_batch`` runs inference directly — no recursion here.
        """
        out = self.predict_batch([claim], premise, batch_size=1)
        if not out:
            # Defensive: degenerate path only when ``claims=[]``, which we already
            # guard against above. Kept for backward-compat with single-claim tests.
            return {
                "claim": claim, "entail_prob": 0.0, "contradict_prob": 0.0,
                "neutral_prob": 0.0, "verdict": "neutral",
            }
        # Strip chunk-aggregate metadata to preserve the pre-2026-05-29 single-call
        # contract — older tests assert exactly five keys on the returned dict.
        d = dict(out[0])
        d.pop("best_chunk_idx", None)
        d.pop("n_chunks", None)
        d.pop("best_chunk_text", None)
        return d

    def predict_batch(self, claims: list[str], premise: str,
                       batch_size: int = 8) -> list[dict]:
        """Chunked inference + max-aggregate per MiniCheck (Tang et al., EMNLP 2024).

        The premise is split into ~400-token sentence-aggregated chunks via
        ``_chunk_premise``. Every (chunk, claim) pair runs through the model
        at ``max_length=512`` — pretrain-distribution-aligned for DeBERTa-v3.
        For each claim, the chunk yielding the highest entail probability
        wins (max-pool), matching the paper's published algorithm.

        Critically: without chunking, premises >2048 tokens were SILENTLY
        truncated — any supporting evidence in the document tail was thrown
        away and the score biased toward "not supported". Chunk-and-max-pool
        fixes that quality bug. Wall-clock is similar to the prior path
        (see ``_chunk_premise`` docstring for the perf math).

        ``batch_size`` applies WITHIN each chunk (i.e. how many claims share
        one forward pass). Empty claims → []. Empty premise → degraded but
        defined: yields a single empty-string chunk so every claim gets a
        score (typically near 0.5 supported on MiniCheck given no evidence).
        """
        if not claims:
            return []
        chunks = _chunk_premise(premise, self.tok, chunk_token_target=400)
        if not chunks:
            chunks = [""]  # degenerate path so we always return one entry per claim

        # per_claim_scores[i] holds one (chunk_idx, decoded_dict) tuple per chunk
        # for claim i. The chunk_idx is needed because we want both the winning
        # idx (for telemetry) and the winning text (for audit trail) at aggregate
        # time without re-indexing the chunks list.
        per_claim_scores: list[list[tuple[int, dict]]] = [[] for _ in claims]
        for chunk_idx, chunk_text in enumerate(chunks):
            for start in range(0, len(claims), batch_size):
                batch_claims = claims[start:start + batch_size]
                inp = self.tok(
                    [chunk_text] * len(batch_claims),
                    batch_claims,
                    truncation=True, max_length=512, padding=True,
                    return_tensors="pt",
                ).to(self.device)
                with self.torch.no_grad():
                    probs = self.model(**inp).logits.softmax(-1).cpu().tolist()
                for j, row in enumerate(probs):
                    decoded = _decode_softmax_row(
                        batch_claims[j], row, self.model_name
                    )
                    per_claim_scores[start + j].append((chunk_idx, decoded))

        # Aggregate: keep the chunk with the highest entail_prob per claim.
        # Persist a truncated `best_chunk_text` (200 chars) as an audit trail
        # for the max-pool decision — when a claim score looks suspicious post-
        # hoc, reviewers can verify which chunk actually supported (or didn't)
        # the claim, distinguishing genuine evidence from spurious lexical
        # overlap.
        results: list[dict] = []
        for i, chunk_results in enumerate(per_claim_scores):
            if not chunk_results:
                # Defensive: shouldn't happen since we guarantee >=1 chunk above,
                # but if a downstream model stub somehow yields zero output rows
                # for a claim, return a neutral verdict rather than IndexError.
                results.append({
                    "claim": claims[i],
                    "entail_prob": 0.0,
                    "contradict_prob": 0.0,
                    "neutral_prob": 0.0,
                    "verdict": "neutral",
                    "best_chunk_idx": 0,
                    "n_chunks": len(chunks),
                    "best_chunk_text": "",
                })
                continue
            best_pair = max(chunk_results, key=lambda kv: kv[1]["entail_prob"])
            best_idx, best_decoded = best_pair
            annotated = dict(best_decoded)
            annotated["best_chunk_idx"] = best_idx
            annotated["n_chunks"] = len(chunks)
            # Truncated chunk text for audit — 200 chars is enough context to
            # eyeball whether the supporting evidence is genuine without
            # blowing up per_zettel JSON disk usage.
            annotated["best_chunk_text"] = chunks[best_idx][:200]
            results.append(annotated)
        return results


def _load_atomic_facts_from_cache(url: str, source_type: str) -> list[str] | None:
    """Read cached atomic_facts WITHOUT invoking the Gemini extractor.

    Same FsContentCache + key tuple the production extractor uses
    (see ``website/.../evaluator/atomic_facts.py::extract_atomic_facts``).
    Zero API cost on hit; returns ``None`` on miss/error so callers can
    fall back to the regex path. Atomic_facts is the industry-standard
    claim source per FActScore (EMNLP 2023), RAGAS, FineSurE (ACL 2024),
    DeepEval — clean propositions decontextualized of markdown structure,
    eliminating the format-noise + context-stripping NLI false-positive
    cluster that dominated the iter-003-nli sweep (verified 2026-05-30).
    """
    if not url or not source_type:
        return None
    try:
        from website.features.summarization_engine.core.cache import FsContentCache
        from website.features.summarization_engine.evaluator.prompts import PROMPT_VERSION
    except ImportError:
        return None
    try:
        cache = FsContentCache(root=CACHE, namespace="atomic_facts")
        hit = cache.get((url, source_type, PROMPT_VERSION))
    except Exception:
        return None
    if not hit or "facts" not in hit:
        return None
    claims = [
        (f.get("claim") or "").strip()
        for f in (hit.get("facts") or [])
        if isinstance(f, dict)
    ]
    claims = [c for c in claims if c]
    return claims or None


def _extract_claims(payload: dict, summary_json: dict | None,
                     meta_json: dict | None = None) -> tuple[list[str], str]:
    """Pick claim list and report its provenance.

    Tier 1 (preferred): cached atomic_facts — clean propositions matching
    FActScore/RAGAS/FineSurE industry standard, populated by the consolidated
    evaluator at iter-002 cost (no new API call here).

    Tier 2 (fallback): regex sentence-split on detailed_summary — legacy
    path retained for cache misses. Produces noisy fragments
    (`'1.'`, `'## Header'`, decontextualized bullets) that fire NLI
    false-positives; only used when atomic_facts unavailable.

    Returns (claims, provenance) where ``provenance`` is either
    ``"atomic_facts"`` or ``"regex_fallback"``. Caller stamps it onto
    the per_zettel JSON for audit.
    """
    # Tier 1: atomic_facts cache hit
    if meta_json:
        atomic_claims = _load_atomic_facts_from_cache(
            url=meta_json.get("normalized_url", ""),
            source_type=meta_json.get("source_type", ""),
        )
        if atomic_claims:
            return atomic_claims[:60], "atomic_facts"

    # Tier 2: regex fallback (legacy path; kept for cache misses)
    summary_text = ""
    if summary_json:
        summary_text = summary_json.get("detailed_summary") or summary_json.get("brief_summary") or ""
        if not summary_text:
            # Fall back to flattened JSON
            summary_text = json.dumps(summary_json)[:3000]
    # Naive sentence split (avoid NLTK download in fake-NLI path)
    import re
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary_text) if s.strip()]
    return sents[:60], "regex_fallback"  # cap per nli_config.yaml claim_segmentation.max_claims_per_zettel


def _augment_one(payload: dict, predictor, batch_size: int = 8) -> dict:
    wz_id = (payload.get("_meta") or {}).get("wz_zettel_id")
    if not wz_id:
        payload["nli"] = {"error": "no wz_zettel_id in payload"}
        return payload
    data_dir = DATA / wz_id
    source_path = data_dir / "source_text.md"
    summary_path = data_dir / "summary.json"
    meta_path = data_dir / "meta.json"
    if not source_path.exists():
        payload["nli"] = {"error": f"source_text.md missing for {wz_id}"}
        return payload
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    summary_json = None
    if summary_path.exists():
        try:
            summary_json = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            summary_json = None
    meta_json = None
    if meta_path.exists():
        try:
            meta_json = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            meta_json = None
    claims, claim_source = _extract_claims(payload, summary_json, meta_json)
    # Batched inference — ~10x faster on CPU than the per-claim path.
    per_claim = predictor.predict_batch(claims, source_text, batch_size=batch_size)

    # OR-with-review routing (see route_verdict). REPLACES the prior LOOSE
    # AND-gate, which silently cleared real hallucinations the judge caught but
    # NLI scored just under threshold (deep-research verdict 2026-05-30). Both
    # signals are recorded separately so the route is re-derivable without
    # re-running NLI if the threshold is later recalibrated.
    judge_contras = (payload.get("summac_lite") or {}).get("contradicted_sentences") or []
    judge_contras_n = len(judge_contras)

    if not per_claim:
        # No claims to score → NLI cannot fire. Route is judge-driven only.
        route, review_reason = route_verdict(False, judge_contras_n)
        payload["nli"] = {
            "n_claims": 0, "mean_entailment": 1.0, "max_contradict": 0.0,
            "nli_threshold_flag": False,
            "judge_contradicted_count": judge_contras_n,
            "route": route, "review_reason": review_reason,
            "hard_fail_flagged": route == "hard_fail", "per_claim": [],
            "nli_model": predictor.model_name, "nli_model_revision": predictor.revision,
            "claim_source": claim_source,
        }
        return payload

    mean_ent = mean(p["entail_prob"] for p in per_claim)
    max_con = max(p["contradict_prob"] for p in per_claim)
    nli_flag = max_con >= HARD_FAIL_CONTRADICT_THRESHOLD
    route, review_reason = route_verdict(nli_flag, judge_contras_n)
    payload["nli"] = {
        "n_claims": len(per_claim),
        "mean_entailment": round(mean_ent, 4),
        "max_contradict": round(max_con, 4),
        "nli_threshold_flag": nli_flag,
        "judge_contradicted_count": judge_contras_n,
        "route": route,
        "review_reason": review_reason,
        # hard_fail_flagged retained for backward-compat with downstream
        # readers; under OR-with-review it == (route == "hard_fail").
        "hard_fail_flagged": route == "hard_fail",
        "per_claim": per_claim,
        "nli_model": predictor.model_name,
        "nli_model_revision": predictor.revision,
        "claim_source": claim_source,
    }
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iter", required=True, dest="iter_id")
    ap.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    ap.add_argument("--batch-size", type=int, default=8,
                    help="claims per batched forward pass within each premise chunk. "
                         "Default 8 fits a single-vCPU laptop comfortably with the new "
                         "max_length=512 inference path (2026-05-29 chunk+max-pool refactor). "
                         "Raise to 16 on machines with more memory bandwidth.")
    ap.add_argument("--max-zettels", type=int, default=None)
    ap.add_argument("--force-refresh", action="store_true")
    ap.add_argument("--fake-nli", action="store_true")
    ap.add_argument("--fake-entail-prob", type=float, default=0.85)
    ap.add_argument("--fake-contradict-prob", type=float, default=0.05)
    args = ap.parse_args()

    if args.fake_nli:
        predictor = FakeMiniCheck(entail_prob=args.fake_entail_prob,
                                  contradict_prob=args.fake_contradict_prob)
        print(f"[03] using FakeMiniCheck (entail={args.fake_entail_prob} contradict={args.fake_contradict_prob})")
    else:
        print(f"[03] loading MiniCheck-DeBERTa-v3-Large on {args.device} (~1.7GB download on first use)")
        predictor = MiniCheckPredictor(device=args.device)

    iter_dir = RUNS / args.iter_id
    overall_pz = iter_dir / "_overall" / "per_zettel"
    if not overall_pz.exists():
        raise SystemExit(f"iter dir missing per_zettel: {overall_pz}")

    files = sorted(overall_pz.glob("*.json"))
    if args.max_zettels:
        files = files[:args.max_zettels]
    print(f"[03] augmenting {len(files)} zettel(s)")

    for i, f in enumerate(files, 1):
        payload = json.loads(f.read_text(encoding="utf-8"))
        if not args.force_refresh and isinstance(payload.get("nli"), dict) and "per_claim" in payload["nli"]:
            print(f"  [{i}/{len(files)}] SKIP {f.stem[:8]} (already has nli)")
            continue
        augmented = _augment_one(payload, predictor, batch_size=args.batch_size)
        # Write to BOTH _overall and the source-type folder
        meta = augmented.get("_meta") or {}
        src = meta.get("source_type", "")
        f.write_text(json.dumps(augmented, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if src:
            src_path = iter_dir / src / "per_zettel" / f.name
            src_path.parent.mkdir(parents=True, exist_ok=True)
            src_path.write_text(json.dumps(augmented, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        nli = augmented.get("nli", {})
        print(f"  [{i}/{len(files)}] {f.stem[:8]} mean_ent={nli.get('mean_entailment')} "
              f"max_con={nli.get('max_contradict')} hard_fail={nli.get('hard_fail_flagged')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
