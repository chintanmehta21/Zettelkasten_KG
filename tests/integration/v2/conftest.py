"""Shared fixtures for v2 integration tests.

Tests in this directory MUST be marked @pytest.mark.live (they hit the live
Supabase project). The asyncpg_pool fixture connects to the direct port-5432
Postgres URL (NOT pgbouncer). The mint_user fixture creates fresh test users
and cleans them up at teardown.
"""
from __future__ import annotations

import os
import re
import uuid
import warnings
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlsplit

import asyncpg
import pytest
import pytest_asyncio

from tests.v2.fixtures import MintedKasten, MintedUser, mint_test_user_with_workspaces
from tests.v2.fixtures.users import delete_test_user
from tests.v2.fixtures.wave_c import (
    GraphJsonValidator,
    SourceFixturePathResolver,
    StubGeminiPool,
    build_random_digraph,
)
from website.core.supabase_v2.client import get_v2_database_url

# Phase 7.3b: end-of-session backstop. Per-test fixtures clean up via
# created_auth_user_ids, but a hard crash (KeyboardInterrupt, segfault, OOM
# on the worker) skips teardown and leaks e2e users. The mint pattern is
# e2e-{uuid.uuid4().hex[:8]}@test.com; allow 6-12 hex chars for forward-
# compat if the prefix length ever changes.
_E2E_EMAIL_PATTERN = re.compile(r"^e2e-[0-9a-f]{6,12}@test\.com$")


@pytest_asyncio.fixture
async def asyncpg_pool() -> AsyncIterator[asyncpg.Pool]:
    """Direct port-5432 asyncpg pool for v2 integration tests.

    Function-scoped so the pool is bound to the same event loop as the test
    that uses it (pytest-asyncio runs each async test in its own loop in
    ``asyncio_mode = auto``; a session-scoped pool would raise
    ``got Future <…> attached to a different loop`` on the second test).
    Per-test pool create+close cost is ~50 ms — acceptable for the integration
    suite size.

    Refuses to start if the URL points at pgbouncer (port 6543) — see
    plan amendment about LISTEN port enforcement. Strict port parse (not a
    substring check) so credentials/host components containing "6543" cannot
    spoof the guard.
    """
    url = get_v2_database_url(listen=False)
    parsed = urlsplit(url)
    if parsed.port == 6543:
        raise ValueError(
            "asyncpg_pool requires direct port 5432 (not pgbouncer 6543)."
        )
    pool = await asyncpg.create_pool(url, min_size=1, max_size=4)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
def created_auth_user_ids() -> list[uuid.UUID]:
    """Per-test list of ``auth.users.id`` UUIDs the test minted; cleaned up at teardown.

    Cleanup is best-effort (does not abort on the first failure) but every
    failure is collected and surfaced via ``warnings.warn`` so a pool exhaustion
    or auth outage cannot silently leak users without test output.

    Phase 8.5.R2 amendment (T1): we run ``account_purge.purge_user_dependencies``
    BEFORE ``auth.admin.delete_user`` to pre-clean FK-bound rows the GoTrue
    admin API doesn't cascade through (rag.retrieval_feedback_events,
    billing.pricing_subscriptions, rag.kasten_members). Without this, content-
    seeding tests left ``AuthApiError('Database error deleting user')``
    warnings that the session-finish backstop swept up — the per-test purge
    eliminates the noise so real test failures aren't drowned in teardown
    noise. Canonical pattern per Supabase Discussion #28776 + storage#65:
    auth.admin.delete_user has no cascade flag in 2024-2026.
    """
    created: list[uuid.UUID] = []
    yield created
    errors: list[tuple[uuid.UUID, BaseException]] = []
    # Lazy import — account_purge pulls supabase client init; only needed at
    # teardown so we defer the cost until the fixture is actually used.
    from website.core.account_purge import purge_user_dependencies
    for auth_user_id in created:
        try:
            # Pre-purge FK-bound rows the admin API doesn't cascade through.
            # profile_id == auth_user_id today (handle_new_auth_user trigger
            # invariant); if the invariant ever breaks, the purge becomes a
            # no-op and admin.delete_user falls back to its prior behaviour —
            # the session-finish backstop sweep then handles the residue.
            try:
                purge_user_dependencies(auth_user_id)
            except Exception as purge_exc:  # noqa: BLE001 — best-effort
                warnings.warn(
                    f"purge_user_dependencies({auth_user_id}) failed: {purge_exc!r}",
                    stacklevel=1,
                )
            delete_test_user(auth_user_id)
        except Exception as exc:  # noqa: BLE001 — collect and report at end
            errors.append((auth_user_id, exc))
    if errors:
        msg = "; ".join(f"{aid}: {exc!r}" for aid, exc in errors)
        warnings.warn(
            f"Test-user cleanup failed for {len(errors)} user(s): {msg}",
            stacklevel=1,
        )


