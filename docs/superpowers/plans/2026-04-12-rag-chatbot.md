# RAG Chatbot — Implementation Plan

**Date:** 2026-04-12
**Spec:** [`docs/superpowers/specs/2026-04-12-rag-chatbot-design.md`](../specs/2026-04-12-rag-chatbot-design.md) (commit `987c40e`, 3500+ lines)
**Mode:** Documentation-only — execute manually at your own pace
**Granularity:** TDD-strict — one failing test → one implementation → green, per task
**Phases:** 9 (Phase 0 Preflight + 8 rollout phases from spec §10)
**Rollback:** Every phase has a single-command rollback described inline

---

## 0. How to read this plan

Each **phase** is a self-contained work session. Phases are ordered; do not skip. Each phase has:

- **Goal** — one sentence, the "definition of done"
- **Dependencies** — what the prior phase must have delivered
- **Phase 0 docs discovery** (for each implementation phase) — cite exact doc locations, grep commands, and spec sections to read BEFORE writing code
- **Tasks** — numbered TDD cycles: each task is `test → implement → green → commit` (one commit per task unless noted)
- **Verification gate** — how to prove the phase is done (tests to run, greps to perform, acceptance criteria)
- **Anti-pattern guards** — what NOT to do (invented APIs, wrong imports, skipped tests)
- **Rollback** — single command to undo the phase

Each task links back to a specific `§X.Y` of the spec so you never write code without a source of truth.

### 0.1 TDD rule of thumb (applies to every task)

For every task:

1. **Red**: write the failing test first. Assert the exact behavior you want. Run the test, see it fail on the *correct* error (missing import / wrong return / missing file). If it fails on an unexpected error, fix the test first.
2. **Green**: write the minimum code to make the test pass. No extra features, no speculative error handling, no unused abstractions. Keep imports minimal.
3. **Refactor**: only if the code has an obvious smell (duplicated logic, overly long function, unclear naming). Never refactor code from another task.
4. **Commit**: `git add <changed files> && git commit -m "<type>(<scope>): <imperative, ≤10 words>"`. One task = one commit unless a task is split across two files and can't be partially committed.

**Commit-message rules** (from `CLAUDE.md`):
- Max 10 words. `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:` prefixes counted.
- No `Co-Authored-By:` trailers. No AI tool names.
- When a commit implements a prior-session decision, append the observation ID: `feat(rag): key-rotation stream (#S155)`.

### 0.2 Anti-patterns to never do (applies to every task)

- **Do not invent APIs**: if a method isn't in the spec or the documentation discovery output, read the docs before calling it. No `.embed_batch`, no `generate_content_stream` on `GeminiKeyPool`, no `langfuse_context`. Use only the verified interfaces in spec §3.7.
- **Do not mock `get_settings()`** — always patch it via `@patch` per `CLAUDE.md`. Calling the real one in a test exits the process.
- **Do not bypass the adapter layer** (spec §3.7): all Gemini calls go through `website/core/rag/adapters/pool_factory.py` + the two helper adapters. Never import `google.generativeai` directly from RAG business logic.
- **Do not add Supabase tables/columns outside the 5 migrations** — schema drift from the spec is a review-blocker.
- **Do not skip `CREATE INDEX CONCURRENTLY`** on HNSW migrations. Blocks writes on prod.
- **Do not commit secrets**: wrap any `.env*` content in `<private>...</private>` tags per `CLAUDE.md`.
- **Do not update `key_pool.py`** to add streaming or async batching. The adapter layer exists precisely to avoid touching it.
- **Do not write tests that hit real Supabase/Gemini/TEI** unless marked `@pytest.mark.live` and opt-in via `--live`.

### 0.3 Terminology

- **The spec** = `docs/superpowers/specs/2026-04-12-rag-chatbot-design.md`
- **Existing code** = whatever is currently on `master` before this plan starts
- **Adapter layer** = `website/core/rag/adapters/` (new in this plan; spec §3.7)
- **Phase 3 target** = the internal-only retrieval core, no public surface
- **Phase 5 target** = the first user-visible web endpoint

---

## Phase 0 — Preflight, Documentation Discovery, Fixtures

**Goal:** Before any code is written, verify every external assumption the spec makes. Generate fixtures. Confirm pgvector version. No production changes.

**Dependencies:** none.

**Deliverables:**
- `tests/eval/ragas/fixtures/synthetic_corpus.json` (50 fake Zettels)
- `tests/eval/ragas/fixtures/golden_qa.json` (30 Q/A pairs in RAGAS 0.4 schema)
- `docs/superpowers/plans/2026-04-12-rag-chatbot-preflight-report.md` — a short file recording each verification's outcome
- Confirmed pgvector version on prod Supabase (captured in the report)

### Task 0.1 — Verify pgvector ≥ 0.8 on prod Supabase

**What to do:** run `SELECT extversion FROM pg_extension WHERE extname = 'vector';` against the production Supabase instance (via the Supabase SQL editor or `psql`). Record the result in the preflight report.

**Docs reference:** spec §13 open question #1.

**Acceptance:** version string is ≥ `0.8.0`. If it's less, stop and upgrade Supabase before proceeding. If upgrade is blocked, open a separate decision doc about the multi-tenant HNSW recall degradation workaround (post-filter CTE). **Do not proceed past this task if the version is unconfirmed.**

**Rollback:** n/a (read-only query).

---

### Task 0.2 — Verify Chonkie `BaseEmbeddings` abstract contract

**What to do:** create a scratch venv, install `chonkie`, read the `BaseEmbeddings` source:

```bash
python -m venv /tmp/chonkie-verify
source /tmp/chonkie-verify/Scripts/activate   # or .../bin/activate on Linux
pip install chonkie
python -c "import chonkie.embeddings; help(chonkie.embeddings.BaseEmbeddings)"
```

Record the exact abstract method names and return types in the preflight report. If Chonkie ships an official `chonkie[gemini]` extra with a `GeminiEmbeddings` class that works with an API-key-based Gemini client, note that — `GeminiChonkieEmbeddings` (spec §3.7.2) may become a no-op wrapper.

**Docs reference:** spec §13 open question #5.

**Acceptance:** a verbatim list of required methods in the report. The adapter in Task 2.5 will implement exactly those.

---

### Task 0.3 — Verify TEI supports `BAAI/bge-reranker-v2-m3`

**What to do:** run a one-off Docker container and curl the `/rerank` endpoint:

```bash
docker run --rm -p 8080:8080 \
  -v /tmp/tei-models:/data \
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.9 \
  --model-id BAAI/bge-reranker-v2-m3 --port 8080
# In another terminal, wait for "Ready" log line, then:
curl http://localhost:8080/rerank -X POST \
  -H 'Content-Type: application/json' \
  -d '{"query":"what is attention","texts":["attention is all you need","a recipe for pancakes"]}'
```

Record: (a) does the container load the model without crashing; (b) what is the exact response JSON shape; (c) does `/health` or `/healthz` return 200. Capture all three in the preflight report.

**If the model fails to load**, fall back to `BAAI/bge-reranker-large` for Phase 3. Document the substitution in the preflight report and update the `command:` block in `ops/docker-compose.{blue,green}.yml` during Phase 3.

**Docs reference:** spec §13 open question #2, #3, #4.

**Acceptance:** 3 answers recorded.

---

### Task 0.4 — Verify Langfuse v3 `@observe` on async generators

**What to do:** scratch venv, install `langfuse>=3.0.0,<4`, write this 20-line script and run it:

```python
# /tmp/langfuse-verify.py
import asyncio, os
os.environ["LANGFUSE_PUBLIC_KEY"] = "dummy"
os.environ["LANGFUSE_SECRET_KEY"] = "dummy"
os.environ["LANGFUSE_BASE_URL"]   = "http://localhost:3000"  # no-op if not running
from langfuse import observe, get_client

@observe(name="gen-test")
async def gen():
    for i in range(3):
        yield i

async def main():
    async for x in gen():
        print(x)
    print("trace_id:", get_client().get_current_trace_id())

asyncio.run(main())
```

Expected: prints `0 1 2 trace_id: <None or a uuid>`. If it errors with "cannot decorate async generator", the orchestrator's `@observe(name="rag.answer_stream")` pattern needs a workaround (flag it in the preflight report).

**Docs reference:** spec §13 open question #6.

**Acceptance:** one of (a) decorator works on async generators → proceed as spec says; (b) it doesn't → document a manual trace pattern (`with langfuse.start_as_current_span(...)`) to use instead in Phase 7.

---

### Task 0.5 — Verify RAGAS 0.4.3 Gemini judge via `LangchainLLMWrapper`

**What to do:** scratch venv, install `ragas==0.4.3 langchain-google-genai`, run:

```python
# /tmp/ragas-verify.py
import os
from ragas.llms import LangchainLLMWrapper
from langchain_google_genai import ChatGoogleGenerativeAI
from ragas.metrics.collections import Faithfulness
from ragas import EvaluationDataset, evaluate

judge = LangchainLLMWrapper(
    ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.environ["GEMINI_API_KEY"]),
)
ds = EvaluationDataset.from_list([{
    "user_input": "What is attention?",
    "retrieved_contexts": ["Attention is all you need. The attention mechanism..."],
    "response": "Attention is a neural network mechanism.",
    "reference": "Attention is a core component of transformers.",
}])
result = evaluate(dataset=ds, metrics=[Faithfulness()], llm=judge)
print(result)
```

Expected: a score between 0 and 1 prints. If the wrapper pattern fails, fall back to LiteLLM + Vertex (spec §6.3 alt path) — document which path was chosen.

**Docs reference:** spec §13 open question #9.

**Acceptance:** either path works end-to-end; note which one in the report.

---

### Task 0.6 — Generate synthetic corpus fixture

**What to do:** write a one-shot Python script `tests/eval/ragas/bootstrap_fixtures.py` (not run in CI, committed only for reproducibility) that produces `synthetic_corpus.json`:

```python
# Pseudocode — expand manually, not via agent.
# Goal: 50 fake Zettels that look like the real KG schema, across 5 topics:
# - machine learning (20 zettels: 12 YouTube transcripts 100-500w, 4 Substack 300-800w, 2 arXiv summaries, 2 Reddit comments)
# - cooking (10 zettels: 6 YouTube 100-400w, 2 Substack 300w, 2 Twitter threads)
# - history (10 zettels)
# - finance (5 zettels)
# - travel (5 zettels)
#
# Each entry matches the kg_nodes row shape: id, user_id=TEST_USER_UUID,
# name, source_type, summary, tags, url, node_date, metadata={}.
# Text is hand-authored or LLM-generated once and frozen in-repo.
# DO NOT re-generate on every test run.
```

