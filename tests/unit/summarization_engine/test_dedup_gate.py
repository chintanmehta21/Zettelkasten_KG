from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from website.core.supabase_v2.repositories.content_repository import ContentRepository
from website.features.functional_gates import reset_for_tests as _reset_fg
from website.features.functional_gates.dedup_gate import get_url_dedup_gate


class _FakeResult:
    data = None


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def schema(self, *_a, **_k):
        return self

    def table(self, *_a, **_k):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        result = _FakeResult()
        result.data = self._rows
        return result


def test_find_canonical_by_url_returns_none_when_absent():
    repo = ContentRepository(client=_FakeQuery([]))
    assert repo.find_canonical_by_url("https://example.com/x") is None


def test_find_canonical_by_url_returns_canonical_and_summary():
    cid = str(uuid4())
    repo = ContentRepository(client=_FakeQuery([
        {"id": cid, "source_type": "web", "title": "T",
         "ai_summary": '{"brief_summary":"b","detailed_summary":"d"}',
         "ai_summary_engine_version": "", "user_tags": ["t1"]},
    ]))
    found = repo.find_canonical_by_url("https://example.com/x")
    assert found is not None
    assert str(found.canonical_zettel_id) == cid
    assert found.ai_summary == '{"brief_summary":"b","detailed_summary":"d"}'
    assert found.source_type == "web"


def test_workspace_links_canonical_true_when_row_present():
    repo = ContentRepository(client=_FakeQuery([{"id": "wz1"}]))
    assert repo.workspace_links_canonical(str(uuid4()), str(uuid4())) is True


def test_workspace_links_canonical_false_when_absent():
    repo = ContentRepository(client=_FakeQuery([]))
    assert repo.workspace_links_canonical(str(uuid4()), str(uuid4())) is False


def test_link_existing_canonical_delegates_to_upsert_workspace_zettel():
    from unittest.mock import MagicMock
    from website.core.supabase_v2.models import WorkspaceZettelCreate

    repo = ContentRepository(client=_FakeQuery([]))
    sentinel = uuid4()
    repo.upsert_workspace_zettel = MagicMock(return_value=sentinel)
    cid = uuid4()
    ws = WorkspaceZettelCreate(workspace_id=uuid4(), ai_summary="x", added_via="website")
    out = repo.link_existing_canonical(cid, ws)
    assert out == sentinel
    repo.upsert_workspace_zettel.assert_called_once_with(cid, ws)


def _gate_repo(found, links):
    r = MagicMock()
    r.find_canonical_by_url.return_value = found
    r.workspace_links_canonical.return_value = links
    return r


def _gate_found():
    return MagicMock(canonical_zettel_id=uuid4(),
                     ai_summary='{"brief_summary":"b","detailed_summary":"d"}',
                     source_type="web", title="T", user_tags=[])


def test_gate_fresh_when_no_canonical():
    _reset_fg()
    d = get_url_dedup_gate().decide(repo=_gate_repo(None, False),
                                    normalized_url="https://x", workspace_id=uuid4())
    assert d.branch == "fresh"
    assert d.found is None


def test_gate_same_user_noop_when_workspace_links():
    f = _gate_found()
    d = get_url_dedup_gate().decide(repo=_gate_repo(f, True),
                                    normalized_url="https://x", workspace_id=uuid4())
    assert d.branch == "same_user_noop"
    assert d.found is f


def test_gate_cross_user_hit_when_canonical_unlinked():
    f = _gate_found()
    d = get_url_dedup_gate().decide(repo=_gate_repo(f, False),
                                    normalized_url="https://x", workspace_id=uuid4())
    assert d.branch == "cross_user_hit"
    assert d.found is f


def test_gate_singleton_reused_and_reset():
    g1 = get_url_dedup_gate()
    assert get_url_dedup_gate() is g1
    _reset_fg()
    assert get_url_dedup_gate() is not g1