@pytest.fixture
def mint_user(created_auth_user_ids: list[uuid.UUID]):
    """Factory: returns a callable that mints a user AND records it for cleanup.

    Usage:
        def test_x(mint_user):
            user = mint_user(workspace_count=2)
            # user.auth_user_id, user.profile_id, user.workspace_ids, user.jwt
    """
    def _mint(*, workspace_count: int = 1) -> MintedUser:
        user = mint_test_user_with_workspaces(workspace_count=workspace_count)
        # Record auth_user_id (NOT profile_id) — delete_test_user requires the
        # auth.users.id, and the FK invariant making them equal today is not
        # something cleanup should depend on.
        created_auth_user_ids.append(user.auth_user_id)
        return user
    return _mint


@pytest_asyncio.fixture
async def created_sandbox_ids(asyncpg_pool: asyncpg.Pool) -> list[uuid.UUID]:
    """Per-test list of ``rag.kastens.id`` UUIDs minted by ``mint_kasten``;
    cleaned up at teardown by direct DELETE through the service-role pool.

    Parallels ``created_auth_user_ids`` rather than piggy-backing on the user
    cleanup chain — ``rag.kastens`` CASCADEs from the owning workspace, so the
    user-teardown path already covers most cases, but an explicit per-row sweep
    means tests that share kastens across users (sharing, cross-tenant) cannot
    leak a row if the owner-cleanup ordering is unfavourable. Best-effort
    deletion; failures emit ``warnings.warn`` and never abort teardown.
    """
    created: list[uuid.UUID] = []
    yield created
    if not created:
        return
    errors: list[tuple[uuid.UUID, BaseException]] = []
    async with asyncpg_pool.acquire() as conn:
        for kasten_id in created:
            try:
                await conn.execute(
                    "DELETE FROM rag.kastens WHERE id = $1", kasten_id
                )
            except Exception as exc:  # noqa: BLE001 — best-effort
                errors.append((kasten_id, exc))
    if errors:
        msg = "; ".join(f"{kid}: {exc!r}" for kid, exc in errors)
        warnings.warn(
            f"Kasten cleanup failed for {len(errors)} row(s): {msg}",
            stacklevel=1,
        )


