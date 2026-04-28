# Iter-03 Plan — Appendix: Zero-Ambiguity Expansions

This appendix expands the 9 tasks in the main plan (`2026-04-28-iter-03-rag-burst-correctness.md`) where a subagent might lack enough detail to execute confidently. Read these expansions BEFORE executing the corresponding task.

---

## Appendix A: Task 1A.2 — finding the exact `nodes_to_exclude` for BGE

The placeholder names in the quantize script (`/classifier/MatMul`, `/pooler/MatMul`) almost certainly don't match the real ONNX export.

**Pre-flight before running quantize:**

- [ ] **Step A.1: Inspect ONNX node graph**

Run:
```bash
python - <<'PY'
import onnx, json
m = onnx.load('models/bge-reranker-base.onnx')
nodes = []
for n in m.graph.node:
    name_lower = n.name.lower()
    if any(k in name_lower for k in ['classifier', 'pooler', 'output', 'logits', 'score']):
        nodes.append({'name': n.name, 'op_type': n.op_type, 'inputs': list(n.input), 'outputs': list(n.output)})
print(json.dumps(nodes, indent=2))
PY
```

Expected output: a list of 4–8 nodes. Look for the LAST `MatMul` node before output — typically named `/classifier/dense/MatMul` or `/score/MatMul`. Capture all such MatMul names.

- [ ] **Step A.2: Update `nodes_to_exclude` in `ops/scripts/quantize_bge_int8.py`**

Replace the placeholder list with the actual node names from Step A.1. Example:
```python
nodes_to_exclude=[
    "/score/MatMul",
    "/score/Add",
    "/pooler/dense/MatMul",
    "/pooler/dense/Add",
],
```

- [ ] **Step A.3: Re-run quantize**

`python ops/scripts/quantize_bge_int8.py`

If it errors with "Node X not in graph", remove that name from the exclude list and re-run.

- [ ] **Step A.4: Verify exclusions held**

```bash
python - <<'PY'
import onnx
m = onnx.load('models/bge-reranker-base-int8.onnx')
quantized = [n.name for n in m.graph.node if n.op_type.startswith('QLinear')]
fp32 = [n.name for n in m.graph.node if 'classifier' in n.name.lower() or 'pooler' in n.name.lower() or 'score' in n.name.lower()]
print("Quantized:", len(quantized))
print("Classifier/pooler/score (must NOT include QLinear):", fp32)
PY
```

Expected: classifier/pooler nodes do NOT appear in the quantized list.

---

## Appendix B: Task 1A.4 — cascade.py refactor with full file outline first

**Step B.1: Outline current cascade.py before editing.**

Run: `python - <<'PY'
from pathlib import Path
src = Path('website/features/rag_pipeline/rerank/cascade.py').read_text()
import ast
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        kind = type(node).__name__
        print(f"{kind} {node.name} (line {node.lineno})")
PY`

Expected output is something like:
```
ClassDef CascadeReranker (line 30)
FunctionDef __init__ (line 50)
FunctionDef _get_stage1_ranker (line 233)
FunctionDef _get_stage2_session (line 240)
FunctionDef _get_stage2_tokenizer (line 245)
FunctionDef _score_one (line 260)
FunctionDef _stage2_lock (line 264)
FunctionDef rerank (line 280)
```

(Actual line numbers may differ; use the live outline.)

**Step B.2: Edit plan — five concrete diffs.**

### Diff B.2.1: Module-level constants + eager-load (top of file, after imports)

Insert after the existing imports:

```python
# ==== iter-03 §3.15: int8 + eager load + score calibration + fp32 verify =====
INT8_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "bge-reranker-base-int8.onnx"
FP32_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "bge-reranker-base.onnx"
SCORE_CAL_PATH = Path(__file__).parent / "_int8_score_cal.json"
THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "retrieval" / "_int8_thresholds.json"
FP32_VERIFY_ENABLED = os.environ.get("RAG_FP32_VERIFY", "on").lower() == "on"

import onnxruntime as ort

_ORT_OPTS = ort.SessionOptions()
_ORT_OPTS.intra_op_num_threads = 1
_ORT_OPTS.inter_op_num_threads = 1
_ORT_OPTS.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

# Eager-load at module import — gunicorn --preload shares this via copy-on-write
_STAGE2_SESSION: ort.InferenceSession = ort.InferenceSession(
    str(INT8_MODEL_PATH),
    sess_options=_ORT_OPTS,
    providers=["CPUExecutionProvider"],
)

_FP32_VERIFY_SESSION: ort.InferenceSession | None = None
if FP32_VERIFY_ENABLED and FP32_MODEL_PATH.exists():
    _FP32_VERIFY_SESSION = ort.InferenceSession(
        str(FP32_MODEL_PATH),
        sess_options=_ORT_OPTS,
        providers=["CPUExecutionProvider"],
    )

_SCORE_CAL = json.loads(SCORE_CAL_PATH.read_text(encoding="utf-8")) if SCORE_CAL_PATH.exists() else {"a": 1.0, "b": 0.0}
_THRESHOLDS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8")) if THRESHOLDS_PATH.exists() else {"default": 0.50}
```

### Diff B.2.2: Replace lazy `_get_stage2_session` body

Find:
```python
def _get_stage2_session(self):
    if self._stage2 is None:
        self._stage2 = ort.InferenceSession(...)
    return self._stage2
```

