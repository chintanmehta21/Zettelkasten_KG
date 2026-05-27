# Design and Testing Plan for `create_kasten`, `ask_kasten`, and `view_graph` APIs
## Overview
This document explains how the existing summarization "Add Zettel" API works in `Zettelkasten_KG`, and then proposes aligned designs for three module-runner style APIs:

- `create_kasten` – create Kasten sandboxes and optionally ingest links via the Add Zettel pipeline.
- `ask_kasten` – run user chats against a Kasten-backed RAG pipeline.
- `view_graph` – fetch knowledge-graph views for the current user and Kasten.

The goal is to mirror the existing async-ops, multi-tenant, and idempotent patterns of the summarization pipeline while keeping infra overhead low and tests thorough. The report also outlines Postman collection structure to validate these APIs end‑to‑end.

***
## Existing summarization async API
### Module runner: `website/api/module_runners/summarization.py`
The summarization runner is implemented as an importable module that encapsulates the Add Zettel pipeline logic for both FastAPI routes and CLI tools.

Key characteristics:

- Two main async entrypoints:
  - `run_add_zettel_pipeline(url, client_action_id, persist, user, effective_user_id, gemini_client_factory)` for URL-based ingestion.
  - `run_add_document_pipeline(filename, content, content_type, client_action_id, persist, user, effective_user_id, gemini_client_factory)` for document uploads.
- Uses a module-level `asyncio.Semaphore(2)` (`_SUMMARIZE_SEMAPHORE`) to limit concurrent summarization work per process.
- Resolves redirects and normalizes URLs via `resolve_redirects` and `normalize_url`, then checks a Supabase v2-based deduplication gate (`get_url_dedup_gate`) to reuse existing canonical zettels where possible.
- Enforces per-link user pricing via `require_entitlement(Meter.ZETTEL, user, action_id)`.
- Calls `summarize_url_bundle` or a document summarizer to obtain an ingest+summary bundle, and normalizes it into a `SummaryDTO` (title, summary variants, tags, source_type, url, token+latency metrics, metadata, and a `source_fingerprint_text` for dedup hashes).
- Persists results via `persist_summarized_result`, shielded with `asyncio.shield` to avoid partial writes on mid-flight cancel.
- Returns an `AddZettelPipelineOutput` DTO (status, operation_id, summary, persistence flags, quality metrics, node_id, workspace_zettel_id, optional error).
- Provides a small CLI entrypoint that loads env, runs `run_add_zettel_pipeline`, and prints JSON.

This structure is what the new module runners should mirror: thin glue around core engines, DTOs for stable contracts, concurrency guard, and optional persistence.
### HTTP facade: `website/api/zettels_routes.py`
The FastAPI routes under `/api/zettels` wrap the summarization runner in a robust async-ops state machine.

Important patterns:

- **Async long-running operations**
  - `POST /api/zettels/add` always returns `202 Accepted` with a status envelope, and the client polls `GET /api/operations/{id}` until a terminal state.
  - Operations are stored in `core.operations` via `operations_repo.accept`, `start`, `finalize`, and `cancel` with a strong consistency contract and TTL.
  - `GET /api/operations/{id}` returns `202` for queued/running/accepted states with `Retry-After` header tuned based on operation age, or `200/410` for terminal states with cache-control and ETags.

- **Idempotency**
  - Uses the IETF Idempotency-Key header (draft `draft-ietf-httpapi-idempotency-key-header`) as the canonical operation identifier when present; otherwise falls back to `client_action_id`.[^1][^2]
  - Computes a `_request_hash` of the JSON request body; if the same (user_id, request_hash) pair is seen, the same canonical operation is reused, aligning with industry best practice for idempotent POSTs.[^3]

- **Rate limiting and backpressure**
  - `_check_rate_limit` enforces simple per-IP sliding-window limits (10 requests per 60 seconds), returning 429 with a problem+json payload.
  - `check_async_backpressure` applies per-user async backpressure based on DB-tracked in-flight jobs.

- **Multi-tenant user scoping**
  - Effective user ID is derived from auth `sub` or a sentinel Zoro user; all operations in `core.operations` are keyed by user id, and Supabase v2 scope is always user-bound.
  - `list_zettels` uses `get_supabase_v2_scope_for_read` to constrain results to the user’s workspace(s), with canonical dedupe and presentation-only title normalization.
  - This mirrors general SaaS multi-tenant guidance where all queries are explicitly tenant-scoped at the data-access layer.[^4][^5]

- **Error surface and structured problems**
  - Uses shared `_problem_dict` builder to return RFC 9457-style `application/problem+json` errors for validation, SSRF blocking, Supabase write failures, and other problem cases.
  - Async failures are normalized via `_async_failure_error_payload` so terminal operation rows and synchronous failures share the same structured shape.

