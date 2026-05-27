# MultimodalText API research report

## Bottom line

The repository already has a clear pattern for “website endpoint → module runner → guarded backend work → typed output,” and it is strongest today in the summarization path. The summarization runner is importable, async-aware, uses Pydantic DTOs, lazy imports, entitlement checks, bounded concurrency, and shielded persistence. There is also already a partially realized sibling pattern for `create_kasten`: the repo contains a design note, unit tests for a consolidated route, and live integration tests proving async `202 Accepted` + polling, idempotent re-submit behavior, immediate read-after-write visibility, and cross-tenant denial. In other words, the practical work remaining is not “invent all three from scratch,” but rather: expand `create_kasten` to fully cover the modal’s current website options, add a true `ask_kasten.py` runner, add a true `view_graph.py` runner, and keep each route’s external transport semantics aligned with its UX instead of forcing every module into the same HTTP shape. fileciteturn48file0L3-L3 fileciteturn45file0L3-L3 fileciteturn46file0L3-L3

The most important architectural recommendation is this: **copy the summarization module’s internal structure, not necessarily its exact external wire contract**. For long-running work, the industry-standard pattern is fast acceptance with a pollable status resource, usually using `202 Accepted`, `Location`, and `Retry-After`, plus a terminal status document and structured errors. Microsoft’s async request-reply guidance explicitly recommends that shape and also recommends idempotency keys and cancel support for long-running work. Google’s API guidance likewise treats long-running operations and request identification as first-class patterns. But the same Microsoft guidance says polling is *not* the best fit when the client needs real-time streaming; for those cases, SSE is appropriate. That distinction matters directly here: `create_kasten` should lean into async polling, `ask_kasten` should keep SSE/non-stream chat semantics, and `view_graph` should stay a normal synchronous GET with cache and invalidation. citeturn3view0turn10view0turn10view1turn10view2turn10view3turn8view0turn14view0turn13view1

## What the current summarization API already establishes

The summarization runner is the clearest “golden template” in the repo. `website/api/module_runners/summarization.py` defines typed DTOs, a shared semaphore, lazy imports for heavy dependencies, entitlement gating before expensive work, conversion to a stable public DTO, and `asyncio.shield()` around persistence so partial cancellation does not corrupt the write path. It also threads `client_action_id` through the request context for correlation and returns a uniform `AddZettelPipelineOutput` with fields such as `status`, `operation_id`, `summary`, `persistence`, `quality`, `workspace_zettel_id`, and `status_url`. fileciteturn48file0L3-L3

The repo’s design note for `create_kasten` explicitly summarizes the current summarization endpoint behavior: the Add Zettel path uses a user-scoped idempotency key based on `(user, client_action_id)` plus a request hash, a 900-second cache window, an in-flight shield, and async polling via the in-memory async operation mode. That same note also records the convention that sibling runners should follow: entitlement gate before work, semaphore-limited concurrency, Pydantic JSON output, lazy imports, and a CLI entrypoint. That is the exact “similar-structured APIs” contract to reuse for the new modules. fileciteturn43file0L3-L3

The Postman scaffolding for summarization already exists in the repo and should be treated as the template location for the new modules: there is a README, a coverage map, a Postman collection, and a smoke data file under `tests/postman`. That means the new `create_kasten`, `ask_kasten`, and `view_graph` collections should be added *next to* the existing summarization collection rather than creating a parallel test layout elsewhere. fileciteturn49file31L1-L3 fileciteturn49file32L1-L3 fileciteturn49file33L1-L3 fileciteturn49file35L1-L3

A final point worth preserving from the summarization path is the idempotency strategy itself. Stripe’s public API guidance is a strong industry reference here: it stores the first result for a given idempotency key, returns the same result on retries, recommends random UUID-like keys, warns against sensitive data in keys, and compares subsequent request parameters against the original to prevent misuse. Microsoft’s async API guidance similarly recommends requiring an idempotency key for initial submissions to protect against duplicate POSTs after network failures, and Google’s request-identification guidance says the purpose is de-duplication, safe retries, and auditing. The summarization path is already moving in that direction; the other runners should do the same. citeturn6view0turn6view1turn6view2turn6view3turn10view2turn14view0

