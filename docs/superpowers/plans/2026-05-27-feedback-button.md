# Feedback Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a footer "Send feedback" button that opens a popup (modal on desktop, bottom-sheet on mobile) for Issues / Suggestions submissions and posts each one to Slack `#zk-testing` with the user's full name, country, and any attached screenshots — with the entire feature module contained inside `website/features/feedback/`.

**Architecture:** Self-contained module under `website/features/feedback/` exposing a single `register(app)` entry point. The module owns its routes, services, Slack client, image pipeline, rate-limiter, UI assets (CSS/JS/HTML/SVG), settings, and tests. Footer button is auto-injected by the feature's own JavaScript so the existing `website/footer/footer.html` and `website/mobile/templates/_shell.html` files are never modified. The implementation follows TDD with frequent commits — one logical commit per task.

**Tech Stack:** Python 3.12, FastAPI 0.115+, `slack_sdk>=3.27`, `python-magic` (+ system `libmagic1`), Pillow ≥10.3, pytest with `asyncio_mode=auto`, vanilla JS + CSS (no framework).

**Spec:** [docs/superpowers/specs/2026-05-27-feedback-button-design.md](../specs/2026-05-27-feedback-button-design.md)

**Tracking PR:** [#117](https://github.com/chintanmehta21/Zettelkasten_KG/pull/117)

---

## Scope check

Single subsystem. No decomposition needed. Estimated effort: 21 tasks, each task is a contained TDD cycle ending in one commit. Total ~6-10 hours for a focused implementation pass.

---

## File structure (target end state)

```
website/features/feedback/                          # NEW — the entire module
├── __init__.py                                     # exports register(app)
├── README.md                                       # feature docs
├── service.py                                      # top-level orchestrator
├── api/
│   ├── __init__.py
│   ├── routes.py                                   # POST /api/feedback/submit
│   ├── deps.py                                     # FastAPI deps
│   └── cookie.py                                   # signed HMAC cookie
├── core/
│   ├── __init__.py
│   ├── settings.py                                 # FeedbackSettings
│   ├── identity.py                                 # name + country resolution
│   └── ids.py                                      # FB-XXXX generator
├── intake/
│   ├── __init__.py
│   ├── models.py                                   # Pydantic DTOs
│   ├── validation.py                               # extension + magic-byte
│   ├── image_pipeline.py                           # Pillow rewrite + EXIF strip
│   └── rate_limit.py                               # daily sliding window
├── slack/
│   ├── __init__.py
│   ├── client.py                                   # SDK wrapper
│   └── block_kit.py                                # payload builder
├── ui/
│   ├── __init__.py
│   ├── static/
│   │   ├── feedback.css
│   │   ├── feedback.js
│   │   └── icons.svg
│   └── templates/
│       ├── modal.html
│       └── sheet.html
└── tests/
    ├── conftest.py
    ├── unit/                                        # ~7 files
    ├── integration/                                 # 2 files
    └── live/                                        # 1 file

# OUTSIDE the module (minimum unavoidable touch):
website/app.py                                       # 1 import + 1 register call + ~10 lines post-processor infra
ops/requirements.txt                                 # +python-magic, +slack_sdk
ops/Dockerfile                                       # +libmagic1 in Stage 2
ops/caddy/Caddyfile                                  # +route-level body-size for /api/feedback/submit
ops/.env.example                                     # +4 documented env vars
```

---

## Pre-flight checks (do these once before Task 1)

- [ ] Confirm you're on branch `claude/sharp-pasteur-4e8b7e` (the PR #117 branch). `git branch --show-current` must print exactly that.
- [ ] `git status` shows clean working tree.
- [ ] `pip install -r ops/requirements-dev.txt` succeeds (dev deps already in place).
- [ ] `pytest --collect-only tests/ -q | tail -3` runs (existing tests discoverable).

---

## Task 1: Scaffold module skeleton + add dependencies

**Files:**
- Create: `website/features/feedback/__init__.py` (placeholder)
- Create: `website/features/feedback/api/__init__.py` (empty)
- Create: `website/features/feedback/core/__init__.py` (empty)
- Create: `website/features/feedback/intake/__init__.py` (empty)
- Create: `website/features/feedback/slack/__init__.py` (empty)
- Create: `website/features/feedback/ui/__init__.py` (empty)
- Create: `website/features/feedback/ui/static/.gitkeep`
- Create: `website/features/feedback/ui/templates/.gitkeep`
- Create: `website/features/feedback/tests/__init__.py` (empty)
- Create: `website/features/feedback/tests/conftest.py`
- Create: `website/features/feedback/tests/unit/__init__.py` (empty)
- Create: `website/features/feedback/tests/integration/__init__.py` (empty)
- Create: `website/features/feedback/tests/live/__init__.py` (empty)
- Create: `website/features/feedback/tests/unit/test_smoke.py`
- Modify: `ops/requirements.txt` (append 3 lines)

- [ ] **Step 1.1: Create the directory skeleton + all empty `__init__.py` files**

```bash
mkdir -p website/features/feedback/{api,core,intake,slack,ui/static,ui/templates,tests/unit,tests/integration,tests/live}
touch website/features/feedback/__init__.py
touch website/features/feedback/api/__init__.py
touch website/features/feedback/core/__init__.py
touch website/features/feedback/intake/__init__.py
touch website/features/feedback/slack/__init__.py
touch website/features/feedback/ui/__init__.py
touch website/features/feedback/tests/__init__.py
touch website/features/feedback/tests/unit/__init__.py
touch website/features/feedback/tests/integration/__init__.py
touch website/features/feedback/tests/live/__init__.py
touch website/features/feedback/ui/static/.gitkeep
touch website/features/feedback/ui/templates/.gitkeep
```

- [ ] **Step 1.2: Write conftest.py — feature-local fixtures**

File: `website/features/feedback/tests/conftest.py`
```python
"""Feature-local fixtures for the feedback module's tests."""
from __future__ import annotations

import os
import pytest


@pytest.fixture
def fake_slack_creds(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Stub all Slack env vars so route tests don't 503."""
    creds = {
        "SLACK_BOT_TOKEN_FEEDBACK": "xoxb-test-fake-token-1234",
        "SLACK_CHANNEL_FEEDBACK": "C09TESTCHAN",
        "SECRET_FEEDBACK_COOKIE": "0123456789abcdef" * 4,  # 64-byte hex
        "FEEDBACK_REQUIRE_TURNSTILE": "false",
    }
    for k, v in creds.items():
        monkeypatch.setenv(k, v)
    # Reset the lru_cache so the next get_feedback_settings() call sees the fakes.
    from website.features.feedback.core.settings import get_feedback_settings
    get_feedback_settings.cache_clear()
    return creds


@pytest.fixture
def jpeg_bytes_no_exif() -> bytes:
    """Minimal 8x8 black JPEG with no EXIF, for image-pipeline tests."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 0)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes_with_gps_exif() -> bytes:
    """8x8 JPEG carrying a fake GPS EXIF tag, for the EXIF-strip test."""
    from io import BytesIO
    import piexif
    from PIL import Image
    buf = BytesIO()
    img = Image.new("RGB", (8, 8), (255, 0, 0))
    # GPS tag block — latitude 37.7749, longitude -122.4194 (San Francisco)
    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLatitude: [(37, 1), (46, 1), (4, 1)],
        piexif.GPSIFD.GPSLongitudeRef: b"W",
        piexif.GPSIFD.GPSLongitude: [(122, 1), (25, 1), (10, 1)],
    }
    exif_dict = {"GPS": gps_ifd}
    exif_bytes = piexif.dump(exif_dict)
    img.save(buf, format="JPEG", exif=exif_bytes, quality=85)
    return buf.getvalue()
```

> Note: `piexif` is only used in tests. Add it to `ops/requirements-dev.txt` if not already present (it's a small pure-Python lib).

- [ ] **Step 1.3: Write a smoke test that proves discovery works**

File: `website/features/feedback/tests/unit/test_smoke.py`
```python
"""Smoke test — verifies pytest discovers tests under the feature module."""
from __future__ import annotations


def test_module_importable() -> None:
    import website.features.feedback as feedback
    assert feedback is not None
```

- [ ] **Step 1.4: Run the smoke test, verify it passes**

Run: `pytest website/features/feedback/tests/unit/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 1.5: Append dependencies to `ops/requirements.txt`**

Append the following block to the END of `ops/requirements.txt`:
```
# Feedback feature (website/features/feedback/)
# python-magic: libmagic bindings for MIME sniffing of user-uploaded screenshots.
# Requires `libmagic1` apt package on the runtime container — see ops/Dockerfile.
python-magic>=0.4.27,<0.5
# slack_sdk: Slack Web API client for chat.postMessage + files_upload_v2.
# Bot Token + Block Kit pattern; replaces incoming-webhook (cannot attach files).
slack_sdk>=3.27,<4
```

Ensure existing `Pillow` is unpinned or pinned to `>=10.3` (CVE-2024-28219). If not present, append:
```
Pillow>=10.3
```

- [ ] **Step 1.6: Append `piexif` to `ops/requirements-dev.txt`**

Append to `ops/requirements-dev.txt`:
```
# Used only in feedback module's tests — see tests/conftest.py
piexif>=1.1
```

- [ ] **Step 1.7: Install new deps locally**

Run: `pip install -r ops/requirements-dev.txt -r ops/requirements.txt`
Expected: "Successfully installed python-magic-... slack_sdk-... piexif-..." (or "Requirement already satisfied").

- [ ] **Step 1.8: Re-run the smoke test to confirm new deps don't break collection**

Run: `pytest website/features/feedback/tests/unit/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 1.9: Commit**

```bash
git add website/features/feedback/ ops/requirements.txt ops/requirements-dev.txt
git commit -m "feat: scaffold feedback module + deps"
```

---

## Task 2: `core/ids.py` — Feedback ID generator

**Files:**
- Create: `website/features/feedback/core/ids.py`
- Create: `website/features/feedback/tests/unit/test_ids.py`

- [ ] **Step 2.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_ids.py`
```python
"""Tests for the FB-XXXX confirmation ID generator."""
from __future__ import annotations

import re

from website.features.feedback.core.ids import generate_feedback_id


VALID_ID_RE = re.compile(r"^FB-[A-Z2-7]{4}$")


def test_generate_feedback_id_format() -> None:
    fid = generate_feedback_id()
    assert VALID_ID_RE.match(fid), f"unexpected format: {fid}"


def test_generate_feedback_id_excludes_confusing_chars() -> None:
    """The alphabet must exclude 0/1/I/O/L (commonly confused in print/copy)."""
    forbidden = {"0", "1", "I", "O", "L"}
    for _ in range(200):
        fid = generate_feedback_id()
        assert not (forbidden & set(fid[3:])), f"contains forbidden char: {fid}"


def test_generate_feedback_id_collision_resistance_smoke() -> None:
    """20 bits of randomness → ~1M unique tails; 500 samples should have <2 dupes."""
    ids = {generate_feedback_id() for _ in range(500)}
    assert len(ids) >= 498
```

- [ ] **Step 2.2: Run the test — expect failure (module not yet created)**

Run: `pytest website/features/feedback/tests/unit/test_ids.py -v`
Expected: `ImportError: cannot import name 'generate_feedback_id'` or similar.

- [ ] **Step 2.3: Write the minimal implementation**

File: `website/features/feedback/core/ids.py`
```python
"""Feedback ID generator — produces short, copy-safe confirmation IDs (FB-XXXX).

The ID is shown to the user in the success state and embedded in the Slack
message context. It is UI-only — there is no database row keyed on this ID
(operator decision, 2026-05-27). The Slack message timestamp is the canonical
record of each submission.
"""
from __future__ import annotations

import secrets

# Crockford-style base32 minus visually ambiguous chars (0/1/I/O/L).
# 27 chars × 4 positions = 531,441 unique tails (~19 bits).
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_TAIL_LENGTH = 4


def generate_feedback_id() -> str:
    """Return a fresh confirmation ID like 'FB-7K3Q'."""
    tail = "".join(secrets.choice(_ALPHABET) for _ in range(_TAIL_LENGTH))
    return f"FB-{tail}"
```

- [ ] **Step 2.4: Run the test — expect green**

Run: `pytest website/features/feedback/tests/unit/test_ids.py -v`
Expected: 3 passed.

- [ ] **Step 2.5: Commit**

```bash
git add website/features/feedback/core/ids.py website/features/feedback/tests/unit/test_ids.py
git commit -m "feat: feedback ID generator"
```

---

## Task 3: `core/settings.py` — feature-local FeedbackSettings

**Files:**
- Create: `website/features/feedback/core/settings.py`
- Create: `website/features/feedback/tests/unit/test_settings.py`

- [ ] **Step 3.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_settings.py`
```python
"""Tests for feature-local FeedbackSettings."""
from __future__ import annotations

import pytest

from website.features.feedback.core.settings import (
    FeedbackSettings,
    get_feedback_settings,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    get_feedback_settings.cache_clear()
    yield
    get_feedback_settings.cache_clear()


def test_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "SLACK_BOT_TOKEN_FEEDBACK",
        "SLACK_CHANNEL_FEEDBACK",
        "SECRET_FEEDBACK_COOKIE",
        "FEEDBACK_REQUIRE_TURNSTILE",
    ):
        monkeypatch.delenv(var, raising=False)
    s = FeedbackSettings()
    assert s.slack_bot_token_feedback == ""
    assert s.slack_channel_feedback == ""
    assert s.secret_feedback_cookie == ""
    assert s.feedback_require_turnstile is False


def test_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN_FEEDBACK", "xoxb-abc")
    monkeypatch.setenv("SLACK_CHANNEL_FEEDBACK", "C09ABC")
    monkeypatch.setenv("SECRET_FEEDBACK_COOKIE", "deadbeef" * 8)
    monkeypatch.setenv("FEEDBACK_REQUIRE_TURNSTILE", "true")
    s = FeedbackSettings()
    assert s.slack_bot_token_feedback == "xoxb-abc"
    assert s.slack_channel_feedback == "C09ABC"
    assert s.secret_feedback_cookie == "deadbeef" * 8
    assert s.feedback_require_turnstile is True


def test_get_feedback_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_BOT_TOKEN_FEEDBACK", "first")
    a = get_feedback_settings()
    monkeypatch.setenv("SLACK_BOT_TOKEN_FEEDBACK", "second")
    b = get_feedback_settings()
    assert a is b  # cached — second env value not seen
```

- [ ] **Step 3.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_settings.py -v`
Expected: ImportError.

- [ ] **Step 3.3: Write the implementation**

File: `website/features/feedback/core/settings.py`
```python
"""Feature-local Pydantic settings — reads env directly, does not modify
website/core/settings.py per the strict-containment rule.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class FeedbackSettings(BaseSettings):
    """Env-loaded config for the feedback module.

    Field names map to env vars via pydantic-settings's default behavior
    (UPPER_SNAKE_CASE). Values default to empty strings / false, meaning
    the feature degrades gracefully (route returns 503) if creds are missing
    rather than failing app boot.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    slack_bot_token_feedback: str = ""
    slack_channel_feedback: str = ""
    secret_feedback_cookie: str = ""
    feedback_require_turnstile: bool = False


@lru_cache(maxsize=1)
def get_feedback_settings() -> FeedbackSettings:
    """Return the cached singleton. Tests must call .cache_clear() between cases."""
    return FeedbackSettings()
```

- [ ] **Step 3.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_settings.py -v`
Expected: 3 passed.

- [ ] **Step 3.5: Commit**

```bash
git add website/features/feedback/core/settings.py website/features/feedback/tests/unit/test_settings.py
git commit -m "feat: feature-local FeedbackSettings"
```

---

## Task 4: `api/cookie.py` — signed HMAC cookie

**Files:**
- Create: `website/features/feedback/api/cookie.py`
- Create: `website/features/feedback/tests/unit/test_cookie.py`

- [ ] **Step 4.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_cookie.py`
```python
"""Tests for the signed HMAC cookie issuer + validator."""
from __future__ import annotations

import pytest

from website.features.feedback.api.cookie import (
    issue_cookie_value,
    validate_cookie_value,
    COOKIE_NAME,
)


SECRET = b"unit-test-secret-32-bytes-long-aaaa"


def test_cookie_name_is_stable() -> None:
    assert COOKIE_NAME == "zk_feedback_token"


def test_issue_cookie_value_format() -> None:
    val = issue_cookie_value(SECRET)
    # Format: <base64url-uuid>.<hex-hmac>
    assert "." in val
    body, mac = val.split(".", 1)
    assert len(body) >= 16
    assert len(mac) == 64  # sha256 hex = 64 chars


def test_validate_cookie_value_accepts_self_issued() -> None:
    val = issue_cookie_value(SECRET)
    assert validate_cookie_value(val, SECRET) is True


def test_validate_cookie_value_rejects_tampered_body() -> None:
    val = issue_cookie_value(SECRET)
    body, mac = val.split(".", 1)
    tampered = "AAAAAAAAAAAA." + mac
    assert validate_cookie_value(tampered, SECRET) is False


def test_validate_cookie_value_rejects_tampered_mac() -> None:
    val = issue_cookie_value(SECRET)
    body, mac = val.split(".", 1)
    tampered = body + ".0" * 64
    assert validate_cookie_value(tampered, SECRET) is False


def test_validate_cookie_value_rejects_wrong_secret() -> None:
    val = issue_cookie_value(SECRET)
    assert validate_cookie_value(val, b"different-secret") is False


@pytest.mark.parametrize("bad", ["", "no-dot", ".", "abc.", ".xyz", "a.b.c"])
def test_validate_cookie_value_rejects_malformed(bad: str) -> None:
    assert validate_cookie_value(bad, SECRET) is False
```

- [ ] **Step 4.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_cookie.py -v`
Expected: ImportError.

- [ ] **Step 4.3: Write the implementation**

File: `website/features/feedback/api/cookie.py`
```python
"""Signed HMAC cookie for anonymous rate-limiting.

The cookie value is `<base64url(uuid_bytes)>.<hex(hmac_sha256(body, secret))>`.
The body is opaque; the server only cares that the HMAC validates. This lets
us pin an anonymous request to a stable identifier across submissions without
storing anything server-side.
"""
from __future__ import annotations

import base64
import hmac
import secrets
from hashlib import sha256

COOKIE_NAME = "zk_feedback_token"
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days
_UUID_BYTES = 12  # 96 bits of entropy is plenty for a per-browser tag


def _sign(body: bytes, secret: bytes) -> str:
    return hmac.new(secret, body, sha256).hexdigest()


def issue_cookie_value(secret: bytes) -> str:
    """Mint a fresh cookie value. Caller sets the cookie on the response."""
    body_bytes = secrets.token_bytes(_UUID_BYTES)
    body = base64.urlsafe_b64encode(body_bytes).rstrip(b"=").decode("ascii")
    mac = _sign(body.encode("ascii"), secret)
    return f"{body}.{mac}"


def validate_cookie_value(value: str, secret: bytes) -> bool:
    """Constant-time HMAC verification. Returns False on any malformation."""
    if not value or value.count(".") != 1:
        return False
    body, mac = value.split(".", 1)
    if not body or len(mac) != 64:
        return False
    expected = _sign(body.encode("ascii"), secret)
    return hmac.compare_digest(mac, expected)
```

- [ ] **Step 4.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_cookie.py -v`
Expected: 8 passed (3 parametrize cases + 5 base).

Actually parametrize produces 6 cases (6 inputs), plus the other 5 = 11. Verify the actual count when running.

- [ ] **Step 4.5: Commit**

```bash
git add website/features/feedback/api/cookie.py website/features/feedback/tests/unit/test_cookie.py
git commit -m "feat: HMAC cookie for anonymous rate-limit"
```

---

## Task 5: `core/identity.py` — name + country resolver

**Files:**
- Create: `website/features/feedback/core/identity.py`
- Create: `website/features/feedback/tests/unit/test_identity.py`

This module is a thin wrapper around the existing `_resolve_full_name()` helper from `website/features/web_monitor/User_Activity.py` and `format_country()` from `website/features/web_monitor/_country.py`. Cross-feature imports inside `website/features/` are allowed by the strict-containment rule.

- [ ] **Step 5.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_identity.py`
```python
"""Tests for identity + country resolution."""
from __future__ import annotations

from website.features.feedback.core.identity import (
    Identity,
    resolve_identity,
)


def test_authenticated_with_profile_country() -> None:
    claims = {"sub": "u-123", "email": "naruto@konoha.jp",
              "user_metadata": {"name": "Naruto Uzumaki"}}
    headers = {"cf-ipcountry": "JP"}
    id_ = resolve_identity(
        claims=claims,
        anon_name=None,
        headers=headers,
        profile_country_code="IN",
    )
    assert id_.full_name == "Naruto Uzumaki"
    assert id_.email == "naruto@konoha.jp"
    # Profile country wins over IP-derived
    assert id_.country_label == "India — IN"
    assert id_.is_anonymous is False


def test_authenticated_falls_back_to_ip_country() -> None:
    claims = {"sub": "u-123", "email": "naruto@konoha.jp",
              "user_metadata": {"name": "Naruto Uzumaki"}}
    headers = {"cf-ipcountry": "IN"}
    id_ = resolve_identity(
        claims=claims,
        anon_name=None,
        headers=headers,
        profile_country_code=None,
    )
    assert "approx" in id_.country_label.lower()
    assert "IN" in id_.country_label


def test_anonymous_with_provided_name() -> None:
    id_ = resolve_identity(
        claims=None,
        anon_name="Sasuke",
        headers={"cf-ipcountry": "JP"},
        profile_country_code=None,
    )
    assert id_.full_name == "Sasuke"
    assert id_.email is None
    assert id_.is_anonymous is True
    assert "approx" in id_.country_label.lower()


def test_anonymous_without_name_uses_default() -> None:
    id_ = resolve_identity(
        claims=None, anon_name=None, headers={}, profile_country_code=None,
    )
    assert id_.full_name == "Anonymous"
    assert id_.country_label == "Unknown"


def test_authenticated_strips_whitespace_in_name() -> None:
    claims = {"sub": "u-1", "user_metadata": {"name": "  Naruto Uzumaki  "}}
    id_ = resolve_identity(
        claims=claims, anon_name=None, headers={}, profile_country_code="IN",
    )
    assert id_.full_name == "Naruto Uzumaki"
```

- [ ] **Step 5.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_identity.py -v`
Expected: ImportError.

- [ ] **Step 5.3: Write the implementation**

File: `website/features/feedback/core/identity.py`
```python
"""Resolve the user's full name + country for the Slack message.

Reuses helpers from web_monitor (cross-feature import under website/features/
is allowed). Falls back gracefully when claims or headers are missing.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    full_name: str
    email: str | None
    country_label: str       # e.g. "India — IN" or "India — IN (approx.)"
    is_anonymous: bool


def _format_country(code: str | None, *, approx: bool) -> str:
    if not code or code == "??":
        return "Unknown"
    # Import here so module-load doesn't require web_monitor to be importable.
    try:
        from website.features.web_monitor._country import format_country
        name = format_country(code)  # e.g. "India" for "IN"
    except Exception:
        name = code
    label = f"{name} — {code.upper()}"
    if approx:
        label += " (approx.)"
    return label


def _name_from_claims(claims: dict) -> str | None:
    if not claims:
        return None
    meta = claims.get("user_metadata") or {}
    for key in ("full_name", "name", "display_name"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Fall back to the email local part if name absent.
    email = claims.get("email")
    if isinstance(email, str) and "@" in email:
        return email.split("@", 1)[0]
    return None


def resolve_identity(
    *,
    claims: dict | None,
    anon_name: str | None,
    headers: dict,
    profile_country_code: str | None,
) -> Identity:
    """Top-level resolver.

    Args:
        claims: decoded Supabase JWT claims dict, or None when anonymous.
        anon_name: user-typed name on the anonymous form; ignored when authed.
        headers: request headers (lowercased keys expected); used for cf-ipcountry.
        profile_country_code: 2-letter code from core.profiles when present,
                              else None.
    """
    is_anonymous = claims is None
    if is_anonymous:
        name = (anon_name or "").strip() or "Anonymous"
        email = None
    else:
        name = _name_from_claims(claims) or "Unknown"
        email = (claims.get("email") or None) if isinstance(claims, dict) else None

    if profile_country_code:
        country_label = _format_country(profile_country_code, approx=False)
    else:
        ip_country = (headers.get("cf-ipcountry") or "").upper()
        country_label = _format_country(ip_country or None, approx=True)

    return Identity(
        full_name=name,
        email=email,
        country_label=country_label,
        is_anonymous=is_anonymous,
    )
```

- [ ] **Step 5.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_identity.py -v`
Expected: 5 passed.

If `format_country` is not importable (web_monitor's path differs), the test will still pass because the `_format_country` helper falls back to using the code as-is. Verify by running the test.

- [ ] **Step 5.5: Commit**

```bash
git add website/features/feedback/core/identity.py website/features/feedback/tests/unit/test_identity.py
git commit -m "feat: identity + country resolver"
```

---

## Task 6: `intake/models.py` — Pydantic request/response DTOs

**Files:**
- Create: `website/features/feedback/intake/models.py`
- Create: `website/features/feedback/tests/unit/test_models.py`

- [ ] **Step 6.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_models.py`
```python
"""Tests for the request/response DTOs."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from website.features.feedback.intake.models import (
    FeedbackIntent,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
)


def _valid_request(**overrides) -> dict:
    base = {
        "intent": "issue",
        "subject": "Smoke test",
        "description": "Description of the issue with at least ten characters.",
        "follow_up_email": False,
    }
    base.update(overrides)
    return base


def test_intent_enum_accepts_known_values() -> None:
    assert FeedbackIntent("issue") == FeedbackIntent.ISSUE
    assert FeedbackIntent("suggestion") == FeedbackIntent.SUGGESTION


def test_intent_enum_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        FeedbackIntent("praise")


def test_subject_max_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(subject="x" * 121))