Replace with:
```python
def _get_stage2_session(self):
    """Return the eagerly-loaded module-level int8 session.
    Kept as method for interface compatibility; no longer lazy.
    """
    return _STAGE2_SESSION
```

### Diff B.2.3: Add new methods to `CascadeReranker` (insert after `__init__`)

```python
def _apply_score_calibration(self, raw: float) -> float:
    """Layer 4: fp32 ≈ a × int8 + b."""
    return self._calibration_a * raw + self._calibration_b

def _threshold_for_class(self, query_class: str) -> float:
    """Layer 6: per-class margin threshold."""
    return _THRESHOLDS.get(query_class, _THRESHOLDS.get("default", 0.50))

def _fp32_verify_top_k(self, query: str, top_docs: list[dict], k: int = 3) -> list[dict]:
    """Layer 5: re-score top-k with fp32 model; replace int8 scores with fp32."""
    if not self._fp32_verify_enabled:
        return top_docs
    sub = top_docs[:k]
    for doc in sub:
        doc["score"] = _score_one(_FP32_VERIFY_SESSION, query, doc["text"])
    sub.sort(key=lambda d: d["score"], reverse=True)
    return sub + top_docs[k:]
```

### Diff B.2.4: Update `__init__` to populate the new instance attrs

Add inside `__init__`:
```python
self.stage2_model_path = str(INT8_MODEL_PATH)
self._calibration_a = _SCORE_CAL.get("a", 1.0)
self._calibration_b = _SCORE_CAL.get("b", 0.0)
self._fp32_verify_enabled = FP32_VERIFY_ENABLED and _FP32_VERIFY_SESSION is not None
self._tta_call_count_for_last_query = 0
```

### Diff B.2.5: Replace the existing `rerank` (or `score_batch`) method

Replace the existing top-level rerank entrypoint with:

```python
def score_batch(self, query: str, docs: list[dict], *, mode: str = "fast") -> list[dict]:
    """Score all docs; if mode=='high', test-time augmentation (Layer 7)."""
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
```

If the existing public method is named `rerank()`, keep that name and apply the same body. Find all callers via `Grep` for `\.rerank(` to confirm the signature is `(query, docs, *, mode)`.

---

## Appendix C: Task 1B.2 — exact concurrency wiring in chat_routes.py

**Step C.1: Outline chat_routes.py.**

Run: `mcp__plugin_mem-vault_mem-vault__smart_outline website/api/chat_routes.py`

Find the streaming POST handler. It should be named something like `post_message` or `chat_stream` and decorated with `@router.post("/api/rag/sessions/{session_id}/messages")`.

**Step C.2: Locate the orchestrator-call line.**

Inside the handler there will be code like:
```python
async def event_generator():
    async for event in orchestrator.answer_stream(query, ...):
        yield format_sse(event)
```

**Step C.3: Wrap with `acquire_rerank_slot`.**

Replace the inner generator with:

```python
from website.api._concurrency import acquire_rerank_slot, QueueFull

async def event_generator():
    try:
        async with acquire_rerank_slot():
            async for event in orchestrator.answer_stream(query, ...):
                yield format_sse(event)
    except QueueFull:
        yield format_sse({"type": "error", "code": "queue_full", "retry_after": 5})
        # NOTE: 503 status is returned ONLY if we haven't started streaming.
        # Once streaming begins, we send the error as an SSE event instead.
```

For the pre-stream 503 path (so Cloudflare gets 503 before any `200 OK` is sent), wrap the route handler entry:

```python
@router.post("/api/rag/sessions/{session_id}/messages")
async def post_message(...):
    from website.api._concurrency import queue_depth, RAG_QUEUE_MAX
    if queue_depth() >= RAG_QUEUE_MAX:
        raise HTTPException(
            status_code=503,
            detail={"reason": "queue_full", "retry_after_seconds": 5},
            headers={"Retry-After": "5"},
        )
    # ... continue with streaming response ...
```

This gives two-tier protection: **pre-stream** = 503 with header; **mid-stream** = SSE error event.

---

## Appendix D: Task 1C.5 — full schema-drift implementation with all CLI flags

**Add these functions and flags to `ops/scripts/apply_migrations.py`:**