- **Graph cache invalidation**
  - On successful persistence, the handler schedules per-user graph cache invalidation via `_schedule_graph_invalidation`, decoupled from the hot path.

These patterns form the baseline contract the new APIs should match: async long-running operations where needed, explicit idempotency, multi-tenant scoping, rate control, and consistent error semantics.
### Existing Postman collection
The `tests/postman/collections/zettelkasten-summarization.postman_collection.json` file defines a comprehensive E2E test suite around the summarization and operations APIs.

Coverage highlights:

- Readiness checks (`/api/health`, `/api/auth/config`).
- Website-triggered Add Zettel for landing, home, and zettels surfaces, validating 202 response, Location/Retry-After headers, and status envelope shape.
- Polling `GET /api/operations/{id}` with exponential backoff until terminal or polling budget, asserting summary presence on success and non-5xx problem detail on failures.[^6][^7]
- Supabase integrity checks for workspace and canonical zettel rows and operations table.
- Validation and failure handling tests for malformed URLs, SSRF candidates, and unauthenticated access.
- v2 summarization endpoints (`/api/v2/summarize`, `/api/v2/batch`, `/api/v2/batch/stream` deprecation), and document upload async behavior.

New Postman tests for the Kasten and graph modules should reuse this pattern: collection-level pre-request gating, per-request test scripts, and environment variables for base URL, auth tokens, and Supabase credentials.

***
## Existing `create_kasten` module runner
### Implementation: `website/api/module_runners/create_kasten.py`
The codebase already includes a substantial `create_kasten` runner, which follows the summarization runner conventions and is invoked from `sandbox_routes`.

Core behaviors:

- Defines DTOs:
  - `IngestedLink` (url, workspace_zettel_id, node_id, was_new).
  - `FailedLink` (url, error).
  - `KastenDTO` with fields matching the sandbox representation (id, name, description, icon, color, default_quality, member_count, timestamps).
  - `CreateKastenOutput` wrapping status, Kasten DTO, ingested/failed lists, and operation_id.

- Uses module-level concurrency and idempotency:
  - `_CREATE_KASTEN_SEMAPHORE = asyncio.Semaphore(2)` to bound concurrent link ingestion, mirroring summarization’s semaphore.
  - An in-memory `OrderedDict` cache keyed by `(user_id, client_action_id)` plus `_IN_FLIGHT` map for deduplication within a 15-minute TTL and size cap; raises `IdempotencyConflict` on mismatched request hashes.

- Validates inputs:
  - `name` is required, trimmed, max length 80 characters; `default_quality` normalized to `fast` or `high`. The UI screenshot shows exactly this binary quality choice.
  - All `links` are required to be non-empty, within 2048 characters, `http/https` only, and pass the same `validate_url` SSRF blockers as Add Zettel.

- Integrates with Supabase v2:
  - Resolves `content_repo` and `workspace_id` via `get_supabase_v2_scope`; fails explicitly if v2 workspace scope is unavailable, consistent with dual-path gating.
  - Uses `RAGRepository` (v2 rag repository) to create or reuse `rag.kastens` rows via `_create_or_get_kasten`, which handles unique(workspace_id, name) duplicate-key errors by fetching the existing Kasten.

- Ingests links through Add Zettel:
  - For each cleaned link, runs the summarization pipeline with a derived `client_action_id` suffix and `persist` flag, inside `_CREATE_KASTEN_SEMAPHORE`.
  - Extracts summary, persistence info, resolves the `workspace_zettel_id` via `content_repo.resolve_workspace_zettel_id_by_url`, and records per-link outcomes in ingested/failed arrays.

- Adds zettels to the Kasten:
  - Uses `rag_repo.add_zettels_to_kasten(kasten_id, workspace_zettel_ids)` with `ON CONFLICT DO NOTHING`, so re-submits are idempotent.

- Enrichment and graph cache:
  - For CLI/short-lived callers, `drain_enrichment=True` drains process-wide pending enrichment tasks to completion before returning; HTTP background routes pass `drain_enrichment=False` to avoid cross-request coupling.
  - Invalidates per-user and global graph caches via `_invalidate_graph(user_sub)` after Kasten+membership creation.

- CLI entrypoint mirrors summarization: parse args, optionally load `.env` files and API keys, run `run_create_kasten_pipeline`, print JSON.

This runner already satisfies most of the requirements in the query for the `create_kasten` module; the main remaining work is aligning documentation and tests, and potentially minor tweaks for additional UI fields (e.g., selection of zettels by source or explicit IDs) if needed.
### HTTP facade: `sandbox_routes.create_sandbox`
`POST /api/rag/sandboxes` is the main entrypoint for Kasten creation and is tightly integrated with the `create_kasten` runner.

