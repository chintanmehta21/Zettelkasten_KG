# RAG Chatbot Preflight Report

Date: 2026-04-12
Plan: `docs/superpowers/plans/2026-04-12-rag-chatbot.md`
Spec: `docs/superpowers/specs/2026-04-12-rag-chatbot-design.md`

## Task 0.1 - pgvector version on Supabase

Status: `blocked`

- Attempted a read-only query through the Supabase Management API using the project URL plus the locally available `SUPABASE_ACCESS_TOKEN`.
- Request target: `/v1/projects/<private>project-ref</private>/database/query/read-only`
- Query attempted: `SELECT extversion FROM pg_extension WHERE extname = 'vector';`
- Result: HTTP `403 Forbidden`
- Local environment does not have `psql`, and no direct Postgres connection variables were available in the checked env sources.

Outcome:
- pgvector version is still unconfirmed.
- This remains a real blocker relative to the plan's strict gate, but local implementation work is continuing under the user's explicit fallback instruction when prod verification is unavailable.

## Task 0.2 - Chonkie `BaseEmbeddings` contract

Status: `verified`

Local verification:
- Created a scratch venv and installed `chonkie`
- Verified installed version: `1.6.2`

Observed abstract contract:
- `dimension` - abstract property
- `embed(self, text: str) -> numpy.ndarray`
- `get_tokenizer(self) -> Any`

Implication for Phase 2:
- `GeminiChonkieEmbeddings` should implement exactly those three requirements.

## Task 0.3 - TEI support for `BAAI/bge-reranker-v2-m3`

Status: `blocked`

Local verification path:
- Docker Desktop was initially unavailable because the daemon was not running.
- Docker Desktop was then started successfully and `docker version` returned both client and server details.
- Attempted to launch:
  `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9 --model-id BAAI/bge-reranker-v2-m3 --port 8080`

Result:
- Image pull began, but container extraction failed with:
  `failed to commit snapshot ... input/output error`
- Because the image never became healthy, `/rerank`, `/health`, and `/healthz` could not be verified.

Outcome:
- Model compatibility is still unverified in this local environment.
- The failure appears environmental, not a confirmed model incompatibility signal.

## Task 0.4 - Langfuse v3 `@observe` on async generators

Status: `verified`

Local verification:
- Created a scratch venv and installed `langfuse>=3.0.0,<4`
- Verified installed version via metadata: `3.14.6`
- Ran the async-generator probe from the plan with dummy keys

Observed output:
- `0`
- `1`
- `2`
- `trace_id: None`

Notes:
- The decorator worked on an async generator in this environment.
- Additional context warnings were emitted because no live Langfuse backend was running, but the core decorator behavior succeeded.

Implication for Phase 7:
- The spec's `@observe` pattern for async-generator streaming can proceed as designed.

## Task 0.5 - RAGAS 0.4.3 Gemini judge path

Status: `blocked`

Local verification attempts:
- First install attempt for `ragas==0.4.3` and `langchain-google-genai` failed because the workstation ran out of free disk space.
- After deleting the temporary RAGAS venv, free disk space increased from roughly `0.06 GB` to `0.56 GB`.
- A second install still failed with `OSError: [Errno 28] No space left on device`.

Outcome:
- The `LangchainLLMWrapper` + Gemini judge path was not verified end-to-end yet.
- This is an environment-capacity blocker, not a design rejection.

## Task 0.6 - Synthetic corpus fixture

Status: `verified`

Artifacts created:
- `tests/eval/ragas/bootstrap_fixtures.py`
- `tests/eval/ragas/fixtures/synthetic_corpus.json`

Verification:
- `synthetic_corpus.json` row count: `50`
- Coverage mix included machine learning, cooking, history, finance, and travel entries.

## Task 0.7 - Golden Q/A fixture

Status: `verified`

Artifacts created:
- `tests/eval/ragas/fixtures/golden_qa.json`

Verification:
- `golden_qa.json` row count: `30`
- Each row contains:
  - `user_input`
  - `retrieved_contexts`
  - `response`
  - `reference`
  - `ground_truth_support`

## Fixture verification command

Status: `verified`

Command run:

```bash
python -m pytest tests/eval/ragas/test_fixtures.py -q
```

Observed result:
- `2 passed`

## Summary

| Task | Status | Notes |
|---|---|---|
| 0.1 pgvector version | blocked | Supabase Management API returned `403` |
| 0.2 Chonkie contract | verified | `dimension`, `embed`, `get_tokenizer` |
| 0.3 TEI reranker smoke test | blocked | Docker image extraction failed with I/O error |
| 0.4 Langfuse async generator | verified | `@observe` worked locally |
| 0.5 RAGAS Gemini judge | blocked | install failed due disk-space exhaustion |
| 0.6 synthetic corpus | verified | 50 entries generated |
| 0.7 golden Q/A | verified | 30 entries generated |

## Carry-forward notes

- The local fixture layer is now ready for later Phase 7 eval wiring.
- The remaining blocked items are infrastructure-level checks, not contradictions in the RAG design.
- Implementation can continue locally, but the blocked items should be revisited before claiming full plan conformance.
