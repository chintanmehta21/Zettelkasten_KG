"""PRF-1 regression net: the profile page must never expose internal source
paths / implementation status to end users (OWASP A05 / Improper Error Handling)."""
from pathlib import Path

PROFILE_HTML = Path("website/features/user_profile/index.html")


def test_profile_html_has_no_internal_path_leak():
    html = PROFILE_HTML.read_text(encoding="utf-8")
    assert "account_purge" not in html, "profile leaks the account_purge module name"
    assert "website/core/" not in html, "profile leaks an internal source path"
    assert "no production endpoint is wired" not in html, "profile leaks build status"