Design highlights:

- Uses `SandboxCreateRequest` (name, description, icon, color, default_quality, client_action_id, links) with validators matching the runner’s constraints and URL validation for links.
- For non-empty `links`:
  - Verifies that a Supabase v2 workspace scope exists; otherwise returns 501 to avoid misleading behavior.
  - Charges `Meter.KASTEN` entitlement once for the whole operation; per-link `Meter.ZETTEL` is enforced inside the summarization pipeline.
  - Uses a per-user, per-operation in-memory operation store (`_KASTEN_OPERATIONS`, `_KASTEN_OP_TASKS`) keyed by `(user_sub, operation_id)` to track async create-with-links operations.
  - Generates `operation_id` from explicit `client_action_id` or a fresh UUID, ensures it is URL-safe (via `quote`), and returns a 202 envelope with `status="accepted"` and `status_url` under `/api/rag/sandboxes/operations/{id}`.
  - Spawns a background task `run_create_kasten_pipeline` with `drain_enrichment=False`; results or errors are stored back into `_KASTEN_OPERATIONS` for subsequent polling.

- For empty `links`:
  - Follows a synchronous dual-path that either writes via v2 `rag.kastens` or falls back to the legacy sandbox store, returning `{ "sandbox": ... }` directly, after charging entitlements.

- Provides `GET /api/rag/sandboxes/operations/{operation_id}` for polling, scoped to the authenticated `sub` via `_scoped_op_key`, mirroring the summarization `operations` contract but within the rag namespace.

Collectively, this means that **for `create_kasten` no new module runner is needed**; instead, the focus is on documenting how to call `run_create_kasten_pipeline` and `create_sandbox` and writing corresponding Postman tests.

***
## Proposed `ask_kasten` module runner
### Backend components to reuse
The core RAG runtime is built in `website/features/rag_pipeline/service.py` and `types.py`.

Key reusable elements:

- `get_rag_runtime(user_sub)` returns a memoized `RAGRuntime` consisting of:
  - `kg_user_id` (UUID derived from auth subject), optional `workspace_id`, and a Supabase v2 client bound to the caller’s workspace.
  - `RAGOrchestrator` wired with query rewriter/router/transformer, `HybridRetriever` (including KG-based expansion), `CascadeReranker`, `ContextAssembler`, `LLMRouter`, `AnswerCritic`, and `QueryMetadataExtractor`.
  - `ChatSessionStore` and `SandboxStore` for chat session history and Kasten membership.

- `ChatQuery`, `ChatTurn`, `AnswerTurn`, `ScopeFilter`, and `Citation` DTOs in `types.py`, which already describe chat requests and structured answers for user-level RAG.

- `sandbox_routes` currently use `get_rag_runtime` for listing nodes and managing kastens, but the actual chat/ask endpoints are in `chat_routes.py` (not fully inspected here but follow similar patterns).
### Runner signature and responsibilities
A proposed module runner for `ask_kasten` in `website/api/module_runners/ask_kasten.py` should:

- Be importable from FastAPI routes and CLI tools.
- Encapsulate:
  - Construction of `ChatQuery` with appropriate `scope_filter` to restrict retrieval to a particular Kasten.
  - Execution of the RAG orchestrator to obtain an `AnswerTurn` (or streaming `AnswerChunk`s).
  - Normalization into a wire DTO (`AskKastenOutput`) that is safe to expose over the API.

A recommended interface (following summarization’s style):

```python
async def run_ask_kasten_pipeline(
    *,
    kasten_id: UUID,
    query: str,
    client_action_id: str,
    user: dict | None,
    effective_user_id: UUID,
    quality: Literal["fast", "high"] = "fast",
    stream: bool = False,
) -> dict[str, Any]:
    """Run a single RAG chat turn scoped to a Kasten for API and CLI callers."""
```

Behavior sketch:

1. Derive `runtime = get_rag_runtime(user.get("sub"))` and assert that the Kasten exists and belongs to the caller’s workspace (using v2 `RAGRepository.get_kasten` or `SandboxStore`).
2. Build a `ScopeFilter` whose `node_ids` are the workspace_zettel IDs belonging to the Kasten, or rely on a repository method that implicitly scopes retrieval by Kasten membership.
3. Construct a `ChatQuery`:
   - `session_id` may be derived from an existing chat session for the Kasten, or left `None` for a stateless one-off.
   - `sandbox_id` set to `kasten_id` so the runtime can associate future turns with this sandbox if needed.
   - `content` is the user’s question.
   - `scope_filter` as above, `quality` mapped from UI (fast vs strong/high), `stream` as requested.
4. Call a RAG orchestrator method such as `runtime.orchestrator.answer(query, runtime.kg_user_id, scope_filter, quality=...)` (the exact method name would be derived from `orchestrator.py`).
5. Translate the result into an `AskKastenOutput`:

```python
class AskKastenOutput(BaseModel):
    status: Literal["succeeded", "failed"]
    operation_id: str
    kasten_id: str
    answer: AnswerTurn | None
    stream: bool = False
    error: dict[str, Any] | None = None
```

6. Return `.model_dump(mode="json")` to keep parity with other runners.
### Multi-user and UI data requirements
From the "Create Kasten" UI screenshot and existing types:

- Each Kasten has:
  - `name` (free-text, max 80).
  - `default_quality` (Fast/Strong → `fast`/`high`).
  - Inclusion options: "All", "By source", "Specific"; these map naturally to `ScopeFilter` combinations for `ask_kasten`.
  - A zettel picker (filter and list) used to choose specific nodes.
  - Optional `description`.

Therefore, the API payload for `ask_kasten` should include:

- `kasten_id` – the sandbox to query.
- `question` – user’s message.
- Optional overrides for quality and scope:
  - `quality` (defaults to Kasten default if omitted).
  - `scope` object specifying `mode` (`all`, `by_source`, `specific`), `node_ids`, `source_types`, `tags`, `tag_mode`.

On a multi-tenant system, all of these must be tenant-scoped:

- `kasten_id` must resolve within the caller’s workspace; cross-tenant IDs must 404/403.[^4]
- `node_ids` must correspond to workspace_zettels within the same tenant; invalid IDs or cross-tenant attempts should be safely ignored or rejected.

To keep infra overhead minimal, the runner should reuse existing repositories (RAGRepository and SandboxStore) and avoid new DB tables.
### Async vs sync
Unlike summarization and create-with-links, a single RAG question typically finishes within tens of seconds, and the orchestrator already includes internal budget controls (e.g., `RAG_RETRY_BUDGET_S`).

Industry guidance suggests using synchronous responses for interactive chat APIs whenever possible, resorting to async operations only for very long-running jobs.[^6][^7]

For `ask_kasten`:

- A synchronous `POST /api/rag/sandboxes/{id}/ask` returning 200 with the answer is appropriate for most cases.
- Streaming (e.g., SSE or WebSocket) can be a future enhancement; for now, the `stream` flag in the runner can be accepted but ignored or used to batch partial outputs.

Because the query is per-user and not persisted as a background operation, there is no need to integrate with the `core.operations` async state machine, which keeps droplet load lower and simplifies implementation.

***
## Proposed `view_graph` module runner
### Existing knowledge-graph backend
The `website/features/knowledge_graph` directory primarily contains static front-end assets (HTML, CSS, JS) for the graph visualization. The backend graph data API itself is exposed through `website/api/routes.py` and `website/api/graph_cache.py` (listed under `website/api`).

`graph_cache.py` suggests that there is a shared per-user and global cache of graph data used by `/api/graph` and invalidated by both summarization and create_kasten flows.

Design intent:

- `GET /api/graph?view=my` returns the current user’s knowledge graph data (nodes, edges, metadata) using precomputed KG edges.
- Add Zettel and create_kasten operations call `invalidate_user_graph(user_sub)` and reset global cache when new content arrives so that subsequent `/api/graph` calls recompute graph data for that user.
### Runner responsibilities
A module runner in `website/api/module_runners/view_graph.py` should:

- Encapsulate graph data retrieval per user, independent of HTTP.
- Offer hooks for different views:
  - `my` – personal graph.
  - `kasten` – subgraph restricted to a specific Kasten’s zettels.
  - Potential future views like `global` or `shared-with-me`.

A proposed interface:

```python
async def run_view_graph_pipeline(
    *,
    effective_user_id: UUID,
    view: Literal["my", "kasten"],
    kasten_id: UUID | None = None,
) -> dict[str, Any]:
    """Render the user-level knowledge graph or Kasten subgraph for API and CLI callers."""
```

Behavior sketch:

1. Convert `effective_user_id` to `user_sub` string.
2. Depending on `view`:
   - For `my`, reuse existing functions in `routes.py`/`graph_cache.py` that compute the full `my` graph.
   - For `kasten`, first verify that `kasten_id` is owned by the user’s workspace (via `RAGRepository` or `SandboxStore`), then restrict the graph-building query to its workspace_zettel_ids.
3. Use any existing caching mechanism (if `graph_cache.py` exposes helpers) so the runner benefits from caching when invoked via HTTP.
4. Return a DTO shape matching existing `/api/graph` responses (nodes, links, metadata) to avoid changing the front-end.
### Multi-tenant and infra considerations
- All graph queries must be constrained by user/workspace ID (consistent with Supabase v2 RLS and general SaaS best practice).[^4][^8]
- For `view=kasten`, both membership and Kasten ownership must be verified; unauthorized Kasten IDs must return a safe 404/403 without leaking existence.
- The runner should rely on existing caches rather than introducing new caching layers, to keep infra overhead low.