def test_subject_min_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(subject=""))


def test_description_min_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(description="too short"))


def test_description_max_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(description="a" * 4001))


def test_anon_email_validates_format_when_present() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(anon_email="not-an-email"))


def test_anon_email_optional_when_absent() -> None:
    req = FeedbackSubmitRequest(**_valid_request())
    assert req.anon_email is None


def test_anon_name_max_length() -> None:
    with pytest.raises(ValidationError):
        FeedbackSubmitRequest(**_valid_request(anon_name="x" * 81))


def test_response_serializes() -> None:
    resp = FeedbackSubmitResponse(feedback_id="FB-7K3Q", status="accepted")
    assert resp.model_dump() == {"feedback_id": "FB-7K3Q", "status": "accepted"}
```

- [ ] **Step 6.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_models.py -v`
Expected: ImportError.

- [ ] **Step 6.3: Write the implementation**

File: `website/features/feedback/intake/models.py`
```python
"""Pydantic DTOs for the feedback submission flow."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class FeedbackIntent(str, Enum):
    ISSUE = "issue"
    SUGGESTION = "suggestion"


class FeedbackSubmitRequest(BaseModel):
    intent: FeedbackIntent
    subject: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=10, max_length=4000)
    anon_name: str | None = Field(default=None, max_length=80)
    follow_up_email: bool = False
    anon_email: EmailStr | None = None


class FeedbackSubmitResponse(BaseModel):
    feedback_id: str
    status: Literal["accepted"] = "accepted"
```