```python
# ==== Schema-drift detection (spec §3.5 atomic group #2) ====

import json as _json

def _introspect_schema(conn, schema: str = "public") -> dict:
    """Build a normalized snapshot of public-schema DB shape."""
    snap = {"tables": {}, "functions": {}, "indexes": {}, "constraints": {}}
    with conn.cursor() as cur:
        # Tables + columns
        cur.execute(
            "SELECT table_name, column_name, data_type, is_nullable, "
            "column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = %s "
            "ORDER BY table_name, ordinal_position",
            (schema,),
        )
        for tbl, col, dt, null, default in cur.fetchall():
            snap["tables"].setdefault(tbl, {"columns": {}, "primary_key": []})
            snap["tables"][tbl]["columns"][col] = {
                "type": dt,
                "nullable": null == "YES",
            }

        # Primary keys
        cur.execute("""
            SELECT tc.table_name, kcu.column_name
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
             WHERE tc.constraint_type = 'PRIMARY KEY'
               AND tc.table_schema = %s
             ORDER BY tc.table_name, kcu.ordinal_position
        """, (schema,))
        for tbl, col in cur.fetchall():
            if tbl in snap["tables"]:
                snap["tables"][tbl]["primary_key"].append(col)

        # Indexes
        cur.execute(
            "SELECT indexname, tablename, indexdef "
            "FROM pg_indexes WHERE schemaname = %s "
            "ORDER BY indexname",
            (schema,),
        )
        for name, tbl, ddef in cur.fetchall():
            snap["indexes"][name] = {"table": tbl, "definition": ddef}

        # Functions
        cur.execute("""
            SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' AS sig,
                   pg_get_function_result(p.oid) AS rettype,
                   p.prosecdef AS security_definer,
                   p.provolatile AS volatility
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = %s
             ORDER BY sig
        """, (schema,))
        for sig, rettype, secdef, vol in cur.fetchall():
            snap["functions"][sig] = {
                "return_type": rettype,
                "security_definer": bool(secdef),
                "volatility": {"i": "immutable", "s": "stable", "v": "volatile"}.get(vol, vol),
            }

    return snap


def _diff_schema(expected: dict, live: dict) -> list[str]:
    """Return human-readable drift lines; empty if no drift."""
    drift: list[str] = []

    # Tables / columns
    for tbl, spec in expected.get("tables", {}).items():
        if tbl not in live["tables"]:
            drift.append(f"missing table: {tbl}")
            continue
        for col, col_spec in spec.get("columns", {}).items():
            live_col = live["tables"][tbl]["columns"].get(col)
            if live_col is None:
                drift.append(f"missing column: {tbl}.{col}")
                continue
            if isinstance(col_spec, dict):
                if live_col.get("type") != col_spec.get("type"):
                    drift.append(f"type mismatch: {tbl}.{col} expected={col_spec.get('type')} live={live_col.get('type')}")
            else:
                # legacy flat string format
                if live_col.get("type") != col_spec:
                    drift.append(f"type mismatch: {tbl}.{col} expected={col_spec} live={live_col.get('type')}")

    # Functions
    for sig in expected.get("functions", {}):
        if sig not in live["functions"]:
            drift.append(f"missing function: {sig}")

    # Indexes (presence only; definitions can vary harmlessly)
    for idx in expected.get("indexes", {}):
        if idx not in live["indexes"]:
            drift.append(f"missing index: {idx}")

    return drift


def _verify_schema(conn, manifest_path: Path) -> int:
    if not manifest_path.exists():
        logger.error("expected_schema.json missing: %s", manifest_path)
        return 1
    expected = _json.loads(manifest_path.read_text(encoding="utf-8"))
    live = _introspect_schema(conn)
    drift = _diff_schema(expected, live)
    if drift:
        logger.error("[migration] SCHEMA DRIFT detected:")
        for d in drift:
            logger.error("  - %s", d)
        return 1
    logger.info("[migration] ✓ schema matches expected_schema.json")
    return 0


def _bootstrap_manifest(conn, manifest_path: Path) -> int:
    snap = _introspect_schema(conn)
    snap["schema_version"] = "<set-by-operator>"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("[migration] wrote %s", manifest_path)
    return 0


def _check_manifest_fresh(conn, manifest_path: Path) -> int:
    """CI gate: confirm checked-in manifest matches DB after applying all migrations.

    Used in `migrations-manifest-check` job: applies all migrations to a fresh
    Postgres-in-Docker, then asserts the resulting schema equals what's committed.
    Fails CI if a migration was added without updating expected_schema.json.
    """
    return _verify_schema(conn, manifest_path)
```

**Add CLI flags to `_parse_args`:**

```python
p.add_argument("--bootstrap-manifest", action="store_true",
               help="Write expected_schema.json from current live DB. One-shot.")
p.add_argument("--update-manifest", action="store_true",
               help="Re-emit expected_schema.json. Same as --bootstrap-manifest.")
p.add_argument("--check-manifest-fresh", action="store_true",
               help="CI mode: verify committed manifest matches live DB.")
p.add_argument("--check-dsn", action="store_true",
               help="Preflight: verify SUPABASE_DB_URL is set + connectable. Exit 0/2.")
```

**Add CLI dispatch to `main()` BEFORE the apply loop:**

```python
manifest_path = directory.parent / "expected_schema.json"

if args.check_dsn:
    return 0  # _build_dsn already raised if missing

if args.bootstrap_manifest or args.update_manifest:
    return _bootstrap_manifest(conn, manifest_path)

if args.check_manifest_fresh:
    return _check_manifest_fresh(conn, manifest_path)
```

**Add post-apply schema verification AFTER the apply loop (before `return rc`):**

```python
if rc == 0:
    drift_rc = _verify_schema(conn, manifest_path)
    if drift_rc != 0:
        rc = 1
```

---

## Appendix E: Task 2A.1 — exact critic prompt replacement

**Step E.1: Read current `_PROMPT` in `answer_critic.py`.**

Run: `grep -n "_PROMPT" website/features/rag_pipeline/critic/answer_critic.py | head -5`

You'll see `_PROMPT = """..."""` starting around line 15.

**Step E.2: Capture the exact existing string and JSON-parse expectations.**