***
## API contracts and payloads
### `create_kasten` API
The HTTP-level `POST /api/rag/sandboxes` contract is mostly implemented already and should be treated as the primary API for Kasten creation.

Key fields (per `SandboxCreateRequest` and `create_kasten` runner):

- Request JSON:

```json
{
  "name": "Climate research",
  "description": "Group of zettels about climate research topics",
  "icon": "stack",
  "color": "#14b8a6",
  "default_quality": "fast",  // or "high" for strong reasoning
  "client_action_id": "web-create-kasten-<uuid>",
  "links": [
    "https://example.com/article-1",
    "https://example.com/article-2"
  ]
}
```

- Response for `links=[]`:

```json
{
  "sandbox": {
    "id": "<kasten-uuid>",
    "name": "Climate research",
    "description": "...",
    "icon": "stack",
    "color": "#14b8a6",
    "default_quality": "fast",
    "member_count": 0,
    "last_used_at": null,
    "created_at": "...",
    "updated_at": "..."
  }
}
```

- Response for `links!=[]` (async):

```json
{
  "status": "accepted",
  "operation_id": "<operation-id>",
  "status_url": "/api/rag/sandboxes/operations/<operation-id>"
}
```

- Polling `GET /api/rag/sandboxes/operations/{operation_id}` eventually returns:

```json
{
  "status": "succeeded",
  "operation_id": "<operation-id>",
  "kasten": { ... KastenDTO ... },
  "ingested": [
    { "url": "https://...", "workspace_zettel_id": "...", "node_id": "...", "was_new": true }
  ],
  "failed": [
    { "url": "https://bad-url", "error": "workspace_zettel not found after persist" }
  ]
}
```
### `ask_kasten` API (proposed)
Proposed HTTP route: `POST /api/rag/sandboxes/{kasten_id}/ask`.

- Request JSON:

```json
{
  "question": "What are the key drivers of climate change?",
  "quality": "fast",  // optional, defaults to Kasten.default_quality
  "scope": {
    "mode": "all",            // "all" | "by_source" | "specific"
    "node_ids": ["<wz-id-1>", "<wz-id-2>"],
    "source_types": ["web", "arxiv"],
    "tags": ["IPCC", "climate"],
    "tag_mode": "any"         // "all" | "any"
  },
  "client_action_id": "web-ask-kasten-<uuid>"
}
```

- Response JSON (synchronous):

```json
{
  "status": "succeeded",
  "operation_id": "web-ask-kasten-<uuid>",
  "kasten_id": "<kasten-uuid>",
  "answer": {
    "content": "Human activities such as burning fossil fuels ...",
    "citations": [
      {
        "id": "itation-id>",
        "node_id": "<wz-id-1>",
        "title": "IPCC report ...",
        "source_type": "web",
        "url": "https://...",
        "snippet": "The IPCC concludes that ...",
        "timestamp": "...",
        "rerank_score": 0.92
      }
    ],
    "query_class": "lookup",
    "critic_verdict": "supported",
    "critic_notes": null,
    "trace_id": "...",
    "latency_ms": 2300,
    "token_counts": { "prompt": 1500, "completion": 250 },
    "llm_model": "gemini-1.5-pro",
    "retrieved_node_ids": ["<wz-id-1>", "<wz-id-2>"],
    "retrieved_chunk_ids": ["hunk-uuid>"]
  },
  "error": null
}
```

- On validation or auth failure, return RFC 9457-style problem+json similar to existing routes.

Given typical chat latencies and industry patterns, this API can remain synchronous, avoiding the complexity and overhead of introducing another async-ops state machine.[^6][^9]
### `view_graph` API (proposed)
Proposed HTTP routes:

- `GET /api/graph?view=my` – existing, to be documented and covered in tests.
- `GET /api/graph?view=kasten&kasten_id={uuid}` – new Kasten-scoped graph view.

- Response JSON:

```json
{
  "nodes": [
    {
      "id": "<node-id>",
      "label": "Climate change",
      "type": "zettel",       // or "topic", "entity", etc.
      "source_type": "web",
      "importance": 0.8,
      "tags": ["climate", "IPCC"]
    }
  ],
  "links": [
    {
      "id": "<edge-id>",
      "source": "<node-id-1>",
      "target": "<node-id-2>",
      "kind": "citation",     // or "co-mention", "topic" etc.
      "weight": 0.7
    }
  ],
  "meta": {
    "view": "kasten",
    "kasten_id": "<kasten-uuid>",
    "updated_at": "...",
    "node_count": 120,
    "edge_count": 340
  }
}
```