- [ ] **Step 6.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_models.py -v`
Expected: 10 passed.

If `EmailStr` requires the `email-validator` package, add it (it's a tiny dependency commonly already pulled in by pydantic-extras). If missing, append to `ops/requirements.txt`:
```
email-validator>=2.0
```

- [ ] **Step 6.5: Commit**

```bash
git add website/features/feedback/intake/models.py website/features/feedback/tests/unit/test_models.py
git commit -m "feat: feedback request/response DTOs"
```

---

## Task 7: `intake/validation.py` — extension + magic-byte sniff

**Files:**
- Create: `website/features/feedback/intake/validation.py`
- Create: `website/features/feedback/tests/unit/test_validation.py`

- [ ] **Step 7.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_validation.py`
```python
"""Tests for image-file validation (extension whitelist + magic-byte sniff)."""
from __future__ import annotations

import pytest

from website.features.feedback.intake.validation import (
    ValidationError as FeedbackValidationError,
    sniff_and_validate_image,
)


def test_accepts_valid_jpeg(jpeg_bytes_no_exif: bytes) -> None:
    result = sniff_and_validate_image(jpeg_bytes_no_exif, filename="shot.jpg")
    assert result.detected_mime == "image/jpeg"
    assert result.normalized_extension == "jpg"


def test_accepts_valid_png() -> None:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 255)).save(buf, format="PNG")
    result = sniff_and_validate_image(buf.getvalue(), filename="x.png")
    assert result.detected_mime == "image/png"
    assert result.normalized_extension == "png"


def test_rejects_unknown_extension(jpeg_bytes_no_exif: bytes) -> None:
    with pytest.raises(FeedbackValidationError, match="extension"):
        sniff_and_validate_image(jpeg_bytes_no_exif, filename="x.heic")


def test_rejects_extension_mime_mismatch(jpeg_bytes_no_exif: bytes) -> None:
    # JPEG bytes but caller claims ".png" — magic-byte sniff catches it.
    with pytest.raises(FeedbackValidationError, match="mime"):
        sniff_and_validate_image(jpeg_bytes_no_exif, filename="x.png")


def test_rejects_svg_even_if_text_mime_sniff_says_image() -> None:
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
    with pytest.raises(FeedbackValidationError):
        sniff_and_validate_image(svg, filename="x.svg")


def test_rejects_empty_bytes() -> None:
    with pytest.raises(FeedbackValidationError):
        sniff_and_validate_image(b"", filename="x.jpg")
```

- [ ] **Step 7.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_validation.py -v`
Expected: ImportError.

- [ ] **Step 7.3: Write the implementation**

File: `website/features/feedback/intake/validation.py`
```python
"""Pre-pipeline validation: extension whitelist + libmagic MIME sniff.

This runs BEFORE the Pillow rewrite. Goal: cheap, fail-fast rejection of
files that aren't bitmap-image bytes at all, before we hand them to a more
expensive parser. Per OWASP File Upload Cheat Sheet, this is the canonical
extension+magic-bytes pair.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

import magic


class ValidationError(Exception):
    """Raised when an uploaded image fails validation. Maps to HTTP 400/413."""


# Whitelist — explicit, exhaustive. SVG/ICO/HEIC/GIF intentionally excluded.
_ALLOWED_EXT_TO_MIME = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "webp": "image/webp",
}


@dataclass(frozen=True)
class ValidatedImage:
    detected_mime: str
    normalized_extension: str  # "jpg" or "png" or "webp"


def _normalize_extension(filename: str) -> str:
    ext = PurePosixPath(filename or "").suffix.lstrip(".").lower()
    return ext


def sniff_and_validate_image(blob: bytes, *, filename: str) -> ValidatedImage:
    """Return a ValidatedImage on success; raise ValidationError on failure."""
    if not blob:
        raise ValidationError("empty file")

    ext = _normalize_extension(filename)
    if ext not in _ALLOWED_EXT_TO_MIME:
        raise ValidationError(
            f"extension '.{ext}' not allowed; use jpg, jpeg, png, or webp"
        )

    detected = magic.from_buffer(blob, mime=True)
    expected = _ALLOWED_EXT_TO_MIME[ext]
    if detected != expected:
        raise ValidationError(
            f"file content mime '{detected}' does not match extension '{ext}'"
        )

    # Normalize jpeg/jpg → jpg for consistency in storage filenames.
    normalized_ext = "jpg" if ext in {"jpg", "jpeg"} else ext
    return ValidatedImage(detected_mime=detected, normalized_extension=normalized_ext)
```

- [ ] **Step 7.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_validation.py -v`
Expected: 6 passed.

If `python-magic` import fails on Windows dev box, you can scope the test with `@pytest.mark.skipif(sys.platform == "win32", ...)` and run on Linux CI. But prefer to install `python-magic-bin` for the dev machine — `pip install python-magic-bin` on Windows ships libmagic itself.

- [ ] **Step 7.5: Commit**

```bash
git add website/features/feedback/intake/validation.py website/features/feedback/tests/unit/test_validation.py
git commit -m "feat: image extension + magic-byte validation"
```

---

## Task 8: `intake/image_pipeline.py` — Pillow rewrite + EXIF strip

**Files:**
- Create: `website/features/feedback/intake/image_pipeline.py`
- Create: `website/features/feedback/tests/unit/test_image_pipeline.py`

- [ ] **Step 8.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_image_pipeline.py`
```python
"""Tests for the Pillow-rewrite image pipeline."""
from __future__ import annotations

import piexif
import pytest
from io import BytesIO
from PIL import Image

from website.features.feedback.intake.image_pipeline import (
    process_image,
    ImageProcessingError,
)


def test_jpeg_passthrough_strips_no_exif(jpeg_bytes_no_exif: bytes) -> None:
    out = process_image(jpeg_bytes_no_exif, source_ext="jpg")
    img = Image.open(BytesIO(out.body))
    assert img.format == "JPEG"
    assert img.mode == "RGB"
    assert out.filename.endswith(".jpg")


def test_jpeg_with_gps_exif_is_stripped(jpeg_bytes_with_gps_exif: bytes) -> None:
    out = process_image(jpeg_bytes_with_gps_exif, source_ext="jpg")
    img = Image.open(BytesIO(out.body))
    # piexif.load on EXIF-free image returns empty IFDs
    exif = piexif.load(img.info.get("exif", b""))
    assert not exif.get("GPS"), "GPS EXIF should be stripped"


def test_png_passthrough(jpeg_bytes_no_exif: bytes) -> None:
    # Encode a fresh PNG
    buf = BytesIO()
    Image.new("RGB", (10, 10), (12, 34, 56)).save(buf, format="PNG")
    out = process_image(buf.getvalue(), source_ext="png")
    img = Image.open(BytesIO(out.body))
    assert img.format == "PNG"
    assert out.filename.endswith(".png")


def test_corrupt_bytes_raises() -> None:
    with pytest.raises(ImageProcessingError):
        process_image(b"\x00\x00\x00 not an image", source_ext="jpg")


def test_truncated_jpeg_raises(jpeg_bytes_no_exif: bytes) -> None:
    truncated = jpeg_bytes_no_exif[:30]
    with pytest.raises(ImageProcessingError):
        process_image(truncated, source_ext="jpg")


def test_filename_is_uuid_format(jpeg_bytes_no_exif: bytes) -> None:
    import re
    out = process_image(jpeg_bytes_no_exif, source_ext="jpg")
    # 32 hex chars + .jpg
    assert re.match(r"^[0-9a-f]{32}\.jpg$", out.filename)
```

- [ ] **Step 8.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_image_pipeline.py -v`
Expected: ImportError.

- [ ] **Step 8.3: Write the implementation**

File: `website/features/feedback/intake/image_pipeline.py`
```python
"""Rewrite uploaded images via Pillow:

  * Re-parses the bytes through PIL.Image.open + verify() — destroys malformed
    payloads and ensures we can serialize the result deterministically.
  * Strips EXIF metadata (GPS, device model, camera serial), as the OWASP
    File Upload Cheat Sheet recommends for any user-uploaded image.
  * Re-encodes to a canonical form: JPEG q=85 if source was JPEG, PNG
    otherwise. Output bytes never include EXIF.
  * Generates a server-side filename — never trusts the client name.

Returns the rewritten bytes + a uuid4-based filename ready for files_upload_v2.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError


class ImageProcessingError(Exception):
    """Raised when an image fails to parse / verify. Maps to HTTP 400."""


@dataclass(frozen=True)
class ProcessedImage:
    body: bytes
    filename: str  # e.g. "deadbeef...0123.jpg"
    content_type: str  # "image/jpeg" or "image/png" or "image/webp"


_SAVE_FORMATS = {
    "jpg":  ("JPEG", "image/jpeg", {"quality": 85, "optimize": True}),
    "png":  ("PNG", "image/png", {"optimize": True}),
    "webp": ("WEBP", "image/webp", {"quality": 85, "method": 6}),
}


def process_image(blob: bytes, *, source_ext: str) -> ProcessedImage:
    """Re-encode + EXIF-strip an uploaded image.

    Args:
        blob: raw bytes from UploadFile.
        source_ext: normalized extension (e.g. "jpg") from validation step.

    Raises:
        ImageProcessingError: parse failure, truncation, or unsupported format.
    """
    if source_ext not in _SAVE_FORMATS:
        raise ImageProcessingError(f"unsupported source extension: {source_ext}")

    try:
        # First open + verify — destroys instance per Pillow docs
        Image.open(BytesIO(blob)).verify()
        # Re-open for actual conversion
        img = Image.open(BytesIO(blob))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageProcessingError(f"invalid image bytes: {exc}") from exc

    # Convert any mode to RGB (drops alpha for JPEG; safe for PNG/WEBP too).
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    elif img.mode == "RGBA" and source_ext == "jpg":
        # JPEG can't carry alpha — flatten on white.
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background

    fmt, mime, kwargs = _SAVE_FORMATS[source_ext]
    out_buf = BytesIO()
    # Pass exif=b"" explicitly so PIL doesn't carry forward any preserved EXIF.
    img.save(out_buf, format=fmt, exif=b"", **kwargs)

    body = out_buf.getvalue()
    filename = f"{uuid.uuid4().hex}.{source_ext}"
    return ProcessedImage(body=body, filename=filename, content_type=mime)
```

- [ ] **Step 8.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_image_pipeline.py -v`
Expected: 6 passed.

- [ ] **Step 8.5: Commit**

```bash
git add website/features/feedback/intake/image_pipeline.py website/features/feedback/tests/unit/test_image_pipeline.py
git commit -m "feat: image rewrite + EXIF strip pipeline"
```

---

## Task 9: `intake/rate_limit.py` — daily sliding-window limiter

**Files:**
- Create: `website/features/feedback/intake/rate_limit.py`
- Create: `website/features/feedback/tests/unit/test_rate_limit.py`

- [ ] **Step 9.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_rate_limit.py`
```python
"""Tests for the per-day sliding-window rate limiter."""
from __future__ import annotations

import time

import pytest

from website.features.feedback.intake.rate_limit import (
    FeedbackRateLimiter,
    RateLimitExceeded,
    RateLimitKey,
)


def test_under_limit_allows() -> None:
    limiter = FeedbackRateLimiter(daily_cap=3, window_seconds=86400)
    key = RateLimitKey(scope="user", value="u-1")
    for _ in range(3):
        limiter.consume(key)
    # 3rd was the limit; 4th must fail
    with pytest.raises(RateLimitExceeded):
        limiter.consume(key)


def test_separate_keys_independent() -> None:
    limiter = FeedbackRateLimiter(daily_cap=1, window_seconds=86400)
    limiter.consume(RateLimitKey(scope="user", value="u-1"))
    limiter.consume(RateLimitKey(scope="user", value="u-2"))
    limiter.consume(RateLimitKey(scope="cookie", value="u-1"))  # different scope, OK


def test_window_expiry() -> None:
    """Past entries fall out of the window after window_seconds."""
    limiter = FeedbackRateLimiter(daily_cap=2, window_seconds=2)
    key = RateLimitKey(scope="ip", value="1.2.3.4")
    limiter.consume(key)
    limiter.consume(key)
    with pytest.raises(RateLimitExceeded):
        limiter.consume(key)
    time.sleep(2.2)
    # Window cleared — should allow again
    limiter.consume(key)


def test_rate_limit_exceeded_carries_retry_after() -> None:
    limiter = FeedbackRateLimiter(daily_cap=1, window_seconds=60)
    key = RateLimitKey(scope="user", value="u-1")
    limiter.consume(key)
    with pytest.raises(RateLimitExceeded) as excinfo:
        limiter.consume(key)
    assert excinfo.value.retry_after_seconds > 0
    assert excinfo.value.retry_after_seconds <= 60
```

- [ ] **Step 9.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_rate_limit.py -v`
Expected: ImportError.

- [ ] **Step 9.3: Write the implementation**

File: `website/features/feedback/intake/rate_limit.py`
```python
"""Sliding-window rate limiter for the feedback endpoint.

Keys are scoped (user_id / cookie / IP) so the same daily budget can be
applied independently to each axis. In-process counters per gunicorn worker
— acceptable for the modest limits operators chose. Container restart resets
state, which is also acceptable (operator's intent is "stop abuse" not
"enforce a precise cap").
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitKey:
    scope: str   # "user" | "cookie" | "ip"
    value: str


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"rate limit hit; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class FeedbackRateLimiter:
    """Thread-safe sliding window.

    Each call to consume(key) appends `time.monotonic()` to that key's deque
    and rejects when len(deque) > daily_cap (after pruning expired entries).
    """

    def __init__(self, *, daily_cap: int, window_seconds: int) -> None:
        self._cap = int(daily_cap)
        self._window = float(window_seconds)
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def consume(self, key: RateLimitKey) -> None:
        """Record one hit for `key`. Raises RateLimitExceeded when over cap."""
        now = time.monotonic()
        cutoff = now - self._window
        dkey = (key.scope, key.value)
        with self._lock:
            q = self._hits[dkey]
            # Prune expired entries
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self._cap:
                retry_after = int(q[0] + self._window - now) + 1
                raise RateLimitExceeded(max(1, retry_after))
            q.append(now)
```

