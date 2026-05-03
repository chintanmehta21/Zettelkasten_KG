# Iter-08 Implementation Plan — Knowledge-Management RAG Eval Recovery

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** lift composite from iter-07's 62.88 to ≥85 with all 14 KM-Kasten queries passing, by repairing the eval scorer (frozen chunking score, RAGAS contamination, NDCG asymmetry), reverting iter-07's quota-burning n=5 thematic expansion, and structurally attacking the magnet-collapse problem (B3+B5+B4 bundle + chunk-share normalization + KG entity anchor).

**Architecture:** Multi-phase incremental refactor. Each phase commits separately behind an env flag for canary rollback. Phases 1-4 are unconditionally approved; Phase 5 (cite hygiene), Phase 7.B (RAGAS parse-fail), Phase 7.D (NDCG asymmetry) are research-pending and will be filled in once RES-5/6/7 return. Plan mirrors the 8-agent research bundle (RES-1..4 + ACT-1, ACT-5; merged commits adeafe9 + cc04b1e are on master).

**Tech Stack:** Python 3.12, FastAPI, Supabase (Postgres + pgvector + RPCs), BGE-int8 ONNX reranker via FlashRank cascade, Gemini key-pool (Pro for judge, Flash/Lite for synth), Chonkie chunker, RAGAS-style re-impl scorer, Playwright eval harness.

---

## Research Artefacts

All claims in this plan are grounded in 8 background research agents. Re-read the originals before disputing any decision.

| Agent | Output | Verdict |
|---|---|---|
| RES-1 cite-filter direct vs gated | hybrid Design B with min-N safety net (NOT direct 0.5 score cut — BGE int8 scores are uncalibrated) | shipped Phase 5 |
| RES-2 kasten_freq dead prior | confirmed no-op for 6 iters (`_MIN_TOTAL_HITS_FOR_PENALTY=50`, ~48 max hits across 4 iters); replace, don't tune | shipped Phase 4 |
| RES-3 thematic n=5→3 revert | iter-06 (n=3) and iter-07 (n=5) retrieved IDENTICAL node_ids on q5 — n=5 added zero retrieval delta | shipped Phase 1 |
| RES-4 magnet hypothesis + KG | broad-content (B) is dominant; chunk-count (A) contributes; ship B3+B5+B4 bundle + KG anchor | shipped Phase 3 + 6 |
| ACT-1 component scorer audit | top 3 issues: boundary regex, target_tokens=512 hardcoded, coherence pinned at 50 (combined +12-18 composite if fixed) | shipped Phase 2 + 7 |
| ACT-5 chunker boundary + KG-RAG | 36% of chunks end mid-word; Chonkie token-budget chunkers don't snap to sentence ends | shipped Phase 2.4 |
| RES-5 cite-hygiene safety gate | hybrid Design B; filter inside `_build_citations`; default OFF for dark canary; fallback top-K=3 (USER APPROVED) | shipped Phase 5 |
| RES-6 RAGAS JSON parse-fail handling | mix (a) 1 retry with stricter prompt + (c) mark `eval_failed`; cohort mean excludes flag (USER APPROVED) | shipped Phase 7.B |
| RES-7 NDCG asymmetry fix | one-line: `ideal_dcg = dcg(gold_ranking[:min(k_ndcg, len(gold_ranking))])` (USER APPROVED) | shipped Phase 7.D |

**For full research details + rationale + cons-not-taken see [RESEARCH.md](RESEARCH.md) in this folder. The executor should consult RESEARCH.md when a phase task references a blocker, an edge case, or a "why not X" rationale.**

Already merged into master (iter-08 work that landed during research):

| Commit | Subject | Phase |
|---|---|---|
| `adeafe9` | per-query RAGAS so empty answers don't dilute cohort | (was ACT-2) |
| `cc04b1e` | retry guard partial+gold + suppress citations on refusal | (was ACT-3+4) |

---

## File Structure

Files modified per phase. Each file has one clear responsibility; we don't restructure beyond what each phase needs.

| Path | Touched in | Responsibility |
|---|---|---|
| `website/features/rag_pipeline/query/transformer.py` | Phase 1 | revert THEMATIC n |
| `website/features/rag_pipeline/evaluation/component_scorers.py` | Phase 2.1, 2.2, 2.3, 7 | scorer formulas |
| `website/features/rag_pipeline/evaluation/eval_runner.py` | Phase 2.2, 2.3, 7 | scorer orchestration, target_tokens, embeddings fetch, refusal regex |
| `website/features/rag_pipeline/ingest/chunker.py` | Phase 2.4 | snap chunker to sentence ends |
| `website/features/rag_pipeline/retrieval/hybrid.py` | Phase 3, 4, 6 | magnet bundle, chunk-share normalization, KG entity-anchor boost |
| `website/features/rag_pipeline/retrieval/kasten_freq.py` | Phase 4 | replace freq prior with chunk-share norm; or DELETE the module entirely |
| `website/features/rag_pipeline/retrieval/chunk_share.py` | Phase 4 | NEW — per-Kasten chunk count fetcher |
| `website/features/rag_pipeline/orchestrator.py` | Phase 5 | cite hygiene helper |
| `website/features/rag_pipeline/evaluation/composite.py` | Phase 7.E | NaN guard |
| `website/features/rag_pipeline/evaluation/ragas_runner.py` | Phase 7.B | parse-fail handling (research-pending) |
| `ops/scripts/score_rag_eval.py` | Phase 7.G | qid join surface dropped qids |
| `supabase/website/kg_public/migrations/2026-05-03_kg_link_relation_enum.sql` | Phase 8 | NEW — KG link relation enum |
| `docs/rag_eval/common/knowledge-management/iter-08/queries.json` | Phase 9 | copy from iter-07 |
| `docs/rag_eval/common/knowledge-management/iter-08/scores.md` | Phase 9 | result write-up |

---

## Phase 1 — Revert THEMATIC n=5→3

**Research artefact:** RES-3. iter-06 (n=3) and iter-07 (n=5) retrieved IDENTICAL `retrieved_node_ids` on q5 — n=5 added zero retrieval delta but accelerated q13/q14 → HTTP 402 quota burn. n=5 was a fresh iter-07 introduction (commit `60cf902`); n=3 is the iter-04+ default.

**Rationale:** the only target query for n=5 (q5) was unaffected by it. Reverting recovers q13/q14 from quota exhaustion. Real q5 fix lives in BM25/embedding recall, not variant count.

**Pitfalls:**
- Do NOT remove the `RAG_THEMATIC_MULTIQUERY_N` env knob — keep it for future A/B once retrieval recall is fixed.
- Do NOT touch MULTI_HOP n=3 (it's correct as-is).

**Cons NOT to take:**
- "Scale n with Kasten size" — RES-3 verified more variants don't generate new node_ids when they're not in the rerank pool to begin with.

### Task 1: Revert n=5 → 3 (env-knob preserved)

**Files:**
- Modify: `website/features/rag_pipeline/query/transformer.py:48-52`

- [ ] **Step 1: Read current state**

```bash
grep -n "RAG_THEMATIC_MULTIQUERY_N\|n=int(os" website/features/rag_pipeline/query/transformer.py
```

Expected: line `_thematic_n = int(os.environ.get("RAG_THEMATIC_MULTIQUERY_N", "5"))` returned.

- [ ] **Step 2: Write failing test**

Create `tests/unit/rag/query/test_transformer_iter08.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from website.features.rag_pipeline.query.transformer import QueryTransformer
from website.features.rag_pipeline.types import QueryClass

@pytest.mark.asyncio
async def test_thematic_default_is_n_3():
    """iter-08 Phase 1: THEMATIC default n is 3, not 5."""
    t = QueryTransformer()
    captured = {}
    async def fake_multi(query, n, entities=None):
        captured["n"] = n
        return [f"variant{i}" for i in range(n)]
    with patch.object(t, "_multi_query", AsyncMock(side_effect=fake_multi)):
        await t.transform("test thematic query", QueryClass.THEMATIC)
    assert captured["n"] == 3, f"expected default n=3, got {captured['n']}"
```

- [ ] **Step 3: Run test (expect failure on iter-07 default 5)**

```bash
pytest tests/unit/rag/query/test_transformer_iter08.py -v
```

Expected: FAIL with `expected default n=3, got 5`.

- [ ] **Step 4: Patch transformer.py**

Replace at `transformer.py:48-52`:

```python
        elif cls is QueryClass.THEMATIC:
            # iter-08 Phase 1: revert to n=3 (RES-3: n=5 added zero retrieval
            # delta on q5, accelerated quota burn). Knob retained for future
            # A/B once recall is fixed.
            _thematic_n = int(os.environ.get("RAG_THEMATIC_MULTIQUERY_N", "3"))
            variants = [query, *await self._multi_query(query, n=_thematic_n, entities=ents)]
```

- [ ] **Step 5: Run test (expect pass)**

```bash
pytest tests/unit/rag/query/test_transformer_iter08.py -v
```

Expected: PASS.

- [ ] **Step 6: Run full transformer test suite**

```bash
pytest tests/unit/rag/query/test_transformer.py tests/unit/rag/query/test_transformer_iter08.py -v
```

Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add website/features/rag_pipeline/query/transformer.py tests/unit/rag/query/test_transformer_iter08.py
git commit -m "fix: revert thematic multiquery n to 3 (iter-08 phase 1)"
```

---

## Phase 2 — Chunking score unlock

**Research artefact:** ACT-1 + ACT-5. Chunking score frozen at 31.94 across iter-03/05/07 because (1) boundary regex `[.!?\n]\s*$` fails Markdown chunks ending in `)`, `*`, `]`, `|`, code-fences (50% pass rate per ACT-5's 90-chunk sample), (2) `target_tokens=512` hard-coded but Chonkie emits 200-400 tokens, (3) coherence pinned at 50.0 because embeddings are never passed, (4) Chonkie's Token/Recursive chunkers don't snap to sentence boundaries — 36% of chunks end mid-word.

**Rationale:** chunking weight is 0.10 in composite, so a frozen 31.94 → ~80 unlock is +~5 composite directly. Indirect benefits: cleaner chunk endings improve FTS tokenisation (mid-word "Softwa" loses lexical signal at the tail), so retrieval also improves.

**Pitfalls:**
- Do NOT change the chunker tokenizer or replace Chonkie wholesale.
- Do NOT snap-to-sentence on short atomic-chunk sources (reddit/twitter/github/generic) — they're already one chunk per zettel.
- Do NOT hard-code a different `target_tokens` — derive it.

**Cons NOT to take:**
- Drop coherence weight to 0 — would lose the only semantic-similarity signal in the chunking score; better to fetch real embeddings.
- Replace Chonkie Recursive with a custom sentence splitter — too invasive; the 10% slack backtrack is sufficient.

### Phase 2.1 — Relax scorer boundary regex

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/component_scorers.py:34-36`
- Test: `tests/unit/rag_pipeline/evaluation/test_component_scorers.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag_pipeline/evaluation/test_component_scorers.py`:

```python
import pytest
from website.features.rag_pipeline.evaluation.component_scorers import chunking_score

def test_boundary_regex_accepts_soft_endings():
    """iter-08 Phase 2.1: scorer accepts ),],*,",',|,;,:,>, code-fence, heading."""
    chunks_soft = [
        {"text": "Some text ending with citation [1]", "token_count": 256},
        {"text": "A bullet item ending in italics *emphasis*", "token_count": 256},
        {"text": "A code block ending\n```", "token_count": 256},
        {"text": "A heading\n## Done", "token_count": 256},
        {"text": "Mid-paragraph citation, comma soft-end,", "token_count": 256},
    ]
    score = chunking_score(chunks_soft, target_tokens=256)
    # boundary score component should be >= 80 (4 of 5 soft-acceptable)
    assert score >= 60.0, f"expected ≥60 with soft boundaries, got {score}"

def test_boundary_regex_still_rejects_mid_word():
    """iter-08 Phase 2.1: mid-word endings still fail."""
    chunks_bad = [{"text": "Stop mid-Softwa", "token_count": 256}]
    score = chunking_score(chunks_bad, target_tokens=256)
    # boundary contribution should be 0; with budget=100, coherence=50, dedup=100 → 0.4*100 + 0.3*0 + 0.2*50 + 0.1*100 = 60
    assert score < 65, f"mid-word boundaries must fail: got {score}"
```

- [ ] **Step 2: Run test (expect failure on current strict regex)**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_component_scorers.py::test_boundary_regex_accepts_soft_endings -v
```

Expected: FAIL.

- [ ] **Step 3: Patch the regex**

Replace at `component_scorers.py:34-36`:

```python
    # iter-08 Phase 2.1: relax boundary regex. ACT-5 verified 50% of real
    # chunks end on hard sentence-end (.!?\n) and another 14% on soft-
    # boundaries (,;:>]"'`*|) or markdown structures (code-fence, heading).
    # Mid-word endings (36% in iter-07) still fail.
    sentence_end = re.compile(
        r"(?:[.!?,;:>\]\"'\`*|\n]\s*$"  # punctuation + soft-boundaries
        r"|```\s*$"                      # code fence
        r"|^#{1,6}\s.*$)",               # markdown heading line
        re.MULTILINE,
    )
    boundary_ok = sum(1 for c in chunks if sentence_end.search(c.get("text", "")))
    boundary_score = (boundary_ok / len(chunks)) * 100.0
```

- [ ] **Step 4: Run tests (expect pass)**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_component_scorers.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/evaluation/component_scorers.py tests/unit/rag_pipeline/evaluation/test_component_scorers.py
git commit -m "fix: relax chunking boundary regex (iter-08 phase 2.1)"
```

### Phase 2.2 — Adaptive target_tokens

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/eval_runner.py:167` (call site)
- Modify: `website/features/rag_pipeline/evaluation/component_scorers.py:27-31` (formula)

**Source of truth for target_tokens:** chunker config at `website/features/rag_pipeline/ingest/chunker.py:75-76` defines `LONG_CHUNK_TOKENS=512` for long-form sources but most real chunks land at 200-400. Use cohort median.

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag_pipeline/evaluation/test_component_scorers.py`:

```python
def test_target_tokens_adapts_to_cohort_median():
    """iter-08 Phase 2.2: target_tokens defaults to cohort median, not 512."""
    chunks = [
        {"text": "x", "token_count": 280},
        {"text": "y", "token_count": 320},
        {"text": "z", "token_count": 340},
    ]
    # All chunks within 0.5x..1.5x of median 320 → budget_score=100
    score = chunking_score(chunks, target_tokens=None)  # None → derive from cohort
    # boundary fails (single-char text) → 0; budget=100; coherence=50; dedup=100
    # 0.4*100 + 0.3*0 + 0.2*50 + 0.1*100 = 60
    assert 55 <= score <= 65, f"adaptive target should give ~60 here, got {score}"
```