Internally, `run_view_graph_pipeline` should call the same graph-building functions used by `routes.py` and follow existing caching rules to avoid recomputation on every request.

***
## Postman test design for new APIs
### Industry-standard testing patterns
Recent API design and testing literature emphasizes:

- End-to-end tests that validate not only HTTP status codes but also schema, idempotency, authorization, and data consistency.[^10][^11]
- Use of environment-level gates to prevent accidental hits to live environments, as in the existing summarization collection.
- Explicit tests for multi-tenant isolation: verifying that users cannot see or influence other tenants’ data, particularly in SaaS contexts.[^4][^5]

The existing `zettelkasten-summarization` collection already follows these practices; new collections should mirror its structure and scripts.
### `create_kasten` Postman collection (new)
Create a new collection, e.g., `zettelkasten-kastens.postman_collection.json`, with folders:

1. **P1 Readiness**
   - Reuse `GET /api/health` and `GET /api/auth/config` tests from summarization to ensure the API is up.

2. **P1 Kasten creation flows**
   - `P1 Create Kasten without links (sync)`
     - POST `/api/rag/sandboxes` with a unique `name`, no `links`, and `Authorization` header.
     - Assert 200, presence of `sandbox` object, and fields `id`, `name`, `default_quality`, `member_count`.
   - `P1 Create Kasten with links (async)`
     - POST `/api/rag/sandboxes` with `links` array and `client_action_id`.
     - Assert 202, `status="accepted"`, `status_url` points to `/api/rag/sandboxes/operations/{id}`, and `Location` header matches.
   - `P1 Poll Kasten operation until terminal` (similar to `P1 Poll home operation` in summarization).
     - GET `/api/rag/sandboxes/operations/{{kasten_op_id}}` with exponential backoff and `Retry-After` awareness.
     - On success, assert `kasten` object present, `ingested` and `failed` arrays well-formed.

3. **P1 Multi-tenant scoping**
   - `P1 User A Kasten list contains only own kastens`
     - GET `/api/rag/sandboxes` as User A, assert no duplicates and optional member counts.
   - `P1 User B cannot poll User A Kasten operation`
     - GET `/api/rag/sandboxes/operations/{{operation_id_from_user_a}}` with User B auth, assert 404 or 404/403 and that response does not leak Kasten metadata.

4. **P1 Validation and idempotency**
   - `P1 Invalid Kasten name is rejected`
     - POST with blank or oversize name, assert 400/422 and structured problem JSON.
   - `P1 Invalid links are rejected by validator`
     - POST with `links` containing `ftp://` or SSRF candidate, assert 400/422.
   - `P1 Idempotent re-submit with same client_action_id and body replays` (or reuses cached result)
     - POST same payload twice, assert that the second call either:
       - returns the same operation_id (async path) and final result via operation polling, or
       - returns a cached result from `_IDEMPOTENCY_CACHE` if invoked via runner.
   - `P1 Idempotency conflict on changed body`
     - POST with one set of links, then with different links but same `client_action_id`; expect 409 conflict mapped from `IdempotencyConflict`.

5. **P2 Supabase integrity (optional)**
   - Similar to summarization Supabase checks, but focusing on `rag.kastens` and `rag.kasten_zettels` rows associated with the created Kasten.
### `ask_kasten` Postman tests (new)
Create a collection `zettelkasten-ask-kasten.postman_collection.json` with folders:

1. **P1 Readiness and setup**
   - A setup folder that calls `create_kasten` with known links and captures `kasten_id` for subsequent tests.

2. **P1 Ask flows**
   - `P1 Ask Kasten returns answer`
     - POST `/api/rag/sandboxes/{{kasten_id}}/ask` with a simple question, as an authenticated user.
     - Assert 200, `status="succeeded"`, non-empty `answer.content`, `citations` array present, and `kasten_id` matches path.
   - `P1 Ask respects default quality`
     - Create two Kastens with `default_quality` fast vs high, ask the same question and capture `llm_model` or `token_counts` differences to verify that high-quality path uses heavier models or more tokens.

3. **P1 Multi-tenant and scoping**
   - `P1 User B cannot ask User A Kasten`
     - Attempt to POST ask on a Kasten created by User A using User B auth; expect 404/403.
   - `P1 Ask with specific node_ids does not leak other zettels`
     - Provide explicit `node_ids` subset; assert that `retrieved_node_ids` and `citations.node_id` are all within the provided set.

4. **P1 Validation and error handling**
   - `P1 Empty question is rejected`
     - POST with blank question; expect 400/422 problem JSON.
   - `P1 Invalid scope mode or quality is rejected`
     - Send `quality=slow` or `scope.mode=unknown`, expect validation error.