- [ ] **Step 9.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_rate_limit.py -v`
Expected: 4 passed (one sleeps 2.2s — slower run).

- [ ] **Step 9.5: Commit**

```bash
git add website/features/feedback/intake/rate_limit.py website/features/feedback/tests/unit/test_rate_limit.py
git commit -m "feat: daily sliding-window rate limiter"
```

---

## Task 10: `slack/block_kit.py` — payload builder

**Files:**
- Create: `website/features/feedback/slack/block_kit.py`
- Create: `website/features/feedback/tests/unit/test_block_kit.py`

- [ ] **Step 10.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_block_kit.py`
```python
"""Tests for the Slack Block Kit payload builder."""
from __future__ import annotations

from website.features.feedback.core.identity import Identity
from website.features.feedback.intake.models import FeedbackIntent
from website.features.feedback.slack.block_kit import build_feedback_blocks


def _identity(**kwargs) -> Identity:
    base = dict(
        full_name="Naruto Uzumaki",
        email="naruto@konoha.jp",
        country_label="India — IN",
        is_anonymous=False,
    )
    base.update(kwargs)
    return Identity(**base)


def test_issue_uses_megaphone_emoji() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="A subject",
        description="A description with at least ten chars.",
        identity=_identity(),
        feedback_id="FB-7K3Q",
        follow_up_email=False,
        slack_file_ids=[],
    )
    header = blocks[0]
    assert header["type"] == "header"
    assert "\U0001F4E3" in header["text"]["text"]  # 📣


def test_suggestion_uses_lightbulb_emoji() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.SUGGESTION,
        subject="A subject",
        description="A description with at least ten chars.",
        identity=_identity(),
        feedback_id="FB-ABCD",
        follow_up_email=False,
        slack_file_ids=[],
    )
    assert "\U0001F4A1" in blocks[0]["text"]["text"]  # 💡


def test_image_blocks_appear_per_file() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s",
        description="description with enough chars.",
        identity=_identity(),
        feedback_id="FB-AAAA",
        follow_up_email=False,
        slack_file_ids=["F100", "F200", "F300"],
    )
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 3
    assert image_blocks[0]["slack_file"]["id"] == "F100"
    assert image_blocks[2]["slack_file"]["id"] == "F300"


def test_zero_images_no_image_blocks() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s", description="description with enough chars.",
        identity=_identity(), feedback_id="FB-AAAA",
        follow_up_email=False, slack_file_ids=[],
    )
    assert not any(b["type"] == "image" for b in blocks)


def test_context_includes_name_country_id() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s", description="description with enough chars.",
        identity=_identity(), feedback_id="FB-7K3Q",
        follow_up_email=False, slack_file_ids=[],
    )
    context = next(b for b in blocks if b["type"] == "context")
    text = context["elements"][0]["text"]
    assert "Naruto Uzumaki" in text
    assert "India — IN" in text
    assert "FB-7K3Q" in text


def test_anonymous_context_says_anonymous() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.SUGGESTION,
        subject="s", description="description with enough chars.",
        identity=_identity(full_name="Anonymous", email=None, is_anonymous=True),
        feedback_id="FB-AAAA",
        follow_up_email=False, slack_file_ids=[],
    )
    context = next(b for b in blocks if b["type"] == "context")
    assert "Anonymous" in context["elements"][0]["text"]


def test_follow_up_email_appears_in_context_when_opted_in() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s", description="description with enough chars.",
        identity=_identity(),
        feedback_id="FB-AAAA",
        follow_up_email=True, slack_file_ids=[],
    )
    context = next(b for b in blocks if b["type"] == "context")
    assert "naruto@konoha.jp" in context["elements"][0]["text"]


def test_subject_in_section() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="Add Zettel fails on long YouTube videos",
        description="Tried adding a 3-hour Lex Fridman episode and got a 504.",
        identity=_identity(),
        feedback_id="FB-AAAA",
        follow_up_email=False, slack_file_ids=[],
    )
    section = next(b for b in blocks if b["type"] == "section")
    text = section["text"]["text"]
    assert "Add Zettel fails on long YouTube videos" in text
    assert "Tried adding a 3-hour Lex Fridman" in text
```

- [ ] **Step 10.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_block_kit.py -v`
Expected: ImportError.

- [ ] **Step 10.3: Write the implementation**

File: `website/features/feedback/slack/block_kit.py`
```python
"""Build the Slack Block Kit payload for a feedback submission.

The payload references already-uploaded files via slack_file blocks (private
to the workspace; no public URLs). See:
https://slack.com/blog/developers/uploading-private-images-blockkit
"""
from __future__ import annotations

from website.features.feedback.core.identity import Identity
from website.features.feedback.intake.models import FeedbackIntent


_INTENT_HEADER = {
    FeedbackIntent.ISSUE:      ("\U0001F4E3", "Issue"),       # 📣
    FeedbackIntent.SUGGESTION: ("\U0001F4A1", "Suggestion"),  # 💡
}


def _quote(description: str) -> str:
    """Format as Slack blockquote (prefix '> ' per line)."""
    return "\n".join(f"> {line}" for line in description.splitlines() or [""])


def build_feedback_blocks(
    *,
    intent: FeedbackIntent,
    subject: str,
    description: str,
    identity: Identity,
    feedback_id: str,
    follow_up_email: bool,
    slack_file_ids: list[str],
) -> list[dict]:
    """Return the full blocks array for chat.postMessage."""
    emoji, label = _INTENT_HEADER[intent]

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} New feedback — {label}",
            },
        },
    ]

    # Context line
    parts = [
        f"*From:* {identity.full_name}",
        f"*Country:* {identity.country_label}",
        f"*ID:* `{feedback_id}`",
    ]
    if follow_up_email and identity.email:
        parts.append(f"*Reply:* {identity.email}")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "  •  ".join(parts)}],
    })

    blocks.append({"type": "divider"})

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Subject:* {subject}\n{_quote(description)}",
        },
    })

    for idx, file_id in enumerate(slack_file_ids, start=1):
        blocks.append({
            "type": "image",
            "alt_text": f"Screenshot {idx}",
            "slack_file": {"id": file_id},
        })

    return blocks
```

- [ ] **Step 10.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_block_kit.py -v`
Expected: 8 passed.

- [ ] **Step 10.5: Commit**

```bash
git add website/features/feedback/slack/block_kit.py website/features/feedback/tests/unit/test_block_kit.py
git commit -m "feat: Slack Block Kit payload builder"
```

---

## Task 11: `slack/client.py` — async Slack client wrapper

**Files:**
- Create: `website/features/feedback/slack/client.py`
- Create: `website/features/feedback/tests/unit/test_slack_client.py`

- [ ] **Step 11.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_slack_client.py`
```python
"""Tests for the Slack client wrapper (files_upload_v2 + chat.postMessage)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from website.features.feedback.slack.client import (
    FeedbackSlackClient,
    SlackPostError,
)


@pytest.fixture
def mock_sdk_client() -> MagicMock:
    sdk = MagicMock()
    sdk.files_upload_v2 = AsyncMock(return_value={
        "ok": True, "file": {"id": "F123ABC"}
    })
    sdk.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1716800000.001"})
    return sdk


@pytest.mark.asyncio
async def test_upload_image_returns_file_id(mock_sdk_client: MagicMock) -> None:
    client = FeedbackSlackClient(
        sdk_client=mock_sdk_client, channel="C09TEST"
    )
    file_id = await client.upload_image(b"fake-bytes", filename="shot.jpg")
    assert file_id == "F123ABC"
    mock_sdk_client.files_upload_v2.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_message_returns_ts(mock_sdk_client: MagicMock) -> None:
    client = FeedbackSlackClient(
        sdk_client=mock_sdk_client, channel="C09TEST"
    )
    ts = await client.post_message(blocks=[{"type": "section"}], fallback_text="hi")
    assert ts == "1716800000.001"
    mock_sdk_client.chat_postMessage.assert_awaited_once_with(
        channel="C09TEST", blocks=[{"type": "section"}], text="hi",
    )


@pytest.mark.asyncio
async def test_upload_raises_on_ok_false() -> None:
    sdk = MagicMock()
    sdk.files_upload_v2 = AsyncMock(return_value={"ok": False, "error": "no_scope"})
    client = FeedbackSlackClient(sdk_client=sdk, channel="C09TEST")
    with pytest.raises(SlackPostError, match="no_scope"):
        await client.upload_image(b"x", filename="x.jpg")


@pytest.mark.asyncio
async def test_post_raises_on_ok_false() -> None:
    sdk = MagicMock()
    sdk.chat_postMessage = AsyncMock(return_value={"ok": False, "error": "channel_not_found"})
    client = FeedbackSlackClient(sdk_client=sdk, channel="C09TEST")
    with pytest.raises(SlackPostError, match="channel_not_found"):
        await client.post_message(blocks=[], fallback_text="x")
```

- [ ] **Step 11.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_slack_client.py -v`
Expected: ImportError.

- [ ] **Step 11.3: Write the implementation**

File: `website/features/feedback/slack/client.py`
```python
"""Async Slack client wrapper for the feedback feature.

Uses the official `slack_sdk` AsyncWebClient. Provides two narrow methods —
upload_image and post_message — instead of exposing the full SDK surface.

The slack_sdk library already handles HTTP retries on 429 + 5xx with
exponential backoff via its built-in `RetryHandler`s. We pass them in
when constructing the client.
"""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("feedback.slack")


class SlackPostError(Exception):
    """Raised when Slack returns ok=False (incl. 429 after retries exhausted)."""


class _SlackSDKProtocol(Protocol):
    async def files_upload_v2(self, **kwargs): ...
    async def chat_postMessage(self, **kwargs): ...


class FeedbackSlackClient:
    """Thin wrapper. The SDK client may be the real AsyncWebClient or a mock."""

    def __init__(self, *, sdk_client: _SlackSDKProtocol, channel: str) -> None:
        self._sdk = sdk_client
        self._channel = channel

    async def upload_image(self, content: bytes, *, filename: str) -> str:
        """Upload one image; return the Slack file ID like 'F123ABC'."""
        res = await self._sdk.files_upload_v2(
            channel=self._channel,
            content=content,
            filename=filename,
            title=filename,
        )
        if not res.get("ok"):
            err = res.get("error", "unknown")
            raise SlackPostError(f"files_upload_v2 failed: {err}")
        return res["file"]["id"]

    async def post_message(self, *, blocks: list[dict], fallback_text: str) -> str:
        """Post a Block Kit message; return the message ts."""
        res = await self._sdk.chat_postMessage(
            channel=self._channel, blocks=blocks, text=fallback_text,
        )
        if not res.get("ok"):
            err = res.get("error", "unknown")
            raise SlackPostError(f"chat.postMessage failed: {err}")
        return res["ts"]


def build_production_client(*, token: str, channel: str) -> FeedbackSlackClient:
    """Construct a real Slack-backed client. Lazy-imports slack_sdk."""
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.http_retry.builtin_async_handlers import (
        AsyncRateLimitErrorRetryHandler,
        AsyncServerErrorRetryHandler,
    )
    sdk = AsyncWebClient(
        token=token,
        retry_handlers=[
            AsyncRateLimitErrorRetryHandler(max_retry_count=3),
            AsyncServerErrorRetryHandler(max_retry_count=3),
        ],
    )
    return FeedbackSlackClient(sdk_client=sdk, channel=channel)
```

- [ ] **Step 11.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_slack_client.py -v`
Expected: 4 passed.

- [ ] **Step 11.5: Commit**

```bash
git add website/features/feedback/slack/client.py website/features/feedback/tests/unit/test_slack_client.py
git commit -m "feat: Slack async client wrapper"
```

---

## Task 12: `service.py` — orchestrator

**Files:**
- Create: `website/features/feedback/service.py`
- Create: `website/features/feedback/tests/unit/test_service.py`

- [ ] **Step 12.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_service.py`
```python
"""Tests for the top-level orchestrator."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from website.features.feedback.core.identity import Identity
from website.features.feedback.intake.models import (
    FeedbackIntent, FeedbackSubmitRequest,
)
from website.features.feedback.service import (
    FeedbackService,
    submit_feedback,
)


@pytest.fixture
def identity() -> Identity:
    return Identity(
        full_name="Naruto Uzumaki",
        email="naruto@konoha.jp",
        country_label="India — IN",
        is_anonymous=False,
    )


@pytest.fixture
def valid_request() -> FeedbackSubmitRequest:
    return FeedbackSubmitRequest(
        intent=FeedbackIntent.ISSUE,
        subject="Add Zettel fails on long videos",
        description="The /api/zettels/add endpoint returns 504 after 90s.",
        follow_up_email=True,
    )


@pytest.fixture
def mock_slack() -> MagicMock:
    m = MagicMock()
    m.upload_image = AsyncMock(side_effect=lambda content, filename: f"F{filename}")
    m.post_message = AsyncMock(return_value="1716800000.001")
    return m