## Create kasten API recommendation

The repo already contains live integration tests showing the shape `create_kasten` should preserve: when links are present, `POST /api/rag/sandboxes` returns `202`, exposes a `status_url`, completes via polling, creates the kasten, adds its members, makes them visible through `GET /api/rag/sandboxes` and `GET /api/rag/sandboxes/{id}/members`, and invalidates the personal graph so the newly ingested links are visible under `/api/graph?view=my`. The unit tests also show the backward-compatibility requirement: if `links` are omitted or `[]`, the response stays byte-identical to the legacy create-only shape. fileciteturn45file0L3-L3 fileciteturn46file0L3-L3

The website modal currently captures much more than the existing link-ingest variant. The HTML shows `name`, `default_quality`, three membership modes (`all`, `source`, `specific`), a source-type grid, a zettel picker for specific mode, and optional `description`. It also shows an important semantic mapping: the UI label says **Strong**, but the value sent by the form is `high`; the backend should therefore treat `fast|high` as the API enum and keep “Strong” purely as presentation text. fileciteturn47file0L3-L3

![Create Kasten modal fields](sandbox:/mnt/data/image.png)

The request body I would standardize for the fully featured create flow is:

```json
{
  "client_action_id": "uuid-v4",
  "name": "Climate research",
  "description": "optional",
  "default_quality": "fast",
  "selection_mode": "all",
  "source_types": ["youtube", "github"],
  "workspace_zettel_ids": ["<uuid>", "<uuid>"],
  "links": ["https://optional-new-link.example"],
  "icon": "stack",
  "color": "#14b8a6"
}
```

The rules should be strict and explicit. `selection_mode` should be one of `all | source | specific | links | mixed`. For `all`, `source_types` and `workspace_zettel_ids` must be empty. For `source`, `source_types` must be non-empty and must map to the backend enum. For `specific`, the client must pass **`workspace_zettel_id` values only**, never canonical IDs and never client-generated `node_id` strings. That matters because the create-kasten design note explicitly calls out a dedup caveat: a summarization result may surface a canonical ID rather than the final workspace-zettel row, and the join table is keyed on `content.workspace_zettels.id`. The server must resolve or validate workspace membership server-side before bulk add. fileciteturn43file0L3-L3

For multi-user correctness, the client should **not** send `user_id`, `profile_id`, or `workspace_id` in this API body. Those must come from the authenticated JWT and the server’s v2 scope resolution. That is not just stylistic; the repo already has live BOLA coverage for kasten ownership and visibility, and OWASP’s API1:2023 guidance is very clear that every endpoint receiving an object ID must do object-level authorization for the logged-in user, because simply comparing a user ID to a request parameter is not sufficient. The tests in this repo already check owner/member/non-member behavior and UUID non-leakage in error paths, so the new API should continue deriving tenancy server-side instead of trusting the body. fileciteturn51file0L3-L3 citeturn11view0turn11view1turn11view3

The response contract should stay close to the current runner pattern:

```json
{
  "status": "accepted",
  "operation_id": "uuid-v4",
  "status_url": "/api/rag/sandboxes/operations/{operation_id}"
}
```

and the terminal payload should look like:

```json
{
  "status": "succeeded",
  "operation_id": "uuid-v4",
  "kasten": { ... },
  "selection": {
    "selection_mode": "source",
    "resolved_member_count": 124,
    "source_types": ["github", "web"]
  },
  "ingested": [ ... ],
  "failed": [ ... ],
  "error": null
}
```

This is the right place to use the summarization-style long-running pattern because the work can include member discovery, optional link ingestion, dedup resolution, bulk inserts, and graph invalidation. Microsoft’s pattern recommends `202 Accepted`, `Location`, `Retry-After`, a status document with `status`, `createdAt`, `lastUpdatedAt`, and a structured `error`, plus optional cancellation via DELETE. That maps cleanly to this module. If backward compatibility with the old modal is mandatory, preserve the current repo behavior for “legacy create-only” and use `202` for any request that actually resolves or adds members. fileciteturn46file0L3-L3 citeturn10view0turn10view1turn10view3turn9view0turn9view2turn9view3

