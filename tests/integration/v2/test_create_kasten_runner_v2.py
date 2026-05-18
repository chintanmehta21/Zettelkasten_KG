"""Phase C live integration tests for the consolidated create-Kasten route.

Marked ``@pytest.mark.live`` (skipped without ``--live``). They:

* Boot a real FastAPI app with ``DB_SCHEMA_VERSION=v2``.
* Mint fresh Supabase Auth users + workspaces via the service-role fixture.
* Drive ``POST /api/rag/sandboxes`` with a non-empty ``links`` list. The
  Gemini summarizer is stubbed at ``module_runners.summarization`` (no quota
  burn / no flaky network) but EVERYTHING else is live: real
  ``content.upsert_canonical_zettel``, real ``rag.bulk_add_to_kasten``, real
  ``rag.list_kasten_zettels``, real ``/api/graph?view=my``.
* Assert: the Kasten + members + graph are visible immediately via the read
  endpoints, scoped to the caller; cross-tenant access is denied with no UUID
  leakage (OWASP API1:2023 BOLA pattern).

Pricing is monkey-patched out at the route-module level — the pricing-module-
authority rule (CLAUDE.md) forbids seeding entitlements; this is the same
bypass ``test_sandbox_routes_v2.py`` uses.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live


def _auth_headers(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


class _FakeSourceType:
    """Minimal stand-in for the engine SourceType enum (only ``.value`` is read
    by ``summarization.summary_dto``)."""

    value = "generic"


class _FakeMeta:
    def __init__(self, url: str) -> None:
        self.source_type = _FakeSourceType()
        self.url = url
        self.total_tokens_used = 10
        self.total_latency_ms = 5

    def model_dump(self, **_kw):
        return {"source_type": "generic", "url": self.url}


class _FakeSummaryResult:
    def __init__(self, url: str) -> None:
        self.mini_title = f"Kasten link {url}"
        self.brief_summary = "detailed body for the kasten link"
        # ``summary_dto`` does ``render_detailed_summary(detailed_summary) or
        # brief_summary``; an empty section list renders to "" and falls back
        # to brief_summary (a valid non-empty body for persistence).
        self.detailed_summary: list = []
        self.tags = ["phase-c", "kasten"]
        self.metadata = _FakeMeta(url)


class _FakeIngest:
    def __init__(self) -> None:
        self.raw_text = "raw source text for the kasten link"
        self.metadata = {"tier_used": "tier-a"}


class _FakeBundle:
    def __init__(self, url: str) -> None:
        self.summary_result = _FakeSummaryResult(url)
        self.ingest_result = _FakeIngest()


@pytest.fixture
def v2_app_with_stub_summarizer(monkeypatch):
    """v2-forced app, entitlement no-op, summarizer + redirects stubbed.

    Persistence (Supabase) stays fully live so rows actually land; only the
    LLM + network egress is short-circuited.
    """
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.api import auth as auth_mod
    auth_mod._jwks_client = None
    from website.core import persist as persist_mod
    persist_mod._v2_core_repo = None
    persist_mod._v2_content_repo = None

    async def _noop(*_a, **_kw):
        return None

    from website.api import sandbox_routes as sandbox_routes_mod
    monkeypatch.setattr(sandbox_routes_mod, "require_entitlement", _noop)

    from website.api.module_runners import summarization as runner_mod

    async def _fake_require_entitlement(*_a, **_kw):
        return None

    async def _fake_summarize(url, *, user_id, gemini_client, source_type=None):
        return _FakeBundle(url)

    async def _fake_resolve(url, *_a, **_kw):
        return url

    monkeypatch.setattr(runner_mod, "require_entitlement", _fake_require_entitlement)
    monkeypatch.setattr(runner_mod, "summarize_url_bundle", _fake_summarize)
    monkeypatch.setattr(runner_mod, "resolve_redirects", _fake_resolve)
    monkeypatch.setattr(runner_mod, "normalize_url", lambda u: u)

    from website.app import create_app

    return create_app()


def _create_kasten_with_links(client, *, jwt, name, links, action_id):
    """POST then poll the create-Kasten op to completion; return final body."""
    resp = client.post(
        "/api/rag/sandboxes",
        json={"name": name, "links": links, "client_action_id": action_id},
        headers=_auth_headers(jwt),
    )
    assert resp.status_code == 202, (
        f"expected 202 accepted, got {resp.status_code}: {resp.text[:400]}"
    )
    status_url = resp.json()["status_url"]
    final = None
    for _ in range(120):
        poll = client.get(status_url, headers=_auth_headers(jwt))
        if poll.status_code == 200:
            final = poll.json()
            break
    assert final is not None, "create-Kasten operation did not complete"
    return final


@pytest.mark.asyncio
async def test_create_kasten_with_links_visible_via_read_endpoints(
    v2_app_with_stub_summarizer, mint_user, asyncpg_pool
):
    """Consolidated route creates a Kasten, ingests 2 links, and the Kasten +
    members + personal graph are visible immediately, scoped to the caller."""
    user = mint_user(workspace_count=1)
    ws_id = user.workspace_ids[0]
    seed = uuid.uuid4().hex[:8]
    links = [
        f"https://phase-c-{seed}-a.example.com/",
        f"https://phase-c-{seed}-b.example.com/",
    ]

    with TestClient(v2_app_with_stub_summarizer) as client:
        final = _create_kasten_with_links(
            client,
            jwt=user.jwt,
            name=f"k-{seed}",
            links=links,
            action_id=f"cak-{seed}",
        )
        assert final["status"] == "succeeded"
        assert final["failed"] == []
        assert len(final["ingested"]) == 2
        kasten_id = final["kasten"]["id"]

        # Kasten row landed in rag.kastens scoped to the caller's workspace.
        async with asyncpg_pool.acquire() as conn:
            krow = await conn.fetchrow(
                "SELECT workspace_id FROM rag.kastens WHERE id = $1",
                uuid.UUID(kasten_id),
            )
            member_rows = await conn.fetch(
                "SELECT workspace_zettel_id FROM rag.kasten_zettels WHERE kasten_id = $1",
                uuid.UUID(kasten_id),
            )
        assert krow is not None and krow["workspace_id"] == ws_id
        assert len(member_rows) == 2, "both links must be members"

        # Every membership row is a real content.workspace_zettels id in THIS
        # workspace (dedup caveat: never a canonical id).
        member_ids = [str(r["workspace_zettel_id"]) for r in member_rows]
        async with asyncpg_pool.acquire() as conn:
            wz_check = await conn.fetch(
                """
                SELECT id FROM content.workspace_zettels
                 WHERE id = ANY($1::uuid[]) AND workspace_id = $2
                   AND deleted_at IS NULL
                """,
                [uuid.UUID(m) for m in member_ids],
                ws_id,
            )
        assert {str(r["id"]) for r in wz_check} == set(member_ids)

        # Visible via the list endpoint.
        resp = client.get("/api/rag/sandboxes", headers=_auth_headers(user.jwt))
        assert resp.status_code == 200, resp.text[:400]
        assert kasten_id in [s["id"] for s in resp.json()["sandboxes"]]

        # Visible via the members endpoint.
        resp = client.get(
            f"/api/rag/sandboxes/{kasten_id}/members",
            headers=_auth_headers(user.jwt),
        )
        assert resp.status_code == 200, resp.text[:400]
        assert len(resp.json()["members"]) == 2

        # Visible via the personal graph (cache invalidated post-add).
        resp = client.get(
            "/api/graph?view=my", headers=_auth_headers(user.jwt)
        )
        assert resp.status_code == 200, resp.text[:400]
        graph_urls = {n.get("url") for n in resp.json().get("nodes", [])}
        assert set(links).issubset(graph_urls), (
            f"ingested links must appear in /api/graph?view=my; got {graph_urls}"
        )


@pytest.mark.asyncio
async def test_create_kasten_idempotent_resubmit_no_dup(
    v2_app_with_stub_summarizer, mint_user, asyncpg_pool
):
    """Same client_action_id re-submitted → same Kasten, no duplicate Kasten,
    membership union (ON CONFLICT no dup rows)."""
    user = mint_user(workspace_count=1)
    ws_id = user.workspace_ids[0]
    seed = uuid.uuid4().hex[:8]
    name = f"k-idem-{seed}"
    links = [f"https://phase-c-idem-{seed}.example.com/"]
    action_id = f"cak-idem-{seed}"

    with TestClient(v2_app_with_stub_summarizer) as client:
        first = _create_kasten_with_links(
            client, jwt=user.jwt, name=name, links=links, action_id=action_id
        )
        second = _create_kasten_with_links(
            client, jwt=user.jwt, name=name, links=links, action_id=action_id
        )

    assert first["kasten"]["id"] == second["kasten"]["id"]
    async with asyncpg_pool.acquire() as conn:
        kasten_count = await conn.fetchval(
            "SELECT count(*) FROM rag.kastens WHERE workspace_id = $1 AND name = $2",
            ws_id, name,
        )
        member_count = await conn.fetchval(
            "SELECT count(*) FROM rag.kasten_zettels WHERE kasten_id = $1",
            uuid.UUID(first["kasten"]["id"]),
        )
    assert kasten_count == 1, "re-submit must NOT create a duplicate Kasten"
    assert member_count == 1, "membership must be union-merged (ON CONFLICT)"


@pytest.mark.asyncio
async def test_create_kasten_cross_tenant_denial_no_uuid_leak(
    v2_app_with_stub_summarizer, mint_user, asyncpg_pool
):
    """User B must NOT see User A's link-built Kasten, its members, or its
    zettels in B's personal graph. No A-owned UUID may leak into B responses
    (OWASP API1:2023 BOLA — UUID-leak assertion)."""
    user_a = mint_user(workspace_count=1)
    user_b = mint_user(workspace_count=1)
    seed = uuid.uuid4().hex[:8]
    links = [f"https://phase-c-xt-{seed}.example.com/"]

    with TestClient(v2_app_with_stub_summarizer) as client:
        final = _create_kasten_with_links(
            client,
            jwt=user_a.jwt,
            name=f"a-{seed}",
            links=links,
            action_id=f"cak-a-{seed}",
        )
        a_kasten_id = final["kasten"]["id"]
        a_member_ids = {
            i["workspace_zettel_id"] for i in final["ingested"] if i["workspace_zettel_id"]
        }
        assert a_member_ids, "A must have at least one resolved member id"

        # B lists kastens — A's must not appear, and no A UUID anywhere.
        resp = client.get("/api/rag/sandboxes", headers=_auth_headers(user_b.jwt))
        assert resp.status_code == 200, resp.text[:400]
        b_list_text = resp.text
        assert a_kasten_id not in [s["id"] for s in resp.json()["sandboxes"]]
        assert a_kasten_id not in b_list_text
        for mid in a_member_ids:
            assert mid not in b_list_text, "A's workspace_zettel id leaked to B"

        # B cannot read A's members (404, no A UUID in the body).
        resp = client.get(
            f"/api/rag/sandboxes/{a_kasten_id}/members",
            headers=_auth_headers(user_b.jwt),
        )
        assert resp.status_code == 404, (
            f"cross-tenant members read must 404, got {resp.status_code}"
        )
        for mid in a_member_ids:
            assert mid not in resp.text

        # B's personal graph must not include A's ingested link.
        resp = client.get("/api/graph?view=my", headers=_auth_headers(user_b.jwt))
        assert resp.status_code == 200, resp.text[:400]
        b_graph_urls = {n.get("url") for n in resp.json().get("nodes", [])}
        assert not set(links).intersection(b_graph_urls), (
            "A's ingested link must NOT appear in B's personal graph"
        )

    # A's Kasten + memberships remain intact after B's failed access.
    async with asyncpg_pool.acquire() as conn:
        still_there = await conn.fetchval(
            "SELECT 1 FROM rag.kastens WHERE id = $1", uuid.UUID(a_kasten_id)
        )
        members_intact = await conn.fetchval(
            "SELECT count(*) FROM rag.kasten_zettels WHERE kasten_id = $1",
            uuid.UUID(a_kasten_id),
        )
    assert still_there == 1
    assert members_intact == len(a_member_ids)