5. **P2 Latency and budgeting**
   - Optional tests verifying that response times are within tolerable bounds for interactive chat (e.g., < 30s), and that long-running queries are surfaced with appropriate errors.
### `view_graph` Postman tests (new)
Create `zettelkasten-graph.postman_collection.json` with folders:

1. **P1 Readiness**
   - `P1 Graph endpoint reachable`
     - GET `/api/graph?view=my` with auth, assert 200 and presence of `nodes` and `links` arrays.

2. **P1 Multi-tenant isolation**
   - `P1 User A graph does not leak User B nodes`
     - After ingesting distinct URLs under each user, GET `/api/graph?view=my` as both users and compare high-level counts or node labels to ensure separation.

3. **P1 Kasten-scoped graph**
   - `P1 Kasten view only includes Kasten zettels`
     - Create a Kasten with a known subset of zettels, then call `/api/graph?view=kasten&kasten_id={{id}}` and assert that all nodes correspond to members returned by `/api/rag/sandboxes/{id}/members`.

4. **P1 Unauthorized Kasten graph access**
   - `P1 User B cannot view User A Kasten graph`
     - Expect 404/403 as with ask_kasten.

5. **P2 Cache behavior**
   - Optional tests to verify that repeated calls within a short window return 200 with similar results and potentially shorter response times, indirectly validating cache.

***
## Industry-standard alignment and rationale
### Async operations and polling
The existing summarization and create_kasten design closely matches common async-ops patterns recommended in modern REST API cookbooks and microservice design guidelines: use 202 Accepted responses with `Location` and `Retry-After` headers, plus a separate status endpoint for polling.[^6][^7]

This approach:

- Avoids long-lived HTTP connections that risk timeouts and poor UX.
- Lets the server offload heavy work to background workers and manage concurrency centrally.
- Keeps the client contract simple: `POST` to start, then `GET` status until terminal.

The new `create_kasten` async behavior is already aligned with these patterns.
`ask_kasten` can stay synchronous, consistent with guidance that interactive chat-style APIs favor direct responses unless operations become genuinely long-running.[^9][^6]
### Idempotency and the Idempotency-Key header
Both summarization and create_kasten use a combination of:

- An `Idempotency-Key` header at the HTTP layer for clients to safely retry POSTs.[^3]
- A server-side request hash/fingerprint embedded in their operation stores/RPCs to ensure that reusing a key with a different request body yields a 409-style conflict instead of silent duplication.[^2]

This matches the emerging IETF standard and MDN guidance on the `Idempotency-Key` header for fault-tolerant non-idempotent methods.[^1][^3][^2]

The new APIs should:

- Reuse `Idempotency-Key` on any async POST (`create_kasten` with links) and treat it as the canonical operation identifier.
- Implement idempotency in `ask_kasten` only if clients need at-least-once retry semantics; for typical chat UI usage, plain POST without idempotency may suffice.
### Multi-tenant scoping
The codebase already follows best practice for SaaS multi-tenancy:

- User-level scoping via JWT `sub` and Supabase v2 RLS using profile/workspace IDs.[^4][^5]
- Per-user operation stores and per-user graph caches keyed by user-subject.
- Strong BOLA (broken object-level authorization) mitigations in Kasten delete and member manipulation endpoints, resolving caller workspace and verifying ownership before any mutation.

The new APIs (especially `ask_kasten` and `view_graph`) must continue to:

- Always resolve Kasten and zettel memberships in the context of the caller’s workspace.
- Avoid accepting arbitrary IDs without verifying they belong to the caller.
- Return uniform 404/403 responses for unauthorized Kasten IDs to avoid leaking existence across tenants.
### Infra overhead considerations
The proposed design keeps additional infra overhead low by:

- Reusing existing async operations infrastructure only where necessary (create-with-links operations).
- Keeping `ask_kasten` synchronous, with no new operations table usage, queues, or background workers.
- Leveraging existing Supabase v2 clients and repositories for all persistent data.
- Using the existing graph cache layer for `view_graph`, rather than introducing new caches or message queues.

This aligns with general recommendations to avoid over-engineering small services and only introduce asynchronous orchestration when operations exceed typical web request budgets.[^6][^12][^9]