From an infra-overhead perspective, this is a good fit for the current droplet model because the repo is already using in-process patterns rather than extra infrastructure: the summarization runner uses a semaphore, the create-kasten route tests clear in-memory operation stores, and the graph layer uses an in-process per-user cache with single-flight. On one droplet, that is pragmatic and low-overhead. The tradeoff is that operation status is process-local, so if you later move to multiple replicas or aggressive restarts, the pollable operation store should move out of RAM and into a shared durable store. fileciteturn48file0L3-L3 fileciteturn46file0L3-L3 fileciteturn59file0L3-L3

## Ask kasten API recommendation

The current chat surface is already mature enough that it should drive the `ask_kasten` runner design. The repo’s chat routes define three core contracts: create a session with optional `sandbox_id`, send a message to `/api/rag/sessions/{session_id}/messages`, or use `/api/rag/adhoc` for one-shot questions. The request body already includes `content`, `quality`, `scope_filter`, `stream`, and `client_action_id`. The `ScopeFilter` model already supports `node_ids`, `tags`, `tag_mode`, and `source_types`, with empty lists normalized to “no filter.” fileciteturn37file0L3-L3 fileciteturn60file0L3-L3

The route and smoke tests also show the right streaming contract to preserve. Streaming answers are SSE-based, and the tests verify that the response includes `event: status`, token events, and a final `done` event. The chat route code adds queue admission, queue-full handling, a first-byte “queued” event, automatic retry around cold-start stream failures, heartbeats, and a terminal `error` event instead of a mid-stream connection drop. That is the right operational posture for a live chat UX. fileciteturn36file0L3-L3 fileciteturn37file0L3-L3

Because of that, I strongly **do not** recommend forcing `ask_kasten` into the same external `202 + polling` shape as summarization. Microsoft’s async-request guidance explicitly says polling is useful when callback endpoints are unavailable or long-held connections add too much complexity, but it separately calls out SSE when the client needs results streamed in real time. MDN’s SSE guidance fits the current implementation well: it is a one-way HTTP-native channel using `EventSource`, supports default `message` events and named custom events through the `event` field, and supports comment-style keep-alives when traffic is sparse. That maps directly to the existing `status`, `citations`, `token`, `done`, and `error` event model. citeturn3view0turn13view0turn13view1turn13view2turn13view3

So the correct “similar structure” for this module is **an internal runner, not a cloned wire contract**. I would create `website/api/module_runners/ask_kasten.py` with two public entrypoints:

```python
async def run_ask_kasten_once(
    *,
    session_id: UUID | None,
    sandbox_id: UUID | None,
    content: str,
    quality: Literal["fast", "high"],
    scope_filter: ScopeFilter,
    client_action_id: str | None,
    user: dict,
    effective_user_id: UUID,
) -> AskKastenOutput: ...

async def stream_ask_kasten(
    *,
    session_id: UUID | None,
    sandbox_id: UUID | None,
    content: str,
    quality: Literal["fast", "high"],
    scope_filter: ScopeFilter,
    client_action_id: str | None,
    user: dict,
    effective_user_id: UUID,
) -> AsyncIterator[AskKastenEvent]: ...
```

The runner should absorb the shared logic that is currently route-resident: session lookup, ownership checks, entitlement enforcement, queue admission, calling the orchestrator, background side effects, and typed response serialization. The route should keep deciding whether it wraps the runner in `StreamingResponse` or returns a single JSON object. That keeps the website endpoint behavior stable while still giving you the same “module_runners” maintainability benefits as summarization. fileciteturn37file0L3-L3

For multi-user safety, keep the same server-side derivation rule as above. Do not accept `workspace_id` from the client, and do not trust any foreign `session_id` or `sandbox_id`. The repo already contains live BOLA tests covering exactly these chat paths: user B cannot post to user A’s session, cannot create a session against A’s kasten, and cannot use A’s `sandbox_id` via the adhoc route without leakage. Those tests are the proof that the authorization boundary must stay inside the server’s runtime lookup rather than in the request body. fileciteturn52file0L3-L3