@pytest.fixture
def mint_kasten(
    asyncpg_pool: asyncpg.Pool,
    created_sandbox_ids: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
):
    """Factory: mints a Kasten via the real ``POST /api/rag/sandboxes`` route.

    Uses ``fastapi.testclient.TestClient`` against a v2-forced FastAPI app
    built per-call. ``require_entitlement`` / ``consume_entitlement`` are
    monkey-patched to no-ops at the route-module level — the pricing-module-
    authority rule forbids seeding entitlements directly, and this bypass
    mirrors the established pattern in ``test_sandbox_routes_v2.py``.

    Usage::

        def test_x(mint_user, mint_kasten):
            user = mint_user(workspace_count=1)
            k = mint_kasten(owner_user=user)
            # k.sandbox_id, k.name, k.owner_user_sub
    """
    from fastapi.testclient import TestClient

    # Force v2 schema before building the app — the route module reads this at
    # request time, but the underlying repository singletons are cached on
    # ``website.core.persist`` and need a reset so a fresh JWT scope is built.
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.api import auth as auth_mod
    auth_mod._jwks_client = None
    from website.core import persist as persist_mod
    persist_mod._v2_core_repo = None
    persist_mod._v2_content_repo = None

    async def _noop(*_args, **_kwargs):  # noqa: D401 — entitlement bypass
        return None

    # 2026-08-01: ``consume_entitlement`` no longer exists on this module —
    # Phase 9 folded consumption into ``require_entitlement`` (see the comment
    # at sandbox_routes.py:770, "gate consumed atomically in
    # require_entitlement above"). monkeypatch.setattr on a missing attribute
    # raises AttributeError, which is what produced the 35 collection ERRORs in
    # the live suite. Patch only the symbol the module actually imports, and
    # assert it is there so a future rename fails loudly instead of silently
    # un-bypassing the gate.
    from website.api import sandbox_routes as sandbox_routes_mod
    assert hasattr(sandbox_routes_mod, "require_entitlement"), (
        "sandbox_routes.require_entitlement missing — the entitlement bypass "
        "below is stale; re-point it at whatever now owns consumption."
    )
    monkeypatch.setattr(sandbox_routes_mod, "require_entitlement", _noop)

    from website.app import create_app

    app = create_app()

    def _factory(*, owner_user: MintedUser, name: str | None = None) -> MintedKasten:
        kasten_name = name or f"k-{uuid.uuid4().hex[:8]}"
        with TestClient(app) as client:
            resp = client.post(
                "/api/rag/sandboxes",
                json={"name": kasten_name, "default_quality": "fast"},
                headers={"Authorization": f"Bearer {owner_user.jwt}"},
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"mint_kasten POST /api/rag/sandboxes failed: "
                f"status={resp.status_code} body={resp.text[:400]}"
            )
        sandbox_id = uuid.UUID(resp.json()["sandbox"]["id"])
        created_sandbox_ids.append(sandbox_id)
        return MintedKasten(
            sandbox_id=sandbox_id,
            name=kasten_name,
            owner_user_sub=owner_user.auth_user_id,
        )

    return _factory


@pytest.fixture
def bulk_insert_zettels(asyncpg_pool: asyncpg.Pool):
    """Factory: bulk-inserts N (canonical_zettel, workspace_zettel) row pairs
    for a given user's personal workspace; returns the list of
    ``content.workspace_zettels.id`` UUIDs in insertion order.

    Uses direct asyncpg INSERT into ``content.canonical_zettels`` and
    ``content.workspace_zettels`` — same path that
    ``tests/integration/v2/test_sandbox_routes_v2._seed_workspace_zettel`` uses.
    We do NOT route through ``website.core.persist.persist_summarized_result``
    here because:

      * That helper expects a fully-summarised pipeline payload and runs the
        RAG-chunk scheduling tail; that is irrelevant overhead for bulk-fixture
        seeding and would force every consumer to construct a fake summariser
        result.
      * Workspace-scoped INSERTs are CASCADE-cleaned when the workspace is
        dropped during ``mint_user`` teardown, so no explicit per-row registry
        is required.

    Bulk size is bounded only by Postgres parameter limits in practice; the
    fixture batches into 200-row INSERTs to stay well under the 65535 ($N)
    parameter ceiling for either table.
    """
    async def _factory(
        *,
        owner_user: MintedUser,
        n: int = 500,
        prefix: str = "bulk",
    ) -> list[uuid.UUID]:
        if n < 1:
            raise ValueError("n must be >= 1")
        workspace_id = owner_user.workspace_ids[0]
        wz_ids: list[uuid.UUID] = []
        suffix_seed = uuid.uuid4().hex[:10]

        async with asyncpg_pool.acquire() as conn:
            async with conn.transaction():
                for batch_start in range(0, n, 200):
                    batch_end = min(batch_start + 200, n)
                    cz_rows = []
                    wz_rows = []
                    for i in range(batch_start, batch_end):
                        cz_id = uuid.uuid4()
                        wz_id = uuid.uuid4()
                        norm_url = (
                            f"https://{prefix}-{suffix_seed}-{i}.example.com/"
                        )
                        # 32-byte content_hash matches the canonical schema.
                        chash = uuid.uuid4().bytes + uuid.uuid4().bytes
                        cz_rows.append(
                            (
                                cz_id,
                                norm_url,
                                chash,
                                "web",
                                f"{prefix} zettel {i}",
                                f"{prefix} body {i}",
                            )
                        )
                        wz_rows.append(
                            (
                                wz_id,
                                workspace_id,
                                cz_id,
                                (
                                    '{"brief_summary": "bulk", '
                                    '"detailed_summary": "bulk detail"}'
                                ),
                                [prefix],
                            )
                        )
                        wz_ids.append(wz_id)
                    await conn.executemany(
                        """
                        INSERT INTO content.canonical_zettels
                            (id, normalized_url, content_hash, source_type,
                             title, body_md, publication_date)
                        VALUES ($1, $2, $3, $4, $5, $6, '2026-04-01'::date)
                        """,
                        cz_rows,
                    )
                    await conn.executemany(
                        """
                        INSERT INTO content.workspace_zettels
                            (id, workspace_id, canonical_zettel_id,
                             ai_summary, user_tags, user_note, pinned,
                             added_via)
                        VALUES ($1, $2, $3, $4, $5, NULL, false, 'website')
                        """,
                        wz_rows,
                    )
        return wz_ids

    return _factory