***
## Summary of sub-modules and their roles
| Module/API | Responsibility | Key inputs | Key outputs | Async? | Multi-tenant mechanisms |
|-----------|----------------|-----------|-------------|--------|-------------------------|
| `module_runners.summarization` + `/api/zettels/add` | Ingest and summarize URLs/documents into zettels, persisting to Supabase and graph, via async operations. | `url` or document, `client_action_id`, `persist`, `user` | `AddZettelPipelineOutput` (summary, persistence, quality, node_id, workspace_zettel_id) or problem+json | Yes (202 + `/api/operations/{id}`) | User ID from auth `sub`, Supabase v2 scope, per-user operations rows, graph invalidation per user. |
| `module_runners.create_kasten` + `POST /api/rag/sandboxes` | Create or reuse Kasten sandboxes; optionally ingest links via Add Zettel and add resulting zettels to the Kasten; invalidate graph. | `name`, `description`, `icon`, `color`, `default_quality`, `links[]`, `client_action_id`, `user` | Sync: `{ "sandbox": KastenDTO }`; Async: `CreateKastenOutput` via `/api/rag/sandboxes/operations/{id}` | Sync for create-only; async for create+links | Supabase v2 `rag.kastens` and `rag.kasten_zettels`, Kasten uniqueness per workspace, per-user in-memory op store scoped by auth `sub`. |
| `module_runners.ask_kasten` + `POST /api/rag/sandboxes/{id}/ask` (proposed) | Run Kasten-scoped RAG queries using orchestrator, respecting Kasten’s default quality and scope filters. | `kasten_id`, `question`, optional `quality` and `scope`, `client_action_id`, `user` | `AskKastenOutput` with `AnswerTurn` payload and citations | No (synchronous 200) | Validate Kasten ownership via v2 repo or sandbox store; restrict retrieval to Kasten’s zettels and caller’s workspace; auth via `get_current_user`. |
| `module_runners.view_graph` + `GET /api/graph` (proposed extension) | Render knowledge graph views per user or per Kasten using existing graph computation and caches. | `view` (`my` or `kasten`), optional `kasten_id`, `user` | Graph JSON (nodes, links, meta) | No (synchronous 200) | Graph queries keyed by user/workspace; Kasten graph view restricted to caller’s Kasten membership; per-user cache invalidated by summarization and create_kasten. |
| Postman collections (summarization + new ones) | Exercise each endpoint under realistic conditions, checking status codes, schema, idempotency, multi-tenant behavior, and Supabase integrity. | Environment variables (base URL, auth tokens, Supabase credentials) and test data URLs | E2E coverage reports and latency logs | N/A | UserA/UserB tokens model multi-tenant boundaries; Supabase queries use service-role keys but assert correct scoping. [^4] |

This plan keeps the new APIs structurally aligned with the existing summarization and Kasten infrastructure, respects modern API design and multi-tenant best practices, and minimizes additional infra complexity while enabling comprehensive Postman-based validation.

---

## References

1. [Security Considerations](https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-01.html) - The HTTP Idempotency-Key request header field can be used to carry idempotency key in order to make ...

2. [draft-ietf-httpapi-idempotency-key-header-03](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header-03) - The HTTP Idempotency-Key request header field can be used to carry idempotency key in order to make ...

3. [Idempotency-Key header - HTTP - MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Idempotency-Key) - The HTTP Idempotency-Key request header can be used to make POST and PATCH requests idempotent.

4. [Multi-tenant SaaS authorization and API access control](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-api-access-authorization/introduction.html) - Design options and best practices for implementing authorization and API access controls for multi-t...

5. [The developer's guide to SaaS multi-tenant architecture - WorkOS](https://workos.com/blog/developers-guide-saas-multi-tenant-architecture) - This guide is a technical walk through the decisions you'll need to make: from modeling tenants, to ...

6. [Design asynchronous API | The REST API cookbook](https://octo-woapi.github.io/cookbook/asynchronous-api.html) - How to design asynchronous API

7. [The Asynchronous Request-Reply pattern](https://dev.to/willvelida/the-asynchronous-request-reply-pattern-16ki) - Client-side applications often rely on APIs to provide data and functionality, which are either in.....

8. [How to Design a Multi-Tenant SaaS Architecture - Clerk](https://clerk.com/blog/how-to-design-multitenant-saas-architecture) - In this guide, we'll walk through the core principles of multi-tenancy, popular database models, aut...

9. [what is the best practice for handling asynchronous api call that take time](https://stackoverflow.com/questions/67173190/what-is-the-best-practice-for-handling-asynchronous-api-call-that-take-time) - So suppose I have an API to create a cloud instance asynchronously. So after I made an API call it w...

10. [Which RESTful API Design Rules Are Important and How Do They Improve
  Software Quality? A Delphi Study with Industry Experts](https://arxiv.org/pdf/2108.00033.pdf) - ...REST concepts and practical
implementations lead us to believe that practitioners perceive many r...

11. [Combining API Patterns in Microservice Architectures: Performance and Reliability Analysis](https://zenodo.org/record/7994295/files/2023131243.pdf) - ...especially using a large distributed system workload setting. This paper experimentally studies t...

12. [Moving beyond API polling to asynchronous API design - Tyk.io](https://tyk.io/blog/moving-beyond-polling-to-async-apis/) - Replacing API polling with more modern and effective methods like asynchronous api design. Explore a...