Commit both the script AND the generated `synthetic_corpus.json`. The script is for reproducibility; the JSON is the source of truth for all future eval runs.

**Acceptance:** `synthetic_corpus.json` exists with 50 entries, `jq length synthetic_corpus.json` returns 50.

---

### Task 0.7 — Generate golden Q/A fixture (RAGAS 0.4 schema)

**What to do:** manual task. Write 30 Q/A pairs by hand where each Q can be answered from 1–4 of the synthetic Zettels in Task 0.6. Use the **exact** RAGAS 0.4 column names:

```json
[
  {
    "user_input": "What does the Attention Is All You Need paper propose?",
    "retrieved_contexts": [],
    "response": "It proposes the Transformer architecture based entirely on self-attention...",
    "reference": "The Transformer architecture using self-attention, dispensing with recurrence and convolutions.",
    "ground_truth_support": ["yt-attention-is-all-you-need", "ss-transformer-math-primer"]
  },
  ...
]
```

`retrieved_contexts` stays empty at authoring time — the eval harness fills it per run by calling the retrieval pipeline. `ground_truth_support` is the oracle we measure context recall against. Column order doesn't matter.

**Acceptance:** `golden_qa.json` has 30 entries, each with all 5 fields.

---

### Task 0.8 — Write the preflight report

**What to do:** consolidate outcomes of 0.1–0.7 into `docs/superpowers/plans/2026-04-12-rag-chatbot-preflight-report.md`. Sections: pgvector version, Chonkie abstract contract, TEI smoke-test results, Langfuse async-generator outcome, RAGAS judge path, fixtures row counts. One commit.

**Acceptance:** the report exists and every row has a "verified / not verified / blocked" tag. No unresolved blockers before proceeding.

### Phase 0 verification gate

Before moving to Phase 1, confirm:

- [ ] pgvector ≥ 0.8 verified
- [ ] Chonkie `BaseEmbeddings` abstract methods documented
- [ ] TEI + BGE smoke-test passed (or fallback to `bge-reranker-large` recorded)
- [ ] Langfuse `@observe` on async-generator outcome recorded
- [ ] RAGAS Gemini judge path decided and verified
- [ ] Fixtures committed (50 + 30 entries)
- [ ] Preflight report committed

**Rollback:** `git reset --hard <commit before Phase 0>`. No production changes made.

---

## Phase 1 — SQL migrations 001–005

**Goal:** Apply all 5 migrations from spec §2 to the production Supabase database without blocking any writes or breaking any existing functionality. Zero Python code changes.

**Dependencies:** Phase 0 complete, pgvector ≥ 0.8 confirmed.

**Deliverables:** 5 migration files committed under `supabase/website/rag_chatbot/`, all applied to prod, all new tables/RPCs callable from `psql`.

### Phase 0 docs discovery (for Phase 1)

Before writing SQL:

1. **Read the spec sections verbatim:** §2.1 (Migration 001), §2.2 (Migration 002), §2.3 (Migration 003), §2.4 (Migration 004), §2.5 (Migration 005).
2. **Read the existing schema** for pattern copies:
   - `supabase/website/kg_public/schema.sql` — RLS policy pattern for `kg_nodes`, `kg_links`, `kg_users` (copy this exact shape)
   - `supabase/website/kg_features/001_intelligence.sql:14-16` — current IVFFlat index declaration (must be dropped)
   - `supabase/website/kg_features/001_intelligence.sql:161-235` — `find_neighbors` recursive CTE (mirror pattern in `rag_hybrid_search` graph_walk CTE)
   - `supabase/website/kg_features/001_intelligence.sql:531-651` — current `hybrid_kg_search` RPC (template for the new RPC)
3. **Verify the spec's SQL** compiles by pasting each migration into a local Postgres with pgvector 0.8 before running against prod.

### Task 1.1 — Create `supabase/website/rag_chatbot/001_hnsw_migration.sql`

**What to do:** copy verbatim from spec §2.1 into the new file. One file.

**Docs reference:** spec §2.1.

**Test (manual, since this is a migration):** run the migration against a local Postgres fork of prod. After it applies, run:
```sql
SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_kg_nodes_embedding_hnsw';
-- Expect: CREATE INDEX idx_kg_nodes_embedding_hnsw ON public.kg_nodes
--         USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')
SHOW hnsw.iterative_scan;
-- Expect: strict_order
```

**Anti-pattern guard:** do NOT wrap the `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY` in a transaction. Supabase SQL editor: paste statements one at a time. If you script it, use `psql --no-psqlrc -c "<stmt>"` per statement.

**Commit:** `feat(rag): HNSW migration 001 for kg_nodes.embedding`

---

### Task 1.2 — Create `002_chunks_table.sql`

**What to do:** copy verbatim from spec §2.2. One file.

**Docs reference:** spec §2.2.

**Test (manual):** after applying to local Postgres:
```sql
\d kg_node_chunks              -- confirm all 13 columns
SELECT COUNT(*) FROM kg_node_chunks;  -- expect 0
-- Confirm HNSW index exists and FTS GIN index exists:
SELECT indexname FROM pg_indexes WHERE tablename = 'kg_node_chunks';
-- Confirm the FTS trigger fires:
INSERT INTO kg_node_chunks (user_id, node_id, chunk_idx, content, content_hash, chunk_type, embedding)
VALUES ('<existing user uuid>', '<existing node id>', 0, 'hello world', '\x00', 'atomic', ARRAY[...]::vector);
SELECT fts FROM kg_node_chunks WHERE chunk_idx = 0;  -- expect non-null tsvector
-- Cleanup:
DELETE FROM kg_node_chunks WHERE chunk_idx = 0;
```

**Commit:** `feat(rag): kg_node_chunks table migration 002`

---

### Task 1.3 — Create `003_sandboxes.sql`

**What to do:** copy verbatim from spec §2.3, including the `rag_sandbox_stats` view and ALL 10 RLS policies. One file.

**Docs reference:** spec §2.3.

**Test (manual):**
```sql
-- Insert test sandbox via service role (bypasses RLS)
INSERT INTO rag_sandboxes (user_id, name) VALUES ('<test user uuid>', 'test-sandbox');
SELECT * FROM rag_sandbox_stats WHERE name = 'test-sandbox';  -- expect member_count=0
-- Test the member FK cascade:
INSERT INTO rag_sandbox_members (sandbox_id, user_id, node_id)
SELECT id, '<test user uuid>', '<existing node id>' FROM rag_sandboxes WHERE name = 'test-sandbox';
SELECT member_count FROM rag_sandbox_stats WHERE name = 'test-sandbox';  -- expect 1
-- Delete the sandbox, confirm members cascade:
DELETE FROM rag_sandboxes WHERE name = 'test-sandbox';
SELECT COUNT(*) FROM rag_sandbox_members WHERE user_id = '<test user uuid>';  -- expect 0
```

**Commit:** `feat(rag): sandboxes + members migration 003`

---

### Task 1.4 — Create `004_chat_sessions.sql`

**What to do:** copy verbatim from spec §2.4, including the stats-update trigger and RLS pattern. One file.

**Docs reference:** spec §2.4.

**Test (manual):**
```sql
-- Create a session, send a user message, confirm trigger updates counters
INSERT INTO chat_sessions (user_id, title) VALUES ('<test user uuid>', 'test-chat');
INSERT INTO chat_messages (session_id, user_id, role, content)
SELECT id, '<test user uuid>', 'user', 'hello'
FROM chat_sessions WHERE title = 'test-chat';
SELECT message_count, last_message_at FROM chat_sessions WHERE title = 'test-chat';
-- expect message_count=1, last_message_at != NULL
-- Cleanup: DELETE FROM chat_sessions WHERE title = 'test-chat';
```

**Commit:** `feat(rag): chat sessions + messages migration 004`

---

### Task 1.5 — Create `005_rag_rpcs.sql`

**What to do:** copy verbatim from spec §2.5. All 5 RPCs. Pay close attention to `rag_hybrid_search` — it's 180+ lines of plpgsql.

**Docs reference:** spec §2.5.

**Test (manual):** after applying:
```sql
-- rag_resolve_effective_nodes with NULL sandbox = all user nodes
SELECT COUNT(*) FROM rag_resolve_effective_nodes('<test user uuid>');
-- rag_hybrid_search with NULL effective_nodes + fake embedding (all-zero vector)
SELECT kind, node_id, rrf_score FROM rag_hybrid_search(
    '<test user uuid>', 'test query',
    ARRAY(SELECT 0::real FROM generate_series(1, 768))::vector,
    NULL, 5
);
-- rag_subgraph_for_pagerank with a known pair of connected nodes
SELECT * FROM rag_subgraph_for_pagerank('<test user uuid>', ARRAY['node-1', 'node-2']);
```

**Anti-pattern guard:** do NOT forget `SET search_path = ''` (or `'public'` where required) on `SECURITY DEFINER` functions. Missing this is a known Postgres security CVE class.

**Commit:** `feat(rag): RAG RPCs migration 005`

---

### Task 1.6 — Apply all 5 migrations to prod Supabase

**What to do:** via the Supabase SQL editor, paste each migration file as a separate execution. In order: 001 → 002 → 003 → 004 → 005. Pause between each and run the verification queries from tasks 1.1–1.5 against the prod instance (read-only, no test data).

**Docs reference:** spec §10 Phase 1.

**Acceptance:**
```sql
-- Must all return row counts, not errors:
SELECT * FROM kg_node_chunks LIMIT 1;  -- table exists
SELECT * FROM rag_sandboxes LIMIT 1;
SELECT * FROM rag_sandbox_members LIMIT 1;
SELECT * FROM chat_sessions LIMIT 1;
SELECT * FROM chat_messages LIMIT 1;
SELECT proname FROM pg_proc
 WHERE proname IN ('rag_resolve_effective_nodes','rag_hybrid_search',
                   'rag_subgraph_for_pagerank','rag_bulk_add_to_sandbox','rag_replace_node_chunks');
-- expect 5 rows
SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_kg_nodes_embedding_hnsw';
SHOW hnsw.iterative_scan;  -- strict_order
```

**Commit:** no code change — tag the deploy in the commit message of Task 1.5 with `(applied to prod 2026-MM-DD)` via an amend, OR create an empty commit `chore(rag): apply migrations 001-005 to prod`.

### Phase 1 verification gate

- [ ] All 5 migrations applied to prod
- [ ] All 6 new tables/views + 5 RPCs exist
- [ ] HNSW index active (`idx_kg_nodes_embedding_hnsw`)
- [ ] `hnsw.iterative_scan = strict_order` at DB level
- [ ] No existing functionality broken (run existing `website/api/graph` endpoint, verify KG page still loads)

