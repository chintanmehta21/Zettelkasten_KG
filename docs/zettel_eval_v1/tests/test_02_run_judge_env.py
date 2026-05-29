"""Tests for 02_run_judge.py::_parse_api_env_lines.

Added 2026-05-29 after catching a pre-iter-003 bug where the legacy parser
in ``_load_env`` split on the first ``=`` it saw. For lines containing a
``role=billing`` token (introduced by the gemini_factory role-tagging fix
the same day), the split fell inside the token and produced the literal
string ``"billing"`` as if it were the key — silently dropping the billing
key and feeding garbage into the pool. These tests pin the new behavior:
role tokens are preserved verbatim so downstream gemini_factory CSV
parsing can recover (key, role) tuples.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "02_run_judge.py"


def _mod():
    sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_02_run_judge", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_parse_bare_keys_simple():
    m = _mod()
    text = "AIzaA\nAIzaB\nAIzaC\n"
    assert m._parse_api_env_lines(text) == ["AIzaA", "AIzaB", "AIzaC"]


def test_parse_preserves_role_billing_token():
    """The 2026-05-29 regression: role=billing on the same line as the key must
    survive intact so gemini_factory can read the role downstream. The legacy
    parser ate everything before the first `=` which destroyed the key."""
    m = _mod()
    text = "AIzaFree\nAIzaPaid role=billing\n"
    out = m._parse_api_env_lines(text)
    assert out == ["AIzaFree", "AIzaPaid role=billing"]
    # No element should be just the role word
    assert "billing" not in out
    assert "free" not in out


def test_parse_preserves_role_free_token():
    m = _mod()
    text = "AIzaOne role=free\n"
    assert m._parse_api_env_lines(text) == ["AIzaOne role=free"]


def test_parse_skips_blank_and_comment_lines():
    m = _mod()
    text = "# comment\n\n   \nAIzaReal\n# trailing comment\n"
    assert m._parse_api_env_lines(text) == ["AIzaReal"]


def test_parse_strips_surrounding_quotes_only():
    """Quotes that wrap the entire value (e.g. `"AIzaX"`) are stripped — that's
    legitimate when operators copy from a JSON payload. Quotes inside the value
    must NOT be touched."""
    m = _mod()
    text = '"AIzaQuoted"\n\'AIzaSingle\'\n'
    out = m._parse_api_env_lines(text)
    assert out == ["AIzaQuoted", "AIzaSingle"]


def test_parse_handles_whitespace_around_role_token():
    m = _mod()
    # Multiple spaces between key and role= are common when operators add the
    # tag manually with a tab or double-space — must survive.
    text = "AIzaKey  role=billing\nAIzaKey2\trole=free\n"
    out = m._parse_api_env_lines(text)
    assert out == ["AIzaKey  role=billing", "AIzaKey2\trole=free"]


def test_parse_real_api_env_does_not_drop_billing_key():
    """End-to-end against the real api_env file. The billing key MUST appear
    in the output as a substring of one of the returned lines — never as the
    literal word 'billing'."""
    m = _mod()
    api_env = REPO_ROOT / "api_env"
    if not api_env.exists():
        # Repo without api_env (e.g. CI shallow clone) — skip rather than fail.
        import pytest
        pytest.skip("api_env not present in this checkout")
    out = m._parse_api_env_lines(api_env.read_text(encoding="utf-8"))
    assert len(out) >= 1, "api_env should produce at least one key"
    # The billing line must contain BOTH the key prefix AND the role token
    billing_lines = [k for k in out if "role=billing" in k]
    assert len(billing_lines) == 1, f"expected exactly 1 billing line, got {len(billing_lines)}"
    bl = billing_lines[0]
    assert bl.startswith("AIza"), f"billing line must start with AIza, got prefix {bl[:10]!r}"
    # And nothing in the output is just the literal word "billing"
    assert "billing" not in out and "free" not in out


if __name__ == "__main__":
    test_parse_bare_keys_simple()
    print("PASS test_parse_bare_keys_simple")
    test_parse_preserves_role_billing_token()
    print("PASS test_parse_preserves_role_billing_token")
    test_parse_preserves_role_free_token()
    print("PASS test_parse_preserves_role_free_token")
    test_parse_skips_blank_and_comment_lines()
    print("PASS test_parse_skips_blank_and_comment_lines")
    test_parse_strips_surrounding_quotes_only()
    print("PASS test_parse_strips_surrounding_quotes_only")
    test_parse_handles_whitespace_around_role_token()
    print("PASS test_parse_handles_whitespace_around_role_token")
    test_parse_real_api_env_does_not_drop_billing_key()
    print("PASS test_parse_real_api_env_does_not_drop_billing_key")
    print("ALL 7 TESTS PASS")