Use Read tool to capture lines 1–80 of answer_critic.py. Note:
- The exact placeholder names (e.g., `{answer}` vs `{ANSWER}`).
- The exact JSON keys the parser expects: probably `verdict`, `reason`, possibly `confidence`.
- Whether the prompt uses XML-tagged citations like `<citation id="c1">...</citation>` or markdown.

**Step E.3: Replace with the new prompt PRESERVING those output contract details.**

If the existing prompt expects `{"verdict": ..., "reason": ...}`, the new prompt must produce the same shape. Example replacement:

```python
_PROMPT = """You are a verifier. Decide if the ANSWER is supported by the CITATIONS.

GUIDANCE (iter-03 §3.6):
- Be lenient on wording divergence. If citations semantically support the claim — even with paraphrasing, partial coverage, or summarization — verdict is "supported".
- Verdict is "partial" if citations support some claims but not all.
- Verdict is "unsupported" ONLY when no citation supports the central claim, OR citations contradict the answer, OR citations are empty.
- Stylistic mismatches (different wording, casual vs formal tone) are NOT grounds for "unsupported".
- An answer like "I cannot find that information" is "supported" only if citations truly are empty/irrelevant.

ANSWER:
{answer}

CITATIONS:
{citations}

Return ONLY this JSON object (no markdown fence):
{{"verdict": "supported"|"partial"|"unsupported", "reason": "<one short sentence>"}}.
"""
```

**Step E.4: Verify JSON parser handles all 3 verdicts.**

Find the parsing block (likely `json.loads(response.text)`) and confirm it accepts `partial` (some legacy parsers may have only handled `supported`/`unsupported`).

---

## Appendix F: Task 2A.2 — exact orchestrator retry-policy patch

**Step F.1: Outline orchestrator.py around line 434.**

Read lines 420–470 of `website/features/rag_pipeline/orchestrator.py` to find the existing retry block. It should look like:

```python
verdict_obj = await critic.verify(answer=draft, citations=citations)
if verdict_obj["verdict"] == "unsupported":
    if attempt == 0:
        # retry
        attempt += 1
        continue
    # second pass still unsupported — return canned refusal
    return _CANNED_REFUSAL_TEXT
```

(Exact variable names may differ — `verdict_obj` / `verdict` / `result`; capture the actual names before editing.)

**Step F.2: Replace the second-pass branch.**

```python
verdict_obj = await critic.verify(answer=draft, citations=citations)
if verdict_obj["verdict"] == "unsupported":
    if attempt == 0:
        attempt += 1
        continue
    # 2nd-pass still unsupported — return draft + low-confidence inline tag (spec §3.6 prong 2)
    low_conf_tag = (
        "\n\n<details>"
        "<summary>How sure am I?</summary>"
        "Citations don't fully cover this claim. The answer is the model's best draft."
        "</details>"
    )
    return draft + low_conf_tag
```

**Step F.3: Refusal preserved ONLY for empty retrieval.**

