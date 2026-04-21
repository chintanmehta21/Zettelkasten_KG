# Auth Provider Registry (Web) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize the web auth provider list in client-side JS and add drift-preventing tests without changing the UI or auth behavior.

**Architecture:** Keep provider list in `auth.js` as a registry. Bind click handlers to existing DOM elements based on that registry. Add tests that parse HTML and JS to confirm the provider list is consistent.

**Tech Stack:** Vanilla JS, FastAPI static HTML, Pytest.

---

## File Structure / Responsibilities

- Modify: `website/features/user_auth/js/auth.js`
  - Define provider registry and gate click handlers.
- Modify: `tests/test_auth.py` OR Create: `tests/test_auth_providers.py`
  - Add tests that parse `website/static/index.html` and `auth.js` to check provider list.

---

### Task 1: Add provider registry + binding in auth.js

**Files:**
- Modify: `website/features/user_auth/js/auth.js`

- [ ] **Step 1: Write the failing tests first (new test file)**

Create `tests/test_auth_providers.py`:

```python
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
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `python -m pytest tests/test_auth_providers.py -v`

Expected: FAIL because `AUTH_PROVIDERS` registry does not exist yet.

- [ ] **Step 3: Implement provider registry + binding in auth.js**

Add the registry and use it to guard provider binding:

```javascript
  var AUTH_PROVIDERS = ['google', 'github', 'apple', 'twitter', 'facebook', 'twitch'];

  function isKnownProvider(value) {
    return AUTH_PROVIDERS.indexOf(value) !== -1;
  }
```

Then adjust binding to skip unknown providers:

```javascript
    var gridItems = document.querySelectorAll('.provider-item');
    gridItems.forEach(function (item) {
      item.addEventListener('click', function () {
        var provider = item.getAttribute('data-provider');
        if (!isKnownProvider(provider)) return;
        providerGrid.classList.remove('open');
        signInWithProvider(provider);
      });
    });
```

Keep modal behavior unchanged, and leave the existing Google modal button intact.

- [ ] **Step 4: Run tests again to confirm they pass**

Run: `python -m pytest tests/test_auth_providers.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add website/features/user_auth/js/auth.js tests/test_auth_providers.py
git commit -m "test: lock auth provider registry"
```

---

### Task 2: Broaden auth.js registry checks to modal provider buttons (non-UI)

**Files:**
- Modify: `website/features/user_auth/js/auth.js`

- [ ] **Step 1: Write a small test to ensure modal bindings are safe**

Append to `tests/test_auth_providers.py`:

```python
def test_modal_google_button_still_present():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "id=\"oauth-google\"" in html
```

- [ ] **Step 2: Run tests to confirm they fail if the button is removed**

Run: `python -m pytest tests/test_auth_providers.py -v`

Expected: PASS (button exists today).

- [ ] **Step 3: Update JS binding to validate provider on modal buttons**

Add guard for `.modal-provider-btn` click binding:

```javascript
    if (modalProviders) {
      modalProviders.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var provider = btn.getAttribute('data-provider');
          if (!isKnownProvider(provider)) return;
          signInWithProvider(provider);
        });
      });
    }
```

No HTML changes.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_auth_providers.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add website/features/user_auth/js/auth.js tests/test_auth_providers.py
git commit -m "test: guard auth provider bindings"
```

---

### Task 3: Update documentation for local OAuth URL assumption

**Files:**
- Modify: `docs/superpowers/specs/2026-04-07-auth-provider-registry-design.md`

- [ ] **Step 1: Add the local URL note (if missing)**

Ensure the spec includes:

```markdown
- OAuth redirect URL for local dev: `http://localhost:8443/auth/callback`
```

- [ ] **Step 2: Run spec lint (manual)**

Quick scan for placeholders like TODO/TBD.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-04-07-auth-provider-registry-design.md
git commit -m "docs: clarify local oauth callback"
```

---

## Plan Self-Review

- Spec coverage: registry centralized, no UI changes, tests for drift, local URL note. Covered by Tasks 1-3.
- Placeholder scan: none found.
- Type/identifier consistency: `AUTH_PROVIDERS`, `isKnownProvider` referenced consistently.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-07-auth-provider-registry.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