**Rollback:** each migration has a commented rollback block at the bottom. Execute them in reverse order (005 → 001). The 001 rollback recreates the IVFFlat index.

---

## Phase 2 — Ingestion (chunker + embedder + upsert + telegram wiring)

**Goal:** New captures through the Telegram bot produce rows in `kg_node_chunks`. Flag-gated; failure tolerant; zero existing-capture regressions.

**Dependencies:** Phase 1 complete.

**Deliverables:**
- `website/core/rag/types.py`, `errors.py`
- `website/core/rag/adapters/pool_factory.py`, `gemini_chonkie.py`
- `website/core/rag/ingest/chunker.py`, `embedder.py`, `upsert.py`
- `telegram_bot/config/settings.py` — new `rag_chunks_enabled` flag (default False)
- `telegram_bot/pipeline/orchestrator.py` — non-blocking chunk-ingest step wired in
- All unit tests for the above

### Phase 0 docs discovery (for Phase 2)

1. Read spec §3.1 (shared types), §3.2 (chunker/embedder/upsert), §3.7.1 (pool_factory), §3.7.2 (GeminiChonkieEmbeddings).
2. Read preflight report for Chonkie abstract contract verified in Task 0.2.
3. Read `telegram_bot/pipeline/orchestrator.py:50-218` for the exact place the new step slots in (after `repo.add_node`, before `duplicate.mark_seen`).
4. Read `telegram_bot/config/settings.py:167-175` for `get_settings()` pattern.
5. Read `website/features/api_key_switching/key_pool.py:220-251` for `embed_content` signature.
6. Verify current version of `chonkie` in `pip list` matches what Phase 0 tested.

### Task 2.1 — Add `rag_chunks_enabled` setting

**Red:** `tests/unit/config/test_settings.py::test_rag_chunks_enabled_default_false`
```python
def test_rag_chunks_enabled_default_false(monkeypatch):
    # Patch required env so Settings() doesn't SystemExit
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("ALLOWED_CHAT_ID", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    from telegram_bot.config.settings import Settings
    s = Settings()
    assert s.rag_chunks_enabled is False
```
Run it — expect `AttributeError: 'Settings' object has no attribute 'rag_chunks_enabled'`.

**Green:** add `rag_chunks_enabled: bool = False` to the `Settings` BaseSettings class in `telegram_bot/config/settings.py`. Also add it to `ops/config.yaml` example if one exists.

**Commit:** `feat(rag): add rag_chunks_enabled setting`

---

### Task 2.2 — Shared types (`website/core/rag/types.py`)

**Red:** `tests/unit/rag/test_types.py::test_queryclass_has_step_back_and_four_others`
```python
def test_queryclass_values():
    from website.core.rag.types import QueryClass
    assert {q.value for q in QueryClass} == {
        "lookup", "vague", "multi_hop", "thematic", "step_back"
    }
```
Also `test_scope_filter_default_tag_mode_is_all`, `test_retrieval_candidate_fields`, `test_chat_query_default_quality_is_fast`. Run — all fail with `ModuleNotFoundError`.

