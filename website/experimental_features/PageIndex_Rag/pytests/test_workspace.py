from pathlib import Path

import pytest

from website.experimental_features.PageIndex_Rag.secrets import (
    LoginDetailsMissingError,
    load_login_details,
)
from website.experimental_features.PageIndex_Rag.types import ZettelRecord
from website.experimental_features.PageIndex_Rag.workspace import PageIndexWorkspace


class FakeAdapter:
    def __init__(self):
        self.index_calls = 0

    def index_markdown(self, markdown_path):
        self.index_calls += 1
        return "doc-1"

    def get_document_structure(self, doc_id):
        return [{"title": "Root", "line_num": 1, "node_id": "0001"}]


def test_missing_login_details_fails_without_secret_echo(tmp_path: Path):
    missing = tmp_path / "login_details.txt"
    with pytest.raises(LoginDetailsMissingError) as exc:
        load_login_details(missing)
    assert str(missing) in str(exc.value)
    assert "password" not in str(exc.value).lower()


def test_login_details_parser_accepts_render_user_id(tmp_path: Path):
    path = tmp_path / "login_details.txt"
    path.write_text("render_user_id=naruto\n", encoding="utf-8")
    assert load_login_details(path) == {"render_user_id": "naruto"}


def test_login_details_parser_defaults_to_naruto_for_local_credentials(tmp_path: Path):
    path = tmp_path / "login_details.txt"
    path.write_text("username: local-user\npassword: local-secret\n", encoding="utf-8")
    parsed = load_login_details(path)
    assert parsed["render_user_id"] == "naruto"


def test_login_details_parser_normalizes_markdown_label_keys(tmp_path: Path):
    path = tmp_path / "login_details.txt"
    path.write_text("- Auth ID: user-123\n- Email: naruto@example.test\n", encoding="utf-8")
    assert load_login_details(path) == {"auth_id": "user-123", "email": "naruto@example.test"}


def test_workspace_indexes_once_for_same_hash(tmp_path: Path):
    adapter = FakeAdapter()
    workspace = PageIndexWorkspace(root=tmp_path, adapter=adapter)
    zettel = ZettelRecord("u", "n", "Title", "summary", "body", "web", None, (), {})
    first = workspace.ensure_indexed(zettel)
    second = workspace.ensure_indexed(zettel)
    assert first.doc_id == second.doc_id == "doc-1"
    assert adapter.index_calls == 1