Find any path where `citations == []` or `len(retrieved) == 0`. That path should still return the canned refusal (because there's no draft to return). Verify by `grep -n 'CANNED_REFUSAL\|i can.{0,3}t find' website/features/rag_pipeline/`. Keep that path unchanged.

**Step F.4: Test fixture.**

Add to `tests/integration/rag/test_orchestrator_retry_policy.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_unsupported_returns_draft_with_tag():
    fake_critic = AsyncMock()
    fake_critic.verify = AsyncMock(return_value={"verdict": "unsupported", "reason": "weak"})

    with patch("website.features.rag_pipeline.critic.answer_critic.AnswerCritic", return_value=fake_critic):
        from website.features.rag_pipeline.orchestrator import answer_query
        result = await answer_query(
            query="any question",
            query_class="lookup",
            quality="high",
            _force_draft="Here is the model's best guess.",
        )
    assert "Here is the model's best guess." in result["text"]
    assert "How sure am I?" in result["text"]
    assert "I can't find" not in result["text"]


@pytest.mark.asyncio
async def test_empty_retrieval_still_returns_canned_refusal():
    with patch(
        "website.features.rag_pipeline.retrieval.hybrid.retrieve",
        return_value=[],
    ):
        from website.features.rag_pipeline.orchestrator import answer_query
        result = await answer_query(query="totally unrelated", query_class="lookup", quality="fast")
    assert "I can't find" in result["text"] or "no Zettels" in result["text"].lower()
```

---

## Appendix G: Task 2C.1 — orchestrator wiring of `_routing` (full)

**Step G.1: Read existing tier-selection code in orchestrator.py.**

Find the block that currently does something like:
```python
if quality == "high":
    model_chain = ["gemini-2.5-pro", "gemini-2.5-flash"]
else:
    model_chain = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
```

**Step G.2: Replace with `_routing.resolve_route`.**

```python
from website.features.rag_pipeline.generation._routing import (
    resolve_route, use_critic, use_hyde, retrieval_top_k,
)

force_pro = (request.query_params.get("force_pro") == "1") if hasattr(request, "query_params") else False
model_chain, max_input_tok, max_output_tok = resolve_route(
    query_class=detected_class,
    quality=quality,
    force_pro=force_pro,
)

top_k = retrieval_top_k(quality)
should_hyde = use_hyde(quality, detected_class)
should_critic = use_critic(quality)
```

**Step G.3: Pass `top_k` to retrieval.**

```python
candidates = await retrieve(query=query, top_k=top_k, ...)
```

**Step G.4: Gate HyDE and critic.**

```python
if should_hyde:
    expanded = await hyde_expand(query)
    # ... use expanded ...

# ... synthesizer call uses model_chain, max_input_tok, max_output_tok ...

if should_critic:
    verdict = await critic.verify(answer=draft, citations=citations)
    # ... existing retry logic ...
else:
    # Fast mode: skip critic — return draft directly
    return draft
```

**Step G.5: Surface `force_pro` to `chat_routes.py`.**

In `chat_routes.py`, capture the URL param and forward to orchestrator:

```python
@router.post("/api/rag/sessions/{session_id}/messages")
async def post_message(session_id: str, body: ChatMessageRequest, request: Request):
    force_pro = request.query_params.get("force_pro") == "1"
    # ... pass force_pro into orchestrator.answer_stream(...) ...
```

**Step G.6: Reduce SDK timeout.**

In `website/features/rag_pipeline/generation/gemini_backend.py`, find the per-call timeout configuration. It's likely:
```python
DEFAULT_TIMEOUT_SECONDS = 180
```
Change to:
```python
DEFAULT_TIMEOUT_SECONDS = 30
```

Then verify the chain-fallback logic does try the next model on timeout (read the `_call_with_chain` or equivalent function). If not, add:

```python
async def _call_with_chain(chain: list[str], prompt: str, **kw) -> str:
    last_exc = None
    for model in chain:
        try:
            return await _call_one(model, prompt, timeout=DEFAULT_TIMEOUT_SECONDS, **kw)
        except (asyncio.TimeoutError, RateLimitError) as e:
            last_exc = e
            logger.warning("model %s failed: %s — falling back", model, e)
            continue
    raise last_exc or RuntimeError("all models in chain failed")
```

---

## Appendix H: Task 3C.1 — full SSE consumeSSE with heartbeat

**Step H.1: Locate current consumeSSE.**

Read `website/features/user_rag/js/user_rag.js` lines 480–560. Capture the existing SSE-frame parsing logic. It typically looks like:

```javascript
async function consumeSSE(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const frames = buf.split('\n\n');
        buf = frames.pop();
        for (const frame of frames) {
            if (!frame.trim()) continue;
            // parse "event: foo\ndata: {...}"
            const lines = frame.split('\n');
            let eventType = 'message';
            let data = '';
            for (const line of lines) {
                if (line.startsWith('event:')) eventType = line.slice(6).trim();
                else if (line.startsWith('data:')) data += line.slice(5).trim();
            }
            try {
                const payload = JSON.parse(data);
                onEvent(eventType, payload);
            } catch (e) { /* skip malformed */ }
        }
    }
}
```

**Step H.2: Full heartbeat-aware replacement.**

```javascript
const HEARTBEAT_TIMEOUT_MS = 15000;  // 15s of silence → dead

async function consumeSSE(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let lastFrameMs = Date.now();
    let doneSeen = false;

    // Watchdog: if no frame for 15s and stream not done, cancel
    const watchdog = setInterval(() => {
        if (!doneSeen && Date.now() - lastFrameMs > HEARTBEAT_TIMEOUT_MS) {
            clearInterval(watchdog);
            reader.cancel('heartbeat-timeout').catch(() => {});
        }
    }, 5000);

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            lastFrameMs = Date.now();
            buf += decoder.decode(value, { stream: true });
            const frames = buf.split('\n\n');
            buf = frames.pop();
            for (const frame of frames) {
                const trimmed = frame.trim();
                if (!trimmed) continue;
                // SSE comments (`:heartbeat`) — server keepalive — skip
                if (trimmed.startsWith(':')) continue;
                const lines = trimmed.split('\n');
                let eventType = 'message';
                let data = '';
                for (const line of lines) {
                    if (line.startsWith('event:')) eventType = line.slice(6).trim();
                    else if (line.startsWith('data:')) data += line.slice(5).trim();
                }
                try {
                    const payload = data ? JSON.parse(data) : null;
                    onEvent(eventType, payload);
                    if (eventType === 'done') doneSeen = true;
                } catch (e) {
                    console.warn('SSE parse error', e, frame);
                }
            }
        }
    } finally {
        clearInterval(watchdog);
    }
}
```

**Step H.3: Auto-retry wrapper.**

```javascript
async function askWithRetry(payload, sessionId) {
    const url = `/api/rag/sessions/${sessionId}/messages`;
    let attempt = 0;
    const MAX_ATTEMPTS = 2;

    while (attempt < MAX_ATTEMPTS) {
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (response.status === 503) {
                const retryAfter = parseInt(response.headers.get('Retry-After') || '5', 10);
                showQueuedNotice(retryAfter);
                await new Promise(r => setTimeout(r, retryAfter * 1000));
                attempt += 1;
                continue;
            }

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            await consumeSSE(response, dispatchEvent);
            return;
        } catch (err) {
            if (err.message === 'heartbeat-timeout' && attempt === 0) {
                showHeartbeatLoader(els.statusContainer, () => {});
                await new Promise(r => setTimeout(r, 1000));
                attempt += 1;
                continue;
            }
            throw err;
        }
    }
    throw new Error('max retries exceeded');
}
```

**Step H.4: Test.**

```javascript
// tests/e2e/test_sse_heartbeat.spec.js (Playwright)
test('heartbeat retry fires after 15s silence', async ({ page }) => {
    await page.goto('http://localhost:10000/rag');
    // Mock fetch to return a stream that never sends frames
    await page.route('**/api/rag/sessions/*/messages', route => {
        route.fulfill({
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
            body: ':heartbeat\n\n', // single heartbeat then silence
        });
    });
    await page.fill('#composer-input', 'test query');
    await page.click('#send-btn');
    await page.waitForSelector('.kasten-shuffle.heartbeat', { timeout: 20_000 });
    expect(await page.locator('.kasten-shuffle.heartbeat .caption').textContent())
        .toContain('Reconnecting');
});
```

---

## Appendix I: Task 4A.1 — eval_runner per-stage metrics (full implementation)

**Step I.1: Outline current `eval_runner.py`.**

Run: `mcp__plugin_mem-vault_mem-vault__smart_outline website/features/rag_pipeline/evaluation/eval_runner.py`

Find `EvalRunner.evaluate()`. It probably loops over queries and calls `orchestrator.answer_query()` collecting `{query, answer, citations}` records.

**Step I.2: Capture per-stage timing via `trace_stage`.**

Existing `trace_stage` decorator in orchestrator emits stage-completion events. Wire those into the answer record:

```python
async def evaluate(self, queries: list[GoldQuery]) -> dict:
    results = []
    for q in queries:
        stage_metrics: dict = {}

        async def _capture_stage(stage_name: str, payload: dict) -> None:
            stage_metrics.setdefault(stage_name, {}).update(payload)

        # Pass capturing hook into orchestrator
        answer = await orchestrator.answer_query(
            query=q.text,
            query_class=q.query_class,
            quality=q.quality,
            _stage_capture=_capture_stage,  # new param: orchestrator emits per-stage payloads here
        )

        # Compute derived metrics
        per_stage = {
            "query_class_detected": stage_metrics.get("query_routing", {}).get("class"),
            "retrieval_recall_at_10": _compute_recall_at_k(answer["candidates"][:10], q.gold_chunk_ids),
            "reranker_top1_top2_margin": (
                answer["reranker_scores"][0] - answer["reranker_scores"][1]
                if len(answer.get("reranker_scores", [])) >= 2 else None
            ),
            "synthesizer_grounding_pct": stage_metrics.get("critic", {}).get("grounding_pct"),
            "critic_verdict": stage_metrics.get("critic", {}).get("verdict"),
            "model_chain_used": stage_metrics.get("synthesizer", {}).get("model_chain"),
            "evidence_compression_ratio": stage_metrics.get("compression", {}).get("ratio"),
            "latency_ms": {
                "retrieval": stage_metrics.get("retrieval", {}).get("ms"),
                "rerank": stage_metrics.get("rerank", {}).get("ms"),
                "synth": stage_metrics.get("synthesizer", {}).get("ms"),
                "critic": stage_metrics.get("critic", {}).get("ms"),
                "total": stage_metrics.get("total", {}).get("ms"),
            },
        }

        record = {
            "query_id": q.id,
            "query": q.text,
            "answer": answer["text"],
            "citations": answer["citations"],
            "per_stage": per_stage,
        }
        results.append(record)

    return {"answers": results}


def _compute_recall_at_k(candidates: list[dict], gold_ids: list[str]) -> float | None:
    if not gold_ids:
        return None
    candidate_ids = {c.get("chunk_id") or c.get("id") for c in candidates}
    hits = candidate_ids.intersection(gold_ids)
    return len(hits) / len(gold_ids)
```

**Step I.3: Wire `_stage_capture` into orchestrator.**

In `orchestrator.answer_query`, accept the optional kwarg and emit at each stage boundary:

```python
async def answer_query(query, query_class, quality, *, _stage_capture=None, **kw):
    async def emit(stage: str, payload: dict) -> None:
        if _stage_capture:
            await _stage_capture(stage, payload)

    t0 = time.perf_counter()
    candidates = await retrieve(query=query, top_k=top_k)
    await emit("retrieval", {"ms": (time.perf_counter() - t0) * 1000, "n_candidates": len(candidates)})

    # ... etc for rerank, synth, critic, total ...
```

**Step I.4: Test record shape.**

```python
def test_eval_record_has_per_stage_fields():
    runner = EvalRunner()
    out = asyncio.run(runner.evaluate([sample_query]))
    rec = out["answers"][0]
    assert "per_stage" in rec
    for key in ["retrieval_recall_at_10", "reranker_top1_top2_margin", "synthesizer_grounding_pct",
                "critic_verdict", "query_class_detected", "model_chain_used", "latency_ms"]:
        assert key in rec["per_stage"], f"missing {key}"
```

---

## Appendix J: Task 4D.1 — Claude in Chrome MCP walkthrough (full)

The main plan referenced "mcp_client" abstractly. Here is the concrete usage with the `mcp__Claude_in_Chrome__*` toolchain.

**Step J.1: Pre-flight — confirm browser is connected.**

Before running, manually verify:
1. Claude Desktop has the Claude in Chrome extension active.
2. Chrome is logged in as Naruto at `https://zettelkasten.in/` (per `<private>login_details.txt</private>`).
3. The `mcp__Claude_in_Chrome__*` tool family is available in the active session.

If logged out: navigate to `https://zettelkasten.in/`, click the login dropdown, sign in with Naruto creds.

**Step J.2: Verification script content.**

```python
"""End-to-end browser verification via Claude in Chrome MCP.

Run AFTER the iter-03/all branch is merged and the deploy has finished.
Naruto must already be logged in via the Chrome extension.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ITER_DIR = ROOT / "docs" / "rag_eval" / "knowledge-management" / "iter-03"
SCREENSHOTS_DIR = ITER_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("verify_iter_03")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# Note: this script is designed to be invoked from a Claude Code session that has
# the Claude in Chrome MCP server registered. It calls the tool-family directly
# via stdin/stdout protocol by writing tool-invocation requests as JSON to a
# helper queue. The harness implementation:
#
# In practice, this script is a checklist that the operator runs interactively
# from a Claude Code session, NOT a fully-automated headless harness. The MCP
# client surface is async/conversational, not subprocess-friendly.
#
# Therefore this file is a sequence of TOOL-CALL specifications + PASS-FAIL
# assertions that an operator pastes into Claude Code, which then drives the
# browser via Claude in Chrome.

CHECKLIST: list[dict] = [
    {
        "step": 1,
        "name": "kasten_chooser",
        "actions": [
            ("navigate", {"url": "https://zettelkasten.in/rag"}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "01_chooser.png")}),
        ],
        "assertions": [
            ("page_contains_text", "Knowledge Management"),
        ],
    },
    {
        "step": 2,
        "name": "chat_composer_placeholder",
        "actions": [
            ("preview_click", {"selector": "[data-kasten-name='Knowledge Management']"}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "02_chat_composer.png")}),
        ],
        "assertions": [
            ("input_placeholder_contains", {"selector": "#composer-input", "text": "Knowledge Management"}),
            ("input_placeholder_contains", {"selector": "#composer-input", "text": "something"}),
        ],
    },
    {
        "step": 3,
        "name": "run_13_eval_queries",
        "expand": "QUERY_LOOP",  # operator runs each of the 13 queries; see code below
    },
    {
        "step": 4,
        "name": "strong_toggle_critic_loop",
        "actions": [
            ("preview_eval", {"js": "document.querySelector('#qualitySelect').value='high'; document.querySelector('#qualitySelect').dispatchEvent(new Event('change'));"}),
            ("preview_fill", {"selector": "#composer-input", "value": "What are the main themes in my Zettels?"}),
            ("preview_click", {"selector": "#send-btn"}),
            ("wait_for_selector", {"selector": ".rag-message[data-role='assistant'].complete", "timeout_ms": 70000}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "04_strong_critic.png")}),
        ],
        "assertions": [
            # Verified later via answers.json: critic_verdict field present
        ],
    },
    {
        "step": 5,
        "name": "add_zettels_select_all",
        "actions": [
            ("preview_click", {"selector": "#open-add-modal"}),
            ("wait_for_selector", {"selector": "#add-select-all"}),
            ("preview_click", {"selector": "#add-select-all"}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "05_select_all.png")}),
        ],
        "assertions": [
            ("counter_matches_total", {"selector": "#add-counter"}),
        ],
    },
    {
        "step": 6,
        "name": "heartbeat_retry",
        "actions": [
            # Trigger by closing TCP connection mid-stream — operator runs:
            #   ssh droplet 'docker pause zettelkasten-blue'
            # then sends a query, waits 16s, then runs:
            #   ssh droplet 'docker unpause zettelkasten-blue'
            ("preview_fill", {"selector": "#composer-input", "value": "Test heartbeat retry"}),
            ("preview_click", {"selector": "#send-btn"}),
            ("wait_for_selector", {"selector": ".kasten-shuffle.heartbeat", "timeout_ms": 20000}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "06_heartbeat_retry.png")}),
        ],
        "assertions": [
            ("element_color_is_teal", {"selector": ".kasten-shuffle.heartbeat .card"}),
        ],
    },
    {
        "step": 7,
        "name": "queue_503_ux",
        "actions": [
            # Fire 12 concurrent submits via JS
            ("preview_eval", {"js": """
                const promises = [];
                for (let i = 0; i < 12; i++) {
                    promises.push(fetch('/api/rag/sessions/x/messages', {
                        method: 'POST',
                        headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({message: 'burst' + i}),
                    }));
                }
                return Promise.all(promises).then(rs => rs.map(r => r.status));
            """}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "07_queue_503.png")}),
        ],
        "assertions": [
            ("response_codes_include", {"code": 503}),
            ("element_visible", {"selector": ".rag-queued-notice"}),
        ],
    },
    {
        "step": 8,
        "name": "debug_panel_hidden_in_prod",
        "actions": [
            ("navigate", {"url": "https://zettelkasten.in/rag?debug=1"}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "08_no_debug_panel.png")}),
        ],
        "assertions": [
            ("element_not_present", {"selector": ".rag-debug-panel"}),
        ],
    },
    {
        "step": 9,
        "name": "schema_drift_gate_fires",
        "actions": [
            # NOT a browser action — done via gh workflow run + log inspection.
            # Operator: edit expected_schema.json to add a fake column, push, watch deploy fail.
            # Documented in verification.md, no screenshot.
        ],
        "assertions": [
            ("manual_check", "Operator confirms intentional drift caused deploy abort"),
        ],
    },
    {
        "step": 10,
        "name": "sse_survives_blue_green_cutover",
        "actions": [
            ("preview_fill", {"selector": "#composer-input", "value": "Long thematic question that triggers Pro tier"}),
            ("preview_eval", {"js": "document.querySelector('#qualitySelect').value='high'; document.querySelector('#qualitySelect').dispatchEvent(new Event('change'));"}),
            ("preview_click", {"selector": "#send-btn"}),
            # While streaming: operator triggers a deploy in another terminal:
            #   gh workflow run deploy-droplet.yml --ref master
            ("wait_for_selector", {"selector": ".rag-message[data-role='assistant'].complete", "timeout_ms": 90000}),
            ("preview_screenshot", {"path": str(SCREENSHOTS_DIR / "10_sse_cutover.png")}),
        ],
        "assertions": [
            ("element_text_not_contains", {"selector": ".rag-message[data-role='assistant']", "text": "Lost connection"}),
        ],
    },
]


def render_checklist_md() -> str:
    lines = ["# Iter-03 Verification Results", "",
             f"Captured: {datetime.now(timezone.utc).isoformat()}", "",
             "| # | Check | Status | Evidence |",
             "|---|---|---|---|"]
    for c in CHECKLIST:
        lines.append(f"| {c['step']} | {c['name']} | ⏳ pending | screenshots/{c['step']:02d}_*.png |")
    return "\n".join(lines)


def main() -> int:
    md = render_checklist_md()
    (ITER_DIR / "verification.md").write_text(md, encoding="utf-8")

    # Print operator instructions
    print("=" * 60)
    print("Iter-03 verification harness")
    print("=" * 60)
    print()
    print("Open Claude Code with the Claude in Chrome MCP server registered.")
    print("Confirm Naruto is logged into https://zettelkasten.in in Chrome.")
    print()
    print("Then for each step in the CHECKLIST list (above), run the actions")
    print("via the matching mcp__Claude_in_Chrome__* tool calls. After each step,")
    print("check the assertions and update verification.md with ✅ or ❌.")
    print()
    print("13 eval queries are loaded from:")
    print(f"  {ITER_DIR / 'queries.json'}")
    print("Run them in step 3 by:")
    print("  for each query, fill #composer-input, click #send-btn,")
    print("  wait for .rag-message[data-role='assistant'].complete,")
    print(f"  screenshot to {SCREENSHOTS_DIR}/03_q_<id>.png")
    print()
    print("After all 10 steps capture answers.json from the iter-03 eval run:")
    print("  python ops/scripts/rag_eval_loop.py \\")
    print("    --queries docs/rag_eval/knowledge-management/iter-03/queries.json \\")
    print("    --baseline docs/rag_eval/knowledge-management/iter-03/baseline.json \\")
    print("    --target-host https://zettelkasten.in \\")
    print("    --emit-final-answers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step J.3: Operator interactive flow.**

The operator pastes each step into Claude Code, which then invokes the matching `mcp__Claude_in_Chrome__*` tools (e.g. `mcp__Claude_in_Chrome__navigate`, `mcp__Claude_in_Chrome__find`, `mcp__Claude_in_Chrome__form_input`, `mcp__Claude_in_Chrome__shortcuts_execute`, `mcp__Claude_in_Chrome__read_page`). The script provides the spec; the human or LLM dispatches.

For pure automation (CI rerunnability) **defer** to a follow-up iter — the MCP client surface in 2026-04 is conversational, not subprocess-driven.

**Step J.4: After all 10 steps complete, update verification.md.**

For each step, replace `⏳ pending` with `✅ pass` or `❌ fail` + brief evidence line. Commit the updated `verification.md` and all screenshots.

---

## Final executor checklist (read before claiming iter-03 done)

This consolidates the per-task verification gates:

- [ ] **Quantization gate** — `python ops/scripts/validate_quantization.py` exits 0
- [ ] **Schema-drift gate** — `python ops/scripts/apply_migrations.py --check-manifest-fresh` against fresh Postgres-in-Docker exits 0
- [ ] **Single-tenant allowlist gate** — deploy.sh runs the allowlist Python check and exits 0
- [ ] **Test suite** — `python -m pytest tests/ -q` 100% pass
- [ ] **Per-class regression suite** — `python -m pytest tests/integration/rag/per_class_regression/ -v --live` all 5 pass
- [ ] **Eval gate** — `python ops/scripts/rag_eval_loop.py --enforce-gates` exits 0 (gold@1 ≥ baseline + 5pp)
- [ ] **Burst test** — `hey -n 50 -c 10 -m POST ... /api/rag/sessions/x/messages` returns no 502s; only 200s and 503-Retry-After
- [ ] **`docker stats`** under burst stays <80% RAM, <90% CPU
- [ ] **Browser verification** — all 10 steps in `verification.md` are ✅
- [ ] **Action-verb anchor queries (av-1/av-2/av-3)** picked github or web zettel as top-1
- [ ] **No "I can't find" refusals** in the 13 iter-03 answers
- [ ] **Strong/Fast difference visible in answers.json** (`per_stage.critic_verdict` set for `quality=high`, null for `quality=fast`)
- [ ] **SSE blue→green cutover** verified (long Pro answer survives a deploy)
- [ ] **mem-vault observations saved**: 5+ feature, 3+ decision, 1 chapter mark