def _pipe_stub_bundle():
    st = SimpleNamespace(value="web")
    md = SimpleNamespace(model_dump=lambda **k: {}, engine_version="2.0.0",
                         source_type=st, url="https://r/x",
                         total_tokens_used=0, total_latency_ms=0)
    res = SimpleNamespace(metadata=md, brief_summary="b", detailed_summary=[],
                          mini_title="T", tags=["t1"], model_dump=lambda **k: {})
    ing = SimpleNamespace(metadata={"tier_used": "html"}, raw_text="x" * 4000)
    return SimpleNamespace(summary_result=res, ingest_result=ing)


def _pipe_found():
    return SimpleNamespace(
        canonical_zettel_id=uuid4(),
        ai_summary='{"brief_summary":"b","detailed_summary":"d"}',
        ai_summary_engine_version="2.0.0",
        source_type="web", title="T", user_tags=["t1"],
    )


def _pipe_scope(found, links):
    r = MagicMock()
    r.find_canonical_by_url.return_value = found
    r.workspace_links_canonical.return_value = links
    r.link_existing_canonical.return_value = uuid4()
    return (r, uuid4(), uuid4())


@pytest.mark.asyncio
async def test_pipeline_fresh_charges_once_runs_engine():
    from website.api.module_runners import summarization as S
    with patch("website.core.persist.get_supabase_v2_scope", return_value=_pipe_scope(None, False)), \
         patch.object(S, "require_entitlement", new=AsyncMock()) as ent, \
         patch.object(S, "resolve_redirects", new=AsyncMock(return_value="https://r/x")), \
         patch.object(S, "summarize_url_bundle", new=AsyncMock(return_value=_pipe_stub_bundle())) as eng, \
         patch.object(S, "persist_summarized_result", new=AsyncMock(return_value=SimpleNamespace(
             file_saved=True, supabase_saved=True, supabase_duplicate=False,
             file_node_id="n1", supabase_node_id="w1"))):
        await S.run_add_zettel_pipeline(url="https://x", client_action_id="a",
            persist=True, user={"sub": str(uuid4())}, effective_user_id=uuid4())
    assert ent.await_count == 1 and eng.await_count == 1


@pytest.mark.asyncio
async def test_pipeline_same_user_noop_no_charge_no_engine():
    from website.api.module_runners import summarization as S
    f = _pipe_found()
    with patch("website.core.persist.get_supabase_v2_scope", return_value=_pipe_scope(f, True)), \
         patch.object(S, "require_entitlement", new=AsyncMock()) as ent, \
         patch.object(S, "resolve_redirects", new=AsyncMock(return_value="https://r/x")), \
         patch.object(S, "summarize_url_bundle", new=AsyncMock()) as eng:
        out = await S.run_add_zettel_pipeline(url="https://x", client_action_id="a",
            persist=True, user={"sub": str(uuid4())}, effective_user_id=uuid4())
    assert ent.await_count == 0 and eng.await_count == 0
    assert out["status"] == "succeeded"


@pytest.mark.asyncio
async def test_pipeline_cross_user_links_charges_once_no_engine():
    from website.api.module_runners import summarization as S
    f = _pipe_found()
    sc = _pipe_scope(f, False)
    with patch("website.core.persist.get_supabase_v2_scope", return_value=sc), \
         patch.object(S, "require_entitlement", new=AsyncMock()) as ent, \
         patch.object(S, "resolve_redirects", new=AsyncMock(return_value="https://r/x")), \
         patch.object(S, "summarize_url_bundle", new=AsyncMock()) as eng:
        out = await S.run_add_zettel_pipeline(url="https://x", client_action_id="a",
            persist=True, user={"sub": str(uuid4())}, effective_user_id=uuid4())
    assert ent.await_count == 1 and eng.await_count == 0
    sc[0].link_existing_canonical.assert_called_once()
    assert out["status"] == "succeeded"


def test_v2_summarize_delegates_to_shared_runner_or_gate():
    """ADR-3: /api/v2/summarize delegates onto the shared async-ops path
    (_accept_and_spawn + _run_add_zettel) so it cannot diverge from
    /api/zettels/add — one dedup gate, entitlement, engine, persistence."""
    import website.features.summarization_engine.api.routes as R
    text = open(R.__file__, encoding="utf-8").read()
    assert "_accept_and_spawn" in text and "_run_add_zettel" in text