**Green:** create `website/core/rag/types.py` verbatim from spec §3.1. Only include the types the tests exercise; leave unused fields out until later tasks need them. (TDD: don't over-implement.)

**Commit:** `feat(rag): shared Pydantic types`

---

### Task 2.3 — Error classes (`website/core/rag/errors.py`)

**Red:** `tests/unit/rag/test_errors.py::test_error_hierarchy`
```python
def test_empty_scope_error_inherits_from_ragerror():
    from website.core.rag.errors import RAGError, EmptyScopeError, LLMUnavailable
    assert issubclass(EmptyScopeError, RAGError)
    assert issubclass(LLMUnavailable, RAGError)
```

**Green:** create `website/core/rag/errors.py` with `class RAGError(Exception): pass` and subclasses. Add at least: `EmptyScopeError`, `LLMUnavailable`, `RerankerUnavailable`, `CriticFailure`, `SessionGoneError`.

**Commit:** `feat(rag): error hierarchy`

---

### Task 2.4 — Pool factory singleton (`adapters/pool_factory.py`)

**Red:** `tests/unit/rag/adapters/test_pool_factory.py::test_returns_same_instance_twice`
```python
def test_get_gemini_pool_returns_singleton(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")   # or whatever the real pool needs
    from website.core.rag.adapters.pool_factory import get_gemini_pool
    p1 = get_gemini_pool()
    p2 = get_gemini_pool()
    assert p1 is p2
```

**Green:** copy verbatim from spec §3.7.1. Use `@lru_cache(maxsize=1)`.

**Anti-pattern guard:** do NOT add a parameter to `get_gemini_pool()`. The singleton is parameterless.

**Commit:** `feat(rag): Gemini pool singleton factory`

---

### Task 2.5 — `GeminiChonkieEmbeddings` adapter

**Red:** `tests/unit/rag/adapters/test_gemini_chonkie.py`
```python
def test_embed_returns_768d_vectors(monkeypatch):
    # Patch the pool's embed_content to return a fake response shape
    from unittest.mock import MagicMock
    fake_pool = MagicMock()
    fake_resp = MagicMock()
    fake_resp.embeddings = [MagicMock(values=[0.1]*768), MagicMock(values=[0.2]*768)]
    fake_pool.embed_content.return_value = fake_resp

    monkeypatch.setattr(
        "website.core.rag.adapters.pool_factory.get_gemini_pool",
        lambda: fake_pool
    )
    from website.core.rag.adapters.gemini_chonkie import GeminiChonkieEmbeddings
    emb = GeminiChonkieEmbeddings()
    vecs = emb.embed(["hello", "world"])
    assert len(vecs) == 2 and len(vecs[0]) == 768

def test_dimension_property_returns_768():
    ...
def test_subclasses_chonkie_base_embeddings():
    from chonkie.embeddings import BaseEmbeddings
    from website.core.rag.adapters.gemini_chonkie import GeminiChonkieEmbeddings
    assert issubclass(GeminiChonkieEmbeddings, BaseEmbeddings)
```

**Green:** implement per spec §3.7.2. Use the abstract methods from the Phase 0 preflight report — if the report found Chonkie uses different method names, use those instead of the spec's `embed` / `embed_query` / `dimension`.

**Anti-pattern guard:** `GeminiChonkieEmbeddings.__init__` must NOT accept a pool parameter — it calls `get_gemini_pool()`. Chonkie instantiates it by name.

**Commit:** `feat(rag): GeminiChonkieEmbeddings adapter`

---

### Task 2.6 — ZettelChunker (source-type dispatch + atomic enrichment)

**Red:** 5 tests in `tests/unit/rag/test_chunker.py`:

```python
def test_reddit_chunk_is_atomic_with_entity_prefix():
    chunker = ZettelChunker()  # no late chunker
    chunks = chunker.chunk(
        source_type=SourceType.REDDIT,
        title="Thoughts on transformers",
        raw_text="This is a Reddit post about attention mechanisms.",
        tags=["transformers", "ml"],
        extra_metadata={"subreddit": "MachineLearning", "mentions": ["vaswani"]},
    )
    assert len(chunks) == 1
    assert chunks[0].chunk_type == ChunkType.ATOMIC
    assert "[Thoughts on transformers]" in chunks[0].content
    assert "#transformers #ml" in chunks[0].content
    assert "@MachineLearning" in chunks[0].content
    assert "@vaswani" in chunks[0].content
    assert "This is a Reddit post" in chunks[0].content

def test_youtube_long_form_uses_semantic_fallback_when_no_late_embedder():
    # With no embedder_for_late_chunking passed, long-form falls through to semantic
    ...

def test_long_form_falls_through_to_recursive_if_semantic_fails():
    ...

def test_long_form_falls_through_to_token_if_recursive_fails():
    ...

def test_short_form_never_uses_late_chunker():
    ...
```

**Green:** implement per spec §3.2 Chunker section (patched version with correct Chonkie parameter names — `min_sentences_per_chunk`, no `chunk_overlap` on RecursiveChunker). Use the fallback ladder: late → semantic → recursive → token.

**Anti-pattern guard:** do NOT pass `chunk_overlap` to `RecursiveChunker` (not a valid parameter). Do NOT use `min_sentences=` (wrong name). Use the exact signatures from spec §3.2.

**Commit:** `feat(rag): ZettelChunker with source-type dispatch`

---

### Task 2.7 — ChunkEmbedder with async-wrapped sync pool

**Red:** `tests/unit/rag/ingest/test_embedder.py`
```python
@pytest.mark.asyncio
async def test_embed_returns_unit_normalized_768d_vectors(monkeypatch):
    fake_pool = MagicMock()
    fake_resp = MagicMock()
    fake_resp.embeddings = [MagicMock(values=[0.0]*768) for _ in range(3)]
    fake_pool.embed_content.return_value = fake_resp
    from website.core.rag.ingest.embedder import ChunkEmbedder
    emb = ChunkEmbedder(pool=fake_pool)
    vecs = await emb.embed(["one", "two", "three"])
    assert len(vecs) == 3 and len(vecs[0]) == 768

@pytest.mark.asyncio
async def test_embed_batches_into_chunks_of_32(monkeypatch):
    fake_pool = MagicMock()
    calls = []
    def _capture(contents, *, config):
        calls.append(len(contents))
        r = MagicMock()
        r.embeddings = [MagicMock(values=[0.0]*768) for _ in contents]
        return r
    fake_pool.embed_content.side_effect = _capture
    from website.core.rag.ingest.embedder import ChunkEmbedder
    emb = ChunkEmbedder(pool=fake_pool, batch_size=32)
    await emb.embed(["x"] * 75)
    assert calls == [32, 32, 11]  # batched correctly

@pytest.mark.asyncio
async def test_embed_uses_retrieval_query_task_type_for_queries(monkeypatch):
    ...  # verify task_type="RETRIEVAL_QUERY" is passed for query path

@pytest.mark.asyncio
async def test_content_hash_is_32_bytes(monkeypatch):
    ...  # sha256 returns 32 bytes
```

**Green:** implement per spec §3.2 (patched version using `asyncio.to_thread` + `EmbedContentConfig` + tuple-unpacked response).

**Anti-pattern guard:** do NOT call `await self._pool.embed_batch(...)` — this method doesn't exist. Use `asyncio.to_thread(self._pool.embed_content, ...)`.

**Commit:** `feat(rag): ChunkEmbedder async wrapper over sync pool`

---

### Task 2.8 — upsert_chunks with content-hash skip

**Red:** 3 tests in `tests/unit/rag/ingest/test_upsert.py`:
```python
@pytest.mark.asyncio
async def test_upsert_skips_unchanged_chunks(monkeypatch):
    # Setup: mock Supabase client to return 2 existing chunks with hashes h1, h2
    # Call upsert_chunks with 2 chunks whose hashes are also h1, h2
    # Assert: embedder.embed is NEVER called, return value is 0

@pytest.mark.asyncio
async def test_upsert_re_embeds_only_changed_chunks(monkeypatch):
    # 3 existing chunks; 3 new chunks where idx 1's content differs
    # Assert: embedder.embed called with exactly 1 text (the changed one)

@pytest.mark.asyncio
async def test_upsert_calls_rag_replace_node_chunks_rpc_before_insert(monkeypatch):
    # Confirm the delete RPC fires before the bulk insert
```

**Green:** implement per spec §3.2 upsert.py (patched version with content-hash skip path). Use `supabase.rpc("rag_replace_node_chunks", ...)` and `supabase.table("kg_node_chunks").insert(rows).execute()`.

**Anti-pattern guard:** do NOT insert without the delete RPC first — that violates the replace-then-insert contract.

**Commit:** `feat(rag): upsert_chunks with hash skip`

---

### Task 2.9 — Wire chunk ingest into Telegram pipeline

**Red:** `tests/integration/rag/test_telegram_pipeline_chunks.py`
```python
@pytest.mark.asyncio
async def test_process_url_skips_chunking_when_flag_off(mocker):
    mocker.patch("telegram_bot.config.settings.get_settings").return_value = MagicMock(
        rag_chunks_enabled=False, ...
    )
    # Mock every other dependency, run process_url on a fake URL,
    # assert that upsert_chunks is NEVER called.

@pytest.mark.asyncio
async def test_process_url_runs_chunking_when_flag_on(mocker):
    # Same setup with rag_chunks_enabled=True, assert upsert_chunks WAS called
    # with the expected (user_id, node_id, chunks) shape

@pytest.mark.asyncio
async def test_process_url_continues_on_chunk_ingest_failure(mocker):
    # Make upsert_chunks raise; assert process_url still completes successfully
    # and mark_seen is called
```

**Green:** add the chunk-ingest block to `telegram_bot/pipeline/orchestrator.py` after `repo.add_node(...)` and before `duplicate.mark_seen(url)`, wrapped in try/except per spec §3.2. Import `ZettelChunker`, `ChunkEmbedder`, `upsert_chunks` lazily (inside the `if settings.rag_chunks_enabled:` block) to avoid paying the import cost when the flag is off.

**Anti-pattern guard:** do NOT fail the capture if chunking fails. `logger.warning(...)` and move on. This is the spec's reliability contract.

**Commit:** `feat(rag): wire chunk ingest into telegram pipeline`

---

### Task 2.10 — Staging validation (manual)

**What to do:** deploy to staging with `rag_chunks_enabled=True` set for that environment only. Capture 10 test URLs via the Telegram bot — mix of source types (YouTube x3, Reddit x2, Substack x2, GitHub x2, Twitter x1). After each, query:

```sql
SELECT chunk_idx, chunk_type, length(content), metadata
  FROM kg_node_chunks
 WHERE user_id = '<your staging user uuid>'
 ORDER BY created_at DESC LIMIT 10;
```

Confirm: (a) chunks appear for each capture; (b) short-form Zettels have exactly 1 atomic chunk; (c) long-form Zettels have N chunks where N > 1; (d) metadata JSONB contains the expected source-specific keys (timestamps for YouTube, subreddit for Reddit, etc.).

**Acceptance:** 10 captures all produce correct chunk rows. Record results in a new `docs/superpowers/plans/2026-04-12-rag-chatbot-phase2-validation.md`.

### Phase 2 verification gate

- [ ] All Phase 2 unit + integration tests green
- [ ] `rag_chunks_enabled` flag works in both states
- [ ] 10 staging captures produce correct chunks
- [ ] Existing capture pipeline unaffected (regression check: old captures still write to `kg_nodes` normally)

**Rollback:** set `rag_chunks_enabled=False` in prod env. No data cleanup — chunks are a read-optional side channel. If bad data must be cleaned: `DELETE FROM kg_node_chunks WHERE created_at > '<deploy timestamp>'`.

---

## Phase 3 — Retrieval core + orchestrator + TEI sidecar (INTERNAL, no surface)

**Goal:** Full RAG orchestrator callable from a test, with BGE reranker running as a Docker sidecar. No HTTP route, no Telegram command. Exercised via `pytest tests/integration/rag/`.

**Dependencies:** Phases 1 and 2 complete.

**Deliverables:**
- Adapter: `gemini_stream.py` (key-rotation streaming)
- Query: `rewriter.py`, `router.py`, `transformer.py`
- Retrieval: `cache.py`, `hybrid.py`, `graph_score.py`
- Rerank: `tei_client.py`
- Context: `assembler.py`
- Generation: `prompts.py`, `llm_router.py`, `gemini_backend.py`, `claude_backend.py` (stubbed)
- Critic: `answer_critic.py`
- Memory: `session_store.py`
- Orchestrator: `orchestrator.py`
- TEI sidecar in `ops/docker-compose.{blue,green}.yml`
- Full unit test coverage + one end-to-end integration test against staging Supabase

### Phase 0 docs discovery (for Phase 3)

Before writing any code in this phase:

1. Re-read spec §3.3 (query pipeline), §3.4 (retrieval), §3.5 (graph score), §3.6 (reranker), §3.7 (adapter layer), §3.8 (TEI sidecar), §4.1 (context), §4.2 (prompts), §4.3 (LLM router + Gemini backend), §4.4 (Claude stub), §4.5 (Answer Critic), §4.6 (session store), §4.7 (orchestrator).
2. Re-read the preflight report — confirm Langfuse async-generator support path and BGE model choice.
3. Read `website/features/api_key_switching/key_pool.py:175-216` for the existing `generate_content` key-rotation pattern — `gemini_stream.py` mirrors this exactly.
4. Read the existing `website/core/supabase_kg/repository.py` RPC call patterns (lines 460-468 for `match_kg_nodes`, etc.) — use these for every `rag_*` RPC call.

This phase has ~30 tasks. Batch them into 5 sub-phases by layer:

- **3.A Query layer** (tasks 3.1–3.3): rewriter, router, transformer
- **3.B Retrieval layer** (tasks 3.4–3.8): cache, resolve, hybrid, dedup, graph scoring
- **3.C Rerank + context** (tasks 3.9–3.12): TEI sidecar, TEI client, context assembler
- **3.D Generation + critic** (tasks 3.13–3.19): prompts, LLM router, Gemini backend, streaming adapter, Claude stub, critic
- **3.E Orchestrator + memory** (tasks 3.20–3.25): session store, full pipeline, error handling, integration test

### 3.A Query layer (3 tasks)

**Task 3.1 — QueryRewriter**

- **Red:** `test_rewrite_returns_original_when_no_history`, `test_rewrite_uses_last_5_turns`, `test_rewrite_falls_back_to_original_on_llm_error`
- **Green:** implement per spec §3.3 with `gemini-2.5-flash-lite` via the pool adapter
- **Commit:** `feat(rag): QueryRewriter multi-turn standalone`

**Task 3.2 — QueryRouter**

- **Red:** `test_classify_lookup_for_entity_query`, `test_classify_thematic_for_broad_query`, `test_fallback_to_lookup_on_parse_error`, `test_classify_returns_one_of_five_classes`
- **Green:** implement per spec §3.3 — flash-lite with `response_mime_type="application/json"`
- **Commit:** `feat(rag): QueryRouter five-class classifier`

**Task 3.3 — QueryTransformer (all 5 paths)**

- **Red:** one test per path: `test_lookup_returns_original_only`, `test_vague_generates_hyde_variant`, `test_multi_hop_decomposes_into_n_subqueries`, `test_thematic_generates_n_reformulations`, `test_step_back_generates_broader_form`
- **Green:** implement per spec §3.3 (now including the STEP_BACK path from the blueprint-gap fix #1)
- **Commit:** `feat(rag): QueryTransformer with HyDE/MQ/Decomp/StepBack`

### 3.B Retrieval layer (5 tasks)

**Task 3.4 — LRUCache with TTL**

- **Red:** `test_get_returns_none_for_missing_key`, `test_put_then_get_returns_value`, `test_get_returns_none_after_ttl_expires`, `test_lru_evicts_oldest_when_full`
- **Green:** implement per spec §3.4 `cache.py`
- **Commit:** `feat(rag): async LRU cache with TTL`

**Task 3.5 — _resolve_nodes (fast path for NULL + RPC for narrowed)**

- **Red:** `test_resolve_returns_none_when_no_sandbox_and_no_filter`, `test_resolve_calls_rpc_when_sandbox_set`, `test_resolve_returns_empty_list_when_sandbox_empty`
- **Green:** implement the `_resolve_nodes` method of `HybridRetriever` per spec §3.4
- **Commit:** `feat(rag): scope resolver with fast path for all-nodes`

**Task 3.6 — hybrid retrieval fan-out + consensus boost**

- **Red:** `test_retrieve_fans_out_across_variants`, `test_dedup_keeps_max_rrf_score`, `test_consensus_boost_adds_per_variant_hit`, `test_retrieve_raises_empty_scope_error_when_resolver_returns_empty_list`
- **Green:** implement `HybridRetriever.retrieve` + `_dedup_and_fuse` per spec §3.4
- **Commit:** `feat(rag): hybrid retrieve with variant fan-out`

**Task 3.7 — Graph depth configuration per query class**

- **Red:** `test_graph_depth_is_1_for_lookup`, `test_graph_depth_is_2_for_thematic`
- **Green:** pass `graph_depth=_DEPTH_BY_CLASS[query_class]` into the `p_graph_depth` RPC param. This is the implementation of blueprint-gap fix #2.
- **Commit:** `feat(rag): per-class graph depth`

**Task 3.8 — LocalizedPageRankScorer**

- **Red:** `test_graph_score_zero_when_fewer_than_2_candidates`, `test_graph_score_zero_when_no_edges`, `test_pagerank_normalized_to_01`, `test_isolated_node_gets_lowest_score`
- **Green:** implement per spec §3.5 with `networkx.pagerank`
- **Commit:** `feat(rag): localized PageRank over retrieved subgraph`

### 3.C Rerank + context (4 tasks)

**Task 3.9 — Add TEI sidecar to blue/green compose files**

- **What to do:** copy the YAML from spec §3.8 into both `ops/docker-compose.blue.yml` and `ops/docker-compose.green.yml`. Use the model ID chosen in Phase 0 (v2-m3 or large fallback).
- **Test (manual):** `docker compose -f ops/docker-compose.blue.yml up reranker` on staging → wait for `Ready` log → `curl http://localhost:8080/health`.
- **Commit:** `feat(ops): TEI reranker sidecar for blue/green`

**Task 3.10 — TEIReranker client**

- **Red:** `test_rerank_returns_empty_for_empty_candidates`, `test_rerank_populates_rerank_score`, `test_rerank_falls_back_to_rrf_on_http_error`, `test_final_score_uses_60_25_15_fusion`
- **Green:** implement per spec §3.6 with `httpx.AsyncClient` + `tenacity.retry`
- **Anti-pattern guard:** do NOT raise on TEI failure. Set `rerank_score=None` and degrade to RRF-only sort.
- **Commit:** `feat(rag): BGE reranker client with graceful fallback`

**Task 3.11 — ContextAssembler with sandwich order + budget**

- **Red:** `test_build_returns_empty_xml_for_no_candidates`, `test_sandwich_places_best_first_and_second_last`, `test_budget_truncates_groups_by_rank`, `test_render_xml_escapes_special_chars`
- **Green:** implement per spec §4.1
- **Commit:** `feat(rag): context assembler with sandwich ordering`

**Task 3.12 — System prompt + user template constants**

- **Red:** `test_system_prompt_contains_seven_rules`, `test_user_template_has_context_xml_and_query_placeholders`, `test_cot_prefix_exists_as_separate_constant`
- **Green:** create `website/core/rag/generation/prompts.py` per spec §4.2 verbatim
- **Commit:** `feat(rag): system prompt and user template`

### 3.D Generation + critic (7 tasks)

**Task 3.13 — GeminiStreamAdapter (key-rotation streaming)**

- **Red:** `test_stream_yields_tokens_from_fake_client`, `test_rotates_to_next_key_on_429`, `test_respects_cooldowns`, `test_raises_when_all_keys_exhausted`
- **Green:** implement per spec §3.7.3. Mock `google.genai.Client` entirely in tests — don't touch real Gemini.
- **Anti-pattern guard:** do NOT modify `key_pool.py`. Everything lives in `adapters/gemini_stream.py`.
- **Commit:** `feat(rag): Gemini streaming adapter with key rotation`

**Task 3.14 — GeminiBackend non-streaming path**

- **Red:** `test_generate_succeeds_with_fast_tier`, `test_falls_through_to_next_tier_on_rate_limit`, `test_raises_llm_unavailable_when_all_tiers_exhausted`, `test_generation_result_has_model_and_tokens`
- **Green:** implement per spec §4.3 `generate()` method using the existing pool's `generate_content`
- **Commit:** `feat(rag): Gemini non-streaming backend`

**Task 3.15 — GeminiBackend streaming path (wires to adapter)**

- **Red:** `test_generate_stream_yields_tokens_with_metadata`, `test_generate_stream_tier_fallback`
- **Green:** implement `generate_stream()` using `generate_stream_with_rotation` from Task 3.13
- **Commit:** `feat(rag): Gemini streaming backend`

**Task 3.16 — ClaudeBackend stub**

- **Red:** `test_claude_backend_disabled_without_api_key`, `test_claude_backend_raises_when_disabled_and_called`
- **Green:** implement per spec §4.4. Shipped disabled.
- **Commit:** `feat(rag): Claude backend stubbed + flag-gated`

**Task 3.17 — LLMRouter dispatch**

- **Red:** `test_router_picks_gemini_when_claude_disabled`, `test_router_picks_claude_when_quality_high_and_enabled`
- **Green:** implement per spec §4.3
- **Commit:** `feat(rag): LLM router with backend selection`

**Task 3.18 — AnswerCritic (LLM verdict + deterministic bad-citation check)**

- **Red:** 5 tests: `test_critic_returns_supported_for_grounded_answer`, `test_critic_returns_partial_when_llm_judge_says_partial`, `test_bad_citation_detector_flags_ids_not_in_context`, `test_critic_failure_defaults_to_supported_with_error_note`, `test_llm_supported_downgraded_to_partial_if_bad_citations_found`
- **Green:** implement per spec §4.5
- **Commit:** `feat(rag): Answer Critic with NLI + citation check`

**Task 3.19 — `record_generation_cost` helper**

- **Red:** `test_cost_helper_calls_langfuse_update_current_generation`, `test_unknown_model_uses_zero_cost`
- **Green:** implement per spec §6.5 `record_generation_cost` function
- **Commit:** `feat(rag): explicit Gemini cost tracking helper`

### 3.E Orchestrator + memory (6 tasks)

**Task 3.20 — ChatSessionStore CRUD**

- **Red:** 6 tests: create/get/list/delete + append_user_message + append_assistant_message. Mock Supabase via fake client.
- **Green:** implement per spec §4.6
- **Commit:** `feat(rag): ChatSessionStore CRUD`

**Task 3.21 — `load_recent_turns` + `auto_title_session`**

- **Red:** `test_load_recent_turns_returns_oldest_first`, `test_auto_title_uses_first_line_up_to_60_chars`
- **Green:** implement the two methods per spec §4.6
- **Commit:** `feat(rag): session history loader + auto-title`

**Task 3.22 — Orchestrator `_run_pipeline` happy path (non-streaming)**

- **Red:** `test_answer_happy_path_returns_grounded_answer_with_citations`. Use fully mocked dependencies — this test verifies the orchestration wiring, not the retrieval quality.
- **Green:** implement `answer()` and `_run_pipeline(stream=False)` per spec §4.7 — all 14 steps, but mock everything.
- **Commit:** `feat(rag): orchestrator non-streaming path`

**Task 3.23 — Orchestrator empty-scope + LLM-down error paths**

- **Red:** `test_empty_scope_raises_empty_scope_error`, `test_llm_unavailable_propagates`
- **Green:** add the error-handling branches to `_run_pipeline` per spec §4.7
- **Commit:** `fix(rag): orchestrator error paths`

**Task 3.24 — Orchestrator critic retry loop**

- **Red:** `test_unsupported_verdict_triggers_multi_query_retry`, `test_retry_supported_verdict_set_on_retry_success`, `test_retry_still_bad_prepends_warning_banner`
- **Green:** add the retry branch per spec §4.7
- **Anti-pattern guard:** the retry is BOUNDED TO ONE. Do not recurse.
- **Commit:** `feat(rag): critic-triggered multi-query retry`

**Task 3.25 — Orchestrator streaming path**

- **Red:** `test_answer_stream_yields_status_citations_tokens_done`, `test_answer_stream_emits_error_on_empty_scope`, `test_answer_stream_replace_events_on_retry_success`
- **Green:** implement `answer_stream()` per spec §4.7 yielding the event dicts
- **Commit:** `feat(rag): orchestrator streaming path with SSE events`

### Phase 3 verification gate

- [ ] All unit tests green (`pytest tests/unit/rag/`)
- [ ] Integration test `tests/integration/rag/test_orchestrator_e2e.py` passes against staging Supabase with a real 3-capture corpus
- [ ] TEI sidecar healthy on staging (`docker compose ps reranker` → healthy)
- [ ] p95 latency on a 10-query smoke test < 8s total (retrieval < 500ms, rerank < 400ms, generation < 5s)
- [ ] No direct imports of `google.generativeai` from RAG business logic (grep check: `grep -rE "^from google" website/core/rag/` should only match `adapters/` files)
- [ ] No direct imports of `langfuse.decorators` (grep check: `grep -r "langfuse.decorators" website/core/rag/` → 0 matches; v3 uses `from langfuse import observe`)

**Rollback:** revert the Phase 3 commits. No production surface to roll back.

---

## Phase 4 — Telegram `/ask` (soft launch)

**Goal:** `chintanmehta21` can DM the production Telegram bot with `/ask <question>` and get a grounded, citation-formatted answer.

**Dependencies:** Phases 1, 2, 3 complete.

**Deliverables:**
- `telegram_bot/bot/ask_handler.py`
- `telegram_bot/main.py` registration
- `telegram_bot/bot/ask_rate_limiter.py` (tiny sliding-window in-memory limiter)
- Unit + integration tests

### Phase 0 docs discovery (for Phase 4)

1. Read spec §5.11.
2. Read `telegram_bot/main.py:92-100` for existing `CommandHandler` registration pattern.
3. Read any existing `handle_*` function for PTB async signature reference.

### Task 4.1 — AskRateLimiter

- **Red:** `test_allow_within_limit`, `test_block_when_over_limit`, `test_window_slides_over_time`
- **Green:** minimal sliding-window class with `allow(chat_id: int) -> bool` per spec §5.11
- **Commit:** `feat(telegram): ask rate limiter`

### Task 4.2 — `_format_answer_for_telegram` helper

- **Red:** `test_renumbers_citations_to_bracket_numbers`, `test_appends_sources_list`, `test_prepends_warning_on_retried_still_bad`, `test_truncates_over_4000_chars`, `test_escapes_markdown_v2_specials`
- **Green:** implement per spec §5.11
- **Commit:** `feat(telegram): ask answer formatter`

### Task 4.3 — `ask_command` handler

- **Red:** `test_ask_with_empty_question_returns_usage`, `test_ask_respects_rate_limit`, `test_ask_unknown_user_returns_friendly_error`, `test_ask_empty_scope_returns_friendly_error`, `test_ask_llm_unavailable_returns_friendly_error`, `test_ask_happy_path_calls_orchestrator_and_sends_formatted_reply`
- **Green:** implement per spec §5.11. Import `get_orchestrator()` lazily inside the handler to avoid startup cost when `/ask` is never used.
- **Commit:** `feat(telegram): /ask command handler`

### Task 4.4 — Register the handler in `main.py`

- **Red:** tiny integration test that the PTB `Application` contains a handler for `/ask` after `build_handler()` is called
- **Green:** add `app.add_handler(build_ask_handler())` and attach the rate limiter to `app.ask_rate_limiter`
- **Commit:** `feat(telegram): register /ask command`

### Task 4.5 — Manual prod smoke test

- **What to do:** deploy to prod via existing blue/green workflow. Send 10 `/ask` queries covering: short fact, ambiguous/vague, multi-hop, thematic, one that should fail ("what do my notes say about quantum zeppelins" — expect "I can't find anything").
- **Acceptance:** 10/10 answers return within 15s, grounded citations format correctly, the "no results" case handles gracefully.
- **No commit** — just capture results in a short `phase4-validation.md` note.

### Phase 4 verification gate

- [ ] All Phase 4 tests green
- [ ] 10/10 manual prod queries successful
- [ ] No regression in existing Telegram commands (`/start`, `/status`, URL-handling flows)

**Rollback:** comment out `app.add_handler(build_ask_handler())` in `telegram_bot/main.py`, redeploy. Zero blast radius.

---

## Phase 5 — Web `/api/chat/adhoc` + minimal chat UI

**Goal:** Logged-in users on the web can open a new page, type a question, and get a streaming answer. No sandboxes, no multi-turn history UI, no KG integration yet.

**Dependencies:** Phases 1–4 complete.

**Deliverables:**
- `website/api/chat_routes.py` with `/api/chat/adhoc` endpoint only
- `website/core/rag/api_models.py` (Pydantic request/response)
- `website/features/rag_chatbot/templates/chat.html` (minimal)
- `website/features/rag_chatbot/static/js/sse_client.js`
- `website/features/rag_chatbot/static/js/chat_adhoc.js` (mini controller, ad-hoc only)
- `website/features/rag_chatbot/static/css/chat.css`

### Phase 0 docs discovery (for Phase 5)

1. Read spec §5.1, §5.2, §5.3, §5.4, §5.5, §5.6, §5.9.
2. Read `website/api/routes.py:27-96` for rate limiter pattern.
3. Read `website/api/routes.py:114-120` for `Depends(get_current_user)` pattern.
4. Read `website/app.py:62-211` for app factory and static-mount pattern.

### Task 5.1 — Pydantic api_models

- **Red:** `test_send_message_request_validates_content_length`, `test_scope_filter_defaults_to_all_none`
- **Green:** copy from spec §5.3 into `website/core/rag/api_models.py`
- **Commit:** `feat(rag): API Pydantic models`

### Task 5.2 — `rag_rate_limiter` buckets

- **Red:** `test_chat_message_bucket_per_user`, `test_retrieve_embedding_bucket_per_user`
- **Green:** extend the existing rate-limiter pattern (copy from `website/api/routes.py:27-96`) with the 5 buckets from spec §5.4. New file: `website/api/rag_rate_limiter.py`.
- **Commit:** `feat(rag): API rate limit buckets`

### Task 5.3 — `/api/chat/adhoc` endpoint

- **Red:** `test_adhoc_returns_sse_stream`, `test_adhoc_respects_rate_limit`, `test_adhoc_requires_auth`, `test_adhoc_handles_empty_scope`
- **Green:** write `website/api/chat_routes.py` with just the `/api/chat/adhoc` route. Use `StreamingResponse(event_stream(), media_type="text/event-stream")` with the headers from spec §5.2. Wire to `RAGOrchestrator.answer_stream()` with `session_id=None, sandbox_id=None`.
- **Anti-pattern guard:** remember `X-Accel-Buffering: no` in response headers or Caddy will buffer the stream to death.
- **Commit:** `feat(rag): adhoc chat SSE endpoint`

### Task 5.4 — SSE client JavaScript

- **Red:** n/a (no JS test framework in this repo). Write a manual test checklist instead.
- **Green:** copy spec §5.9 SSEClient verbatim into `website/features/rag_chatbot/static/js/sse_client.js` as an ES module.
- **Commit:** `feat(rag): SSE client JS module`

### Task 5.5 — Minimal chat page

- **What to do:** Create `chat.html` (Jinja template) with a textarea input, a send button, a status pill, and a message area. Wire `chat_adhoc.js` to POST the SSE endpoint and stream tokens into the message area. Citation chips rendered on the `citations` event, tokens streamed on `token`.
- **Design language:** teal accent, amber citation chips — NO purple. Consistency with the existing website's Tailwind palette.
- **Commit:** `feat(rag): minimal chat page UI`

### Task 5.6 — Register `chat.html` route in `website/app.py`

- **Red:** `test_chat_route_requires_auth`, `test_chat_route_renders_chat_html`
- **Green:** add `@app.get("/chat")` returning `FileResponse("website/features/rag_chatbot/templates/chat.html")` (or Jinja-rendered). Mount the static files for css/js.
- **Commit:** `feat(rag): /chat route`

### Task 5.7 — Manual staging + prod validation

- **What to do:** send 10 ad-hoc queries via the web UI on staging. Verify: tokens stream in (not a single delayed block), citation chips render, rate limit errors display gracefully, auth redirect works when logged out.
- **Commit:** none — capture in `phase5-validation.md`.

### Phase 5 verification gate

- [ ] All Phase 5 tests green
- [ ] SSE streaming works end-to-end on staging
- [ ] Auth redirect + rate limiting verified
- [ ] p95 time-to-first-token < 2.5s on staging

**Rollback:** remove `@app.get("/chat")` route + the POST endpoint registration in `chat_routes.py`. Revert the static/template files. No data changes.

---

## Phase 6 — Sandboxes + multi-turn + full frontend + KG integration

**Goal:** Full NotebookLM-style experience: persistent sandboxes, session history, multi-turn conversations, edit-and-retry, "Ask about this" from the 3D KG page, "Add to sandbox" multi-select.

**Dependencies:** Phases 1–5 complete.

**Deliverables:**
- `website/api/sandbox_routes.py` (9 routes)
- `website/api/chat_routes.py` extended with 8 more routes
- Full `website/features/rag_chatbot/` frontend (8 JS modules, 4 CSS files, 4 templates)
- KG integration touchpoints in `website/features/knowledge_graph/static/js/kg_rag_integration.js`

This phase has ~25 tasks. Batch into 4 sub-phases:

- **6.A Sandbox API** (tasks 6.1–6.6)
- **6.B Chat session API extension** (tasks 6.7–6.11)
- **6.C Frontend polish** (tasks 6.12–6.20)
- **6.D KG integration** (tasks 6.21–6.23)

### Phase 0 docs discovery (for Phase 6)

1. Re-read spec §1.4 (sandbox concept), §5.1 (endpoint catalog), §5.5 (frontend layout), §5.7 (pages), §5.8 (UX flows), §5.10 (KG integration), §12 edge cases 1–46.
2. Read `website/features/knowledge_graph/static/js/` for the existing `kgScene`, `kgSelection` hooks.

### 6.A Sandbox API (6 tasks)

**Task 6.1** — `POST /api/rag/sandboxes` + `GET /api/rag/sandboxes` (list)
  - 4 tests (create, list-empty, list-with-entries, unique-name-constraint)
  - Implement per spec §5.1 and §5.3
  - `feat(rag): sandbox create + list`

**Task 6.2** — `GET /api/rag/sandboxes/{id}` (single sandbox via `rag_sandbox_stats` view)
  - 2 tests (exists, 404)
  - `feat(rag): sandbox get by id`

**Task 6.3** — `GET /api/rag/sandboxes/{id}/members` (paginated)
  - 3 tests (empty, pagination, filter-by-added_via)
  - `feat(rag): list sandbox members`

**Task 6.4** — `POST /api/rag/sandboxes/{id}/members` (add, manual or bulk)
  - 4 tests: explicit node_ids, bulk tag filter, bulk source filter, validation error for empty payload
  - Call `rag_bulk_add_to_sandbox` RPC per spec §2.5 RPC #4
  - `feat(rag): sandbox add members with bulk RPC`

**Task 6.5** — `DELETE /api/rag/sandboxes/{id}/members/{node_id}` + bulk delete
  - 3 tests
  - `feat(rag): sandbox remove members`

**Task 6.6** — `PATCH` and `DELETE /api/rag/sandboxes/{id}` (rename, delete w/ cascade)
  - 3 tests (rename, delete-with-cascade-confirmation, 404)
  - `feat(rag): sandbox rename + cascade delete`

### 6.B Chat session API extension (5 tasks)

**Task 6.7** — `POST /api/chat/sessions` (create, optionally with `sandbox_id`)
  - 3 tests (ad-hoc, sandbox-tied, 404-for-unknown-sandbox)
  - `feat(rag): chat session create`

**Task 6.8** — `GET /api/chat/sessions` + `GET /api/chat/sessions/{id}` + `GET .../messages` (list with pagination)
  - 4 tests
  - `feat(rag): chat session list + get`

**Task 6.9** — `POST /api/chat/sessions/{id}/messages` (SSE streaming, scoped to session's sandbox)
  - 5 tests: stream completes, rate-limited, session-not-found, session-deleted-mid-stream emits session_gone, multi-turn rewriter loads history
  - **This is the main prod endpoint** — test coverage is critical
  - `feat(rag): chat send-message SSE endpoint`

**Task 6.10** — `DELETE /api/chat/sessions/{id}` (cascade) + `DELETE .../messages/{mid}` (edit-and-retry fork)
  - 3 tests (cascade, fork from mid-session, 404)
  - `feat(rag): chat session delete + message fork`

**Task 6.11** — `PATCH /api/chat/sessions/{id}` (rename, update quality)
  - 2 tests
  - `feat(rag): chat session update`

### 6.C Frontend polish (9 tasks)

**Tasks 6.12–6.20** — one task per frontend module. These are manual/visual tasks; tests are limited to route-registration and template-renders-without-error checks. Each task:

- **6.12** — `session_store.js` client-side cache
- **6.13** — `sandbox_manager.js` CRUD + modals
- **6.14** — `scope_picker.js` (tag, source, node-id narrowing UI)
- **6.15** — `citation_panel.js` (right rail)
- **6.16** — `message_renderer.js` (markdown + citation linking)
- **6.17** — `chat_controller.js` (top-level coordinator, multi-turn, edit-and-retry)
- **6.18** — `sandboxes.html` page + template
- **6.19** — `sandbox_detail.html` page
- **6.20** — Full `chat.html` integration with left rail + center + right rail

Each commit: `feat(rag): <module name>`

### 6.D KG integration (3 tasks)

**Task 6.21** — "Ask about this" right-click in 3D KG page
  - Write `kg_rag_integration.js`, wire `kgScene.onNodeRightClick`
  - Visual test only
  - `feat(kg): ask-about-node context menu`

**Task 6.22** — "Add to sandbox" multi-select toolbar
  - Wire to `window.kgSelection` registry
  - Opens sandbox picker modal (reuses `sandbox_manager.js`)
  - `feat(kg): add-to-sandbox toolbar`

**Task 6.23** — "View in graph" from citation chip (reverse direction)
  - Slide-over iframe pointing at `/knowledge-graph?focus=<id>&embed=true`
  - Requires `embed=true` param handling in the existing KG page (add if missing)
  - `feat(rag): view-in-graph from citation`

### Phase 6 verification gate

- [ ] All Phase 6 tests green
- [ ] Full end-to-end scenario on staging: create sandbox → add 20 Zettels via 3 different affordances → 5-turn conversation → edit one old message and retry → rename sandbox → cascade-delete sandbox → verify cascade removed chat sessions + messages
- [ ] Visual check: no purple anywhere. Teal/amber only.
- [ ] Spec §12 edge cases 38, 44, 45, 46 manually verified

**Rollback:** feature-flag via `rag_sandboxes_enabled=False` hides all `/sandboxes` routes and the sandbox rail in the chat page. Ad-hoc chat from Phase 5 still works.

---

## Phase 7 — Observability + RAGAS CI eval

**Goal:** Langfuse sidecar running in prod; every RAG turn emits a trace; GitHub Actions runs RAGAS on every PR touching `website/core/rag/**`.

**Dependencies:** Phases 1–6 complete. Preflight Task 0.4 (Langfuse `@observe` on async generators) and 0.5 (RAGAS Gemini judge path) outcomes known.

### Phase 0 docs discovery (for Phase 7)

1. Re-read spec §6.1 (3 eval layers), §6.3 (RAGAS in CI), §6.4 (Langfuse sidecar), §6.5 (instrumentation), §6.6 / §6.6a (cost tracking).
2. Re-read Phase 0 preflight report rows 4 and 5 (the verified paths).

### Task 7.1 — Langfuse + Langfuse-Postgres sidecars in compose files

- Copy spec §6.4 YAML into `ops/docker-compose.blue.yml` and `ops/docker-compose.green.yml`
- Add required env vars to `ops/.env.example`:
  ```
  LANGFUSE_DB_PASSWORD=
  LANGFUSE_NEXTAUTH_SECRET=
  LANGFUSE_SALT=
  LANGFUSE_PUBLIC_KEY=
  LANGFUSE_SECRET_KEY=
  LANGFUSE_BASE_URL=http://langfuse:3000
  ```
- Add Caddy route `langfuse.internal.<APP_DOMAIN>` with basic auth
- Manual: deploy, login to Langfuse UI via basic auth, create an org + project, save the keys
- `feat(ops): Langfuse sidecar + postgres`

### Task 7.2 — `tracer.py` + explicit cost helper

- **Red:** `test_trace_stage_decorator_wraps_async`, `test_record_generation_cost_calls_update_current_generation`
- **Green:** implement `website/core/rag/observability/tracer.py` per spec §6.5 (patched with `from langfuse import observe, get_client`)
- **Commit:** `feat(rag): Langfuse tracer + cost helper`

### Task 7.3 — Wire `@trace_stage` decorators + cost recording on orchestrator

- Add `@trace_stage("query_rewrite")` etc. to the orchestrator stages per spec §6.5
- Call `record_generation_cost(...)` after every LLM generation
- **Red:** hard to test directly; add an integration test that runs one orchestrator turn and then queries Langfuse API to confirm a trace was ingested (only in a dedicated CI job with real Langfuse, or skipped locally)
- **Green:** add the decorators
- **Commit:** `feat(rag): orchestrator tracing + cost tracking`

### Task 7.4 — RAGAS test module `tests/eval/ragas/test_retrieval_quality.py`

- **Red (for the test file itself)**: write the test as spec §6.3 shows. When run against the synthetic corpus, it must fail with a missing-fixtures error first, then pass once Phase 0 fixtures are loaded.
- **Green:** implement the test. Use the judge path verified in Task 0.5.
- **Commit:** `test(rag): RAGAS retrieval quality eval`

### Task 7.5 — RAGAS test module `tests/eval/ragas/test_answer_quality.py`

- Similar structure, measures answer-quality metrics (Faithfulness, AnswerRelevancy, AnswerCorrectness)
- Threshold assertions per spec §6.3
- `test(rag): RAGAS answer quality eval`

### Task 7.6 — GitHub Actions workflow `.github/workflows/rag-eval.yml`

- Copy spec §6.3 CI job shape
- Use `paths:` filter on `website/core/rag/**` and `supabase/website/rag_chatbot/**`
- **Initial mode: warning-only** (job runs but `continue-on-error: true`). After a week of green runs, flip to blocking.
- `feat(ci): RAG eval workflow (warning mode)`

### Phase 7 verification gate

- [ ] All Phase 7 tests green
- [ ] Langfuse dashboard receiving traces from staging
- [ ] Gemini cost numbers visible in Langfuse (non-zero, non-absurd)
- [ ] `rag-eval` workflow runs on a test PR and posts results
- [ ] After 5 consecutive green runs: flip `continue-on-error: false` in a follow-up commit

**Rollback:** disable `@trace_stage` via a setting flag (e.g. `rag_tracing_enabled=False` → decorator becomes a no-op). Sidecar stays up but unused. CI workflow: remove the `paths:` filter temporarily to stop triggering.

---

## Phase 8 — Hardening

**Goal:** Monitor real usage for 1–2 weeks, fix top issues, raise eval thresholds as metrics stabilize, and announce publicly.

**Dependencies:** Phases 1–7 complete.

This phase has no fixed task list — it's a monitoring and triage phase. Expected activities:

### 8.1 Weekly Langfuse review ritual

- Every Monday morning, open Langfuse dashboard
- Review: worst-faithfulness traces (top 10), highest-latency traces (p99 outliers), highest-cost traces, critic-retry traces
- File one issue per distinct problem pattern
- Commit new golden Q/A entries to `tests/eval/ragas/fixtures/golden_qa.json` when a real user hits a hallucination or a retrieval miss

### 8.2 Incident response

- Define alert thresholds per spec §6.6:
  - p95 `rag.retrieve_hybrid` > 800ms over 10 min
  - `unsupported + retried_still_bad` rate > 5% over 1h
  - Gemini key rotation events > 20 / 5 min
  - TEI reranker `reranker_degraded` > 3 / 5 min
  - Avg cost per turn > $0.02 / 1h window
  - Empty-scope errors > 10 / hour
- Route alerts to the existing Telegram bot error channel

### 8.3 Threshold ratcheting

- If a RAGAS metric stays above its floor for 5 consecutive days, file a PR raising the floor by 0.02
- Never lower a floor without an explicit user-facing reason documented in the commit

### 8.4 Public launch

- Once 2 weeks of stable metrics: update the README (minimal addition — no env var lists per user memory), announce via whatever channel makes sense

**Rollback plan for the whole system**: every phase has its own rollback. Nothing in this plan is irreversible. Worst case:
1. Feature-flag all `rag_*` routes off (`rag_sandboxes_enabled=False`, `rag_adhoc_enabled=False`)
2. Shut down TEI and Langfuse sidecars
3. `rag_chunks_enabled=False` on the ingest side
4. Schema remains (harmless if unused)
5. Fully reversible to pre-RAG state

---

## Appendix A — Task-to-spec-section cross-reference

| Task | Spec § | Blueprint gap fix |
|---|---|---|
| 1.1 HNSW migration | §2.1 | — |
| 1.2 Chunks table | §2.2 | — |
| 1.3 Sandboxes | §2.3 | — |
| 1.4 Chat sessions | §2.4 | — |
| 1.5 RPCs | §2.5 | #2 (graph depth in rag_hybrid_search) |
| 2.6 Chunker | §3.2 | #3 (atomic entity enrichment) |
| 2.7 Embedder | §3.2 (patched) | — |
| 2.8 Upsert | §3.2 (patched) | #4 (content-hash skip) |
| 2.9 Telegram wiring | §3.2 end-of-section | — |
| 3.3 QueryTransformer | §3.3 | #1 (STEP_BACK query class) |
| 3.4 LRUCache | §3.4 | #5 (query + retrieval cache) |
| 3.7 Graph depth config | §3.4 | #2 (graph depth) |
| 3.10 TEIReranker | §3.6 | — |
| 3.11 ContextAssembler | §4.1 | — |
| 3.13 Gemini streaming | §3.7.3 | — |
| 3.18 Answer Critic | §4.5 | — |

All 5 blueprint-gap fixes from spec §3 are grounded in specific tasks.

---

## Appendix B — Commit-prefix cheat sheet

| Prefix | Use for |
|---|---|
| `feat(rag)` | new Python module in `website/core/rag/**` |
| `feat(telegram)` | new handler in `telegram_bot/**` |
| `feat(kg)` | new JS/templates in `website/features/knowledge_graph/**` |
| `feat(ops)` | new/edited files in `ops/**` (compose, requirements) |
| `feat(ci)` | new workflow in `.github/workflows/**` |
| `fix(rag)` | bug fix to an existing RAG module |
| `test(rag)` | test-only additions to `tests/**` |
| `refactor(rag)` | no behavior change, structure only |
| `docs(rag)` | changes to spec / plan / preflight report |
| `chore(rag)` | version bumps, dep updates |

All commits: max 10 words in subject line, no `Co-Authored-By`, no AI tool names (per CLAUDE.md).

---

## Appendix C — Sanity-check greps before declaring a phase complete

Run these at the end of every phase:

```bash
# 1. No invented APIs: ensure no direct imports of google.generativeai from business logic
grep -rE "^(from|import) google" website/core/rag/ | grep -v adapters/

# 2. No v2 Langfuse imports
grep -r "langfuse.decorators" website/core/rag/ website/features/rag_chatbot/

# 3. No chunk_overlap on RecursiveChunker
grep -rn "RecursiveChunker.*chunk_overlap" website/

# 4. No min_sentences= (wrong param name)
grep -rn "min_sentences=" website/

# 5. No TEI cpu-1.5 anywhere
grep -rn "cpu-1.5" ops/ docs/

# 6. No direct key_pool mutation outside adapters
grep -rn "key_pool\._" website/core/rag/ | grep -v adapters/

# 7. No purple in CSS
grep -rEi "(purple|violet|lavender|#[89ab][0-9a-f][0-9a-f]f[0-9a-f]{3})" website/features/rag_chatbot/static/css/
```

If any grep returns a match, the phase is not complete.

---

---

## Appendix D — Gap-fix addendum (16 items from spec-vs-plan audit)

A post-write audit (subagent QA, ~200-row cross-check) found 16 spec items with no explicit plan task. Each is assigned to a phase and given a task number below. **Execute these alongside their phase's tasks, not as a separate pass.**

### Phase 2 additions

**Task 2.0 — Update `ops/requirements.txt` with new runtime deps**

Before any Phase 2 code can import, add to `ops/requirements.txt`:

```
chonkie>=1.0.0           # chunking (Semantic, Late, Recursive, Token)
networkx>=3.2            # localized PageRank (may already be present)
# anthropic>=0.30.0      # future Claude backend, commented out in v1
```

Run `pip install -r ops/requirements.txt` locally to verify no conflicts. **This task is prerequisite to every subsequent task.**

**Commit:** `chore(rag): add chonkie + networkx deps`

---

**Task 2.0b — Create `website/core/rag/__init__.py` package marker**

Create `website/core/rag/__init__.py` (empty, or with a version string). Without this, every `from website.core.rag import ...` fails. Also create `website/core/rag/ingest/__init__.py` and `website/core/rag/adapters/__init__.py`. Run before Task 2.2.

**Commit:** `chore(rag): init package markers`

---

**Task 2.11 — Create `ops/scripts/backfill_chunks.py` skeleton**

Spec §9 (parked features) says to create a skeleton backfill script. Write the argparse shell + a `TODO: iterate Obsidian markdown files, extract raw text, chunk, embed, upsert` body. No implementation. This documents the future path.

```python
# ops/scripts/backfill_chunks.py
"""
Backfill kg_node_chunks for existing Zettels from Obsidian markdown files.
NOT part of the v1 pipeline — run manually when summary-only fallback
causes retrieval misses on old content. See spec §9.
"""
import argparse
# TODO: iterate KG_DIRECTORY markdown files, parse "Extracted Text" sections,
#       run ZettelChunker + ChunkEmbedder + upsert_chunks for each.
```

**Commit:** `docs(rag): backfill_chunks.py skeleton`

---

### Phase 3 additions

**Task 3.26 — Create `website/core/rag/backends/` package with `websearch.py` stub**

Spec §8.1 and §9 explicitly call for this parked stub:

```python
# website/core/rag/backends/__init__.py
# (empty)

# website/core/rag/backends/websearch.py
"""
PARKED: Future web-search popup feature.
Spec §9: "future ad-hoc info-needs feature, reserved namespace."
"""
class WebSearchBackend:
    async def search(self, query: str) -> str:
        raise NotImplementedError(
            "WebSearchBackend is parked for v2. See spec §9."
        )
```

No test needed (just an `__init__` + a stub).

**Commit:** `feat(rag): parked websearch backend stub`

---

**Task 3.27 — Update deploy script with reranker health-check preflight**

Spec §7.2 says: before Caddy upstream swap, run `docker compose run --rm reranker wget -qO- http://localhost:8080/health`. Add this line to `ops/deploy/deploy.sh` **after** the new containers are up but **before** the Caddy swap.

**Test (manual):** run deploy on staging; confirm the health-check step prints "OK" or blocks the swap on failure.

**Commit:** `feat(ops): reranker health preflight in deploy`

---

### Phase 5 additions

**Task 5.0 — Create `website/features/rag_chatbot/__init__.py`**

Python package marker. Empty file. Create it before Task 5.4 (SSE client) since the template mount expects the package to exist.

**Commit:** fold into Task 5.5 (minimal chat page) — no separate commit needed.

---

### Phase 6 additions

**Task 6.24 — Create `content/example_queries.json` for empty-state UX**

Spec §5.5 lists this file. Write 10–15 sample queries the UI shows when the user opens `/chat` with no history (spec §5.8 "first-time empty state"). Examples:

```json
[
  "What have I saved about attention mechanisms?",
  "Compare the perspectives on transformers across my YouTube notes",
  "Summarize everything I know about reinforcement learning",
  "Which of my Zettels mention Andrej Karpathy?",
  ...
]
```

**Commit:** `feat(rag): example queries for empty-state UX`

---

**Phase 6 verification gate — add 2 edge-case notes:**

- **Edge case #36 (multiple browser tabs):** manually open `/chat` in 2 tabs, send a message in tab 1, switch to tab 2, verify it shows the new turn after clicking into the session list or refreshing. No dedicated test needed — note this as a manual check in the Phase 6 gate.
- **Edge case #44 (double-click duplicate session creation):** verify the client generates a UUID for the session and the server upserts on it. Note in Phase 6 gate.

### Phase 7 additions

**Task 7.0 — Update `ops/requirements.txt` + `ops/requirements-dev.txt` for eval deps**

Add to `ops/requirements.txt`:
```
langfuse>=3.0.0          # observability SDK
```

Add to `ops/requirements-dev.txt`:
```
ragas>=0.4.3,<0.5        # CI synthetic eval (class-based API)
respx>=0.22.0            # HTTP mocking
langchain-google-genai    # RAGAS Gemini judge wrapper
```

**Commit:** `chore(rag): add langfuse + ragas + respx deps`

---

**Task 7.3b — Create `tests/eval/ragas/conftest.py`**

Shared fixtures for both RAGAS test modules (Tasks 7.4 and 7.5):

```python
# tests/eval/ragas/conftest.py
import json
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture(scope="session")
def synthetic_corpus():
    return json.loads((FIXTURES_DIR / "synthetic_corpus.json").read_text())

@pytest.fixture(scope="session")
def golden_qa():
    return json.loads((FIXTURES_DIR / "golden_qa.json").read_text())

@pytest.fixture(scope="session")
def ragas_judge():
    """Returns the LLM judge (Langchain-wrapped Gemini or LiteLLM)."""
    # Use the path verified in Phase 0 Task 0.5
    from ragas.llms import LangchainLLMWrapper
    from langchain_google_genai import ChatGoogleGenerativeAI
    import os
    return LangchainLLMWrapper(
        ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            api_key=os.environ["GEMINI_API_KEY"],
        ),
    )
```

**Commit:** `test(rag): RAGAS conftest with fixtures + judge`

---

**Task 7.2b — Create `website/core/rag/observability/metrics.py`**

Spec §8.1 lists this file. Create it with per-stage latency tracking helpers used by `@trace_stage`:

```python
# website/core/rag/observability/metrics.py
import time
from contextlib import asynccontextmanager
from langfuse import get_client

langfuse = get_client()

@asynccontextmanager
async def track_latency(stage_name: str):
    """Context manager that records wall-clock latency to Langfuse metadata."""
    t0 = time.monotonic()
    yield
    elapsed = int((time.monotonic() - t0) * 1000)
    langfuse.update_current_span(metadata={f"{stage_name}_latency_ms": elapsed})
```

**Commit:** `feat(rag): latency tracking helper`

---

**Task 7.2c — Configure Langfuse client sanitization**

Spec §6.7 says: "Langfuse `sanitize` function strips keys matching `{api_key, token, password, secret}`." Implement this as a custom callback or a pre-send filter on the Langfuse client:

```python
# In website/core/rag/observability/tracer.py, after get_client():
import re

_SENSITIVE_PATTERN = re.compile(r"(api_key|token|password|secret)", re.IGNORECASE)

def _sanitize_payload(data: dict) -> dict:
    """Redact sensitive keys from trace payloads before upload."""
    if not isinstance(data, dict):
        return data
    return {
        k: ("***REDACTED***" if _SENSITIVE_PATTERN.search(k) else
            _sanitize_payload(v) if isinstance(v, dict) else v)
        for k, v in data.items()
    }
```

Wire this into the Langfuse SDK's configuration if it supports a `before_send` callback, or apply it manually to `input`/`output` before `update_current_span()`.

**Commit:** `feat(rag): Langfuse payload sanitization`

---

### Phase 8 additions

**Task 8.5 — Implement L3 5% production sampling**

Spec §6.8 says: "5% sampling of chat turns → gemini-2.5-flash-lite runs a lightweight faithfulness check on every 20th turn." Implement as a post-generation decorator or a counter-based check inside the orchestrator's `_run_pipeline`:

```python
# In orchestrator, after step 12 (persist message):
if turn_counter % 20 == 0:
    asyncio.create_task(_sample_faithfulness(answer_text, context_xml, trace_id))
```

`_sample_faithfulness` calls flash-lite with a short NLI prompt (same as the critic, but cheaper/lighter), tags the result into Langfuse as `sampled_faithfulness` on the trace. Non-blocking, non-fatal.

**Commit:** `feat(rag): L3 5% faithfulness sampling`

---

**Task 8.6 — Create quarterly blueprint re-read calendar entry**

Spec §6.8 and §13 #10 describe this as an operational discipline item. Create a note:

```
# docs/superpowers/plans/blueprint-re-read-schedule.md
Re-read docs/research/RAG_blueprint{1,2,3} every ~3 months.
Next scheduled: 2026-07-12
```

OR set up a recurring GitHub issue via `.github/ISSUE_TEMPLATE/blueprint-reread.yml`.

**Commit:** `docs(rag): quarterly blueprint re-read schedule`

---

**Task 8.7 — Document pre-computed Leiden community summaries migration path**

Spec §9 parked feature says "migration placeholder documented." Add a short markdown section to the spec or a separate doc describing:
- When to trigger: thematic-query ContextRecall < 0.55 for 2 consecutive weeks
- What to do: new migration `006_communities.sql` with `kg_communities(id, user_id, label, summary, embedding)` + `kg_community_members(community_id, node_id)`. Periodic Leiden detection via NetworkX + LLM-generated community summaries.
- Where it plugs in: `rag_hybrid_search` adds a 6th stream over community summary embeddings.

No code. Just the documented recipe.

**Commit:** `docs(rag): Leiden community summaries migration recipe`

---

**Task 3.25 addendum — Edge case #28 (answer exceeds max_output_tokens)**

Add to the streaming-path test (Task 3.25):

```python
def test_answer_stream_handles_truncated_finish_reason():
    # Mock LLM to return finish_reason="length"
    # Assert: the final SSE 'done' event includes "truncated": true
    # Assert: the persisted chat_message includes a metadata flag for truncation
```

---

## Summary of the 16 gap fixes

| # | Phase | Task | Spec § | What's added |
|---|---|---|---|---|
| 1 | 2 | 2.0 | §8.2 | `ops/requirements.txt` chonkie + networkx |
| 2 | 2 | 2.0b | §8.1 | `__init__.py` package markers for `rag/`, `ingest/`, `adapters/` |
| 3 | 2 | 2.11 | §9 | `ops/scripts/backfill_chunks.py` skeleton |
| 4 | 3 | 3.26 | §8.1, §9 | `backends/websearch.py` stub + `__init__.py` |
| 5 | 3 | 3.27 | §7.2 | Reranker health-check in deploy script |
| 6 | 3 | 3.25+ | §12 #28 | Edge case: answer exceeds max_output_tokens |
| 7 | 5 | 5.0 | §5.5 | `rag_chatbot/__init__.py` package marker |
| 8 | 6 | 6.24 | §5.5 | `content/example_queries.json` |
| 9 | 6 | gate | §12 #36, #44 | Manual edge-case checks added to verification gate |
| 10 | 7 | 7.0 | §8.2, §8.3 | `ops/requirements.txt` langfuse + `ops/requirements-dev.txt` ragas/respx |
| 11 | 7 | 7.3b | §6.2 | `tests/eval/ragas/conftest.py` |
| 12 | 7 | 7.2b | §8.1 | `observability/metrics.py` latency helper |
| 13 | 7 | 7.2c | §6.7 | Langfuse payload sanitization |
| 14 | 8 | 8.5 | §6.8 | L3 5% faithfulness sampling |
| 15 | 8 | 8.6 | §6.8, §13 #10 | Quarterly blueprint re-read schedule |
| 16 | 8 | 8.7 | §9 | Leiden community summaries migration recipe |

With these 16 additions, **every item from the spec is covered by at least one explicit plan task**.

---

**End of plan.** When ready, begin Phase 0.