# ---------------------------------------------------------------------------
# WAVE-C Phase 1a fixtures (additive; safe alongside WAVE-A/B fixtures above)
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_zettels(asyncpg_pool):
    """Seed N workspace_zettels for the given workspace, spaced 1 day apart back from now.

    Used by Task 3.1+ profile_stats RPC tests. Inserts canonical_zettels (one per
    workspace_zettel; no dedup across calls because each gets a fresh uuid in the
    normalized_url to bypass the UNIQUE(normalized_url, content_hash) gate) and
    then their workspace_zettels overlay rows. CASCADE-cleaned via mint_user
    teardown (workspace drop).

    content_hash is bytea per schema 02 — synthesised via decode(md5(...), 'hex')
    so each seed run is collision-free and the column type matches.
    """
    async def _seed(workspace_id, count: int = 5):
        async with asyncpg_pool.acquire() as conn:
            for i in range(count):
                cz_id = await conn.fetchval(
                    """
                    INSERT INTO content.canonical_zettels
                        (id, normalized_url, content_hash, source_type, title, created_at)
                    VALUES
                        (gen_random_uuid(),
                         'https://example.com/seed-' || gen_random_uuid()::text,
                         decode(md5(random()::text), 'hex'),
                         'web',
                         'seed-' || $1::text,
                         now() - ($1 || ' days')::interval)
                    RETURNING id
                    """,
                    # str(i): ``$1::text`` and ``$1 || ' days'`` both force a TEXT
                    # parameter, so asyncpg rejects an int. Same defect as seed_kg_graph.
                    str(i),
                )
                await conn.execute(
                    """
                    INSERT INTO content.workspace_zettels
                        (workspace_id, canonical_zettel_id, ai_summary, user_tags, added_via, created_at)
                    VALUES
                        ($1, $2, 'summary ' || $3::text,
                         ARRAY['tag-' || $3::text]::text[],
                         'website',
                         now() - ($3 || ' days')::interval)
                    """,
                    workspace_id, cz_id, str(i),
                )
    return _seed


@pytest.fixture
def seed_kastens(asyncpg_pool):
    """Seed N rag.kastens for the given workspace, spaced 1 day apart back from now.

    Used by Task 3.1+ profile_stats RPC tests. CASCADE-cleaned via mint_user
    teardown (workspace drop). UNIQUE(workspace_id, name) is satisfied by the
    sequential 'kasten-N' naming within a single workspace.
    """
    async def _seed(workspace_id, count: int = 3):
        async with asyncpg_pool.acquire() as conn:
            for i in range(count):
                await conn.execute(
                    """
                    INSERT INTO rag.kastens
                        (id, workspace_id, name, created_at)
                    VALUES
                        (gen_random_uuid(), $1, 'kasten-' || $2::text,
                         now() - ($2 || ' days')::interval)
                    """,
                    workspace_id, str(i),  # TEXT-inferred param; see seed_zettels
                )
    return _seed