One additional recommendation: require `client_action_id` for non-stream POSTs and log it for stream POSTs. This keeps parity with summarization and makes idempotent retries, tracing, and incident analysis much cleaner. Google’s request-identification guidance specifically frames request IDs as useful for de-duplication, safe retries, and auditing, and Microsoft recommends idempotency keys for exactly the “lost response vs never received” ambiguity that long-running or unstable network flows create. citeturn14view0turn10view2

## View graph API recommendation

The `view_graph` case is different from both summarization and chat. The current system already exposes a synchronous read endpoint, `GET /api/graph`, with optional `view`, `limit`, `offset`, and `min_strength` query parameters. The knowledge-graph frontend calls that route directly, passing `view=my` when the Personal mode is active and `min_strength` as the slider changes. The route assembles a per-user v2 graph when possible, enriches analytics, filters by strength, trims the payload, and otherwise falls back to the file-store graph for the global view. fileciteturn40file0L3-L3 fileciteturn41file0L3-L3

The repo also already contains the infrastructure that makes this path safe to keep synchronous. `website/api/graph_cache.py` implements a per-user in-process LRU with a 30-second TTL, stale-while-revalidate behavior, single-flight coalescing, and a 20-second upstream timeout. The route invalidates the user graph cache on summarize and zettel mutation. This is exactly the kind of read-heavy optimization you want on a droplet because it avoids adding Redis or extra coordination infrastructure while still protecting the expensive path from same-user stampedes. fileciteturn59file0L3-L3 fileciteturn40file0L3-L3

That means `view_graph.py` should be created as an **internal module runner** only:

```python
async def run_view_graph(
    *,
    user: dict | None,
    view: Literal["global", "my"] | None,
    limit: int = 5000,
    offset: int = 0,
    min_strength: float | None = None,
) -> dict[str, Any]: ...
```

The route should remain a normal `GET` returning `200 OK`, because there is no clear UX benefit to turning a cached read into a long-running pollable job. This also matches standard cache guidance better than a job abstraction would. `stale-while-revalidate` is a well-established pattern precisely for “immediacy plus eventual freshness” on resources that can tolerate short staleness windows, and the repo is already implementing the same idea in-process. fileciteturn59file0L3-L3 citeturn5view3turn5view4

There are two important improvements I would make while introducing the runner. The first is **explicit Personal-view semantics**. Today, the route can fall through to the anonymous/global graph if the v2 personal graph cannot be assembled. If the caller explicitly asks for `view=my`, that is too implicit. I would make the new runner return either `401/403`, or an explicit empty personal graph, when the request is authenticated but there is no valid personal graph scope. That removes ambiguity and reduces the chance of a UI bug accidentally showing the global dataset when the user explicitly asked for their own. That recommendation is an inference from the current route logic and frontend usage pattern. fileciteturn40file0L3-L3 fileciteturn41file0L3-L3

The second is **bucket alignment**. The frontend’s strength buckets use `strong >= 0.7`, `medium >= 0.5`, and `weak >= 0.3`, while the server cache bucketizer uses `strong >= 0.7`, `medium >= 0.4`, else `weak`. The server still applies the exact threshold post-load, so this is not a correctness break, but it does create a semantic mismatch between client labels and cache buckets. I would standardize both ends on the same cutoffs before freezing the module runner. fileciteturn41file0L3-L3 fileciteturn59file0L3-L3

## Concrete Postman test design

The repo already has a summarization Postman README, coverage map, collection, and smoke dataset under `tests/postman`, so the clean extension is to add three sibling collections there:

- `tests/postman/collections/zettelkasten-create-kasten.postman_collection.json`
- `tests/postman/collections/zettelkasten-ask-kasten.postman_collection.json`
- `tests/postman/collections/zettelkasten-view-graph.postman_collection.json`

and matching data files plus a coverage-map update. That keeps these tests discoverable in the same place as the existing summarization suite. fileciteturn49file31L1-L3 fileciteturn49file32L1-L3 fileciteturn49file33L1-L3 fileciteturn49file35L1-L3