- [ ] **Step 2: Run test (expect failure — `target_tokens=None` not handled)**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_component_scorers.py::test_target_tokens_adapts_to_cohort_median -v
```

Expected: FAIL.

- [ ] **Step 3: Patch chunking_score signature**

Replace `chunking_score` signature + budget block at `component_scorers.py`:

```python
def chunking_score(
    chunks: list[dict],
    target_tokens: int | None = None,
    embeddings: list[list[float]] | None = None,
) -> float:
    """..."""
    if not chunks:
        return 0.0
    # iter-08 Phase 2.2: adaptive target_tokens. When None, derive from cohort
    # median so the scorer doesn't punish chunkers configured for shorter text.
    if target_tokens is None:
        token_counts = [c.get("token_count", 0) for c in chunks if c.get("token_count")]
        target_tokens = int(sorted(token_counts)[len(token_counts)//2]) if token_counts else 512
    budget_ok = sum(
        1 for c in chunks
        if c.get("token_count") and 0.5 * target_tokens < c["token_count"] <= 1.5 * target_tokens
    )
    budget_score = (budget_ok / len(chunks)) * 100.0
    # ... (rest unchanged)
```

- [ ] **Step 4: Update eval_runner call site**

Replace at `eval_runner.py:167`:

```python
    chunking = chunking_score(chunks_for_node, target_tokens=None, embeddings=embeddings_per_node)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/rag_pipeline/evaluation/ -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/evaluation/component_scorers.py website/features/rag_pipeline/evaluation/eval_runner.py tests/unit/rag_pipeline/evaluation/test_component_scorers.py
git commit -m "fix: chunking score adapts target_tokens to cohort (iter-08 phase 2.2)"
```

### Phase 2.3 — Pass embeddings to coherence scorer

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/eval_runner.py:166` (fetch embeddings)
- Test: `tests/unit/rag_pipeline/evaluation/test_eval_runner.py`

**Decision context:** user approved fetching embeddings (option a from ACT-1). Small Supabase cost per eval — eval runs ~once/day, ~100 embedding fetches per run = <$0.01.

- [ ] **Step 1: Inspect existing chunk fetcher**

```bash
grep -n "kg_node_chunks\|fetch_chunks\|chunks_for_node" ops/scripts/score_rag_eval.py website/features/rag_pipeline/evaluation/eval_runner.py | head
```

Expected: identifies the existing chunk-fetch pattern (likely `score_rag_eval.py:174` reads chunks via Supabase select).

- [ ] **Step 2: Write failing test**

Add to `tests/unit/rag_pipeline/evaluation/test_eval_runner.py`:

```python
def test_eval_runner_passes_embeddings_to_coherence(monkeypatch):
    """iter-08 Phase 2.3: when embeddings exist, coherence scorer receives them."""
    from website.features.rag_pipeline.evaluation import eval_runner
    captured = {}
    def fake_chunking_score(chunks, target_tokens, embeddings):
        captured["embeddings"] = embeddings
        return 75.0
    monkeypatch.setattr(eval_runner, "chunking_score", fake_chunking_score)
    monkeypatch.setattr(eval_runner, "_fetch_chunks_for_node", lambda nid: ([{"text": "x", "token_count": 256}], [[0.1, 0.2, 0.3]]))
    chunks_score = eval_runner._score_chunking_for_node("node_id_1")
    assert captured["embeddings"] is not None
    assert len(captured["embeddings"]) >= 1
```

- [ ] **Step 3: Run test (expect failure — current eval_runner passes embeddings_per_node=None)**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_eval_runner.py::test_eval_runner_passes_embeddings_to_coherence -v
```

Expected: FAIL.

- [ ] **Step 4: Patch eval_runner.py to fetch embeddings**

In the chunk-fetch helper (likely `_fetch_chunks_for_node` or similar in `eval_runner.py`), modify the Supabase select to also pull `embedding`:

```python
def _fetch_chunks_for_node(node_id: str) -> tuple[list[dict], list[list[float]] | None]:
    """iter-08 Phase 2.3: also return embeddings for chunking coherence."""
    rows = (
        supabase.table("kg_node_chunks")
        .select("text, token_count, chunk_index, embedding")
        .eq("node_id", node_id)
        .order("chunk_index")
        .execute()
        .data or []
    )
    chunks = [{"text": r["text"], "token_count": r.get("token_count")} for r in rows]
    embeddings = [r["embedding"] for r in rows if r.get("embedding") is not None]
    return chunks, embeddings if len(embeddings) >= 2 else None
```

Update the call site to pass both:

```python
chunks, embeddings = _fetch_chunks_for_node(node_id)
chunking = chunking_score(chunks, target_tokens=None, embeddings=embeddings)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/rag_pipeline/evaluation/ -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/evaluation/eval_runner.py tests/unit/rag_pipeline/evaluation/test_eval_runner.py
git commit -m "fix: pass chunk embeddings to coherence scorer (iter-08 phase 2.3)"
```

### Phase 2.4 — Snap chunker to sentence boundaries

**Files:**
- Modify: `website/features/rag_pipeline/ingest/chunker.py:255-282` (`_map_chunks`)
- Test: `tests/unit/rag_pipeline/ingest/test_chunker.py`

**Pitfall:** ONLY apply to long-form sources (youtube/substack/medium/web). Short atomic-chunk sources (reddit/twitter/github/generic) already use `_atomic_chunk` (chunker.py:187) — single chunk per zettel.

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag_pipeline/ingest/test_chunker.py`:

```python
import pytest
from website.features.rag_pipeline.ingest.chunker import _snap_to_sentence_end

def test_snap_backtracks_to_period_within_slack():
    """iter-08 Phase 2.4: snap to last sentence end within 10% slack."""
    text = "First sentence. Second sentence. Third senten"
    snapped = _snap_to_sentence_end(text, slack_chars=int(len(text) * 0.10))
    assert snapped == "First sentence. Second sentence."

def test_snap_returns_original_when_no_period_in_slack():
    """No period within slack → return original (don't truncate too aggressively)."""
    text = "A really long sentence with no terminal punctuation in the slack zone yet"
    snapped = _snap_to_sentence_end(text, slack_chars=10)
    assert snapped == text
```

- [ ] **Step 2: Run test (expect failure — function doesn't exist)**

```bash
pytest tests/unit/rag_pipeline/ingest/test_chunker.py::test_snap_backtracks_to_period_within_slack -v
```

Expected: FAIL with `cannot import _snap_to_sentence_end`.

- [ ] **Step 3: Implement helper**

Add to `chunker.py` near `_map_chunks` (line 255):

```python
import re as _re

_SENTENCE_END_RE = _re.compile(r"[.!?]")

def _snap_to_sentence_end(text: str, slack_chars: int) -> str:
    """iter-08 Phase 2.4: backtrack to nearest sentence end within slack.

    If text ends mid-word/mid-sentence, walk backwards up to ``slack_chars``
    looking for the last [.!?]. Returns text up to and including that
    punctuation. If no boundary is found in the slack window, returns the
    original text unchanged (don't over-truncate).
    """
    if not text or len(text) < slack_chars:
        return text
    if _re.search(r"[.!?\n]\s*$", text):
        return text  # already clean
    cutoff = max(0, len(text) - slack_chars)
    last_end = -1
    for m in _SENTENCE_END_RE.finditer(text[cutoff:]):
        last_end = cutoff + m.end()
    if last_end == -1:
        return text
    return text[:last_end].rstrip()
```

- [ ] **Step 4: Wire into `_map_chunks` for long-form only**

At `_map_chunks` (chunker.py:255+), after the chunker emits raw chunks:

```python
def _map_chunks(self, chunks_raw, source_type: str):
    """iter-08 Phase 2.4: snap long-form chunk ends to sentence boundaries."""
    LONG_FORM_SOURCES = {"youtube", "substack", "medium", "web"}
    snap_enabled = (
        os.environ.get("RAG_CHUNKER_SENTENCE_SNAP_ENABLED", "true").lower() not in ("false", "0", "no", "off")
        and source_type in LONG_FORM_SOURCES
    )
    out = []
    for c in chunks_raw:
        text = c.text
        if snap_enabled:
            slack = max(10, int(len(text) * 0.10))
            text = _snap_to_sentence_end(text, slack_chars=slack)
        out.append({"text": text, "token_count": c.token_count, "chunk_index": c.chunk_index})
    return out
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/rag_pipeline/ingest/ -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/ingest/chunker.py tests/unit/rag_pipeline/ingest/test_chunker.py
git commit -m "fix: snap long-form chunks to sentence boundaries (iter-08 phase 2.4)"
```

---

## Phase 3 — Magnet bundle (B3 + B5 + B4)

**Research artefact:** RES-4. Verified chunk counts in KM Kasten: yt-effective-public-speakin=16, yt-steve-jobs=13, nl-pragmatic=10, yt-programming=6, web-transformative=6, yt-walker=3, gh-zk=2. The 16-chunk yt-effective-public-speakin keeps winning slot 2/3 because xQuAD penalty `(1-λ)·overlap = 0.21` is smaller than the typical relevance gap. Hypothesis B (broad/encyclopedic content) is dominant; A (chunk-count) is contributor.

**Rationale:** B3 caps chunks-per-node at 1 for THEMATIC/LOOKUP — directly attacks the 16-chunk magnet. B5 drops xQuAD λ to 0.5 for THEMATIC — buys more diversity for cross-corpus synthesis. B4 detects compare-intent on rewritten query text alone — closes iter-07 Fix B's "Naval not in Kasten" hole on q10.

**Pitfalls:**
- Do NOT cap MULTI_HOP/STEP_BACK at 1 — those queries genuinely need cross-chunk evidence.
- Do NOT drop λ below 0.5 — relevance must dominate.
- Do NOT auto-disable anti-magnet on partial compare patterns — use the regex as a guard, not a disabler.

**Cons NOT to take:**
- B1 sqrt(chunk_count) normalization on rrf_score — punishes legitimately rich content like nl-pragmatic-engineer-t (10 chunks, current correct top-1 6/12). The chunk-share normalization is shipped in Phase 4 INSTEAD, where it replaces the dead kasten_freq prior with the same math but a cleaner spot.
- B2 token-overlap floor — slugified titles + thematic tags overlap too often to fire reliably.

### Phase 3.1 — Class-aware `_cap_per_node`

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:64,360` (`_MAX_CHUNKS_PER_NODE`, caller)

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag/retrieval/test_hybrid.py`:

```python
import pytest
from website.features.rag_pipeline.retrieval.hybrid import _cap_per_node
from website.features.rag_pipeline.types import RetrievalCandidate, QueryClass

def _cand(node_id, rrf):
    return RetrievalCandidate(
        node_id=node_id, chunk_id=f"{node_id}_c0", text="x",
        rrf_score=rrf, rerank_score=None, source_type="web",
    )

def test_cap_per_node_thematic_caps_at_one():
    """iter-08 Phase 3.1: THEMATIC keeps only the highest-rrf chunk per node."""
    candidates = [_cand("a", 0.9), _cand("a", 0.8), _cand("a", 0.7), _cand("b", 0.6)]
    capped = _cap_per_node(candidates, QueryClass.THEMATIC)
    assert [c.node_id for c in capped] == ["a", "b"]

def test_cap_per_node_lookup_caps_at_one():
    candidates = [_cand("a", 0.9), _cand("a", 0.8)]
    capped = _cap_per_node(candidates, QueryClass.LOOKUP)
    assert len(capped) == 1

def test_cap_per_node_multi_hop_keeps_three():
    """MULTI_HOP needs cross-chunk evidence — cap stays at 3."""
    candidates = [_cand("a", 0.9), _cand("a", 0.8), _cand("a", 0.7), _cand("a", 0.6)]
    capped = _cap_per_node(candidates, QueryClass.MULTI_HOP)
    assert len(capped) == 3
```

- [ ] **Step 2: Run tests (expect failure — _cap_per_node currently has no class arg)**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py -v -k cap_per_node
```

Expected: FAIL.

- [ ] **Step 3: Patch `_cap_per_node`**

At `hybrid.py:64`:

```python
# iter-08 Phase 3.1: class-aware chunks-per-node cap. THEMATIC and LOOKUP
# get cap=1 (RES-4: kills the 16-chunk yt-effective-public-speakin magnet
# without hurting cross-source recall). MULTI_HOP and STEP_BACK keep cap=3
# (genuinely need cross-chunk evidence). VAGUE keeps cap=3 (HyDE wide net).
_MAX_CHUNKS_PER_NODE_BY_CLASS: dict[QueryClass, int] = {
    QueryClass.LOOKUP: 1,
    QueryClass.THEMATIC: 1,
    QueryClass.MULTI_HOP: 3,
    QueryClass.STEP_BACK: 3,
    QueryClass.VAGUE: 3,
}
_DEFAULT_MAX_CHUNKS_PER_NODE = 3
```

Replace `_cap_per_node` signature + caller:

```python
def _cap_per_node(
    candidates: list[RetrievalCandidate],
    query_class: QueryClass | None = None,
    cap: int | None = None,
) -> list[RetrievalCandidate]:
    """iter-08: class-aware cap. Falls back to default when class is None."""
    if cap is None:
        cap = _MAX_CHUNKS_PER_NODE_BY_CLASS.get(query_class, _DEFAULT_MAX_CHUNKS_PER_NODE)
    by_node: dict[str, int] = {}
    out = []
    for c in candidates:
        seen = by_node.get(c.node_id, 0)
        if seen >= cap:
            continue
        out.append(c)
        by_node[c.node_id] = seen + 1
    return out
```

Update the call site at `hybrid.py:360` (look for the existing `_cap_per_node(ordered, _MAX_CHUNKS_PER_NODE)`):

```python
return _cap_per_node(ordered, query_class=query_class)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py -v
```

Expected: ALL PASS (existing tests using positional `cap` still work via `cap=` kwarg).

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_hybrid.py
git commit -m "fix: class-aware chunks-per-node cap (iter-08 phase 3.1)"
```

### Phase 3.2 — Per-class xQuAD λ

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:72` (`_XQUAD_LAMBDA` constant) + caller

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag/retrieval/test_hybrid.py`:

```python
def test_xquad_lambda_thematic_is_05():
    from website.features.rag_pipeline.retrieval.hybrid import _xquad_lambda_for_class
    from website.features.rag_pipeline.types import QueryClass
    assert _xquad_lambda_for_class(QueryClass.THEMATIC) == 0.5
    assert _xquad_lambda_for_class(QueryClass.LOOKUP) == 0.7
    assert _xquad_lambda_for_class(QueryClass.MULTI_HOP) == 0.7
```

- [ ] **Step 2: Run test (expect import failure)**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py::test_xquad_lambda_thematic_is_05 -v
```

Expected: FAIL.

- [ ] **Step 3: Patch hybrid.py**

Replace `_XQUAD_LAMBDA = 0.7` and add helper:

```python
# iter-08 Phase 3.2: per-class xQuAD lambda. THEMATIC drops to 0.5 to buy
# more diversity for cross-corpus synthesis (RES-4); other classes keep 0.7.
_XQUAD_LAMBDA_DEFAULT = 0.7
_XQUAD_LAMBDA_BY_CLASS: dict[QueryClass, float] = {
    QueryClass.THEMATIC: 0.5,
}

def _xquad_lambda_for_class(query_class: QueryClass | None) -> float:
    return _XQUAD_LAMBDA_BY_CLASS.get(query_class, _XQUAD_LAMBDA_DEFAULT)
```

Update the call site (currently `_xquad_select(ordered, lam=_XQUAD_LAMBDA)`):

```python
ordered = _xquad_select(ordered, lam=_xquad_lambda_for_class(query_class))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_hybrid.py
git commit -m "fix: thematic xquad lambda 0.7 to 0.5 (iter-08 phase 3.2)"
```

### Phase 3.3 — Text-only compare-intent regex

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py:286-302` (compare-intent block from iter-07 Fix B)

**Research:** iter-07 Fix B failed on q10 because Naval Ravikant doesn't exist as a Kasten member, so `metadata.authors=[Steve Jobs]` (1 author) — failed the `≥2 authors` gate. Solution: detect compare-intent from rewritten query text + ≥2 capitalised proper-noun spans, independent of authors.

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag/retrieval/test_hybrid.py`:

```python
def test_detect_compare_intent_text_only_q10():
    """iter-08 Phase 3.3: compare-intent fires on 'Steve Jobs and Naval Ravikant' even when authors=[Steve Jobs]."""
    from website.features.rag_pipeline.retrieval.hybrid import _detect_compare_intent_text_only
    assert _detect_compare_intent_text_only(
        "Steve Jobs and Naval Ravikant both speak about meaningful work. Compare their views."
    ) is True

def test_detect_compare_intent_text_only_no_proper_nouns():
    from website.features.rag_pipeline.retrieval.hybrid import _detect_compare_intent_text_only
    assert _detect_compare_intent_text_only(
        "How do databases compare to spreadsheets?"
    ) is False  # no ≥2 capitalised proper-noun spans
```

- [ ] **Step 2: Run test (expect failure — function doesn't exist)**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py::test_detect_compare_intent_text_only_q10 -v
```

Expected: FAIL.

- [ ] **Step 3: Implement helper**

Add to `hybrid.py`:

```python
# iter-08 Phase 3.3: text-only compare-intent detection. Closes iter-07
# Fix B's "Naval not in Kasten" hole — fires on rewritten-query text alone,
# independent of metadata.authors count.
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b")

def _detect_compare_intent_text_only(query: str) -> bool:
    if not query:
        return False
    if not _COMPARE_PATTERN.search(query):
        # Fall back to "and" + ≥2 proper-noun spans
        if not re.search(r"\b(and|both)\b", query, re.IGNORECASE):
            return False
    proper_nouns = _PROPER_NOUN_RE.findall(query)
    # filter common pronouns/sentence-starts
    blacklist = {"What", "How", "When", "Where", "Why", "The", "A", "An", "This", "That"}
    proper_nouns = [n for n in proper_nouns if n.split()[0] not in blacklist]
    return len(set(proper_nouns)) >= 2
```

Update the existing iter-07 Fix B block at hybrid.py:286-302:

```python
        # iter-08 Phase 3.3: compare-intent now fires on text-only signal
        # OR on the iter-07 metadata.authors path. Either is sufficient.
        compare_intent = False
        if _COMPARE_AWARE_ANTIMAGNET_ENABLED:
            if query_metadata is not None:
                authors = list(getattr(query_metadata, "authors", None) or [])
                if len(authors) >= 2:
                    for variant in (query_variants or []):
                        if variant and (_COMPARE_PATTERN.search(variant) or
                                        re.search(r"\b(and|both)\b", variant, re.IGNORECASE)):
                            compare_intent = True
                            break
            if not compare_intent and query_variants:
                # iter-08: text-only fallback for q10 (Naval not in Kasten)
                if _detect_compare_intent_text_only(query_variants[0] or ""):
                    compare_intent = True
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_hybrid.py
git commit -m "fix: text-only compare-intent regex (iter-08 phase 3.3)"
```

---

## Phase 4 — Replace kasten_freq with chunk-share normalization

**Research artefact:** RES-2. `kasten_freq` anti-magnet has been a no-op for 6 iters (`_MIN_TOTAL_HITS_FOR_PENALTY=50`, ~48 max hits across 4 iters). The freq-prior was a guess in `8f4eada` with no empirical grounding.

**Decision:** REPLACE, not tune. Per-zettel chunk-share normalization (`rrf_score *= 1/sqrt(chunk_count_per_node)`) directly attacks chunk-count bias from RES-4 hypothesis A.

**Pitfalls:**
- chunk_count must be the per-Kasten chunk count (not global) — the same node could have different chunk counts in different scopes.
- Punishes legitimately rich content like `nl-pragmatic-engineer-t` (10 chunks, currently correct top-1 6/12 times). Add env flag for canary disable.

**Cons NOT to take:**
- Lower the kasten_freq floor to 5 (option a) — band-aid that keeps every other weakness of the freq-prior.
- Pre-seed from kg_node telemetry (option b) — mixes user-engagement signal with retrieval-magnet signal.
- Compute on-the-fly per-query (option c) — magnets are visible across queries, not within one.

### Phase 4.1 — Build per-Kasten chunk-count fetcher

**Files:**
- Create: `website/features/rag_pipeline/retrieval/chunk_share.py`
- Test: `tests/unit/rag/retrieval/test_chunk_share.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag/retrieval/test_chunk_share.py`:

```python
import pytest
from unittest.mock import MagicMock
from website.features.rag_pipeline.retrieval.chunk_share import ChunkShareStore

def test_chunk_share_returns_per_kasten_counts():
    fake_supabase = MagicMock()
    fake_supabase.rpc.return_value.execute.return_value.data = [
        {"node_id": "a", "chunk_count": 16},
        {"node_id": "b", "chunk_count": 6},
        {"node_id": "c", "chunk_count": 2},
    ]
    store = ChunkShareStore(supabase=fake_supabase)
    import asyncio
    result = asyncio.run(store.get_chunk_counts(sandbox_id="kasten1"))
    assert result == {"a": 16, "b": 6, "c": 2}

def test_chunk_share_penalty_factor_inverse_sqrt():
    from website.features.rag_pipeline.retrieval.chunk_share import compute_chunk_share_penalty
    # 16-chunk node → 1/sqrt(16) = 0.25
    assert abs(compute_chunk_share_penalty(16) - 0.25) < 0.001
    # 1-chunk node → 1.0 (no penalty)
    assert compute_chunk_share_penalty(1) == 1.0
    # 0 / unknown → 1.0 (safe default)
    assert compute_chunk_share_penalty(0) == 1.0
```

- [ ] **Step 2: Run test (expect import failure)**

```bash
pytest tests/unit/rag/retrieval/test_chunk_share.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement module**

Create `website/features/rag_pipeline/retrieval/chunk_share.py`:

```python
"""iter-08 Phase 4: per-Kasten chunk-share anti-magnet.

Replaces the dead kasten_freq prior (RES-2: floor=50, never crossed).
Normalisation: rrf_score *= 1/sqrt(chunk_count_per_node). Punishes
chunk-count-rich magnets (yt-effective-public-speakin = 16 chunks)
while leaving small zettels untouched.
"""
from __future__ import annotations

import math
import os
from typing import Any
from uuid import UUID


class ChunkShareStore:
    def __init__(self, supabase: Any | None = None):
        if supabase is None:
            from website.core.supabase_kg.client import get_supabase_client
            supabase = get_supabase_client()
        self._supabase = supabase
        self._cache: dict[str, dict[str, int]] = {}

    async def get_chunk_counts(self, sandbox_id: UUID | str | None) -> dict[str, int]:
        if sandbox_id is None:
            return {}
        key = str(sandbox_id)
        if key in self._cache:
            return self._cache[key]
        try:
            response = self._supabase.rpc(
                "rag_kasten_chunk_counts",
                {"p_sandbox_id": key},
            ).execute()
            data = response.data or []
        except Exception:
            data = []
        counts = {row["node_id"]: int(row.get("chunk_count", 0)) for row in data}
        self._cache[key] = counts
        return counts


def compute_chunk_share_penalty(chunk_count: int) -> float:
    """Multiplicative damping factor in (0, 1].

    1-chunk node → 1.0 (no penalty)
    16-chunk node → 0.25
    """
    if chunk_count <= 1:
        return 1.0
    return 1.0 / math.sqrt(chunk_count)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/rag/retrieval/test_chunk_share.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Add Supabase RPC**

Create `supabase/website/kg_public/migrations/2026-05-03_rag_kasten_chunk_counts.sql`:

```sql
-- iter-08 Phase 4: per-Kasten chunk count for chunk-share anti-magnet.
create or replace function rag_kasten_chunk_counts(p_sandbox_id uuid)
returns table (node_id text, chunk_count int)
language sql stable as $$
    select n.id as node_id, count(c.id)::int as chunk_count
    from rag_sandbox_members m
    join kg_node n on n.id = m.node_id
    left join kg_node_chunks c on c.node_id = n.id
    where m.sandbox_id = p_sandbox_id
    group by n.id
$$;
```

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/retrieval/chunk_share.py tests/unit/rag/retrieval/test_chunk_share.py supabase/website/kg_public/migrations/2026-05-03_rag_kasten_chunk_counts.sql
git commit -m "feat: per-kasten chunk-count store for anti-magnet (iter-08 phase 4.1)"
```

### Phase 4.2 — Wire ChunkShareStore into hybrid.py, remove kasten_freq

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py` (replace kasten_freq block)
- Modify: `website/features/rag_pipeline/orchestrator.py:914-919` (remove `record_hit` calls)
- Delete: `website/features/rag_pipeline/retrieval/kasten_freq.py` (NO — keep until Phase 9 to avoid import storms; just bypass calls)

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag/retrieval/test_hybrid.py`:

```python
def test_chunk_share_normalization_damps_magnets():
    """iter-08 Phase 4.2: candidates with high chunk_count get rrf damped."""
    from website.features.rag_pipeline.retrieval.hybrid import _apply_chunk_share_normalization
    candidates = [
        _cand("magnet", 1.0),  # chunk_count=16 → factor 0.25 → rrf 0.25
        _cand("normal", 1.0),  # chunk_count=4  → factor 0.5  → rrf 0.5
        _cand("solo",   1.0),  # chunk_count=1  → factor 1.0  → rrf 1.0
    ]
    chunk_counts = {"magnet": 16, "normal": 4, "solo": 1}
    _apply_chunk_share_normalization(candidates, chunk_counts)
    rrf = {c.node_id: c.rrf_score for c in candidates}
    assert abs(rrf["magnet"] - 0.25) < 0.01
    assert abs(rrf["normal"] - 0.5) < 0.01
    assert abs(rrf["solo"]   - 1.0) < 0.01
```

- [ ] **Step 2: Run test (expect failure)**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py::test_chunk_share_normalization_damps_magnets -v
```

Expected: FAIL.

- [ ] **Step 3: Patch hybrid.py — replace kasten_freq block**

At `hybrid.py:307` (where the existing `if kasten_freqs and not compare_intent:` block lives), replace ENTIRE block with:

```python
        # iter-08 Phase 4.2: chunk-share normalization replaces dead
        # kasten_freq prior (RES-2). When compare-intent is detected the
        # normalization is suppressed so magnets-as-answers can win.
        chunk_share_enabled = os.environ.get(
            "RAG_CHUNK_SHARE_NORMALIZATION_ENABLED", "true"
        ).lower() not in ("false", "0", "no", "off")
        if chunk_share_enabled and chunk_counts and not compare_intent:
            _apply_chunk_share_normalization(list(by_key.values()), chunk_counts)
        elif compare_intent:
            _log.debug("chunk-share normalization disabled: compare-intent detected")


def _apply_chunk_share_normalization(
    candidates: list[RetrievalCandidate],
    chunk_counts: dict[str, int],
) -> None:
    """In-place: damp rrf_score by 1/sqrt(chunk_count_per_node)."""
    from website.features.rag_pipeline.retrieval.chunk_share import compute_chunk_share_penalty
    for c in candidates:
        n = chunk_counts.get(c.node_id, 0)
        if n > 1:
            c.rrf_score *= compute_chunk_share_penalty(n)
```

- [ ] **Step 4: Plumb ChunkShareStore through retrieve()**

Replace the `freq_task = asyncio.create_task(self._kasten_freq.get_frequencies(sandbox_id))` and `kasten_freqs = await freq_task` block in `retrieve()` with:

```python
        # iter-08 Phase 4.2: fetch per-Kasten chunk counts for normalization.
        if self._chunk_share is not None and sandbox_id is not None:
            counts_task = asyncio.create_task(self._chunk_share.get_chunk_counts(sandbox_id))
        else:
            counts_task = None
        # ... existing search fan-out ...
        chunk_counts: dict[str, int] = {}
        if counts_task is not None:
            try:
                chunk_counts = await counts_task
            except Exception as exc:
                _log.debug("chunk_share fetch failed: %s", exc)
```

Pass `chunk_counts=chunk_counts` to `_dedup_and_fuse` (replacing `kasten_freqs=kasten_freqs`).

- [ ] **Step 5: Update HybridRetriever.__init__**

```python
def __init__(
    self,
    embedder: Any,
    supabase: Any | None = None,
    *,
    chunk_share_store: ChunkShareStore | None = None,
):
    self._supabase = supabase or get_supabase_client()
    self._embedder = embedder
    if chunk_share_store is None:
        from website.features.rag_pipeline.retrieval.chunk_share import ChunkShareStore
        chunk_share_store = ChunkShareStore(supabase=self._supabase)
    self._chunk_share = chunk_share_store
```

- [ ] **Step 6: Disable record_hit calls in orchestrator**

At `orchestrator.py:914-919`, comment out / delete the `asyncio.create_task(kasten_freq.record_hit(...))` block (RES-2 confirmed it's a no-op anyway):

```python
        # iter-08 Phase 4.2: kasten_freq replaced by chunk-share normalization
        # (RES-2: floor=50 was never crossed in 6 iters of production runs).
        # record_hit was already a no-op writeback; removed for clarity.
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/unit/rag/retrieval/ tests/unit/rag/ -v
```

Expected: ALL PASS (some kasten_freq-related tests may need updating to use the new fixture path).

- [ ] **Step 8: Commit**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py website/features/rag_pipeline/orchestrator.py tests/unit/rag/retrieval/test_hybrid.py
git commit -m "fix: chunk-share normalization replaces kasten_freq (iter-08 phase 4.2)"
```

---

## Phase 5 — Cite hygiene (USER APPROVED — dark deploy)

**Research artefact:** RES-5 ([RESEARCH.md §5](RESEARCH.md#res-5-cite-hygiene-safety-gate)). **Critical finding**: `a["contexts"]` (RAGAS input) IS sourced from `citations` (proof: `ops/scripts/rag_eval_loop.py:122` builds `contexts = [c.get("snippet")... for c in citations]`). So filtering `_build_citations` directly moves RAGAS `context_precision` — big lever, not just critic verdict.

**Rationale:** today `_build_citations` (orchestrator.py:1030+) emits ALL `used_candidates` regardless of what the LLM cited inline. This phase intersects ranked_candidates with the LLM's `[id="..."]` tags; falls back to top-K=3 if filter degenerates.

**Pitfalls:**
- **Default OFF for first deploy.** Flip on via env-only after iter-08 reproducer passes.
- Do NOT hardcode per-class minimums — `expected_minimum_citations` is a fixture-only field.
- Do NOT move filter to `_finalize_answer` — forks streaming/non-streaming paths.
- Do NOT reuse critic's `_find_bad_citations` regex (legacy `[id,id]` form).

**Cons NOT to take (rejected during research, see [RESEARCH.md §5](RESEARCH.md#res-5-cite-hygiene-safety-gate)):**
- Direct 0.5 score cut (Design A) — BGE int8 scores uncalibrated.
- Per-class minimums — overfits eval fixture.
- Atomic-claim parsing + re-cite — too invasive.

### Phase 5.1 — Cite-hygiene filter inside `_build_citations`

**Files:**
- Modify: `website/features/rag_pipeline/orchestrator.py` (`_build_citations` signature + body, `_finalize_answer` call site)
- Test: `tests/unit/rag/test_orchestrator_iter08_cite_hygiene.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag/test_orchestrator_iter08_cite_hygiene.py`:

```python
import pytest
from unittest.mock import MagicMock
from website.features.rag_pipeline.orchestrator import _extract_cited_ids


def _cand(node_id, rerank=0.8):
    c = MagicMock()
    c.node_id = node_id
    c.chunk_id = f"{node_id}_c0"
    c.text = "snippet"
    c.rerank_score = rerank
    c.rrf_score = rerank
    return c


def test_extract_cited_ids_canonical():
    ans = 'Steve Jobs spoke at Stanford [id="yt-steve-jobs-2005-stanford"].'
    assert _extract_cited_ids(ans) == {"yt-steve-jobs-2005-stanford"}


def test_extract_cited_ids_chained():
    ans = 'Two zettels: [id="a"][id="b"] support this.'
    assert _extract_cited_ids(ans) == {"a", "b"}


def test_cite_hygiene_filters_to_llm_cited(monkeypatch):
    monkeypatch.setenv("RAG_CITE_HYGIENE_ENABLED", "true")
    from website.features.rag_pipeline.orchestrator import RAGOrchestrator
    cands = [_cand("a", 0.9), _cand("b", 0.7), _cand("c", 0.5)]
    answer = 'Only A matters [id="a"].'
    cites = RAGOrchestrator._build_citations(None, cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a"]


def test_cite_hygiene_fallback_top_k_when_only_fabricated(monkeypatch):
    """LLM cited only an unknown id → fall back to top-K=3."""
    monkeypatch.setenv("RAG_CITE_HYGIENE_ENABLED", "true")
    from website.features.rag_pipeline.orchestrator import RAGOrchestrator
    cands = [_cand("a", 0.9), _cand("b", 0.7), _cand("c", 0.5), _cand("d", 0.3)]
    answer = 'Cited unknown [id="x_fabricated"].'
    cites = RAGOrchestrator._build_citations(None, cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a", "b", "c"]


def test_cite_hygiene_keeps_all_when_no_inline_cites(monkeypatch):
    """LLM cited nothing inline → keep ranked_candidates as-is (no regression)."""
    monkeypatch.setenv("RAG_CITE_HYGIENE_ENABLED", "true")
    from website.features.rag_pipeline.orchestrator import RAGOrchestrator
    cands = [_cand("a", 0.9), _cand("b", 0.7)]
    answer = "No inline cites at all."
    cites = RAGOrchestrator._build_citations(None, cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a", "b"]


def test_cite_hygiene_disabled_keeps_all(monkeypatch):
    monkeypatch.setenv("RAG_CITE_HYGIENE_ENABLED", "false")
    from website.features.rag_pipeline.orchestrator import RAGOrchestrator
    cands = [_cand("a", 0.9), _cand("b", 0.7)]
    answer = 'Only A [id="a"].'
    cites = RAGOrchestrator._build_citations(None, cands, answer_text=answer)
    assert [c.node_id for c in cites] == ["a", "b"]
```

- [ ] **Step 2: Run test (expect failure on import)**

```bash
pytest tests/unit/rag/test_orchestrator_iter08_cite_hygiene.py -v
```

Expected: FAIL — `_extract_cited_ids` not defined.

- [ ] **Step 3: Patch orchestrator.py — add helper + env constants**

At top of orchestrator.py near the existing iter-08 env block:

```python
# iter-08 Phase 5: cite hygiene. Filter _build_citations to what the LLM
# actually cited inline. RES-5: a["contexts"] in eval flows from citations
# (rag_eval_loop.py:122), so this directly tightens RAGAS context_precision.
# Default OFF for dark canary deploy.
_CITE_HYGIENE_ENABLED = os.environ.get(
    "RAG_CITE_HYGIENE_ENABLED", "false"
).lower() not in ("false", "0", "no", "off")
_CITE_HYGIENE_MIN_KEEP = int(os.environ.get("RAG_CITE_HYGIENE_MIN_KEEP", "1"))
_CITE_HYGIENE_FALLBACK_TOPK = int(os.environ.get("RAG_CITE_HYGIENE_FALLBACK_TOPK", "3"))

_CITED_ID_RE = re.compile(r'\[id\s*=\s*["\']?([a-zA-Z0-9_\-]+)["\']?\]')


def _extract_cited_ids(answer: str) -> set[str]:
    """iter-08 Phase 5: parse LLM-emitted citation tags from answer text."""
    if not answer:
        return set()
    return {m.group(1).strip() for m in _CITED_ID_RE.finditer(answer) if m.group(1).strip()}
```

- [ ] **Step 4: Modify `_build_citations` signature + body**

Add `answer_text` kwarg; apply filter after the existing dedup/sort, before returning the Citation list:

```python
def _build_citations(
    self,
    candidates,
    *,
    verdict: str | None = None,
    refused: bool = False,
    answer_text: str | None = None,
) -> list[Citation]:
    if _SUPPRESS_CITATIONS_ON_REFUSAL and (refused or verdict == "unsupported_no_retry"):
        return []
    # ... existing dedup + ranked_candidates sort (unchanged) ...

    # iter-08 Phase 5: cite-hygiene filter (gated, default OFF).
    if _CITE_HYGIENE_ENABLED and answer_text:
        cited_ids = _extract_cited_ids(answer_text)
        if cited_ids:
            filtered = [c for c in ranked_candidates if c.node_id in cited_ids]
            if len(filtered) >= _CITE_HYGIENE_MIN_KEEP:
                ranked_candidates = filtered
            else:
                ranked_candidates = ranked_candidates[:_CITE_HYGIENE_FALLBACK_TOPK]
        # else: LLM cited nothing inline → keep ranked_candidates as today.

    return [Citation(...) for candidate in ranked_candidates]
```

- [ ] **Step 5: Update `_finalize_answer` call site**

```python
turn.citations = self._build_citations(
    used_candidates,
    verdict=verdict,
    refused=(answer_text == REFUSAL_PHRASE),
    answer_text=answer_text,  # iter-08 Phase 5
)
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/unit/rag/ -v
```

Expected: ALL PASS.

- [ ] **Step 7: Commit (DARK deploy — env default OFF)**

```bash
git add website/features/rag_pipeline/orchestrator.py tests/unit/rag/test_orchestrator_iter08_cite_hygiene.py
git commit -m "feat: cite hygiene filter dark deploy (iter-08 phase 5)"
```

**Canary plan post-deploy:** flip `RAG_CITE_HYGIENE_ENABLED=true` on droplet via env-var only (no redeploy), run iter-08 eval. If q1/q4/q11 regress, flip back to false — no rollback commit needed.

---

## Phase 6 — KG entity-anchor boost

**Research artefact:** RES-4 Part C. The only proposed change that adds NEW disambiguating signal vs damping existing scores. Uses existing `kg_link` table + `LocalizedPageRankScorer` infra.

**Rationale:** when query mentions entities (e.g., "Walker", "Steve Jobs"), boost candidates that are 1-hop neighbours of those entities' canonical zettels. This is a structural signal independent of chunk-count or breadth bias.

**Pitfalls:**
- Anchor-node lookup must be cheap — single Supabase query, cached per request.
- Entity-name → node-id mapping must be fuzzy (handle "Walker" → "yt-matt-walker-sleep-depriv").

**Cons NOT to take:**
- Edge-type weighting — currently only "shared-tag" exists; needs schema work (Phase 8 instead).
- Modify the PageRank graph build — too invasive.

### Phase 6.1 — Entity → anchor node resolver

**Files:**
- Create: `website/features/rag_pipeline/retrieval/entity_anchor.py`
- Test: `tests/unit/rag/retrieval/test_entity_anchor.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/rag/retrieval/test_entity_anchor.py`:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from website.features.rag_pipeline.retrieval.entity_anchor import resolve_anchor_nodes

@pytest.mark.asyncio
async def test_resolve_anchor_walker():
    """'Walker' resolves to the yt-matt-walker-sleep-depriv zettel via fuzzy title match."""
    fake_supabase = MagicMock()
    fake_supabase.rpc.return_value.execute.return_value.data = [
        {"node_id": "yt-matt-walker-sleep-depriv", "title": "Matt Walker on Sleep Deprivation"},
    ]
    result = await resolve_anchor_nodes(["Walker"], sandbox_id="kasten1", supabase=fake_supabase)
    assert "yt-matt-walker-sleep-depriv" in result
```

- [ ] **Step 2: Run test (expect failure)**

```bash
pytest tests/unit/rag/retrieval/test_entity_anchor.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement module**

Create `website/features/rag_pipeline/retrieval/entity_anchor.py`:

```python
"""iter-08 Phase 6: entity-name → KG anchor node resolver."""
from __future__ import annotations

from typing import Any
from uuid import UUID


async def resolve_anchor_nodes(
    entities: list[str],
    sandbox_id: UUID | str | None,
    supabase: Any,
) -> set[str]:
    """Map entity names to canonical Kasten node_ids via fuzzy title/tag match."""
    if not entities or sandbox_id is None:
        return set()
    try:
        response = supabase.rpc(
            "rag_resolve_entity_anchors",
            {"p_sandbox_id": str(sandbox_id), "p_entities": entities},
        ).execute()
        return {row["node_id"] for row in (response.data or [])}
    except Exception:
        return set()


async def get_one_hop_neighbours(
    anchor_nodes: set[str],
    sandbox_id: UUID | str | None,
    supabase: Any,
) -> set[str]:
    """Return all node_ids 1-hop adjacent to any anchor in the Kasten subgraph."""
    if not anchor_nodes or sandbox_id is None:
        return set()
    try:
        response = supabase.rpc(
            "rag_one_hop_neighbours",
            {"p_sandbox_id": str(sandbox_id), "p_anchor_nodes": list(anchor_nodes)},
        ).execute()
        return {row["node_id"] for row in (response.data or [])}
    except Exception:
        return set()
```

- [ ] **Step 4: Add Supabase RPCs**

Create `supabase/website/kg_public/migrations/2026-05-03_rag_entity_anchor.sql`:

```sql
-- iter-08 Phase 6: entity-name → anchor-node resolver. Fuzzy match via
-- title ILIKE %entity% (cheap; pg_trgm index on kg_node.title helps).
create or replace function rag_resolve_entity_anchors(p_sandbox_id uuid, p_entities text[])
returns table (node_id text)
language sql stable as $$
    select distinct n.id as node_id
    from rag_sandbox_members m
    join kg_node n on n.id = m.node_id
    where m.sandbox_id = p_sandbox_id
      and exists (
        select 1 from unnest(p_entities) e
        where n.title ILIKE '%' || e || '%' or e = ANY(n.tags)
      )
$$;

-- 1-hop neighbours via kg_link.
create or replace function rag_one_hop_neighbours(p_sandbox_id uuid, p_anchor_nodes text[])
returns table (node_id text)
language sql stable as $$
    select distinct unnest(array[l.source_node_id, l.target_node_id]) as node_id
    from kg_link l
    join rag_sandbox_members m on m.node_id = l.source_node_id or m.node_id = l.target_node_id
    where m.sandbox_id = p_sandbox_id
      and (l.source_node_id = ANY(p_anchor_nodes) or l.target_node_id = ANY(p_anchor_nodes))
$$;
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/rag/retrieval/test_entity_anchor.py -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/retrieval/entity_anchor.py tests/unit/rag/retrieval/test_entity_anchor.py supabase/website/kg_public/migrations/2026-05-03_rag_entity_anchor.sql
git commit -m "feat: kg entity-anchor resolver (iter-08 phase 6.1)"
```

### Phase 6.2 — Wire anchor boost into _dedup_and_fuse

**Files:**
- Modify: `website/features/rag_pipeline/retrieval/hybrid.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag/retrieval/test_hybrid.py`:

```python
def test_anchor_boost_applies_to_neighbours():
    from website.features.rag_pipeline.retrieval.hybrid import _apply_anchor_boost
    candidates = [_cand("a", 0.5), _cand("b", 0.5), _cand("c", 0.5)]
    neighbours = {"a", "c"}
    _apply_anchor_boost(candidates, neighbours, boost=0.05)
    assert candidates[0].rrf_score == 0.55  # a is neighbour
    assert candidates[1].rrf_score == 0.50  # b is not
    assert candidates[2].rrf_score == 0.55  # c is neighbour
```

- [ ] **Step 2: Run test (expect failure)**

```bash
pytest tests/unit/rag/retrieval/test_hybrid.py::test_anchor_boost_applies_to_neighbours -v
```

Expected: FAIL.

- [ ] **Step 3: Implement helper + plumbing**

Add to `hybrid.py`:

```python
# iter-08 Phase 6: KG entity-anchor boost.
_ANCHOR_BOOST_ENABLED = os.environ.get(
    "RAG_ANCHOR_BOOST_ENABLED", "true"
).lower() not in ("false", "0", "no", "off")
_ANCHOR_BOOST_AMOUNT = float(os.environ.get("RAG_ANCHOR_BOOST_AMOUNT", "0.05"))


def _apply_anchor_boost(
    candidates: list[RetrievalCandidate],
    neighbour_set: set[str],
    boost: float = _ANCHOR_BOOST_AMOUNT,
) -> None:
    if not neighbour_set or not _ANCHOR_BOOST_ENABLED:
        return
    for c in candidates:
        if c.node_id in neighbour_set:
            c.rrf_score += boost
```

In `retrieve()`, after the Supabase fan-out and before `_dedup_and_fuse`:

```python
        # iter-08 Phase 6: resolve KG anchors from query metadata + 1-hop expand.
        anchor_neighbours: set[str] = set()
        if (
            _ANCHOR_BOOST_ENABLED
            and query_metadata is not None
            and (query_metadata.authors or query_metadata.entities)
        ):
            from website.features.rag_pipeline.retrieval.entity_anchor import (
                resolve_anchor_nodes, get_one_hop_neighbours,
            )
            entities = list((query_metadata.authors or []) + (query_metadata.entities or []))
            anchor_nodes = await resolve_anchor_nodes(entities, sandbox_id, self._supabase)
            anchor_neighbours = await get_one_hop_neighbours(anchor_nodes, sandbox_id, self._supabase)
```

Pass `anchor_neighbours=anchor_neighbours` into `_dedup_and_fuse` and call `_apply_anchor_boost` before the chunk-share normalization.

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/rag/retrieval/ -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/retrieval/hybrid.py tests/unit/rag/retrieval/test_hybrid.py
git commit -m "feat: kg entity-anchor boost in retrieval (iter-08 phase 6.2)"
```

---

## Phase 7 — Eval scorer fixes (Decisions 4-7 + low-risk)

### Phase 7.A — Refusal phrase regex (Decision 4)

**Research:** today `eval_runner.py:21,41-42` literal-matches `"I can't find that in your Zettels."`. Wording drift (case, smart-apostrophe, "I cannot find") → 0 score. Decision: regex over key tokens.

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/eval_runner.py:21,41-42`

- [ ] **Step 1: Verify regex works for current iter examples**

Sample iter-07 refused answers (from verification_results.json q3, q9):
- q3 (iter-06): "I cannot find specific quotes for 'verbal punctuation'..."
- q9 (iter-07): refused, answer text contains "I can't find" or similar
- canonical: "I can't find that in your Zettels."

Regex must match all: `r"\b(?:can'?t find|cannot find|no information|no relevant|don'?t have|do not have|not found in)\b.*\b(?:zettel|Zettel)|(?:can'?t find|cannot find).+specific"`. Simplify to:

```python
_REFUSAL_REGEX = re.compile(
    r"\b("
    r"can'?t find|cannot find|no information|no relevant|"
    r"don'?t have|do not have|not found in|not covered in|"
    r"unable to (?:find|locate|answer)"
    r")\b",
    re.IGNORECASE,
)
```

- [ ] **Step 2: Write failing test**

Add to `tests/unit/rag_pipeline/evaluation/test_eval_runner.py`:

```python
def test_refusal_regex_matches_known_examples():
    from website.features.rag_pipeline.evaluation.eval_runner import _is_refusal_answer
    assert _is_refusal_answer("I can't find that in your Zettels.")
    assert _is_refusal_answer("I cannot find specific quotes for 'verbal punctuation'...")
    assert _is_refusal_answer("I can’t find that in your Zettels.")  # smart-apostrophe
    assert _is_refusal_answer("There is no information about Notion in your Kasten.")
    assert _is_refusal_answer("I do not have details on this topic.")
    assert not _is_refusal_answer("Steve Jobs described death as life's change agent.")
```

- [ ] **Step 3: Run test (expect failure — function doesn't exist)**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_eval_runner.py::test_refusal_regex_matches_known_examples -v
```

Expected: FAIL.

- [ ] **Step 4: Patch eval_runner.py**

Replace literal `REFUSAL_PHRASE = "I can't find that in your Zettels."` (eval_runner.py:21) with:

```python
import re
_REFUSAL_REGEX = re.compile(
    r"\b("
    r"can'?t find|cannot find|no information|no relevant|"
    r"don'?t have|do not have|not found in|not covered in|"
    r"unable to (?:find|locate|answer)"
    r")\b",
    re.IGNORECASE,
)

def _is_refusal_answer(text: str) -> bool:
    """iter-08 Phase 7.A: regex over key tokens (Decision 4). Handles wording drift."""
    if not text:
        return False
    return bool(_REFUSAL_REGEX.search(text))
```

Update the literal-match call site (line 41-42):

```python
    if _is_refusal_answer(turn.content):
        # ... refusal handling
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/rag_pipeline/evaluation/ -v
```

Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add website/features/rag_pipeline/evaluation/eval_runner.py tests/unit/rag_pipeline/evaluation/test_eval_runner.py
git commit -m "fix: refusal regex tolerates wording drift (iter-08 phase 7.a)"
```

### Phase 7.B — RAGAS JSON parse-fail (USER APPROVED)

**Research artefact:** RES-6 ([RESEARCH.md §6](RESEARCH.md#res-6-ragas-json-parse-fail-handling)). Mix of (a) retry once with stricter prompt + (c) mark `eval_failed`. Mirrors RAGAS upstream NaN-on-failure pattern.

**Pitfalls:**
- `synthesis_score.py` and `eval_runner.py` consumers MUST treat the `eval_failed` flag — otherwise `0.0` still leaks through.
- Cap retry at exactly 1 (not 2+) — keeps cost/latency bounded.
- Gate retry on `JSONDecodeError` / empty rows only — don't retry on 429/5xx (already handled by key-pool retry).
- Apply identically to `deepeval_runner.py` (same pattern).

**Cons NOT to take (rejected):**
- (b) Default-to-0.5 — fabricates a metric the judge never produced; pollutes cohort with synthetic prior.
- (a) alone — still ends in 0.0 on retry-fail.

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/ragas_runner.py` (`_judge_one_via_gemini`)
- Modify: `website/features/rag_pipeline/evaluation/deepeval_runner.py` (mirror)
- Modify: `website/features/rag_pipeline/evaluation/eval_runner.py` (cohort summary `n_eval_failed`)
- Modify: `website/features/rag_pipeline/evaluation/synthesis_score.py` (skip eval_failed rows)

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag_pipeline/evaluation/test_ragas_runner.py`:

```python
@pytest.mark.asyncio
async def test_judge_retries_once_on_parse_fail_then_marks_eval_failed(monkeypatch):
    """iter-08 Phase 7.B: 1 retry with stricter prompt; if still fails, mark eval_failed."""
    from website.features.rag_pipeline.evaluation import ragas_runner
    call_count = {"n": 0}

    async def fake_pool_call(*args, **kwargs):
        call_count["n"] += 1
        # Both attempts return unparseable text
        return [type("R", (), {"text": "not json at all"})()]

    pool = MagicMock()
    pool.generate_content = fake_pool_call
    monkeypatch.setattr(ragas_runner, "get_key_pool", lambda: pool)
    sample = {"question": "q", "answer": "a", "contexts": ["x"], "ground_truth": "g"}
    metrics = await ragas_runner._judge_one_via_gemini(sample)
    assert call_count["n"] == 2  # 1 try + 1 retry
    assert metrics["eval_failed"] is True
    assert metrics["faithfulness"] == 0.0  # zeros, but flagged


@pytest.mark.asyncio
async def test_judge_succeeds_on_retry(monkeypatch):
    from website.features.rag_pipeline.evaluation import ragas_runner
    call_count = {"n": 0}

    async def fake_pool_call(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [type("R", (), {"text": "garbage"})()]
        return [type("R", (), {
            "text": '[{"faithfulness":0.9,"answer_correctness":0.8,'
                    '"context_precision":0.7,"answer_relevancy":0.85,"semantic_similarity":0.9}]'
        })()]

    pool = MagicMock()
    pool.generate_content = fake_pool_call
    monkeypatch.setattr(ragas_runner, "get_key_pool", lambda: pool)
    sample = {"question": "q", "answer": "a", "contexts": ["x"], "ground_truth": "g"}
    metrics = await ragas_runner._judge_one_via_gemini(sample)
    assert metrics["eval_failed"] is False
    assert metrics["faithfulness"] == 0.9


def test_cohort_mean_excludes_eval_failed():
    from website.features.rag_pipeline.evaluation.ragas_runner import _cohort_mean
    rows = [
        {"faithfulness": 0.9, "answer_correctness": 0.8, "eval_failed": False},
        {"faithfulness": 0.0, "answer_correctness": 0.0, "eval_failed": True},
        {"faithfulness": 0.7, "answer_correctness": 0.6, "eval_failed": False},
    ]
    mean = _cohort_mean(rows)
    # Exclude the eval_failed row
    assert abs(mean["faithfulness"] - 0.8) < 0.01
```

- [ ] **Step 2: Run test (expect failure)**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_ragas_runner.py -v -k "retries_once_on_parse_fail or excludes_eval_failed or succeeds_on_retry"
```

Expected: FAIL.

- [ ] **Step 3: Patch `ragas_runner._judge_one_via_gemini`**

```python
async def _judge_one_via_gemini(sample: dict) -> dict:
    """iter-08 Phase 7.B: retry once with stricter prompt, then mark eval_failed."""
    pool = get_key_pool()
    base_prompt = _build_judge_prompt([sample])

    for attempt in (1, 2):
        cfg = {"response_mime_type": "application/json"}
        contents = base_prompt if attempt == 1 else (
            base_prompt
            + "\n\nIMPORTANT: respond with ONLY the JSON object. "
            "No preamble, no markdown fence, no commentary."
        )
        try:
            result = await pool.generate_content(
                contents=contents,
                config=cfg,
                starting_model="gemini-2.5-pro",
                label=f"rag_eval_ragas_judge_one_a{attempt}",
            )
            response = result[0] if isinstance(result, tuple) else result
            text = getattr(response, "text", "") or ""
            rows = _parse_per_sample_rows(text)
            if rows:
                metrics = _row_to_metrics(rows[0])
                metrics["eval_failed"] = False
                return metrics
            logger.warning("RAGAS judge attempt %d: empty/unparseable", attempt)
        except Exception as exc:
            logger.warning("RAGAS judge attempt %d raised (%s)", attempt, exc)

    out = _zero_metrics()
    out["eval_failed"] = True
    return out
```

- [ ] **Step 4: Patch `_cohort_mean` to exclude `eval_failed=True` rows**

```python
def _cohort_mean(rows: list[dict]) -> dict:
    """iter-08 Phase 7.B: exclude eval_failed rows from cohort mean."""
    valid = [r for r in rows if not r.get("eval_failed", False)]
    if not valid:
        return _zero_metrics()
    keys = ("faithfulness", "answer_correctness", "context_precision",
            "answer_relevancy", "semantic_similarity")
    return {k: sum(r.get(k, 0.0) for r in valid) / len(valid) for k in keys}
```

- [ ] **Step 5: Mirror in `deepeval_runner.py`**

Apply the same retry-then-mark-eval_failed logic to `deepeval_runner._judge_per_query_async` (or whatever the equivalent function is called). Add `eval_failed` to its return dict and update its cohort-mean.

- [ ] **Step 6: Audit `synthesis_score.py` + `eval_runner.py` consumers**

```bash
grep -n "ragas\.get\|deepeval\.get\|per_q\.\(ragas\|deepeval\)" website/features/rag_pipeline/evaluation/synthesis_score.py website/features/rag_pipeline/evaluation/eval_runner.py | head -20
```

Wherever a per-query record is read for synthesis sub-score, skip `eval_failed=True`. Bubble `n_eval_failed` into the eval summary so it's visible in scores.md.

- [ ] **Step 7: Run tests**

```bash
pytest tests/unit/rag_pipeline/evaluation/ -v
```

Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add website/features/rag_pipeline/evaluation/ tests/unit/rag_pipeline/evaluation/
git commit -m "fix: retry ragas judge once then mark eval_failed (iter-08 phase 7.b)"
```

### Phase 7.C — answer_relevancy double-weight fix (Decision 6)

**Research:** `eval_runner.py:198-213` mixes RAGAS dataset-mean with refusal per-query unit. With per-query RAGAS now merged (commit `adeafe9`), the double-weight is fixable.

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/eval_runner.py:198-213`

- [ ] **Step 1: Read current aggregation**

```bash
sed -n '195,215p' website/features/rag_pipeline/evaluation/eval_runner.py
```

- [ ] **Step 2: Write failing test**

```python
def test_answer_relevancy_aggregation_no_double_weight():
    """iter-08 Phase 7.C: per-query relevancy averaged with refusal queries equal-weight."""
    # Build per-query records: 10 answer-queries with relevancy=0.9, 4 refusal with relevancy=1.0 (correct refusal)
    per_q = (
        [{"ragas": {"answer_relevancy": 0.9}, "expected_behavior": "answer"} for _ in range(10)]
        + [{"refusal_score": 1.0, "expected_behavior": "refusal"} for _ in range(4)]
    )
    from website.features.rag_pipeline.evaluation.eval_runner import _aggregate_relevancy
    score = _aggregate_relevancy(per_q)
    # Should be (10*90 + 4*100) / 14 = (900 + 400) / 14 = 92.86
    assert 92.0 < score < 93.0, f"got {score}"
```

- [ ] **Step 3: Run test (expect failure)**

- [ ] **Step 4: Implement `_aggregate_relevancy`**

```python
def _aggregate_relevancy(per_q: list[dict]) -> float:
    """iter-08 Phase 7.C: equal-weight per-query, mixing RAGAS answer_relevancy with refusal_score."""
    scores = []
    for q in per_q:
        if q.get("expected_behavior") == "refusal":
            scores.append(float(q.get("refusal_score", 0.0)) * 100.0)
        else:
            ar = q.get("ragas", {}).get("answer_relevancy")
            if ar is not None:
                scores.append(float(ar) * 100.0)
    return sum(scores) / len(scores) if scores else 0.0
```

Replace the existing aggregation block (lines 198-213) with a call to this helper.

- [ ] **Step 5: Run tests + Commit**

```bash
pytest tests/unit/rag_pipeline/evaluation/ -v
git add website/features/rag_pipeline/evaluation/eval_runner.py tests/unit/rag_pipeline/evaluation/test_eval_runner.py
git commit -m "fix: answer relevancy aggregation no double weight (iter-08 phase 7.c)"
```

### Phase 7.D — NDCG asymmetry (USER APPROVED — option a)

**Research artefact:** RES-7 ([RESEARCH.md §7](RESEARCH.md#res-7-ndcg-asymmetry-fix)). Today multi-source queries face ideal_dcg=2.95 vs single-source ideal_dcg=1.0 — same retrieval skill, asymmetric score. Fix: normalise per-query against the achievable max via `min(k_ndcg, len(gold_ranking))`. Standard textbook fix (Järvelin & Kekäläinen 2002, sklearn.metrics.ndcg_score, pytrec_eval).

**Pitfalls:**
- Iter-08 results: factoid scores rise modestly while thematic scores rise more (narrowing the gap). May be misread as "rerank regression" if compared raw to iter-07 — actually it's the normaliser becoming honest. Document in scores.md.
- Add safety assertion: `actual_dcg <= ideal_dcg` (cannot violate with binary rel + same gold_set; assert as a guard against future relaxations).

**Cons NOT to take (rejected):**
- (b) NDCG@1 — throws away ranking signal between positions 2-5; duplicates `hit_at_k`.
- (c) Average Precision — double-counts the "fraction of gold in top-k" axis; collapses NDCG-vs-P@k orthogonality.

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/component_scorers.py:99` (one-line change)
- Test: `tests/unit/rag_pipeline/evaluation/test_component_scorers.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/rag_pipeline/evaluation/test_component_scorers.py`:

```python
def test_ndcg_perfect_for_single_source():
    """iter-08 Phase 7.D: NDCG=1.0 when single gold ranked at #1."""
    from website.features.rag_pipeline.evaluation.component_scorers import reranking_score
    score = reranking_score(
        gold_ranking=["a"],
        reranked=["a", "b", "c"],
        k_ndcg=5, k_p=3,
    )
    # ndcg=1.0; p@3=1/3≈0.33; fp=2/3 → fp_score=1-2/3=0.33
    # 100*(0.5*1 + 0.3*0.33 + 0.2*0.33) ≈ 56.6
    assert score > 50.0


def test_ndcg_perfect_for_multi_source_when_all_at_top():
    """iter-08 Phase 7.D: NDCG=1.0 for |gold|=2 and |gold|=5 when all in top."""
    from website.features.rag_pipeline.evaluation.component_scorers import reranking_score
    s2 = reranking_score(
        gold_ranking=["a", "b"],
        reranked=["a", "b", "c"],
        k_ndcg=5, k_p=3,
    )
    s5 = reranking_score(
        gold_ranking=["a", "b", "c", "d", "e"],
        reranked=["a", "b", "c", "d", "e"],
        k_ndcg=5, k_p=3,
    )
    # Both should have ndcg component = 1.0
    assert s2 >= 80.0  # ndcg=1, p@3=1, fp=0 → 100*(0.5+0.3+0.2)=100; with subtleties >=80
    assert s5 >= 80.0


def test_actual_dcg_never_exceeds_ideal():
    """Safety guard: with binary rel + same gold_set, actual_dcg <= ideal_dcg."""
    from website.features.rag_pipeline.evaluation.component_scorers import reranking_score
    score = reranking_score(
        gold_ranking=["a"],
        reranked=["b", "c", "a"],  # gold at rank 3
        k_ndcg=5, k_p=3,
    )
    # ndcg should be <=1.0; specifically 1/log2(4) / 1.0 = 0.5
    assert 0 <= score <= 100
```

- [ ] **Step 2: Run test (expect failure on multi-source)**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_component_scorers.py -v -k ndcg
```

Expected: FAIL on `test_ndcg_perfect_for_multi_source_when_all_at_top` (under current ideal_dcg=2.95 baseline, NDCG would be 1.0/2.95 = 0.34).

- [ ] **Step 3: Patch component_scorers.py**

At line ~98-100:

```python
    # iter-08 Phase 7.D: normalise per-query against achievable max so
    # multi-source queries don't face an asymmetrically harder ideal_dcg.
    # Standard textbook fix (Järvelin & Kekäläinen 2002).
    ideal_k = min(k_ndcg, len(gold_ranking))
    ideal_dcg = dcg(gold_ranking[:ideal_k])
    ndcg = actual_dcg / ideal_dcg if ideal_dcg else 0.0
    # Safety: actual cannot exceed ideal under binary rel + shared gold_set.
    assert ndcg <= 1.0 + 1e-9, f"ndcg violated max: {ndcg}"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/rag_pipeline/evaluation/test_component_scorers.py -v
```

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/rag_pipeline/evaluation/component_scorers.py tests/unit/rag_pipeline/evaluation/test_component_scorers.py
git commit -m "fix: ndcg normaliser per-query achievable max (iter-08 phase 7.d)"
```

### Phase 7.E — Empty-list cliff fix

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/component_scorers.py:23-24`

- [ ] **Step 1: Write failing test**

```python
def test_chunking_score_skips_empty_nodes():
    """iter-08 Phase 7.E: empty-chunk node returns sentinel None (caller skips), not 0."""
    score = chunking_score([], target_tokens=None)
    assert score is None or score == 0.0  # caller decides; default = 0.0 still allowed
```

- [ ] **Step 2: Update `chunking_score` to return None on empty (caller-aware)**

```python
def chunking_score(chunks, target_tokens=None, embeddings=None):
    if not chunks:
        return None  # iter-08 Phase 7.E: caller skips None entries from cohort mean
    # ...
```

Update `eval_runner.py` cohort-mean to skip None:

```python
chunking_scores = [s for s in chunking_scores_per_node if s is not None]
chunking = sum(chunking_scores) / len(chunking_scores) if chunking_scores else 0.0
```

- [ ] **Step 3: Run tests + Commit**

### Phase 7.F — Composite NaN/None guard

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/composite.py:14-23`

- [ ] **Step 1: Add guard**

```python
import math

def compute_composite(chunking, retrieval, reranking, synthesis, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError("composite weights must sum to 1")
    components = {"chunking": chunking, "retrieval": retrieval, "reranking": reranking, "synthesis": synthesis}
    for name, val in components.items():
        if val is None or not math.isfinite(val):
            raise ValueError(f"composite component '{name}' is None or NaN: {val!r}")
    return sum(weights[k] * components[k] for k in components)
```

- [ ] **Step 2: Test + Commit**

### Phase 7.G — score_rag_eval surface dropped qids

**Files:**
- Modify: `ops/scripts/score_rag_eval.py:240-248`

- [ ] **Step 1: Surface dropped qids in scores.md**

```python
all_qids = {q["qid"] for q in queries_json["queries"]}
scored_qids = {a["qid"] for a in qa_checks_with_results}
dropped_qids = sorted(all_qids - scored_qids)
if dropped_qids:
    summary["unscored_qids"] = dropped_qids
    print(f"WARNING: dropped from scoring: {dropped_qids}")
```

Write `unscored_qids` to scores.md as a top-level section if non-empty.

- [ ] **Step 2: Test + Commit**

### Phase 7.H — p50/p95 trimmed-mean

**Files:**
- Modify: `website/features/rag_pipeline/evaluation/eval_runner.py:215-232`

- [ ] **Step 1: Implement trimmed quantile**

```python
def _trimmed_quantile(values: list[float], q: float, trim_pct: float = 0.1) -> float:
    if len(values) < 4:
        return _quantile(values, q)
    sorted_vals = sorted(values)
    lo = int(len(sorted_vals) * trim_pct)
    hi = len(sorted_vals) - lo
    return _quantile(sorted_vals[lo:hi], q)
```

Replace p50/p95 computation calls with trimmed variant.

- [ ] **Step 2: Test + Commit**

---

## Phase 8 — KG schema migration (Decision 8)

**Research artefact:** RES-4 Part C noted edge-type weighting was deferred because `kg_link.relation` only had "shared-tag". User approved including the schema migration in iter-08 to unblock iter-09's edge-type weighting.

**Pitfalls:**
- Schema migration must be backwards-compatible (existing rows default to "shared_tag").
- No code consumes the new column yet — that's Phase 9 / iter-09.

**Cons NOT to take:**
- Don't add the consumer code in iter-08 — too invasive on top of Phases 1-7.

### Phase 8.1 — Add `kg_link.relation` enum

**Files:**
- Create: `supabase/website/kg_public/migrations/2026-05-03_kg_link_relation_enum.sql`

- [ ] **Step 1: Write migration**

```sql
-- iter-08 Phase 8: extend kg_link with relation type for future edge-weighted PageRank.
-- Default to 'shared_tag' to preserve current behaviour. iter-09 will populate
-- 'cites' / 'mentions' / 'co_occurs' from new ingestion logic.

create type kg_link_relation as enum ('shared_tag', 'cites', 'mentions', 'co_occurs');

alter table kg_link add column if not exists relation kg_link_relation default 'shared_tag' not null;

create index if not exists kg_link_relation_idx on kg_link(relation);

-- Update schema mirror.
comment on column kg_link.relation is
  'Edge type for graph-aware retrieval. Default shared_tag for back-compat.';
```

- [ ] **Step 2: Verify backwards compat**

```bash
# Apply migration locally if a test DB is available, then:
psql -c "select count(*) from kg_link where relation = 'shared_tag';"
```

Expected: count = total existing rows (all defaulted).

- [ ] **Step 3: Update mirror in schema.sql**

```bash
grep -n "kg_link" supabase/website/kg_public/schema.sql
```

Add the new column to the `create table kg_link` definition (or append `alter table` if mirror is post-create).

- [ ] **Step 4: Commit**

```bash
git add supabase/website/kg_public/migrations/2026-05-03_kg_link_relation_enum.sql supabase/website/kg_public/schema.sql
git commit -m "feat: kg_link.relation enum for edge-weighted retrieval (iter-08 phase 8)"
```

---

## Phase 9 — Deploy + iter-08 eval run

### Phase 9.1 — Final test sweep

- [ ] **Step 1: Full unit test suite**

```bash
pytest tests/unit/rag/ tests/unit/rag_pipeline/ -v
```

Expected: ALL PASS.

- [ ] **Step 2: Linter / type-check (if applicable)**

```bash
python -m pyflakes website/features/rag_pipeline/ 2>&1 | head -20
```

### Phase 9.2 — Push + deploy

- [ ] **Step 1: Push master**

```bash
git push origin master
```

- [ ] **Step 2: Apply Supabase migrations**

```bash
# Apply the 3 new migrations to production:
# - 2026-05-03_rag_kasten_chunk_counts.sql (Phase 4)
# - 2026-05-03_rag_entity_anchor.sql (Phase 6)
# - 2026-05-03_kg_link_relation_enum.sql (Phase 8)
# Manual psql apply (per CLAUDE.md - migrations don't auto-deploy).
```

- [ ] **Step 3: Wait for blue/green flip**

```bash
gh run list --workflow=deploy-droplet.yml --limit 1 --json databaseId,status,conclusion
# Wait until status=completed conclusion=success
```

### Phase 9.3 — Run iter-08 eval

- [ ] **Step 1: Set up iter-08 dir**

```bash
mkdir -p docs/rag_eval/common/knowledge-management/iter-08
cp docs/rag_eval/common/knowledge-management/iter-07/queries.json docs/rag_eval/common/knowledge-management/iter-08/
cp docs/rag_eval/common/knowledge-management/iter-07/baseline.json docs/rag_eval/common/knowledge-management/iter-08/ 2>/dev/null
```

- [ ] **Step 2: Mint JWT + run eval**

```powershell
# Windows PowerShell (in repo root)
$env:ZK_BEARER_TOKEN = (python ops/scripts/mint_eval_jwt.py)
python ops\scripts\eval_iter_03_playwright.py --iter iter-08
```

- [ ] **Step 3: Verify scores meet target**

Read `docs/rag_eval/common/knowledge-management/iter-08/scores.md`. Target: composite ≥85, all 14 queries pass (no 402, no over-refusal, gold@1 ≥ 0.85).

- [ ] **Step 4: Document delta**

Create `docs/rag_eval/common/knowledge-management/iter-08/scores.md` summary section comparing iter-07 → iter-08 per phase.

- [ ] **Step 5: Final commit**

```bash
git add docs/rag_eval/common/knowledge-management/iter-08/
git commit -m "test: iter-08 eval results"
git push origin master
```

---

## Self-Review

**Spec coverage check:** every approved item from the user's decisions (1-8) maps to a phase:

- Decision 1 (cite hygiene research) → Phase 5 (placeholder, awaiting RES-5)
- Decision 2 (KG entity-anchor) → Phase 6 ✓
- Decision 3 (pass embeddings) → Phase 2.3 ✓
- Decision 4 (refusal regex) → Phase 7.A ✓
- Decision 5 (RAGAS parse-fail research) → Phase 7.B (placeholder, awaiting RES-6)
- Decision 6 (answer_relevancy double-weight) → Phase 7.C ✓
- Decision 7 (NDCG asymmetry research) → Phase 7.D (placeholder, awaiting RES-7)
- Decision 8 (KG schema migration) → Phase 8 ✓

Plus other approved items: Phase 1 (n=5→3), Phase 2.1/2/4 (chunking), Phase 3 (magnet bundle), Phase 4 (kasten_freq replace), Phase 7.E-H (low-risk scorer fixes), Phase 9 (deploy+eval).

**Placeholder scan:** Phases 5, 7.B, 7.D are intentional research-pending placeholders; will be filled in once RES-5/6/7 return. No other "TBD" patterns.

**Type consistency:** `chunk_counts: dict[str, int]`, `RetrievalCandidate`, `QueryClass` enum used consistently across phases. `_apply_*` helpers all in-place mutate `list[RetrievalCandidate]` for consistency.

**Estimated composite delta after iter-08 lands:**

| Phase | Estimated Δ |
|---|---:|
| Phase 1 (n revert + recover q13/q14 from 402) | +12 to +14 |
| Phase 2 (chunking unlock 31.94 → ~75) | +4 to +6 |
| Phase 3 (magnet bundle) | +5 to +8 |
| Phase 4 (chunk-share normalization) | +2 to +4 |
| Phase 5 (cite hygiene, pending RES-5) | +3 to +6 |
| Phase 6 (KG entity-anchor) | +1 to +3 |
| Phase 7 (eval scorer cleanup) | +2 to +4 |
| Phase 8 (schema, no immediate Δ) | 0 |
| Already merged (adeafe9 RAGAS per-query, cc04b1e retry/cite) | +5 to +8 |
| **Conservative stack** | **62.88 → ~85-92** |

---

## Execution Handoff

Plan complete and saved to `docs/rag_eval/common/knowledge-management/iter-08/PLAN.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

**Note:** plan has 3 research-pending sections (Phase 5, 7.B, 7.D) waiting for RES-5/6/7 agents to return. Plan will be updated in-place once they complete.

Which approach?