@pytest.fixture
def seed_chat_messages(asyncpg_pool):
    """Seed chat session + messages for a workspace.

    Creates one chat_session under the workspace, then N user messages and
    M assistant messages with citations pointing at the first available
    workspace_zettel (so most_cited_source_type has something to find).
    """
    async def _seed(workspace_id, user_messages: int = 3, assistant_with_citations: int = 0):
        async with asyncpg_pool.acquire() as conn:
            session_id = await conn.fetchval(
                """
                INSERT INTO rag.chat_sessions (id, workspace_id, profile_id, created_at)
                VALUES (
                  gen_random_uuid(),
                  $1,
                  (SELECT owner_profile_id FROM core.workspaces WHERE id = $1),
                  now()
                )
                RETURNING id
                """,
                workspace_id,
            )
            for i in range(user_messages):
                await conn.execute(
                    """
                    INSERT INTO rag.chat_messages
                        (id, session_id, workspace_id, role, content, created_at)
                    VALUES (gen_random_uuid(), $1, $2, 'user', 'q' || $3::text,
                            now() - ($3 || ' hours')::interval)
                    """,
                    session_id, workspace_id, str(i),  # TEXT-inferred param
                )
            # Lookup a canonical_zettel_id for citation payloads.
            cz_id = await conn.fetchval(
                """
                SELECT cz.id
                  FROM content.workspace_zettels wz
                  JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id
                 WHERE wz.workspace_id = $1 AND wz.deleted_at IS NULL
                 LIMIT 1
                """,
                workspace_id,
            )
            for i in range(assistant_with_citations):
                await conn.execute(
                    """
                    INSERT INTO rag.chat_messages
                        (id, session_id, workspace_id, role, content,
                         citations, verdict, created_at)
                    VALUES (gen_random_uuid(), $1, $2, 'assistant', 'a' || $3::text,
                            CASE WHEN $4::uuid IS NULL THEN '[]'::jsonb
                                 ELSE jsonb_build_array(jsonb_build_object('canonical_zettel_id', $4::text))
                            END,
                            'supported', now())
                    """,
                    session_id, workspace_id, str(i), cz_id,  # $3 is TEXT-inferred
                )
    return _seed


@pytest.fixture
def seed_zettels_with_tags(asyncpg_pool):
    """Seed workspace_zettels with explicit tag distributions.

    Args:
        workspace_id: target workspace
        tag_distribution: dict[str, int] mapping tag name to occurrence count.

    Spreads zettels back from now() by 1 day per record so older tags
    are present in lifetime but not in recent (30d) — exercises the
    emerging/declining logic.
    """
    async def _seed(workspace_id, tag_distribution: dict):
        async with asyncpg_pool.acquire() as conn:
            offset = 0
            for tag, n in tag_distribution.items():
                for i in range(n):
                    cz_id = await conn.fetchval(
                        """
                        INSERT INTO content.canonical_zettels
                            (id, normalized_url, content_hash, source_type, title)
                        VALUES (
                          gen_random_uuid(),
                          'https://example.com/' || gen_random_uuid()::text,
                          decode(md5(random()::text), 'hex'),
                          'web',
                          $1::text
                        )
                        RETURNING id
                        """,
                        f"{tag}-{i}",
                    )
                    await conn.execute(
                        """
                        INSERT INTO content.workspace_zettels
                            (workspace_id, canonical_zettel_id, ai_summary,
                             user_tags, added_via, created_at)
                        VALUES ($1, $2, '', ARRAY[$3]::text[], 'website',
                                now() - ($4 || ' days')::interval)
                        """,
                        workspace_id, cz_id, tag, str(offset),  # $4 is TEXT-inferred
                    )
                    offset += 1
    return _seed


@pytest.fixture
def seed_kg_graph(asyncpg_pool):
    """Seed kg_nodes + kg_edges for a workspace.

    Used by Task 3.7 (graph section) tests. Creates N nodes ('n0'..'n{N-1}')
    and a chain of edges (n0-n1, n1-n2, ...) with relation_type='shared_tag'.
    CASCADE-cleaned via mint_user teardown (workspace drop).

    2026-08-01: the note that once lived here — "kg.kg_edges has no
    workspace_strength column" — is no longer true; the live table has
    connection_strength / workspace_strength / global_strength. Verified
    against production. We simply don't set them, which is fine (nullable).
    """
    async def _seed(workspace_id, nodes: int = 10, edges: int = 15):
        async with asyncpg_pool.acquire() as conn:
            node_ids = []
            for i in range(nodes):
                nid = await conn.fetchval(
                    """
                    INSERT INTO kg.kg_nodes
                        (workspace_id, type, canonical_name, slug)
                    VALUES ($1, 'zettel', 'n' || $2::text, 'n' || $2::text)
                    RETURNING id
                    """,
                    # str(i), not i: the ``$2::text`` cast makes asyncpg infer a
                    # TEXT parameter, so passing an int raised
                    # "TypeError: expected str, got int" — 9 live-test failures
                    # from this single line.
                    workspace_id, str(i),
                )
                node_ids.append(nid)
            for i in range(min(edges, len(node_ids) - 1)):
                await conn.execute(
                    """
                    INSERT INTO kg.kg_edges
                        (workspace_id, src_node_id, dst_node_id,
                         relation_type, weight)
                    VALUES ($1, $2, $3, 'shared_tag', 1.0)
                    """,
                    workspace_id, node_ids[i], node_ids[i + 1],
                )
    return _seed