At the collection level, use Postman’s normal post-response test model with `pm.test`, `pm.response`, and `pm.expect`, because that is the supported way to validate response status, body shape, and environment state. For automation, use Newman or Postman CLI in CI; Postman’s docs explicitly position Newman as a command-line runner for collections, with CI integration, reporters, Docker support, and file upload support. citeturn5view0turn5view1turn12view0turn12view1turn12view2turn12view3

A useful collection-level helper is:

```javascript
function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

if (!pm.environment.get("client_action_id")) {
  pm.environment.set("client_action_id", uuidv4());
}

function assertNoLeak(text, forbiddenValues) {
  forbiddenValues.filter(Boolean).forEach(v => {
    pm.expect(text.includes(String(v)), `response leaked ${v}`).to.equal(false);
  });
}
```

### Create kasten Postman coverage

The `create_kasten` collection should cover six concrete use cases.

The first is **legacy create-only compatibility**. `POST /api/rag/sandboxes` with `name`, `description`, and `default_quality`, but no members and no links, should return `200` with the legacy `sandbox` envelope if you preserve backward compatibility, exactly as the repo’s unit tests require. fileciteturn46file0L3-L3

The second is **async member-building**. Submit a request using one of the new selection modes and assert `202`, `operation_id`, and `status_url`. Then poll `GET {{status_url}}` until `status` becomes `succeeded`, and assert that `kasten.id` exists, `selection.resolved_member_count` is present, and `failed.length === 0` for the happy path. This mirrors the current create-with-links integration tests. Use `Retry-After` if the endpoint returns it, per the async-request standard. fileciteturn45file0L3-L3 citeturn10view0turn10view1

The third is **idempotent replay**. Re-send the exact same request with the same `client_action_id`. Assert that the returned operation resolves to the same `kasten.id` and that no duplicate membership rows are visible through `GET /api/rag/sandboxes/{id}/members`. This is non-negotiable in a multi-user system because browser retries and dropped mobile connections will happen. fileciteturn45file0L3-L3 citeturn6view0turn6view1turn14view0

The fourth is **validation correctness**. Send `selection_mode="source"` with an empty `source_types`, `selection_mode="specific"` with an empty `workspace_zettel_ids`, or an unsupported source type. Assert `422` with an RFC 9457-style body containing `type`, `title`, `status`, and a corrective `detail`. If you support multiple field errors at once, use an `errors` extension array, which RFC 9457 explicitly accommodates. fileciteturn47file0L3-L3 citeturn9view0turn9view1turn9view2turn9view3

The fifth is **tenant isolation**. Use token A to create a kasten, then token B to poll A’s operation or read A’s members. Assert `404` or `403` and run the UUID-leak guard against A’s user IDs, workspace IDs, and kasten ID. The repo already treats this as a core acceptance criterion. fileciteturn45file0L3-L3 fileciteturn51file0L3-L3

The sixth is **graph visibility after mutation**. After a successful create flow, call `GET /api/graph?view=my` and verify the selected or ingested zettels are now visible to the same user, proving cache invalidation is still wired correctly. fileciteturn45file0L3-L3 fileciteturn40file0L3-L3

### Ask kasten Postman coverage

The `ask_kasten` collection should test both the non-stream and stream paths.

Start with **session creation**. `POST /api/rag/sessions` using a valid `sandbox_id`, `title`, `quality`, and `scope_filter`, and assert a `session.id` is returned. Also test bad `quality` values and ensure you get validation rejection rather than a silent fallback. fileciteturn37file0L3-L3

Then test **non-stream answers**. `POST /api/rag/sessions/{{session_id}}/messages` with `stream:false` should return `200` and a `turn` object with `content`, `citations`, `query_class`, and `critic_verdict`. The smoke tests in the repo verify this exact shape exists. fileciteturn35file0L3-L3 fileciteturn36file0L3-L3

Then test **SSE answers**. `POST /api/rag/sessions/{{session_id}}/messages` with `stream:true` should return `200` and a body containing `event: status`, at least one token-bearing event, and a terminal `done` event. Because Postman is not an actual `EventSource` runtime, assert against the buffered text body rather than trying to emulate browser SSE behavior. This is consistent with the repo’s own route smoke test and with MDN’s named-event SSE model. fileciteturn36file0L3-L3 citeturn13view0turn13view2

