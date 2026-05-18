from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "purge_e2e_test_zettels", ROOT / "ops" / "scripts" / "purge_e2e_test_zettels.py"
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_email_scope_is_narrow_and_cannot_match_real_users() -> None:
    # Regression guard: the pattern must stay anchored so it can never widen to
    # match real users (naruto@zettelkasten.local, zoro@zettelkasten.test, etc.)
    assert _mod._EMAIL_PATTERN == "e2e-%@test.com"
    pat = _mod._EMAIL_PATTERN

    def like(value: str, pattern: str) -> bool:
        import re

        regex = "^" + re.escape(pattern).replace("%", ".*").replace(r"\%", ".*") + "$"
        return re.match(regex, value) is not None

    assert like("e2e-8ab8d127@test.com", pat)
    assert like("e2e-@test.com", pat)
    assert not like("naruto@zettelkasten.local", pat)
    assert not like("zoro@zettelkasten.test", pat)
    assert not like("e2e-user@gmail.com", pat)
    assert not like("real-e2e@test.com", pat)  # must start with 'e2e-'


def test_select_filters_by_owner_email_only() -> None:
    sql = _mod._SELECT
    assert "p.email LIKE %s" in sql
    assert "content.workspace_zettels" in sql
    # Must not accidentally filter/keep by anything that could spare e2e rows.
    assert "deleted_at" not in sql  # delete ALL e2e rows incl. soft-deleted