@pytest.fixture
def mock_gemini_pool(monkeypatch: pytest.MonkeyPatch):
    """Factory: returns a configured ``StubGeminiPool`` AND monkey-patches
    ``api_key_switching.get_key_pool`` to return it.

    The stub records every call (key_index, model, content_hash) so tests can
    assert on rotation + content-aware routing decisions without burning real
    Gemini quota. Supports forced 429 injection (``force_429_after``) and
    per-(key_index, model) cooldown injection (``stub.inject_cooldown(...)``).

    Usage::

        def test_x(mock_gemini_pool):
            stub = mock_gemini_pool(embedding_dim=768, force_429_after=2)
            stub.inject_cooldown(key_index=0, model="gemini-2.5-flash")
            ...
            assert stub.calls[0].key_index == 1  # rotated past cooled key

    Anti-pattern guard: this stub never persists anywhere, never bypasses
    auth (real JWTs from ``mint_user`` continue to flow), and never alters
    SQL function bodies. It only short-circuits the network call to Gemini.
    """
    created: list[StubGeminiPool] = []

    def _factory(**stub_kwargs) -> StubGeminiPool:
        stub = StubGeminiPool(**stub_kwargs)
        created.append(stub)
        # Patch BOTH the module-level singleton accessor AND the import-time
        # alias so callers that did ``from api_key_switching import get_key_pool``
        # also see the stub.
        from website.features import api_key_switching as aks_mod

        monkeypatch.setattr(aks_mod, "get_key_pool", lambda: stub)
        # Some sites (kg_features.embeddings) imported get_key_pool at module
        # load. Patch those too if loaded.
        try:
            from website.features.kg_features import embeddings as emb_mod

            monkeypatch.setattr(emb_mod, "get_key_pool", lambda: stub, raising=False)
        except ImportError:
            pass
        return stub

    return _factory


@pytest.fixture
def recorded_source_fixtures(monkeypatch: pytest.MonkeyPatch):
    """Factory: load a recorded HTTP fixture for one of the 10 source ingestors.

    Phase 1a scaffolding: the per-source directories exist (with ``.gitkeep``)
    but actual cassettes are recorded by Phase 1b sub-agents per source.
    Calling ``_load(source="github", scenario="happy")`` raises
    ``FileNotFoundError`` until the cassette lands — clear feedback to the
    sub-agent that needs to provide it.

    The factory returns a tuple ``(payload_dict, path)`` where ``payload_dict``
    is the parsed cassette JSON. Tests can wire it into ``respx`` themselves;
    we deliberately avoid auto-installing routes here to keep the fixture
    composable with each ingestor's own respx/httpx pattern.

    Usage::

        def test_github_happy(recorded_source_fixtures, respx_mock):
            payload, _ = recorded_source_fixtures(source="github", scenario="happy")
            respx_mock.get(payload["request_url"]).respond(json=payload["body"])
            ...
    """
    def _load(*, source: str, scenario: str = "happy") -> tuple[dict, str]:
        path = SourceFixturePathResolver.path_for(source=source, scenario=scenario)
        payload = SourceFixturePathResolver.load(source=source, scenario=scenario)
        return payload, str(path)

    return _load