Then test **scope filtering**. Use the same question content but vary `scope_filter.node_ids`, `scope_filter.tags`, and `scope_filter.source_types`. Assert that the request is accepted and that the endpoint does not reject empty arrays incorrectly, since the backend intentionally normalizes empty lists to `None`. This is important for UI checkboxes that may serialize empty arrays. fileciteturn60file0L3-L3

Finally, test **BOLA on chat**. Token B should not be able to post into token A’s `session_id`, create a session against token A’s `sandbox_id`, or use token A’s `sandbox_id` in `/api/rag/adhoc`. Assert `402|403|404` per the repo’s existing acceptance range, and assert the error body does not leak A’s identifiers. fileciteturn52file0L3-L3

### View graph Postman coverage

The `view_graph` collection should stay mostly read-only and fast.

Start with **global graph**. Call `GET /api/graph` without auth and assert the response has `nodes` and `links` arrays. Then call `GET /api/graph?view=my` with auth and assert the result is still `200`, but scoped to the caller’s personal graph if the account has valid v2 scope. fileciteturn40file0L3-L3

Then test **strength filtering**. Call the endpoint twice with the same authentication but different `min_strength` values, for example `0.3` and `0.7`, and assert that the stronger threshold does not return *more* links than the weaker threshold. This is a direct functional check for the strength filter. fileciteturn40file0L3-L3 fileciteturn41file0L3-L3

Then test **pagination controls**. Call with `limit=10&offset=0`, then `limit=10&offset=10`, and assert the responses stay `200` and remain structurally valid. If you keep the current clamping behavior instead of returning `422` for bad limits, add tests that confirm negative `limit`/`offset` are sanitized rather than crashing the handler. fileciteturn40file0L3-L3

Then test **explicit Personal-view behavior**. If you adopt my recommendation and make `view=my` strict, add a no-auth test that must now return `401/403` or an explicit empty personal graph rather than silently falling back to the global graph. This is the single biggest semantic tightening I would make before calling `view_graph` “production-stable” as a standalone module API. fileciteturn40file0L3-L3

Finally, test **cache invalidation by mutation** as a chained flow. Add a zettel through summarization or create a kasten membership, then request `/api/graph?view=my` and assert the change is visible without requiring a cache-expiry wait. That proves the graph invalidation hook still works after each mutating module. fileciteturn40file0L3-L3 fileciteturn45file0L3-L3

## Implementation guidance that best fits this codebase

The cleanest code organization is:

- keep `website/api/module_runners/summarization.py` as the reference implementation,
- keep and extend `website/api/module_runners/create_kasten.py`,
- add `website/api/module_runners/ask_kasten.py`,
- add `website/api/module_runners/view_graph.py`.

All four should expose one importable public function per route-facing job, use typed input/output models, do heavy imports lazily, derive tenancy from the authenticated user rather than the payload, and return either a terminal model or a standardized accepted-state envelope. For long-running jobs, use `client_action_id`/`request_id` and the existing in-memory operation pattern on the droplet; for read-heavy jobs, prefer cache + invalidation over a job abstraction; for real-time chat, keep SSE and centralize the shared logic in the runner rather than changing the route’s transport. That approach is closest to the repo’s existing conventions and to current API design guidance from Microsoft, Google, Stripe, OWASP, RFC 9457, and Postman. fileciteturn48file0L3-L3 fileciteturn45file0L3-L3 fileciteturn46file0L3-L3 fileciteturn59file0L3-L3 citeturn10view0turn10view2turn14view0turn6view0turn11view1turn9view0turn5view0turn12view0

## Open questions and limitations

I could not execute live Postman or Newman runs against a deployed base URL from this environment, so the Postman section above is a repo-grounded test specification rather than a record of executed collection results.

A few repository details were visible only indirectly through design notes and tests rather than all route files line-by-line. The core conclusions are still high-confidence because they are triangulated from the runner code, live integration tests, unit tests, and frontend contracts, but if you want a follow-up implementation pass, the first thing I would verify in code before editing is the exact current operation-store implementation in the summarization and sandbox routes so the new runners match that behavior byte-for-byte.