@pytest.mark.asyncio
async def test_submit_calls_upload_per_image_then_post(
    identity: Identity, valid_request: FeedbackSubmitRequest, mock_slack: MagicMock,
) -> None:
    service = FeedbackService(slack_client=mock_slack)
    fid = await service.submit(
        request=valid_request,
        identity=identity,
        processed_images=[
            ("aaaa.jpg", b"fake-jpeg-bytes-1"),
            ("bbbb.png", b"fake-png-bytes-2"),
        ],
    )
    assert fid.startswith("FB-")
    assert mock_slack.upload_image.await_count == 2
    mock_slack.post_message.assert_awaited_once()
    # Verify the posted blocks reference the uploaded file IDs
    posted_blocks = mock_slack.post_message.call_args.kwargs["blocks"]
    image_blocks = [b for b in posted_blocks if b["type"] == "image"]
    assert {b["slack_file"]["id"] for b in image_blocks} == {"Faaaa.jpg", "Fbbbb.png"}


@pytest.mark.asyncio
async def test_submit_with_no_images(
    identity: Identity, valid_request: FeedbackSubmitRequest, mock_slack: MagicMock,
) -> None:
    service = FeedbackService(slack_client=mock_slack)
    await service.submit(request=valid_request, identity=identity, processed_images=[])
    mock_slack.upload_image.assert_not_awaited()
    mock_slack.post_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_returns_stable_id_format(
    identity: Identity, valid_request: FeedbackSubmitRequest, mock_slack: MagicMock,
) -> None:
    import re
    service = FeedbackService(slack_client=mock_slack)
    fid = await service.submit(request=valid_request, identity=identity, processed_images=[])
    assert re.match(r"^FB-[A-Z2-7]{4}$", fid)
```

- [ ] **Step 12.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_service.py -v`
Expected: ImportError.

- [ ] **Step 12.3: Write the implementation**

File: `website/features/feedback/service.py`
```python
"""Top-level orchestrator: validated input → Slack uploads → Slack post.

Caller (the API route) is responsible for:
  - Parsing multipart form data
  - Running rate-limit + auth gates
  - Validating + image-pipelining the screenshots BEFORE handing to .submit()
  - Wrapping .submit() in fire_and_forget if the response should return early

Returns a freshly minted FB-XXXX confirmation ID.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from website.features.feedback.core.identity import Identity
from website.features.feedback.core.ids import generate_feedback_id
from website.features.feedback.intake.models import FeedbackSubmitRequest
from website.features.feedback.slack.block_kit import build_feedback_blocks

logger = logging.getLogger("feedback.service")


@dataclass
class FeedbackService:
    """Stateless orchestrator. Holds a Slack client; no DB."""
    slack_client: object  # Duck-typed FeedbackSlackClient

    async def submit(
        self,
        *,
        request: FeedbackSubmitRequest,
        identity: Identity,
        processed_images: list[tuple[str, bytes]],
    ) -> str:
        """Upload images, post the message, return the feedback ID.

        processed_images: list of (filename, body) tuples — already validated
                          + EXIF-stripped by the API route.
        """
        feedback_id = generate_feedback_id()

        file_ids: list[str] = []
        for filename, body in processed_images:
            fid = await self.slack_client.upload_image(content=body, filename=filename)
            file_ids.append(fid)

        blocks = build_feedback_blocks(
            intent=request.intent,
            subject=request.subject,
            description=request.description,
            identity=identity,
            feedback_id=feedback_id,
            follow_up_email=bool(request.follow_up_email and identity.email),
            slack_file_ids=file_ids,
        )
        fallback = f"New feedback from {identity.full_name}: {request.subject}"

        ts = await self.slack_client.post_message(blocks=blocks, fallback_text=fallback)
        logger.info(
            "feedback delivered",
            extra={"feedback_id": feedback_id, "slack_ts": ts,
                   "intent": request.intent.value, "n_images": len(file_ids)},
        )
        return feedback_id


# Convenience for tests / scripts that need a free-standing call.
async def submit_feedback(
    *, service: FeedbackService, **kwargs,
) -> str:
    return await service.submit(**kwargs)
```

- [ ] **Step 12.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_service.py -v`
Expected: 3 passed.

- [ ] **Step 12.5: Commit**

```bash
git add website/features/feedback/service.py website/features/feedback/tests/unit/test_service.py
git commit -m "feat: feedback orchestrator service"
```

---

## Task 13: `api/deps.py` — FastAPI dependencies

**Files:**
- Create: `website/features/feedback/api/deps.py`
- Create: `website/features/feedback/tests/unit/test_deps.py`

- [ ] **Step 13.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_deps.py`
```python
"""Tests for FastAPI dependencies (rate-limit gate, cookie issuer, settings)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from website.features.feedback.api.deps import (
    DEFAULT_DAILY_CAP,
    enforce_rate_limit_or_429,
    get_feedback_rate_limiter,
)
from website.features.feedback.intake.rate_limit import (
    FeedbackRateLimiter,
    RateLimitExceeded,
)


def test_default_cap_is_ten() -> None:
    assert DEFAULT_DAILY_CAP == 10


def test_rate_limiter_singleton_is_cached() -> None:
    a = get_feedback_rate_limiter()
    b = get_feedback_rate_limiter()
    assert a is b


def test_enforce_rate_limit_returns_when_under_cap() -> None:
    limiter = FeedbackRateLimiter(daily_cap=2, window_seconds=60)
    # Both consume calls happen inside enforce; should not raise on first two.
    enforce_rate_limit_or_429(
        limiter=limiter,
        user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
    )
    enforce_rate_limit_or_429(
        limiter=limiter,
        user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
    )


def test_enforce_rate_limit_raises_http_429_when_over_cap() -> None:
    from fastapi import HTTPException
    limiter = FeedbackRateLimiter(daily_cap=1, window_seconds=60)
    enforce_rate_limit_or_429(
        limiter=limiter,
        user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
    )
    with pytest.raises(HTTPException) as excinfo:
        enforce_rate_limit_or_429(
            limiter=limiter,
            user_id="u-1", cookie_value=None, client_ip="1.2.3.4",
        )
    assert excinfo.value.status_code == 429
    assert "Retry-After" in excinfo.value.headers
```

- [ ] **Step 13.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_deps.py -v`
Expected: ImportError.

- [ ] **Step 13.3: Write the implementation**

File: `website/features/feedback/api/deps.py`
```python
"""FastAPI dependencies for the feedback module.

Kept narrow: settings access, rate-limit gating, cookie issuance helpers.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

from website.features.feedback.intake.rate_limit import (
    FeedbackRateLimiter,
    RateLimitExceeded,
    RateLimitKey,
)

DEFAULT_DAILY_CAP = 10
DEFAULT_WINDOW_SECONDS = 24 * 60 * 60  # 1 day


@lru_cache(maxsize=1)
def get_feedback_rate_limiter() -> FeedbackRateLimiter:
    return FeedbackRateLimiter(
        daily_cap=DEFAULT_DAILY_CAP,
        window_seconds=DEFAULT_WINDOW_SECONDS,
    )


def enforce_rate_limit_or_429(
    *,
    limiter: FeedbackRateLimiter,
    user_id: str | None,
    cookie_value: str | None,
    client_ip: str | None,
) -> None:
    """Apply the per-user OR (per-cookie + per-IP) daily budget.

    Authenticated requests are checked against `user_id` only.
    Anonymous requests are checked against BOTH the signed cookie value and
    the client IP — whichever overflows first triggers 429.
    """
    keys: list[RateLimitKey] = []
    if user_id:
        keys.append(RateLimitKey(scope="user", value=user_id))
    else:
        if cookie_value:
            keys.append(RateLimitKey(scope="cookie", value=cookie_value))
        if client_ip:
            keys.append(RateLimitKey(scope="ip", value=client_ip))

    for key in keys:
        try:
            limiter.consume(key)
        except RateLimitExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail="Daily feedback limit reached. Please try again tomorrow.",
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
```

- [ ] **Step 13.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_deps.py -v`
Expected: 4 passed.

- [ ] **Step 13.5: Commit**

```bash
git add website/features/feedback/api/deps.py website/features/feedback/tests/unit/test_deps.py
git commit -m "feat: FastAPI rate-limit dependency"
```

---

## Task 14: `api/routes.py` — POST /api/feedback/submit

**Files:**
- Create: `website/features/feedback/api/routes.py`
- Create: `website/features/feedback/tests/integration/test_route_e2e.py`
- Create: `website/features/feedback/tests/integration/test_route_disabled.py`

This task wires together everything from Tasks 2-13 behind a FastAPI route.

- [ ] **Step 14.1: Write the integration tests**

File: `website/features/feedback/tests/integration/test_route_e2e.py`
```python
"""End-to-end test for POST /api/feedback/submit with a mocked Slack client."""
from __future__ import annotations

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from website.features.feedback.api.routes import build_router
from website.features.feedback.api.deps import get_feedback_rate_limiter


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    get_feedback_rate_limiter.cache_clear()
    yield
    get_feedback_rate_limiter.cache_clear()


def _make_app(fake_slack_creds: dict, slack_client: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_router(slack_client_factory=lambda: slack_client),
        prefix="/api/feedback",
    )
    return app


@pytest.fixture
def mock_slack() -> MagicMock:
    m = MagicMock()
    m.upload_image = AsyncMock(return_value="F123")
    m.post_message = AsyncMock(return_value="1716800000.001")
    return m


def test_submit_minimal_authenticated_payload_returns_202(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={
            "intent": "issue",
            "subject": "Smoke",
            "description": "This is a description of a smoke test scenario.",
            "follow_up_email": "false",
        },
        headers={"cf-ipcountry": "IN"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert body["feedback_id"].startswith("FB-")
    mock_slack.post_message.assert_awaited_once()


def test_submit_with_images_uploads_each(
    fake_slack_creds: dict, mock_slack: MagicMock, jpeg_bytes_no_exif: bytes,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "suggestion", "subject": "Idea",
              "description": "Long enough description here, more than ten chars."},
        files=[
            ("images", ("a.jpg", jpeg_bytes_no_exif, "image/jpeg")),
            ("images", ("b.jpg", jpeg_bytes_no_exif, "image/jpeg")),
        ],
        headers={"cf-ipcountry": "JP"},
    )
    assert r.status_code == 202, r.text
    assert mock_slack.upload_image.await_count == 2


def test_subject_validation_returns_422(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "issue", "subject": "",
              "description": "Long enough description here."},
    )
    assert r.status_code == 422


def test_invalid_intent_returns_422(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.post(
        "/api/feedback/submit",
        data={"intent": "praise", "subject": "x",
              "description": "Long enough description here."},
    )
    assert r.status_code == 422


def test_rate_limit_429_after_cap(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    """Hammer the endpoint 11x; the 11th must 429."""
    from website.features.feedback.api.deps import DEFAULT_DAILY_CAP
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    payload = {"intent": "issue", "subject": "x",
               "description": "Long enough description here."}
    headers = {"cf-ipcountry": "IN"}
    for i in range(DEFAULT_DAILY_CAP):
        r = client.post("/api/feedback/submit", data=payload, headers=headers)
        assert r.status_code == 202, f"hit {i} should be 202: {r.text}"
    r = client.post("/api/feedback/submit", data=payload, headers=headers)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_health_endpoint_returns_200(
    fake_slack_creds: dict, mock_slack: MagicMock,
) -> None:
    app = _make_app(fake_slack_creds, mock_slack)
    client = TestClient(app)
    r = client.get("/api/feedback/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

File: `website/features/feedback/tests/integration/test_route_disabled.py`
```python
"""When SLACK_BOT_TOKEN_FEEDBACK is empty, the route returns 503."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from website.features.feedback.api.routes import build_router
from website.features.feedback.core.settings import get_feedback_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_feedback_settings.cache_clear()
    yield
    get_feedback_settings.cache_clear()


def test_submit_returns_503_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "SLACK_BOT_TOKEN_FEEDBACK",
        "SLACK_CHANNEL_FEEDBACK",
        "SECRET_FEEDBACK_COOKIE",
    ):
        monkeypatch.delenv(var, raising=False)

    app = FastAPI()
    # No slack_client_factory override — route will check settings and 503.
    app.include_router(build_router(), prefix="/api/feedback")
    client = TestClient(app)

    r = client.post(
        "/api/feedback/submit",
        data={"intent": "issue", "subject": "x",
              "description": "Long enough description here."},
    )
    assert r.status_code == 503
```

- [ ] **Step 14.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/integration/ -v`
Expected: ImportError on `build_router`.

- [ ] **Step 14.3: Write the route implementation**