@pytest.fixture
def nx_graph_factory():
    """Factory: produces a seedable NetworkX ``DiGraph`` for analytics tests.

    Default: Erdős-Rényi with seed=42, n=100 nodes, edge probability p=0.05,
    weighted edges (weight ∈ [0, 1) deterministic per (seed, edge)).

    Usage::

        def test_louvain(nx_graph_factory):
            g = nx_graph_factory(n=500, p=0.02)
            metrics = compute_graph_metrics(g)
            assert metrics.modularity > 0.0
    """
    def _factory(*, n: int = 100, p: float = 0.05, seed: int = 42, weighted: bool = True):
        return build_random_digraph(n=n, p=p, seed=seed, weighted=weighted)

    return _factory


@pytest.fixture
def graph_json_loader():
    """Factory: load + JSON-Schema-validate ``content/graph.json``.

    Default path resolves to
    ``website/features/knowledge_graph/content/graph.json`` relative to the
    repo root. Tests can override ``path=`` for fixture variants.

    Usage::

        def test_graph_integrity(graph_json_loader):
            graph = graph_json_loader()
            assert len(graph["nodes"]) > 0
    """
    import json as _json

    repo_root = Path(__file__).resolve().parents[3]
    default_path = (
        repo_root
        / "website"
        / "features"
        / "knowledge_graph"
        / "content"
        / "graph.json"
    )

    def _load(*, path: Path | str | None = None) -> dict:
        target = Path(path) if path else default_path
        if not target.exists():
            raise FileNotFoundError(f"graph.json not found at {target}")
        payload = _json.loads(target.read_text(encoding="utf-8"))
        GraphJsonValidator.validate(payload)
        return payload

    return _load


@pytest.fixture
def frozen_clock():
    """Wrap each test in a ``freezegun.freeze_time`` context anchored at
    2026-05-12T00:00:00Z. Yields the FrozenDateTimeFactory so tests can
    advance time via ``frozen_clock.tick(timedelta(seconds=N))`` without
    sleeping.

    Used for TTL-cache boundary tests (KG-10), cooldown-clock-skew tests
    (KP-05), and any other time-sensitive surface that would otherwise need
    a real ``time.sleep()``.

    Usage::

        def test_cache_expires(frozen_clock):
            cache.set("k", "v", ttl=30)
            frozen_clock.tick(timedelta(seconds=29))
            assert cache.get("k") == "v"
            frozen_clock.tick(timedelta(seconds=2))
            assert cache.get("k") is None
    """
    from freezegun import freeze_time

    with freeze_time("2026-05-12T00:00:00Z") as frozen:
        yield frozen


# ---------------------------------------------------------------------------


