from uuid import uuid4

from website.core.supabase_v2.repositories.content_repository import ContentRepository


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