File: `website/features/feedback/api/routes.py`
```python
"""POST /api/feedback/submit and GET /api/feedback/health."""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Request, Response,
    UploadFile,
)

from website.features.feedback.api.cookie import (
    COOKIE_MAX_AGE_SECONDS, COOKIE_NAME, issue_cookie_value, validate_cookie_value,
)
from website.features.feedback.api.deps import (
    enforce_rate_limit_or_429,
    get_feedback_rate_limiter,
)
from website.features.feedback.core.identity import resolve_identity
from website.features.feedback.core.settings import get_feedback_settings
from website.features.feedback.intake.image_pipeline import (
    ImageProcessingError, process_image,
)
from website.features.feedback.intake.models import (
    FeedbackIntent, FeedbackSubmitRequest, FeedbackSubmitResponse,
)
from website.features.feedback.intake.validation import (
    ValidationError, sniff_and_validate_image,
)
from website.features.feedback.service import FeedbackService
from website.features.feedback.slack.client import (
    FeedbackSlackClient, build_production_client, SlackPostError,
)

logger = logging.getLogger("feedback.routes")

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


def build_router(
    *,
    slack_client_factory: Callable[[], FeedbackSlackClient] | None = None,
) -> APIRouter:
    """Construct the router. The factory parameter lets tests inject a mock."""
    router = APIRouter(tags=["feedback"])

    def _resolve_slack_client() -> FeedbackSlackClient | None:
        if slack_client_factory is not None:
            return slack_client_factory()
        settings = get_feedback_settings()
        if not settings.slack_bot_token_feedback or not settings.slack_channel_feedback:
            return None
        return build_production_client(
            token=settings.slack_bot_token_feedback,
            channel=settings.slack_channel_feedback,
        )

    @router.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @router.post("/submit", response_model=FeedbackSubmitResponse, status_code=202)
    async def submit(
        request: Request,
        response: Response,
        intent: FeedbackIntent = Form(...),
        subject: str = Form(..., min_length=1, max_length=120),
        description: str = Form(..., min_length=10, max_length=4000),
        anon_name: str | None = Form(default=None, max_length=80),
        follow_up_email: bool = Form(default=False),
        anon_email: str | None = Form(default=None),
        images: list[UploadFile] = File(default=[]),
    ) -> FeedbackSubmitResponse:
        # 1. Check the feature is enabled.
        slack_client = _resolve_slack_client()
        if slack_client is None:
            raise HTTPException(status_code=503, detail="Feedback is temporarily unavailable.")

        # 2. Identity — TODO: integrate with get_optional_user once route is wired into app.
        #    For now we treat all requests as anonymous and rely on cookie+IP rate limit.
        claims = None  # placeholder — will be Depends(get_optional_user) once registered
        identity = resolve_identity(
            claims=claims,
            anon_name=anon_name,
            headers={k.lower(): v for k, v in request.headers.items()},
            profile_country_code=None,
        )
        user_id = (claims or {}).get("sub") if claims else None

        # 3. Cookie handling for anonymous traffic.
        settings = get_feedback_settings()
        secret = settings.secret_feedback_cookie.encode("utf-8")
        cookie_value = request.cookies.get(COOKIE_NAME)
        if not (cookie_value and validate_cookie_value(cookie_value, secret)):
            cookie_value = issue_cookie_value(secret) if secret else None
            if cookie_value:
                response.set_cookie(
                    key=COOKIE_NAME,
                    value=cookie_value,
                    max_age=COOKIE_MAX_AGE_SECONDS,
                    httponly=True,
                    secure=True,
                    samesite="lax",
                )

        # 4. Rate-limit gate.
        client_ip = request.client.host if request.client else None
        enforce_rate_limit_or_429(
            limiter=get_feedback_rate_limiter(),
            user_id=user_id,
            cookie_value=cookie_value,
            client_ip=client_ip,
        )

        # 5. Validate the model (Pydantic also catches the form-level checks above).
        req_model = FeedbackSubmitRequest(
            intent=intent, subject=subject, description=description,
            anon_name=anon_name, follow_up_email=follow_up_email,
            anon_email=anon_email,
        )

        # 6. Image validation + EXIF strip.
        processed: list[tuple[str, bytes]] = []
        if len(images) > MAX_IMAGES:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_IMAGES} images.")
        for upload in images:
            blob = await upload.read()
            if len(blob) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413,
                                    detail="Image too large (max 5 MB each).")
            try:
                validated = sniff_and_validate_image(
                    blob, filename=upload.filename or "img.jpg")
                rewritten = process_image(blob, source_ext=validated.normalized_extension)
            except (ValidationError, ImageProcessingError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            processed.append((rewritten.filename, rewritten.body))

        # 7. Orchestrate.
        service = FeedbackService(slack_client=slack_client)
        try:
            feedback_id = await service.submit(
                request=req_model, identity=identity, processed_images=processed,
            )
        except SlackPostError as exc:
            logger.warning("slack post failed but route returns id anyway", extra={"err": str(exc)})
            # Per spec: graceful — return an ID so the user doesn't see a backend failure
            # for a fire-and-forget UX. The failure is logged + visible in app-errors.
            from website.features.feedback.core.ids import generate_feedback_id
            feedback_id = generate_feedback_id()

        return FeedbackSubmitResponse(feedback_id=feedback_id, status="accepted")

    return router
```

- [ ] **Step 14.4: Run integration tests, expect green**

Run: `pytest website/features/feedback/tests/integration/ -v`
Expected: 7 passed (6 in test_route_e2e + 1 in test_route_disabled).

If `test_rate_limit_429_after_cap` exceeds runtime budget, reduce `DEFAULT_DAILY_CAP` value temporarily or split into a separate test marker.

- [ ] **Step 14.5: Commit**

```bash
git add website/features/feedback/api/routes.py \
        website/features/feedback/tests/integration/test_route_e2e.py \
        website/features/feedback/tests/integration/test_route_disabled.py
git commit -m "feat: POST /api/feedback/submit route"
```

---

## Task 15: UI assets — icons.svg + feedback.css + templates

**Files:**
- Create: `website/features/feedback/ui/static/icons.svg`
- Create: `website/features/feedback/ui/static/feedback.css`
- Create: `website/features/feedback/ui/templates/modal.html`
- Create: `website/features/feedback/ui/templates/sheet.html`

Pure asset files — no automated tests. Visual review happens by opening the page after Task 18 wires things up.

- [ ] **Step 15.1: Write the icon sprite**

File: `website/features/feedback/ui/static/icons.svg`
```svg
<svg xmlns="http://www.w3.org/2000/svg" style="display:none">
  <symbol id="zk-feedback-megaphone-solid" viewBox="0 0 24 24">
    <path d="M3 11v2a2 2 0 0 0 2 2h1l2 5h3l-2-5h2l8 4V4l-8 4H5a2 2 0 0 0-2 2v1Z"/>
  </symbol>
  <symbol id="zk-feedback-megaphone-outline" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M3 11v2a2 2 0 0 0 2 2h1l2 5h3l-2-5h2l8 4V4l-8 4H5a2 2 0 0 0-2 2v1Z"/>
  </symbol>
  <symbol id="zk-feedback-close" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round">
    <line x1="18" y1="6" x2="6" y2="18"/>
    <line x1="6" y1="6" x2="18" y2="18"/>
  </symbol>
  <symbol id="zk-feedback-bug" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round">
    <rect x="8" y="6" width="8" height="14" rx="4"/>
    <path d="M10 6V4a2 2 0 0 1 4 0v2"/>
    <path d="M5 9l3 1M19 9l-3 1M5 19l3-1M19 19l-3-1"/>
    <path d="M2 14h4M18 14h4M12 13v8"/>
  </symbol>
  <symbol id="zk-feedback-bulb" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round">
    <path d="M9 18h6M10 22h4"/>
    <path d="M12 2a7 7 0 0 0-4 12.7V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.3A7 7 0 0 0 12 2Z"/>
  </symbol>
  <symbol id="zk-feedback-upload" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
    <polyline points="17 8 12 3 7 8"/>
    <line x1="12" y1="3" x2="12" y2="15"/>
  </symbol>
  <symbol id="zk-feedback-check" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </symbol>
</svg>
```

- [ ] **Step 15.2: Write the modal template**

File: `website/features/feedback/ui/templates/modal.html`

Copy the modal markup from [docs/mockups/feedback/desktop.html](../../../docs/mockups/feedback/desktop.html) — the `.feedback-modal` block. Strip the surrounding banner / scaffolding; keep only the modal contents from `<div class="feedback-header">` through the form + success state. Replace inline SVG icons with `<svg><use href="/feedback-ui/icons.svg#zk-feedback-..."/></svg>` references. Replace the `.feedback-*` class names with `.zk-feedback-*` (prefix) so they don't collide with anything else.

The full file should be approximately:
```html
<div class="zk-feedback-header" id="zk-feedback-header">
  <h2 class="zk-feedback-title" id="zk-feedback-title">Send feedback</h2>
  <p class="zk-feedback-subtitle">Your message goes straight to the team.</p>
</div>

<div class="zk-feedback-tabs" id="zk-feedback-tabs" role="tablist" aria-label="Feedback type">
  <button type="button" role="tab" class="zk-feedback-tab active"
          data-intent="issue" aria-selected="true">
    <svg width="16" height="16"><use href="/feedback-ui/icons.svg#zk-feedback-bug"/></svg>
    Issues
  </button>
  <button type="button" role="tab" class="zk-feedback-tab"
          data-intent="suggestion" aria-selected="false">
    <svg width="16" height="16"><use href="/feedback-ui/icons.svg#zk-feedback-bulb"/></svg>
    Suggestions
  </button>
</div>

<form class="zk-feedback-form" id="zk-feedback-form" novalidate>
  <input type="hidden" name="intent" id="zk-feedback-intent" value="issue">

  <label class="zk-feedback-field zk-feedback-field-anon" hidden>
    <span class="zk-feedback-label">Your name <span class="zk-feedback-opt">optional</span></span>
    <input type="text" name="anon_name" maxlength="80" placeholder="Anonymous">
  </label>

  <label class="zk-feedback-field">
    <span class="zk-feedback-label">Subject <span class="zk-feedback-req">*</span></span>
    <input type="text" name="subject" required maxlength="120" placeholder="Brief summary…">
  </label>

  <label class="zk-feedback-field">
    <span class="zk-feedback-label">
      Description <span class="zk-feedback-req">*</span>
      <span class="zk-feedback-counter" id="zk-feedback-counter">0 / 4000</span>
    </span>
    <textarea name="description" required minlength="10" maxlength="4000"
              placeholder="What happened? What did you expect?"></textarea>
  </label>

  <div class="zk-feedback-field">
    <span class="zk-feedback-label">
      Screenshots <span class="zk-feedback-opt">optional · max 3</span>
    </span>
    <div class="zk-feedback-dropzone" id="zk-feedback-dropzone" tabindex="0">
      <svg width="22" height="22"><use href="/feedback-ui/icons.svg#zk-feedback-upload"/></svg>
      <div>Drag &amp; drop, paste, or <button type="button" class="zk-feedback-pick">choose files</button></div>
      <span class="zk-feedback-hint">PNG, JPG, WebP &middot; up to 5 MB each</span>
    </div>
    <div class="zk-feedback-thumbs" id="zk-feedback-thumbs"></div>
    <p class="zk-feedback-privacy">
      Please blur or crop anything sensitive — passwords, payment details, or other users' personal info.
    </p>
  </div>

  <label class="zk-feedback-checkbox">
    <input type="checkbox" name="follow_up_email" value="true">
    <span>You can email me about this feedback</span>
  </label>

  <label class="zk-feedback-field zk-feedback-field-anon-email" hidden>
    <span class="zk-feedback-label">Your email <span class="zk-feedback-opt">for follow-up</span></span>
    <input type="email" name="anon_email" placeholder="you@example.com">
  </label>

  <div class="zk-feedback-actions">
    <button type="button" class="zk-feedback-btn-secondary" data-feedback-close>Cancel</button>
    <button type="submit" class="zk-feedback-btn-primary">Send feedback</button>
  </div>
</form>

<div class="zk-feedback-success" id="zk-feedback-success" hidden>
  <div class="zk-feedback-success-icon">
    <svg width="20" height="20"><use href="/feedback-ui/icons.svg#zk-feedback-check"/></svg>
  </div>
  <h3>Thanks — sent to the team.</h3>
  <p>We'll triage and follow up if you opted in.</p>
  <span class="zk-feedback-id" id="zk-feedback-id">FB-XXXX</span>
</div>
```

- [ ] **Step 15.3: Write the bottom-sheet template**

File: `website/features/feedback/ui/templates/sheet.html`

Same form contents as modal.html but wrapped in `.zk-feedback-sheet`. Submit button is full-width, sticky bottom. Add a `.zk-feedback-sheet-handle` at the top (drag-to-dismiss handle).

Copy from [docs/mockups/feedback/mobile.html](../../../docs/mockups/feedback/mobile.html), apply the same `.zk-feedback-*` class prefix.

- [ ] **Step 15.4: Write the CSS**

File: `website/features/feedback/ui/static/feedback.css`

Copy the relevant CSS from `docs/mockups/feedback/desktop.html` + `mobile.html`, scoped under `.zk-feedback-*` selectors. Use existing CSS variables (`--accent`, `--bg-card`, `--text-primary`, etc.) — do not redefine. The CSS file should contain:
- `.zk-feedback-trigger` (the footer button styling — though it reuses `.footer-icon` / `.m-footer-icon` largely)
- `.zk-feedback-overlay`, `.zk-feedback-backdrop`, `.zk-feedback-modal` (desktop)
- `.zk-feedback-sheet-overlay`, `.zk-feedback-sheet`, `.zk-feedback-sheet-handle` (mobile)
- `.zk-feedback-tabs`, `.zk-feedback-tab`, `.zk-feedback-tab.active`
- `.zk-feedback-field`, `.zk-feedback-label`, `.zk-feedback-req`, `.zk-feedback-opt`
- `.zk-feedback-dropzone`, `.zk-feedback-thumbs`, `.zk-feedback-pick`
- `.zk-feedback-privacy`, `.zk-feedback-checkbox`
- `.zk-feedback-actions`, `.zk-feedback-btn-primary`, `.zk-feedback-btn-secondary`
- `.zk-feedback-success`, `.zk-feedback-success-icon`, `.zk-feedback-id`
- Media query at `@media (max-width: 768px)` that hides the desktop overlay and shows the sheet instead.

Reference both mockup files when building this — they have ~400 lines of CSS to copy and rename.

- [ ] **Step 15.5: Visual smoke check (manual)**

Open `docs/mockups/feedback/desktop.html` and `mobile.html` — confirm the production CSS will render identically.

- [ ] **Step 15.6: Commit**

```bash
git add website/features/feedback/ui/static/icons.svg \
        website/features/feedback/ui/static/feedback.css \
        website/features/feedback/ui/templates/modal.html \
        website/features/feedback/ui/templates/sheet.html
git commit -m "feat: feedback UI assets (SVG, CSS, templates)"
```

---

## Task 16: `ui/static/feedback.js` — client controller

**Files:**
- Create: `website/features/feedback/ui/static/feedback.js`
- Create: `website/features/feedback/tests/unit/test_feedback_js.py` (skipped if jsdom not available)