def pytest_sessionfinish(session, exitstatus):
    """Sweep any leftover ``e2e-*@test.com`` users + orphan test-fixture
    canonical_zettels from this session.

    Backstop for per-test cleanup (which already runs via
    ``created_auth_user_ids``). When a test crashes hard or the runner is
    killed, teardown is skipped and fixture users leak — this hook catches
    them at session boundary. Set ``SKIP_TEST_FIXTURE_SWEEP=1`` to opt out
    (e.g., when running across two parallel sessions sharing a project).

    Best-effort only: errors here must NOT fail the session.
    """
    if os.environ.get("SKIP_TEST_FIXTURE_SWEEP"):
        return

    try:
        from website.core.supabase_v2.client import get_v2_client
    except Exception as exc:  # noqa: BLE001 — config missing → silently skip
        print(
            f"\n[pytest_sessionfinish] skip sweep "
            f"({type(exc).__name__}: {exc})"
        )
        return

    try:
        client = get_v2_client()
        leftover = []
        page = 1
        while True:
            resp = client.auth.admin.list_users(page=page, per_page=200)
            users = resp if isinstance(resp, list) else getattr(resp, "users", [])
            if not users:
                break
            for u in users:
                email = getattr(u, "email", None) or ""
                if email and _E2E_EMAIL_PATTERN.match(email):
                    leftover.append(u)
            if len(users) < 200:
                break
            page += 1
            if page > 50:  # hard safety cap (10k users)
                break

        for u in leftover:
            try:
                client.auth.admin.delete_user(u.id)
            except Exception:  # noqa: BLE001 — best-effort
                pass

        if leftover:
            print(
                f"\n[pytest_sessionfinish] swept {len(leftover)} leftover "
                f"test-fixture user(s)"
            )
    except Exception as exc:  # noqa: BLE001 — never fail the session
        print(
            f"\n[pytest_sessionfinish] cleanup error: "
            f"{type(exc).__name__}: {exc}"
        )

    # Sweep orphan canonical_zettels with RFC-2606 reserved test-domain URLs.
    # Tests write to content.canonical_zettels (shared cross-tenant infra) via
    # content.upsert_canonical_zettel; delete_test_user only CASCADEs through
    # workspace-scoped rows, so canonicals leak. Scoping to example.{com,net,
    # org,test} bounds this strictly to RFC-2606 reserved space — no real
    # user content can live there. NOT EXISTS sub-select on workspace_zettels
    # (which has ON DELETE RESTRICT) is the safety floor: even a bad pattern
    # cannot reach a row that still has a live ws_zettel.
    try:
        import asyncio
        import asyncpg
        from website.core.supabase_v2.client import get_v2_database_url

        async def _sweep_canonicals() -> int:
            conn = await asyncpg.connect(get_v2_database_url())
            try:
                tag = await conn.execute(
                    r"""
                    DELETE FROM content.canonical_zettels c
                    WHERE c.normalized_url ~
                          '^https?://([a-z0-9][a-z0-9.-]*\.)?example\.(com|net|org|test)([/?#]|$)'
                      AND NOT EXISTS (
                          SELECT 1 FROM content.workspace_zettels w
                          WHERE w.canonical_zettel_id = c.id
                      )
                    """
                )
                return int(tag.split()[-1]) if tag.startswith("DELETE ") else 0
            finally:
                await conn.close()

        deleted = asyncio.run(_sweep_canonicals())
        if deleted:
            print(
                f"\n[pytest_sessionfinish] swept {deleted} orphan "
                f"test-fixture canonical_zettels row(s)"
            )
    except Exception as exc:  # noqa: BLE001 — never fail the session
        print(
            f"\n[pytest_sessionfinish] canonical sweep error: "
            f"{type(exc).__name__}: {exc}"
        )


# ── Entitlement bypass (2026-08-01) ─────────────────────────────────────────
# One implementation, reused everywhere. Nine test modules each hand-rolled a
# monkeypatch pair against module attributes that Phase 9 / the D2
# strangler-fig had already moved, producing 52 of the live suite's remaining
# failures as bare AttributeErrors at fixture setup:
#
#   website.api.sandbox_routes   require_entitlement ✓   consume_entitlement ✗
#   website.api.chat_routes      require_entitlement ✗   consume_entitlement ✗
#     (chat_routes delegates to the runner: ask_kasten._require_entitlement)
#
# monkeypatch.setattr raises when the target attribute does not exist, so every
# rename silently converted a working bypass into a collection error. This
# helper patches whatever each module actually owns today and fails loudly if
# it can patch nothing at all — so the next rename surfaces as one clear error
# here instead of scattering AttributeErrors across the suite.
#
# Scope note: this is a TEST-ONLY bypass of the quota gate. It must never seed
# entitlements or touch billing.pricing_* — pricing semantics are operator-locked.
_ENTITLEMENT_TARGETS = (
    ("website.api.sandbox_routes", "require_entitlement"),
    ("website.api.module_runners.ask_kasten", "_require_entitlement"),
    ("website.api.module_runners.summarization", "require_entitlement"),
    ("website.api.module_runners.summarization", "consume_entitlement"),
)


def bypass_entitlements(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """No-op every entitlement gate that currently exists. Returns what it patched."""
    import importlib

    async def _noop(*_args, **_kwargs):
        return None

    patched: list[str] = []
    for module_path, attr in _ENTITLEMENT_TARGETS:
        try:
            mod = importlib.import_module(module_path)
        except Exception:  # pragma: no cover - module genuinely gone
            continue
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, _noop)
            patched.append(f"{module_path}.{attr}")

    if not patched:
        raise AssertionError(
            "bypass_entitlements patched nothing — every known entitlement "
            "symbol has moved. Update _ENTITLEMENT_TARGETS in "
            "tests/integration/v2/conftest.py rather than leaving tests to fail "
            "with bare AttributeErrors."
        )
    return patched


@pytest.fixture
def entitlement_bypass(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fixture form of :func:`bypass_entitlements`."""
    return bypass_entitlements(monkeypatch)
