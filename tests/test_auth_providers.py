from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "website" / "static" / "index.html"
AUTH_JS = PROJECT_ROOT / "website" / "features" / "user_auth" / "js" / "auth.js"

EXPECTED_PROVIDERS = {"google", "github", "apple", "twitter", "facebook", "twitch"}


def _extract_providers_from_html(html: str) -> set[str]:
    providers = set()
    marker = "data-provider=\""
    idx = 0
    while True:
        start = html.find(marker, idx)
        if start == -1:
            break
        start += len(marker)
        end = html.find("\"", start)
        if end == -1:
            break
        providers.add(html[start:end])
        idx = end + 1
    return providers


def _extract_registry_from_js(js: str) -> set[str]:
    # Look for a literal array like: var AUTH_PROVIDERS = ['google', ...];
    marker = "AUTH_PROVIDERS"
    start = js.find(marker)
    if start == -1:
        return set()
    open_bracket = js.find("[", start)
    close_bracket = js.find("]", open_bracket)
    if open_bracket == -1 or close_bracket == -1:
        return set()
    body = js[open_bracket + 1 : close_bracket]
    items = []
    for chunk in body.split(","):
        value = chunk.strip().strip("'\"")
        if value:
            items.append(value)
    return set(items)


def test_provider_list_in_html_dropdown():
    html = INDEX_HTML.read_text(encoding="utf-8")
    providers = _extract_providers_from_html(html)
    missing = EXPECTED_PROVIDERS - providers
    assert not missing, f"Missing providers in HTML: {sorted(missing)}"


def test_provider_registry_in_auth_js():
    js = AUTH_JS.read_text(encoding="utf-8")
    providers = _extract_registry_from_js(js)
    missing = EXPECTED_PROVIDERS - providers
    assert not missing, f"Missing providers in auth.js registry: {sorted(missing)}"