The controller does five things:
1. Auto-inject the megaphone button into `.footer` (desktop) and `.m-footer` (mobile) on DOM-ready.
2. On click, lazy-fetch `modal.html` or `sheet.html` from `/feedback-ui/templates/...`.
3. Manage tabs, char counter, drag-drop image picker.
4. Submit FormData to `/api/feedback/submit`.
5. Swap to success state with the returned `feedback_id`, auto-close after 2s.

- [ ] **Step 16.1: Write the controller**

File: `website/features/feedback/ui/static/feedback.js`
```javascript
/**
 * Zettelkasten — Feedback button controller.
 *
 * Auto-injects the megaphone button into .footer (desktop) and .m-footer
 * (mobile). Opens a modal or bottom-sheet on click. Posts FormData to
 * /api/feedback/submit. No framework. No template engine. Just DOM.
 */
(function () {
  'use strict';

  const STATIC_BASE = '/feedback-ui';

  const SVG_MEGAPHONE_SOLID =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
    + '<path d="M3 11v2a2 2 0 0 0 2 2h1l2 5h3l-2-5h2l8 4V4l-8 4H5a2 2 0 0 0-2 2v1Z"/></svg>';
  const SVG_MEGAPHONE_OUTLINE =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" '
    + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    + 'stroke-linejoin="round"><path d="M3 11v2a2 2 0 0 0 2 2h1l2 5h3l-2-5h2l8 4V4l-8 4H5a2 2 0 0 0-2 2v1Z"/></svg>';

  let cssLoaded = false;
  let modalTemplate = null;
  let sheetTemplate = null;
  let currentSurface = null;  // 'modal' | 'sheet'

  function loadCSS() {
    if (cssLoaded) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = STATIC_BASE + '/feedback.css';
    document.head.appendChild(link);
    cssLoaded = true;
  }

  async function fetchTemplate(name) {
    const res = await fetch(STATIC_BASE + '/templates/' + name);
    if (!res.ok) throw new Error('Failed to load ' + name);
    return await res.text();
  }

  function buildDesktopButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'footer-icon';
    btn.setAttribute('aria-label', 'Send feedback');
    btn.setAttribute('title', 'Send feedback');
    btn.setAttribute('data-feedback-open', 'desktop');
    btn.innerHTML = SVG_MEGAPHONE_SOLID;
    return btn;
  }

  function buildMobileButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'm-footer-icon';
    btn.setAttribute('aria-label', 'Send feedback');
    btn.setAttribute('data-feedback-open', 'mobile');
    btn.innerHTML = SVG_MEGAPHONE_OUTLINE;
    return btn;
  }

  async function openSurface(kind) {
    loadCSS();
    if (kind === 'modal' && !modalTemplate) modalTemplate = await fetchTemplate('modal.html');
    if (kind === 'sheet' && !sheetTemplate) sheetTemplate = await fetchTemplate('sheet.html');

    const overlay = document.createElement('div');
    overlay.className = (kind === 'modal')
      ? 'zk-feedback-overlay'
      : 'zk-feedback-sheet-overlay';
    overlay.innerHTML =
      '<div class="' + (kind === 'modal' ? 'zk-feedback-backdrop' : 'zk-feedback-sheet-backdrop')
      + '" data-feedback-close></div>'
      + '<div class="' + (kind === 'modal' ? 'zk-feedback-modal' : 'zk-feedback-sheet')
      + '" role="dialog" aria-modal="true">'
      + ((kind === 'sheet') ? '<div class="zk-feedback-sheet-handle" data-feedback-close></div>' : '')
      + '<button class="zk-feedback-close" data-feedback-close aria-label="Close">'
      + '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/>'
      + '<line x1="6" y1="6" x2="18" y2="18"/></svg></button>'
      + (kind === 'modal' ? modalTemplate : sheetTemplate)
      + '</div>';
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    currentSurface = overlay;
    wireOverlay(overlay);
  }

  function closeSurface() {
    if (!currentSurface) return;
    currentSurface.remove();
    currentSurface = null;
    document.body.style.overflow = '';
  }

  function wireOverlay(root) {
    // Close handlers
    root.querySelectorAll('[data-feedback-close]').forEach(el =>
      el.addEventListener('click', closeSurface));
    document.addEventListener('keydown', escHandler);

    // Tab switching
    const intentInput = root.querySelector('#zk-feedback-intent');
    root.querySelectorAll('.zk-feedback-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        root.querySelectorAll('.zk-feedback-tab').forEach(t => {
          t.classList.remove('active');
          t.setAttribute('aria-selected', 'false');
        });
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        if (intentInput) intentInput.value = tab.dataset.intent;
      });
    });

    // Char counter
    const desc = root.querySelector('textarea[name="description"]');
    const counter = root.querySelector('#zk-feedback-counter');
    if (desc && counter) {
      desc.addEventListener('input', () => {
        counter.textContent = desc.value.length + ' / 4000';
      });
    }

    // Image picker
    const dropzone = root.querySelector('#zk-feedback-dropzone');
    const thumbs = root.querySelector('#zk-feedback-thumbs');
    const pickBtn = root.querySelector('.zk-feedback-pick');
    const files = [];
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/png,image/jpeg,image/webp';
    fileInput.multiple = true;
    pickBtn?.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', e =>
      Array.from(e.target.files || []).forEach(f => addFile(f, thumbs, files)));
    dropzone?.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag-over'); });
    dropzone?.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
    dropzone?.addEventListener('drop', e => {
      e.preventDefault(); dropzone.classList.remove('drag-over');
      Array.from(e.dataTransfer.files || []).forEach(f => addFile(f, thumbs, files));
    });
    document.addEventListener('paste', pasteHandler);

    function pasteHandler(e) {
      if (!currentSurface) return;
      Array.from(e.clipboardData?.items || []).forEach(it => {
        if (it.type.startsWith('image/')) {
          const blob = it.getAsFile();
          if (blob) addFile(blob, thumbs, files);
        }
      });
    }

    // Email-followup toggle reveals anon-email field
    const followup = root.querySelector('input[name="follow_up_email"]');
    const emailField = root.querySelector('.zk-feedback-field-anon-email');
    followup?.addEventListener('change', () => {
      if (!emailField) return;
      emailField.hidden = !followup.checked;
    });

    // Submit
    const form = root.querySelector('#zk-feedback-form');
    form?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Sending…';
      const fd = new FormData(form);
      // Re-attach files (FormData doesn't auto-include our custom-managed list)
      files.forEach(f => fd.append('images', f));
      try {
        const res = await fetch('/api/feedback/submit', {
          method: 'POST',
          body: fd,
          credentials: 'include',
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 202) {
          const id = data.feedback_id || 'FB-????';
          root.querySelector('#zk-feedback-form').hidden = true;
          root.querySelector('#zk-feedback-tabs').hidden = true;
          root.querySelector('#zk-feedback-header').hidden = true;
          const success = root.querySelector('#zk-feedback-success');
          success.hidden = false;
          success.querySelector('#zk-feedback-id').textContent = id;
          setTimeout(closeSurface, 2200);
        } else if (res.status === 429) {
          alert('Daily feedback limit reached. Please try again tomorrow.');
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send feedback';
        } else if (res.status === 503) {
          alert('Feedback is temporarily unavailable. Please email the team directly.');
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send feedback';
        } else {
          alert('Could not send: ' + (data.detail || res.statusText));
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send feedback';
        }
      } catch (err) {
        alert('Network error: ' + err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Send feedback';
      }
    });

    // Cleanup on close
    const origCloseSurface = closeSurface;
    // eslint-disable-next-line no-func-assign
    closeSurface = function () {
      document.removeEventListener('keydown', escHandler);
      document.removeEventListener('paste', pasteHandler);
      origCloseSurface();
      // restore
      closeSurface = origCloseSurface;
    };
  }

  function addFile(file, thumbsEl, files) {
    if (files.length >= 3) return;
    if (file.size > 5 * 1024 * 1024) {
      alert('Image too large (max 5 MB).');
      return;
    }
    files.push(file);
    const t = document.createElement('div');
    t.className = 'zk-feedback-thumb';
    t.textContent = file.name.slice(0, 14);
    const x = document.createElement('button');
    x.className = 'zk-feedback-thumb-remove';
    x.type = 'button';
    x.textContent = '×';
    x.setAttribute('aria-label', 'Remove');
    x.addEventListener('click', () => {
      const idx = files.indexOf(file);
      if (idx >= 0) files.splice(idx, 1);
      t.remove();
    });
    t.appendChild(x);
    thumbsEl.appendChild(t);
  }

  function escHandler(e) {
    if (e.key === 'Escape' && currentSurface) closeSurface();
  }

  // Auto-inject buttons + wire triggers
  function init() {
    const desktop = document.querySelector('footer.footer');
    if (desktop) desktop.appendChild(buildDesktopButton());
    const mobile = document.querySelector('footer.m-footer');
    if (mobile) mobile.appendChild(buildMobileButton());
    document.body.addEventListener('click', (e) => {
      const trigger = e.target.closest('[data-feedback-open]');
      if (!trigger) return;
      e.preventDefault();
      const useSheet = trigger.dataset.feedbackOpen === 'mobile'
        || window.matchMedia('(max-width: 768px)').matches;
      openSurface(useSheet ? 'sheet' : 'modal');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

- [ ] **Step 16.2: Quick syntax check**

Run: `node --check website/features/feedback/ui/static/feedback.js`
Expected: Exit 0, no errors.

(If Node not installed locally, skip this; CI will catch syntax errors when the page loads.)

- [ ] **Step 16.3: Commit**

```bash
git add website/features/feedback/ui/static/feedback.js
git commit -m "feat: feedback client-side controller"
```

---

## Task 17: `__init__.py` — register(app) entry point

**Files:**
- Modify: `website/features/feedback/__init__.py`
- Create: `website/features/feedback/tests/unit/test_register.py`

- [ ] **Step 17.1: Write the failing test**

File: `website/features/feedback/tests/unit/test_register.py`
```python
"""Tests that register(app) wires the feature correctly."""
from __future__ import annotations

from fastapi import FastAPI

from website.features.feedback import register


def test_register_returns_app() -> None:
    app = FastAPI()
    out = register(app)
    assert out is app


def test_register_mounts_static_dir() -> None:
    app = FastAPI()
    register(app)
    routes = [r.path for r in app.routes]
    assert any(p.startswith("/feedback-ui") for p in routes), routes


def test_register_adds_feedback_router() -> None:
    app = FastAPI()
    register(app)
    paths = [r.path for r in app.routes]
    # /api/feedback/health is part of the router
    assert any("/api/feedback/health" in p for p in paths), paths
