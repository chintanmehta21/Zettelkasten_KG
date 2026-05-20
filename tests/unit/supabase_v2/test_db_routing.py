from __future__ import annotations

from uuid import UUID

import pytest

from website.core import db_version
from website.core import persist
from website.core.supabase_v2.models import CanonicalUpsertResult


def test_db_schema_version_requires_v2_credentials(monkeypatch) -> None:
    """PR #39 follow-up (2026-05-20): also unset the canonical SUPABASE_*
    fallback names. `_v2_env` in supabase_v2/client.py falls back to
    SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY when the
    V2-prefixed namespace is empty (post-2026-05 deprecation), so deleting
    only the V2 names left the canonical .env values leaking through and
    `is_v2_configured()` stayed True. Delete both namespaces so the test
    actually exercises the "no creds available anywhere" branch."""
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    for name in (
        "SUPABASE_V2_URL", "SUPABASE_V2_SERVICE_ROLE_KEY", "SUPABASE_V2_ANON_KEY",
        # Fallback canonical names also consulted by _v2_env in client.py.
        "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    assert db_version.get_db_schema_version() == "v2"
    assert db_version.use_supabase_v2() is False


class _FakeV2Repo:
    def __init__(self) -> None:
        self.calls = []

    def upsert_canonical_zettel(self, zettel, *, workspace=None, chunks=None):
        self.calls.append((zettel, workspace, chunks))
        return CanonicalUpsertResult(
            canonical_zettel_id=UUID("00000000-0000-0000-0000-000000000111"),
            workspace_zettel_id=UUID("00000000-0000-0000-0000-000000000222"),
            was_new=True,
        )


@pytest.mark.asyncio
async def test_persist_routes_to_v2_when_scope_available(monkeypatch) -> None:
    """v2-scope routing invariant: with a v2 scope available, persist
    writes the canonical zettel + workspace zettel via the v2 repo.

    PR #39 Wave-3 CONTRACT CHANGE: chunks no longer land inline — the
    inline upsert_canonical_zettel is now called with ``chunks=[]`` and a
    lazy enrichment job is enqueued for the chunker+Gemini batch embed.
    We assert both: the inline call uses empty chunks, AND
    ``enrichment_repo.enqueue_chunk_embed`` is called exactly once with
    the canonical_zettel_id of the freshly-written row.
    """
    monkeypatch.setattr(persist, "_schedule_kg_population", lambda **_k: None)

    from website.features.summarization_engine.lazy_enrichment import (
        repo as enrichment_repo,
    )

    enqueued: list[dict] = []

    def _capture(**kw):
        enqueued.append(kw)
        return ("stub-job", True)

    monkeypatch.setattr(enrichment_repo, "enqueue_chunk_embed", _capture)

    repo = _FakeV2Repo()
    monkeypatch.setattr(
        persist,
        "get_supabase_v2_scope",
        lambda user_sub: (
            repo,
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
        ),
    )
    monkeypatch.setattr(persist, "_file_graph_contains_url", lambda url: False)
    monkeypatch.setattr(persist, "_persist_file_node", lambda payload, skip_duplicate: None)

    outcome = await persist.persist_summarized_result(
        {
            "title": "Example",
            "source_type": "web",
            "source_url": "https://example.com",
            "summary": "Detailed summary.",
            "tags": ["Test"],
        },
        user_sub="00000000-0000-0000-0000-000000000001",
    )

    assert outcome.supabase_saved is True
    assert outcome.supabase_node_id == "00000000-0000-0000-0000-000000000222"
    zettel, workspace, chunks = repo.calls[0]
    assert zettel.normalized_url == "https://example.com"
    assert workspace.workspace_id == UUID("00000000-0000-0000-0000-000000000002")
    # Wave-3 invariant: chunks always [] on the critical path.
    assert chunks == []
    # ...and the lazy enrichment job is enqueued exactly once.
    assert len(enqueued) == 1
    assert enqueued[0]["canonical_zettel_id"] == UUID("00000000-0000-0000-0000-000000000111")