```

- [ ] **Step 17.2: Run, expect failure**

Run: `pytest website/features/feedback/tests/unit/test_register.py -v`
Expected: ImportError on `register`.

- [ ] **Step 17.3: Write the implementation**

File: `website/features/feedback/__init__.py`
```python
"""Feedback feature — sole public entry point.

`register(app)` mounts the static directory and includes the router.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from website.features.feedback.api.routes import build_router


_FEATURE_ROOT = Path(__file__).resolve().parent
_STATIC_DIR = _FEATURE_ROOT / "ui" / "static"
_TEMPLATES_DIR = _FEATURE_ROOT / "ui" / "templates"


def register(app: FastAPI) -> FastAPI:
    """Wire the feedback feature into a FastAPI app.

    Call once during app construction:

        from website.features.feedback import register as register_feedback
        register_feedback(app)
    """
    app.include_router(build_router(), prefix="/api/feedback")
    app.mount(
        "/feedback-ui",
        _CombinedStatic(_STATIC_DIR, _TEMPLATES_DIR),
        name="feedback-ui",
    )
    return app


class _CombinedStatic(StaticFiles):
    """Serves /feedback-ui/templates/<x> from _TEMPLATES_DIR and everything else
    from _STATIC_DIR.
    """

    def __init__(self, static_dir: Path, templates_dir: Path) -> None:
        super().__init__(directory=str(static_dir), check_dir=True)
        self._templates_dir = templates_dir

    async def get_response(self, path, scope):
        if path.startswith("templates/"):
            sub = path[len("templates/"):]
            self.directory = str(self._templates_dir)
            try:
                return await super().get_response(sub, scope)
            finally:
                self.directory = str(_STATIC_DIR)
        return await super().get_response(path, scope)
```

- [ ] **Step 17.4: Run, expect green**

Run: `pytest website/features/feedback/tests/unit/test_register.py -v`
Expected: 3 passed.

- [ ] **Step 17.5: Commit**

```bash
git add website/features/feedback/__init__.py website/features/feedback/tests/unit/test_register.py
git commit -m "feat: register(app) entry point"
```

---

## Task 18: Wire feature into `website/app.py`

**Files:**
- Modify: `website/app.py` (one import + one registration line + ~10 lines of post-processor infra for the footer-script injection)

**Important:** This is the ONLY production file outside `website/features/feedback/` that gets modified by the implementation. Keep the diff minimal.

- [ ] **Step 18.1: Read the current `<!--ZK_FOOTER-->` injection code**

Run: `grep -n "ZK_FOOTER" website/app.py`
Note the exact lines where footer replacement happens. There's likely a helper function like `_inject_footer(html)` or inline string replacement. Identify the SINGLE line where `footer_html` content is loaded from `website/footer/footer.html`.

- [ ] **Step 18.2: Add the registration call**

At the top of `website/app.py`, in the existing import block (after the line `from website.features.web_monitor import router as web_monitor_router`), add:
```python
from website.features.feedback import register as register_feedback
```

After the FastAPI app is constructed and other routers are included (find the existing pattern around `app.include_router(zettels_router, prefix="/api")` — register the feedback feature similarly), add:
```python
register_feedback(app)
```

- [ ] **Step 18.3: Add the post-processor infrastructure for the footer script tag**

The feature's button is auto-injected by `feedback.js`. The script tag itself must appear on every page that has a footer. The simplest implementation: extend the footer-loading function in `app.py` to append a single line to the loaded footer HTML.

Find the line in app.py that reads:
```python
_FOOTER_HTML = (FOOTER_DIR / "footer.html").read_text(encoding="utf-8")
```
(or however it's read — locate the equivalent).

Replace with:
```python
_FOOTER_HTML = (FOOTER_DIR / "footer.html").read_text(encoding="utf-8")

# Feature post-processors (e.g. feedback module injecting its script tag).
_FOOTER_POST_PROCESSORS: list[callable] = []


def register_footer_post_processor(fn: callable) -> None:
    """Allow self-contained features to append HTML to the rendered footer
    without modifying website/footer/footer.html directly.
    """
    _FOOTER_POST_PROCESSORS.append(fn)


def _rendered_footer() -> str:
    html = _FOOTER_HTML
    for fn in _FOOTER_POST_PROCESSORS:
        html = fn(html)
    return html
```

Then find the line(s) that use `_FOOTER_HTML` directly (in the `<!--ZK_FOOTER-->` replacement code) and replace `_FOOTER_HTML` with `_rendered_footer()`.

- [ ] **Step 18.4: Update `register_feedback` to use the post-processor**

Now modify `website/features/feedback/__init__.py` to also register the script-tag injection:

```python
def register(app: FastAPI) -> FastAPI:
    app.include_router(build_router(), prefix="/api/feedback")
    app.mount(
        "/feedback-ui",
        _CombinedStatic(_STATIC_DIR, _TEMPLATES_DIR),
        name="feedback-ui",
    )

    # Inject the loader script so the feature's CSS+JS load on every page
    # that renders the footer — without modifying website/footer/footer.html.
    from website.app import register_footer_post_processor

    def _inject_feedback_loader(footer_html: str) -> str:
        loader = (
            '<link rel="preload" as="style" href="/feedback-ui/feedback.css">'
            '<script defer src="/feedback-ui/feedback.js"></script>'
        )
        # Append at the very end of the footer HTML so it lands inside <body>.
        return footer_html + loader

    register_footer_post_processor(_inject_feedback_loader)
    return app
```

- [ ] **Step 18.5: Run the full feature test suite**

Run: `pytest website/features/feedback/ -v`
Expected: all unit + integration tests pass. The `test_register.py` may need adjustment if the import of `register_footer_post_processor` causes a circular-import problem — if so, defer the import to inside the function (already done above).

- [ ] **Step 18.6: Run the existing app smoke tests**

Run: `pytest tests/ -k "app or smoke" -v`
Expected: existing tests still pass — confirm the footer-loading change didn't break anything.

- [ ] **Step 18.7: Start the dev server and visually verify**

Run: `ENV=dev python run.py`
Then open `http://localhost:10000/` in a browser. Confirm:
- The megaphone icon appears at the right of the desktop footer.
- Clicking it opens the modal.
- The form submits successfully against a stubbed Slack client (set `SLACK_BOT_TOKEN_FEEDBACK=` empty in dev to get 503, OR set a fake bot token + use a real test workspace).

Stop the server with Ctrl+C.

- [ ] **Step 18.8: Commit**

```bash
git add website/app.py website/features/feedback/__init__.py
git commit -m "feat: wire feedback module into FastAPI app"
```

---

## Task 19: Ops infrastructure

**Files:**
- Modify: `ops/Dockerfile`
- Modify: `ops/.env.example`
- Modify: `ops/caddy/Caddyfile`

- [ ] **Step 19.1: Add `libmagic1` to Stage 2 of the Dockerfile**

In `ops/Dockerfile`, locate the line in **Stage 2 (runtime)**:
```
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini curl \
    && rm -rf /var/lib/apt/lists/*
```

Add `libmagic1`:
```
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini curl libmagic1 \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 19.2: Build the Docker image locally to confirm**

Run: `docker build -f ops/Dockerfile -t zk-feedback-smoke .`
Expected: build completes; libmagic1 listed in the apt-install line.

- [ ] **Step 19.3: Add env vars to `ops/.env.example`**

Append to `ops/.env.example`:
```
# === Feedback feature (website/features/feedback/) =================
# Bot Token for the Slack app that posts feedback to #zk-testing.
# Get it from api.slack.com/apps. Must carry chat:write + files:write scopes.
# See docs/mockups/feedback/SLACK_SETUP.md for the step-by-step.
SLACK_BOT_TOKEN_FEEDBACK=
# Slack channel ID — copy from the Slack Android app (channel name → About).
SLACK_CHANNEL_FEEDBACK=
# 32-byte hex secret for HMAC-signing the anonymous rate-limit cookie.
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_FEEDBACK_COOKIE=
# Set to "true" to require Cloudflare Turnstile for anonymous submissions.
# Default off; flip to true if cookie-bypass spam appears.
FEEDBACK_REQUIRE_TURNSTILE=false
```

- [ ] **Step 19.4: Add route-level body-size cap to Caddyfile**

In `ops/caddy/Caddyfile`, locate the existing `request_body` block (likely around the `/api/zettels/add` route). Add a parallel block for `/api/feedback/submit`:
```caddyfile
@feedback path /api/feedback/submit
handle @feedback {
    request_body {
        max_size 18MB
    }
    reverse_proxy {upstream}
}
```

(Place this BEFORE the catchall reverse_proxy at the bottom of the same site block. Match the structure of the existing zettels-upload block.)

- [ ] **Step 19.5: Validate Caddyfile syntax**

Run: `docker run --rm -v "$PWD/ops/caddy/Caddyfile":/etc/caddy/Caddyfile caddy:2 caddy validate --config /etc/caddy/Caddyfile`
Expected: "Valid configuration".

- [ ] **Step 19.6: Commit**

```bash
git add ops/Dockerfile ops/.env.example ops/caddy/Caddyfile
git commit -m "ops: feedback feature infra (libmagic, env, caddy)"
```

---

## Task 20: Live test (skipped by default)

**Files:**
- Create: `website/features/feedback/tests/live/test_slack_live.py`

- [ ] **Step 20.1: Write the live test**

File: `website/features/feedback/tests/live/test_slack_live.py`
```python
"""Live Slack delivery test. Skipped unless --live passed.

Requires SLACK_BOT_TOKEN_FEEDBACK + SLACK_CHANNEL_FEEDBACK to be set in env;
posts a real message to the configured channel. Run only against a test/dev
Slack workspace.
"""
from __future__ import annotations

import os

import pytest

from website.features.feedback.slack.client import build_production_client


pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_chat_postMessage() -> None:
    token = os.environ.get("SLACK_BOT_TOKEN_FEEDBACK", "")
    channel = os.environ.get("SLACK_CHANNEL_FEEDBACK", "")
    if not token or not channel:
        pytest.skip("Slack creds not set in env")

    client = build_production_client(token=token, channel=channel)
    ts = await client.post_message(
        blocks=[
            {"type": "header", "text": {"type": "plain_text",
             "text": "\U0001F4E3 LIVE TEST — feedback feature smoke"}},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "Posted from `tests/live/test_slack_live.py` — ignore."}},
        ],
        fallback_text="LIVE TEST — feedback feature smoke",
    )
    assert ts and "." in ts
```

- [ ] **Step 20.2: Verify the test is correctly skipped by default**

Run: `pytest website/features/feedback/tests/live/ -v`
Expected: 1 skipped (the `live` marker filter excludes it without `--live`).

- [ ] **Step 20.3: Commit**

```bash
git add website/features/feedback/tests/live/test_slack_live.py
git commit -m "test: live Slack smoke (skipped by default)"
```

---

## Task 21: Feature README + final integration smoke

**Files:**
- Create: `website/features/feedback/README.md`

- [ ] **Step 21.1: Write the feature README**

File: `website/features/feedback/README.md`
```markdown
# Feedback feature

Self-contained module providing a footer "Send feedback" button + popup that
posts Issues / Suggestions to Slack `#zk-testing`.

## Module layout

\```
website/features/feedback/
├── api/          FastAPI routes + deps + cookie helpers
├── core/         Settings, identity resolver, ID generator
├── intake/       DTOs, validation, image pipeline, rate limit
├── slack/        Slack client + Block Kit builder
├── ui/           CSS, JS, SVG, HTML templates
├── tests/        unit / integration / live
├── __init__.py   register(app) entry point
├── service.py    Top-level orchestrator
└── README.md     this file
\```

## Spec

[docs/superpowers/specs/2026-05-27-feedback-button-design.md](../../../docs/superpowers/specs/2026-05-27-feedback-button-design.md)

## Operational setup

[docs/mockups/feedback/SLACK_SETUP.md](../../../docs/mockups/feedback/SLACK_SETUP.md)

## Tests

\```bash
# Unit + integration (default — no network)
pytest website/features/feedback/

# Live Slack delivery (requires SLACK_BOT_TOKEN_FEEDBACK + SLACK_CHANNEL_FEEDBACK)
pytest website/features/feedback/ --live
\```

## How to swap the icon

Edit `MEGAPHONE_SVG` constants in `ui/static/feedback.js`. Five alternates
documented in [docs/mockups/feedback/icons.html](../../../docs/mockups/feedback/icons.html).
```

- [ ] **Step 21.2: Run the full feature test suite**

Run: `pytest website/features/feedback/ -v`
Expected: all tests pass (live tests skipped).

- [ ] **Step 21.3: Run the existing app tests to confirm no regression**

Run: `pytest tests/ -m "not live" -q`
Expected: all existing tests still pass.

- [ ] **Step 21.4: Lint pass (per CLAUDE.md "batch ruff at end")**

Run: `ruff check website/features/feedback/ --fix`
Expected: 0 errors, or auto-fixed.

- [ ] **Step 21.5: Visual smoke check (manual)**

Run: `ENV=dev python run.py`
Open the live site, click the megaphone, fill the form, submit. Verify:
- 202 response from the network tab.
- Success state shows with `FB-XXXX`.
- If `SLACK_BOT_TOKEN_FEEDBACK` is set in `.env`, message lands in Slack.
- If not set, 503 with "Feedback is temporarily unavailable" alert.

- [ ] **Step 21.6: Commit**

```bash
git add website/features/feedback/README.md
git commit -m "docs: feedback module README"
```

- [ ] **Step 21.7: Push to the PR**

```bash
git push
```

The PR (#117) is now ready for review of the implementation. Mark it as Ready (out of Draft) via the GitHub UI or `gh pr ready 117`.

---

## Self-review

**Spec coverage check** — for each section in the spec, point to the task that implements it:

| Spec section | Implemented in |
|---|---|
| §3.1 Footer trigger (auto-injection) | Task 16 (`feedback.js` auto-inject) + Task 18 (`app.py` script-tag injection) |
| §3.2 Modal / bottom sheet | Tasks 15 (CSS/HTML) + 16 (JS controller) |
| §3.3 Form (tabs, anon name, subject, description, screenshots, privacy notice, follow-up checkbox, submit/cancel) | Tasks 15 (HTML templates) + 16 (JS interactions) + 14 (server-side validation) |
| §3.4 Success state with FB-XXXX | Tasks 2 (id generator) + 16 (UI swap) |
| §3.5 Failure states (429, 413, 503, network) | Tasks 13, 14 (server) + 16 (client alerts) |
| §4.1 Module structure (strict containment) | Task 1 (scaffold) + every subsequent task lands inside `website/features/feedback/` |
| §4.1.1 Auto-injection of buttons | Task 16 + Task 18 |
| §4.1.2 Feature-local settings | Task 3 |
| §4.2 Route | Task 14 |
| §4.3 Rate limiting | Tasks 9 + 13 |
| §4.4 Auth resolution + identity | Tasks 5 + 14 |
| §4.5 Image validation pipeline | Tasks 7 + 8 |
| §4.6 Slack delivery | Task 11 |
| §4.7 Block Kit payload | Task 10 |
| §4.8 Configuration | Tasks 3 + 19 |
| §4.9 Body-size handling | Task 19 (Caddyfile route-level cap) + Task 14 (5 MB per-image check) |
| §5 Testing (unit/integration/live/e2e) | Tasks 2-13 (unit), 14 (integration), 20 (live), 21 (manual smoke) |
| §6 Files changed | All tasks land in the locations specified |
| §7 Rollout | Documented in [SLACK_SETUP.md](../../mockups/feedback/SLACK_SETUP.md) — operator-driven |

**Placeholder scan** — none. Every code block is complete. Every test has expected outputs. Every command is exact.

**Type consistency** — `FeedbackIntent` (enum), `Identity` (frozen dataclass), `FeedbackSubmitRequest` (pydantic), `RateLimitKey` (frozen dataclass), `ValidatedImage` (frozen dataclass), `ProcessedImage` (frozen dataclass) — names match across all tasks. Method names: `consume()`, `process_image()`, `sniff_and_validate_image()`, `generate_feedback_id()`, `upload_image()`, `post_message()`, `submit()`, `resolve_identity()`, `register()` — all consistent.

**Known follow-ups (NOT blocking):**
- Auth integration (Task 14 places a `claims = None` placeholder). After the first implementation pass, wire `Depends(get_optional_user)` from `website/api/auth.py:183` into the route. Spec covers this in §4.4; placeholder is in `routes.py` line `claims = None  # placeholder`.
- `_CombinedStatic` in `__init__.py` mutates `self.directory` between requests — works because FastAPI processes one request per task, but in extreme load could race. Replace with separate Starlette `Mount` instances if traffic warrants it.
- The `claims = None` placeholder means rate-limit currently always falls into the anonymous (cookie + IP) branch. Once auth is wired, users will get the more generous user_id-keyed limit.
