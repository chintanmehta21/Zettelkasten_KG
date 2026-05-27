# Feedback button — design spec

**Date:** 2026-05-27
**Status:** Operator-approved on 2026-05-27 (8/8 questions answered in PR #117)
**Tracking PR:** https://github.com/chintanmehta21/Zettelkasten_KG/pull/117
**Implementation PR:** TBD — opens after `superpowers:writing-plans` produces the plan

---

## 1. Goal

Add a "Send feedback" button to the website footer (desktop + mobile) that lets any visitor — authenticated or anonymous — submit an Issue or a Suggestion with Subject, Description, and up to three screenshots. Submissions post to Slack `#zk-testing` as a well-formatted Block Kit message that carries the user's full name and country.

## 2. Scope

**In scope**
- Footer button on every page that renders `website/footer/footer.html` (`/`, `/about`, `/pricing`) and on every `/m/*` route that uses `website/mobile/templates/_shell.html`.
- Modal popup (desktop) / bottom sheet (mobile) with **two horizontal tabs**: Issues, Suggestions.
- Subject + Description + optional screenshots + optional email opt-in + optional anonymous-name input.
- New backend route `POST /api/feedback/submit`.
- Slack delivery: Bot Token + `files_upload_v2` + Block Kit message with `slack_file` image blocks.
- Rate limits: 10 submissions/day (per user_id when authenticated; per signed cookie + per IP when anonymous).
- Operational changes: env vars, `ops/.env.example` update, Dockerfile `libmagic1` install, Caddyfile body-size sub-route.

**Out of scope (operator decisions, 2026-05-27)**
- DB persistence per submission (operator: "No need"). Feedback ID shown to user is **UI-only confirmation**, not a DB foreign key. The Slack message timestamp (`ts`) is the only canonical record.
- GDPR Art. 17 erasure mapping — no DB → nothing to delete on our side; Slack workspace retention policy applies.
- CAPTCHA / Cloudflare Turnstile in v1 — operator chose cookie + IP rate-limit. A `FEEDBACK_REQUIRE_TURNSTILE=true` env flag is reserved for future enablement without code change.
- Follow-up email automation — the opt-in is captured and surfaces in the Slack message as a flag; operator manually replies. No transactional-email infra in v1.
- Privacy-policy text update — operator handles separately; Slack added to Trust Center / DPA sub-processor list.
- The 4 mockup HTMLs under `docs/mockups/feedback/` stay in the repo as design reference (icons/selector variants retained per operator's "might change eventually").

## 3. UX

### 3.1 Footer trigger (auto-injected, no template edits)

The feature **does not modify** `website/footer/footer.html` or `website/mobile/templates/_shell.html`. Instead, `website/features/feedback/ui/static/feedback.js` runs at `DOMContentLoaded` and appends the button to whichever rail exists on the page:

```javascript
// Auto-inject at DOM-ready
const desktop = document.querySelector('footer.footer');
const mobile  = document.querySelector('footer.m-footer');
if (desktop) desktop.appendChild(buildDesktopButton());
if (mobile)  mobile.appendChild(buildMobileButton());
```

**Desktop button** (built by `buildDesktopButton()`):
- Element: `<button class="footer-icon" data-feedback-open ...>`
- Reuses the existing `.footer-icon` class so colour, hover, focus-ring, and spacing match the other four icons exactly (no new desktop button styles needed).
- Icon: Lucide `megaphone`, solid, 20×20, `fill="currentColor"`.

**Mobile button** (built by `buildMobileButton()`):
- Element: `<button class="m-footer-icon" data-feedback-open ...>`
- Reuses the existing `.m-footer-icon` class.
- Icon: Lucide `megaphone`, outline weight (18×18, stroke-width 2).

The script is loaded via `<script defer src="/feedback-ui/feedback.js">` injected into every page that has the `<!--ZK_FOOTER-->` marker. The `defer` attribute means the script runs after HTML parse but before `DOMContentLoaded` — the button appears at first paint with no visible flash.

The icon choice is reversible via [`docs/mockups/feedback/icons.html`](../../mockups/feedback/icons.html) — five alternates documented. To swap the icon: edit `feedback.js`'s `MEGAPHONE_SVG` constant; no other file changes.

### 3.2 Modal (desktop) / bottom sheet (mobile)

Both surfaces use **new feature-local classes** scoped under a `.zk-feedback-*` prefix, defined entirely in `website/features/feedback/ui/static/feedback.css`. The existing `.zettels-summary-overlay` family from `website/static/css/zk_summary_popup.css` is **referenced as a visual model** (same backdrop blur, modal shadow, animation timing) — the new CSS replicates the patterns but does not import or extend the global stylesheet. This keeps the feature self-contained.

**Desktop modal** — `.zk-feedback-overlay` + `.zk-feedback-backdrop` + `.zk-feedback-modal`. Width: `min(560px, calc(100vw - 2rem))`. Close: backdrop click, ESC, X-button. Body-scroll lock via a small feature-local helper (not the global `setBodyScrollLocked()`).

**Mobile bottom sheet** — `.zk-feedback-sheet-overlay` + `.zk-feedback-sheet`. Slides up from bottom; rounded top corners; swipe-down handle; sticky full-width Submit pinned above `env(safe-area-inset-bottom)`. Animation: `cubic-bezier(0.16, 1, 0.3, 1)` over 0.28s. Backdrop blur 4px.

**Design-token reuse, not CSS reuse:** the new `feedback.css` reads the same CSS custom properties (`--accent`, `--bg-card`, `--text-primary`, etc.) the rest of the site defines on `:root` in `style.css`. The feature does not redefine those tokens; it consumes them. This means a site-wide token rename (e.g., `--accent`) propagates into the feedback UI for free.

### 3.3 Form (both surfaces)

Identical fields on both surfaces, rendered:

| Element | Behavior |
|---|---|
| **Tabs** | Horizontal `role="tablist"` with two `role="tab"`s: Issues / Suggestions. Active state = teal underline (`border-bottom: 2px solid var(--accent)`). Keyboard arrow-key nav between tabs. `tabpanel` shares one form — switching tabs only swaps the `intent` value. |
| **Anonymous name** | Only renders if `get_optional_user()` returned None. Text input, optional, max 80 chars. Empty → "Anonymous" in Slack. |
| **Subject** | Required text input, max 120 chars. |
| **Description** | Required textarea, min 10 / max 4000 chars, live char counter. |
| **Screenshots** | Drag-drop zone + file-picker button + paste-from-clipboard listener. Max 3 images. Each ≤ 5 MB **after** client-side `<canvas>` compression (max-edge 1600 px, JPEG q=0.85). Thumbnail strip with × remove button per item. |
| **Privacy notice** | One muted line above the upload: "Please blur or crop anything sensitive — passwords, payment details, or other users' personal info." |
| **Email follow-up** | Checkbox, unchecked by default. Label varies: authenticated → "You can email me about this feedback"; anonymous → "Send me a copy / let me know when this is handled" with an optional `email` text field that appears when checked. Email format validated server-side. |
| **Submit** | Primary action button. Triggers POST to `/api/feedback/submit`. |
| **Cancel** | Closes the modal/sheet without sending. |

### 3.4 Success state

On 2xx response, swap the form contents for an inline success view:

```
✓ Thanks — sent to the team.
   We'll triage and follow up if you opted in.
   [ FB-7K3Q ]
```

Feedback ID is generated client-side as a 4-character base32 (e.g. `FB-7K3Q`); displayed only — not persisted. After ~2 seconds the modal auto-closes.

### 3.5 Failure states

| Response | UI |
|---|---|
| `429 Too Many Requests` | Inline error in the form: "You've hit the daily feedback limit. Try again tomorrow." |
| `413 Payload Too Large` | Inline error on the upload row: "Image too large — please attach files up to 5 MB each." |
| `503 Service Unavailable` (Slack creds unset) | Inline error: "Feedback is temporarily unavailable. Please email <contact-email> directly." |
| Network / 5xx | Toast + inline retry: "Couldn't send right now — try again?" with a Retry button. |

## 4. Backend

### 4.1 New module structure (strict containment)

**Operator constraint (2026-05-27):** *"Build the full module in `website/features` only. Nowhere else."*

Everything for this feature — Python code, CSS, JavaScript, HTML templates, SVG assets, and tests — lives under `website/features/feedback/`. The only changes outside this folder are minimal integration glue (one registration call in `website/app.py`) and unavoidable operational infrastructure (`ops/`). **No edits to `website/footer/footer.html`, `website/mobile/templates/_shell.html`, `website/static/`, `website/mobile/css/`, `website/mobile/js/`, `website/core/settings.py`, or any other existing module.**

```
website/features/feedback/
├── __init__.py                          # Exports register(app) — sole public entry point
├── README.md                            # Feature-local documentation
│
├── api/
│   ├── __init__.py
│   ├── routes.py                        # POST /api/feedback/submit
│   ├── deps.py                          # FastAPI dependencies (cookie issuer, rate-limit gate)
│   └── cookie.py                        # Signed HMAC cookie issue + validate
│
├── core/
│   ├── __init__.py
│   ├── settings.py                      # Feature-local pydantic Settings, reads env directly
│   ├── identity.py                      # Resolve full_name + country from claims OR cf-ipcountry
│   └── ids.py                           # FB-XXXX generator (UI-only IDs, not persisted)
│
├── intake/
│   ├── __init__.py
│   ├── models.py                        # Pydantic request/response DTOs
│   ├── validation.py                    # Subject/description/extension whitelist
│   ├── image_pipeline.py                # libmagic + PIL.verify + RGB convert + EXIF strip
│   └── rate_limit.py                    # Daily sliding-window (user_id | cookie + IP)
│
├── slack/
│   ├── __init__.py
│   ├── client.py                        # AsyncWebClient wrapper, retry + Retry-After honoring
│   └── block_kit.py                     # build_feedback_blocks(...)
│
├── service.py                           # Top-level orchestrator (validate → pipeline → Slack)
│
├── ui/
│   ├── __init__.py
│   ├── static/                          # Served via app.mount("/feedback-ui", ...)
│   │   ├── feedback.css                 # ALL styles: desktop modal + mobile bottom sheet
│   │   ├── feedback.js                  # Controller: auto-inject button, open/close, submit
│   │   └── icons.svg                    # Megaphone (solid + outline) sprite
│   └── templates/                       # Loaded by feature, NOT by global Jinja2 env
│       ├── modal.html                   # Desktop popup markup (fetched async on first open)
│       └── sheet.html                   # Mobile bottom-sheet markup (fetched async on first open)
│
└── tests/
    ├── __init__.py
    ├── conftest.py                      # Feature-local fixtures (mock Slack client, etc.)
    ├── unit/
    │   ├── test_image_pipeline.py
    │   ├── test_rate_limit.py
    │   ├── test_block_kit.py
    │   ├── test_models.py
    │   ├── test_ids.py
    │   ├── test_identity.py
    │   └── test_cookie.py
    ├── integration/
    │   ├── test_route_e2e.py
    │   └── test_route_disabled.py
    └── live/
        └── test_slack_live.py
```

### 4.1.1 Auto-injection (zero template touch)

The footer button is added to the page **without modifying** `website/footer/footer.html` or `website/mobile/templates/_shell.html`. The mechanism:

1. `website/features/feedback/__init__.py` exports `register(app)`.
2. `register(app)` does three things, all in one call from `app.py`:
   - `app.include_router(api.routes.router, prefix="/api/feedback")`
   - `app.mount("/feedback-ui", StaticFiles(directory="website/features/feedback/ui/static"))`
   - Extends app.py's existing HTML-injection pipeline (the same one that handles `<!--ZK_FOOTER-->` replacement) so that every page served with a footer also gets a single `<script defer src="/feedback-ui/feedback.js"></script>` and `<link rel="preload" as="style" href="/feedback-ui/feedback.css">` injected before `</body>`.
3. `feedback.js` runs at `DOMContentLoaded`:
   - Queries for `.footer` (desktop) and `.m-footer` (mobile). If found, appends a megaphone `<button>` matching the existing styling.
   - Lazy-loads `feedback.css` and the modal/sheet HTML on first click (via `fetch` to `/feedback-ui/`).
4. FOUC mitigation: the script is `defer` + the `preload` hint tells the browser to fetch the CSS early. The button injection happens between HTML parse and first paint, so users do not see a footer flash.

If app.py's existing footer-injection logic does NOT already expose a post-process hook, the implementation PR adds a minimal one (`register_footer_post_processor(fn)` — ~8 lines) as enabling infrastructure for all future feature modules that follow this containment pattern. This is the ONLY non-trivial change to `app.py`.

### 4.1.2 Settings — feature-local

The new module reads its env vars **directly** rather than extending `website/core/settings.py`. `website/features/feedback/core/settings.py` is a small pydantic-settings class that loads from `os.environ` with the same precedence rules the global Settings uses. This keeps `website/core/settings.py` untouched and the feature's config self-documenting.

### 4.2 Route

`POST /api/feedback/submit` (multipart/form-data):

```python
async def submit_feedback(
    intent: Literal["issue", "suggestion"] = Form(...),
    subject: str = Form(..., min_length=1, max_length=120),
    description: str = Form(..., min_length=10, max_length=4000),
    anon_name: str | None = Form(None, max_length=80),
    follow_up_email: bool = Form(False),
    anon_email: str | None = Form(None),  # only honored for anonymous
    images: list[UploadFile] = File(default=[]),
    request: Request = ...,
    response: Response = ...,
    user: dict | None = Depends(get_optional_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
```

Returns `{"feedback_id": "FB-7K3Q", "status": "accepted"}` with HTTP 202.

The Slack post runs via `fire_and_forget()` — the response returns in <100 ms; Slack delivery completes async. Slack delivery failures are logged but do not propagate to the user (graceful — the user shouldn't see backend errors for a "post and forget" UX).

### 4.3 Rate-limiting

New module `website/features/feedback/rate_limit.py`. Reuses the sliding-window pattern from [`website/features/functional_gates/upload_rate_limit.py`](../../../website/features/functional_gates/upload_rate_limit.py) but with daily window.

**Limits (operator decision, 2026-05-27):**
- Authenticated: 10 submissions/day per `user_id`.
- Anonymous: 10 submissions/day per signed `zk_feedback_token` HMAC cookie **AND** 10/day per IP (whichever hits first).

**Cookie design:**
- Cookie name: `zk_feedback_token`.
- Value: `base64url(uuid4) + "." + hmac_sha256_hex(uuid4, SECRET_FEEDBACK_COOKIE)`.
- Attributes: `HttpOnly`, `Secure`, `SameSite=Lax`, `Max-Age=30 days`, `Path=/`.
- Issued on first GET to a page that includes the footer.
- Server re-validates HMAC on every submit; rejects unsigned values.

**Counter storage:**
- In-process per-worker dict: `{ key: [(timestamp, ...), ...] }`. Sliding window expires entries > 24h old.
- Per-worker storage means: with 2 gunicorn workers, the effective real-world limit is 20/day (10 per worker). Acceptable — operator's intent is "stop abuse, not enforce exactness".
- Container restart resets all counters. Acceptable for v1.

**Known limitation (flagged):**
- Clearing the cookie or private-browsing resets the counter. Per-IP backstop catches bulk spam from one IP but not distributed attacks. Mitigation lever: `FEEDBACK_REQUIRE_TURNSTILE=true` env flag — flip to require Cloudflare Turnstile token on anonymous submissions. **Default in v1: off.**

**Response on exceed:**
- HTTP 429 with `Retry-After: <seconds until next UTC midnight>`.

### 4.4 Auth resolution

- `get_optional_user()` from [`website/api/auth.py`](../../../website/api/auth.py) line 183 — returns the JWT claims dict or None.
- **Authenticated path:**
  - `full_name` = `_resolve_full_name(claims)` from [`website/features/web_monitor/User_Activity.py`](../../../website/features/web_monitor/User_Activity.py) line 223.
  - `email` = `claims["email"]`.
  - `country_code` = `core.profiles.country_code` if set (read via `CoreRepository`), else `request.headers.get("cf-ipcountry", "??")` labelled as "(approx.)".
- **Anonymous path:**
  - `full_name` = `anon_name or "Anonymous"`.
  - `email` = `anon_email if follow_up_email else None` (validated `EmailStr` if provided).
  - `country_code` = `cf-ipcountry` only, labelled "(approx.)" in Slack.
- Country format in Slack: `Full Country Name — XX` (e.g. `India — IN`). Reuse the existing `format_country()` helper from [`website/features/web_monitor/_country.py`](../../../website/features/web_monitor/_country.py).

### 4.5 Image validation pipeline

For each `UploadFile`, in order — reject early:

1. Raw byte count ≤ 5 MB. (Stream-counter; abort + 413 on overflow.)
2. Extension whitelist on the **client-provided** filename: `.jpg`, `.jpeg`, `.png`, `.webp`. (Used for the saved filename; trust nothing about content yet.)
3. **Magic-byte sniff** via `python-magic` (libmagic): the actual file content must match one of `image/jpeg`, `image/png`, `image/webp`. Reject `image/gif`, `image/svg+xml`, `image/x-icon` even if the extension matches.
4. **Pillow rewrite**: `Image.open(buf).verify()` → re-open (verify invalidates the instance) → `.convert("RGB")` → save without EXIF (`img.save(out, format="JPEG", optimize=True, exif=b"")`). This is the OWASP canonical "image rewriting" pattern; it both validates the bytes parse cleanly and strips PII metadata (GPS, device, camera).
5. **Server-generated filename**: `f"{uuid4()}.{sniffed_ext}"`. Never trust the client filename for storage.
6. Resulting bytes feed `files_upload_v2`.

Dependency additions:
- `ops/Dockerfile` Stage 1: append `apt-get install -y libmagic1`.
- `ops/requirements.txt`: add `python-magic==0.4.27` and bump `Pillow` if older than 10.4 (CVE-2024-28219 buffer-overflow patched in 10.3+).

### 4.6 Slack delivery

New module `website/features/feedback/slack_client.py` — bot-token client. Mirrors the retry/backoff discipline of [`website/features/web_monitor/_slack_client.py`](../../../website/features/web_monitor/_slack_client.py) (stamina decorator, jittered exponential backoff, max 4 attempts, honor `Retry-After`).

Two SDK calls per submission (use the `slack_sdk` Python library):

```python
import slack_sdk.web.async_client as sdk

client = sdk.AsyncWebClient(token=settings.slack_bot_token_feedback)

# 1. Upload images via files_upload_v2 (the SDK convenience wrapper handles
#    files.getUploadURLExternal + PUT + files.completeUploadExternal).
file_ids = []
for img_bytes, filename in validated_images:
    res = await client.files_upload_v2(
        channel=settings.slack_channel_feedback,  # shares file with the channel
        content=img_bytes,
        filename=filename,
    )
    file_ids.append(res["file"]["id"])

# 2. Post the message referencing files via slack_file blocks.
blocks = build_feedback_blocks(intent, subject, description,
                                full_name, country_code, feedback_id,
                                follow_up_email, anon_email, file_ids)
await client.chat_postMessage(
    channel=settings.slack_channel_feedback,
    blocks=blocks,
    text=f"New feedback from {full_name}",  # fallback text for notifications
)
```

Both calls run inside `fire_and_forget()` so the route returns 202 fast.

### 4.7 Block Kit payload

`build_feedback_blocks()` produces:

```json
{
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": "📣 New feedback — Issue" }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "*From:* Naruto Uzumaki  •  *Country:* India — IN  •  *ID:* `FB-7K3Q`  •  *Email:* user@example.com  •  <!date^1716800000^{date_short_pretty} at {time}|just now>"
        }
      ]
    },
    { "type": "divider" },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Subject:* Add Zettel fails on long YouTube videos\n> I tried adding a 3-hour Lex Fridman episode and the API returns a 504 after about 90 seconds…"
      }
    },
    {
      "type": "image",
      "alt_text": "Screenshot 1",
      "slack_file": { "id": "F12345ABC" }
    }
  ]
}
```

**Variants:**
- Header emoji: `📣` for Issue, `💡` for Suggestion.
- Anonymous: `*From:* Anonymous`; if `anon_email` present, append `  •  *Reply:* anon@example.com`.
- No email follow-up → omit the `*Email:*` segment entirely.
- 0 images → omit all `image` blocks.
- 2–3 images → 2–3 `image` blocks in sequence (each referencing its own `slack_file.id`).

**Image rendering note:** standalone `image` blocks render reliably across Slack web, iOS, and Android. Section-block `accessory` images have a documented iOS bug (per Slack Bolt-JS issue #2631) — we use **top-level image blocks**, not accessories.

### 4.8 Configuration

Per the strict-containment rule, env vars are loaded by a **feature-local** `FeedbackSettings` class at `website/features/feedback/core/settings.py`. The global `website/core/settings.py` is NOT modified.

```python
# website/features/feedback/core/settings.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class FeedbackSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    slack_bot_token_feedback: str = ""
    slack_channel_feedback: str = ""
    secret_feedback_cookie: str = ""
    feedback_require_turnstile: bool = False

@lru_cache
def get_feedback_settings() -> FeedbackSettings:
    return FeedbackSettings()
```

`ops/.env.example` lists each var with a comment. None are validated as required at boot — if `slack_bot_token_feedback` is empty, the route returns 503 with "Feature unavailable" but the app boots fine.

Operational setup: see [`docs/mockups/feedback/SLACK_SETUP.md`](../../mockups/feedback/SLACK_SETUP.md).

### 4.9 Body-size handling

- Client compresses each image to a ~1.5 MB target (max-edge 1600 px, JPEG q=0.85) before upload.
- Worst case: 3 × 5 MB raw + form fields ≈ 16 MB.
- Current edge cap is **11 MB** in Caddy ([`ops/caddy/Caddyfile`](../../../ops/caddy/Caddyfile) line 91), which would reject this.
- **Solution: add a route-level body-size sub-route to Caddyfile** for `/api/feedback/submit` only:

```caddyfile
@feedback path /api/feedback/submit
handle @feedback {
    request_body {
        max_size 18MB
    }
    reverse_proxy {upstream}
}
```

- Do **NOT** raise the global ASGI body-size guard — that's a CLAUDE.md "protected knob" (the `narrow async_backpressure defense-in-depth` work). Route-level scope keeps the protection in place for every other endpoint.

## 5. Testing

### 5.1 Unit (`tests/unit/feedback/`)
- `test_image_pipeline.py` — magic-byte rejection, EXIF strip verification (assert no GPS in output bytes), Pillow-rewrite on a synthetic malformed PNG.
- `test_rate_limit.py` — auth/anon paths, sliding-window boundary, cookie HMAC validation, daily reset.
- `test_block_kit.py` — payload shape for 0/1/3 images, Issue vs Suggestion, auth/anon, email present/absent.
- `test_models.py` — Pydantic validation (subject length, description length, intent enum, anon_email format).
- `test_feedback_id.py` — generator produces correct format `FB-[A-Z2-7]{4}`.

### 5.2 Integration (`tests/integration/feedback/`)
- `test_route_e2e.py` — full multipart POST with mocked Slack client; verifies 202, fire-and-forget runs, Slack mock called with expected payload.
- `test_route_disabled.py` — `SLACK_BOT_TOKEN_FEEDBACK` empty → 503.

### 5.3 Live (`@pytest.mark.live`, run only with `--live`)
- `test_slack_live.py` — real Slack post to a `#bot-test` channel using a test bot token; asserts `ts` returned and message visible.

### 5.4 E2E (Claude-in-Chrome harness)
- Logged-in flow: open `/` → click megaphone → fill form → submit → assert success state shows.
- Anonymous flow: log out → click megaphone → fill (including anon_name) → submit → assert cookie `zk_feedback_token` set on response.
- Rate-limit hit: submit 11 times in sequence (mocking date) → 11th returns 429.
- Mobile bottom-sheet: open `/m/home` → tap megaphone → assert sheet slides up; swipe handle dismisses.

### 5.5 Manual
- Visual review of all 4 mockup pages + the SLACK_SETUP.md walkthrough.
- After deploy, smoke-test on production: one submission of each type from each surface; verify Slack rendering on Slack web, iOS, Android.

## 6. Files changed (strict-containment)

**Inside `website/features/feedback/` (all new — implementation PR):**

| Path | Purpose |
|---|---|
| `__init__.py` | Exports `register(app)` — the sole integration entry point |
| `README.md` | Feature-local docs (architecture + how to run tests) |
| `service.py` | Top-level orchestrator |
| `api/routes.py` | `POST /api/feedback/submit` + `GET /api/feedback/health` |
| `api/deps.py` | FastAPI dependencies (rate-limit gate, identity resolver) |
| `api/cookie.py` | Signed HMAC cookie issuer + validator |
| `core/settings.py` | Feature-local pydantic Settings (reads env directly) |
| `core/identity.py` | Resolve full_name + country |
| `core/ids.py` | Generate FB-XXXX confirmation IDs |
| `intake/models.py` | Pydantic request/response DTOs |
| `intake/validation.py` | Subject + description + extension whitelist |
| `intake/image_pipeline.py` | libmagic + Pillow rewrite + EXIF strip |
| `intake/rate_limit.py` | Daily sliding-window (user/cookie/IP) |
| `slack/client.py` | AsyncWebClient wrapper with retry |
| `slack/block_kit.py` | Build Slack Block Kit payload |
| `ui/static/feedback.css` | All styles — desktop modal + mobile sheet |
| `ui/static/feedback.js` | Controller — auto-inject button + open/close + submit |
| `ui/static/icons.svg` | Megaphone sprite (solid + outline) |
| `ui/templates/modal.html` | Desktop popup markup |
| `ui/templates/sheet.html` | Mobile bottom-sheet markup |
| `tests/conftest.py` | Feature-local fixtures |
| `tests/unit/test_image_pipeline.py` | Image pipeline tests |
| `tests/unit/test_rate_limit.py` | Rate-limit tests |
| `tests/unit/test_block_kit.py` | Block Kit payload tests |
| `tests/unit/test_models.py` | Pydantic model tests |
| `tests/unit/test_ids.py` | ID generator tests |
| `tests/unit/test_identity.py` | Identity-resolver tests |
| `tests/unit/test_cookie.py` | Cookie HMAC tests |
| `tests/integration/test_route_e2e.py` | Full multipart POST flow with mocked Slack |
| `tests/integration/test_route_disabled.py` | 503 when Slack creds unset |
| `tests/live/test_slack_live.py` | Real Slack post (`--live` only) |

**Outside `website/features/feedback/` (minimal — implementation PR):**

| Path | Change | Why unavoidable |
|---|---|---|
| `website/app.py` | One line: `from website.features.feedback import register; register(app)` | FastAPI requires explicit router/static registration at app construction; cannot be done from within an isolated module without `app` reference. **Plus** ~8 lines of `register_footer_post_processor(fn)` enabling infrastructure if not already present — this is generic plumbing other feature modules can reuse. |
| `ops/.env.example` | Add `SLACK_BOT_TOKEN_FEEDBACK`, `SLACK_CHANNEL_FEEDBACK`, `SECRET_FEEDBACK_COOKIE`, `FEEDBACK_REQUIRE_TURNSTILE` documentation lines | Operator runbook lives in `ops/` by convention |
| `ops/Dockerfile` | Add `libmagic1` to Stage-1 `apt-get install` | System-level dependency for `python-magic` |
| `ops/requirements.txt` | Add `python-magic==0.4.27`, ensure `Pillow >= 10.3` (CVE-2024-28219), add `slack_sdk>=3.27` | Python deps live where pip looks for them |
| `ops/caddy/Caddyfile` | Add a route-level `request_body { max_size 18MB }` block scoped to `/api/feedback/submit` | Edge body-size cap is a Caddy concern; CLAUDE.md "protected knob" rules forbid raising the global ASGI cap |

**Explicitly NOT touched (verify via diff):**
- `website/footer/footer.html`
- `website/mobile/templates/_shell.html`
- `website/static/css/style.css`
- `website/static/css/zk_summary_popup.css`
- `website/static/js/*`
- `website/mobile/css/components/*`
- `website/mobile/js/*`
- `website/core/settings.py`
- `website/core/persist.py`
- `website/api/*` (no new route registration anywhere except via the `register(app)` call)
- Any existing route, dependency, or middleware in the app

The implementation PR's `git diff --stat` should show new files almost entirely under `website/features/feedback/` (or `ops/`), with no modifications to `website/footer/`, `website/static/`, `website/mobile/`, `website/core/`, or `website/api/`.

**Reference docs (this PR — already authored):**
- `docs/mockups/feedback/{README.md, desktop.html, mobile.html, icons.html, selector-variants.html, SLACK_SETUP.md}` — mockups + operator runbook. Retained in the repo per operator's "might change eventually".
- `docs/superpowers/specs/2026-05-27-feedback-button-design.md` — this file.

## 7. Rollout

1. Operator completes the Slack setup in [`SLACK_SETUP.md`](../../mockups/feedback/SLACK_SETUP.md) — generates bot token + channel ID + cookie secret.
2. Operator appends three env vars to `/etc/secrets/api_env` on the production droplet: `SLACK_BOT_TOKEN_FEEDBACK`, `SLACK_CHANNEL_FEEDBACK`, `SECRET_FEEDBACK_COOKIE`.
3. Implementation PR merges to `master`. CI runs unit + integration tests with stubbed Slack creds; live tests skipped per default.
4. Blue/green deploy on the droplet picks up the new container with the new env vars.
5. Smoke test on production: submit one Issue + one Suggestion from `/` and from `/m/home`. Verify Slack rendering on three clients (web, iOS, Android).
6. Watch `app-errors` Slack channel for the first 24 hours.
7. If a 5xx rate >5% appears for `/api/feedback/submit`, the operator can disable the feature instantly by setting `SLACK_BOT_TOKEN_FEEDBACK=""` and triggering a redeploy — the route then 503s gracefully.

## 8. Open follow-ups (do NOT block v1)

- **Cookie-bypass abuse:** monitor anon submission rate per IP for 30 days. If we see clear distributed spam, flip `FEEDBACK_REQUIRE_TURNSTILE=true` and front-load a Turnstile widget in the modal.
- **Multi-language**: the form copy is English-only. Add i18n keys in a follow-up if/when the rest of the site is localised.
- **Per-intent rate limits**: if operator clarifies that question 7 meant "10 Suggestions/day specifically", change the rate-limit key to include `intent` and split the budget.
- **Slack thread replies**: future feature — when operator replies in the Slack thread, send the reply to the user via email (requires DB row mapping `feedback_id → user_id → ts`). Out of scope for v1.
- **Admin redaction**: no DB → no programmatic redaction path for v1. If a sensitive submission lands in Slack, operator deletes the Slack message manually + cycles `SECRET_FEEDBACK_COOKIE` if the submission was anonymous and the operator wants to invalidate the cookie chain.

---

## Spec self-review (per brainstorming skill)

- **Placeholder scan**: No "TBD", "TODO", or vague sentences remain. Implementation PR number is the only TBD field, intentionally (it's filed after spec approval).
- **Internal consistency**: Cross-checked sections 3 (UX) and 4 (Backend) — form fields match request body; success state matches 202 response; failure states match the rate-limit + image-pipeline error codes.
- **Scope check**: Single implementation plan-sized. ~6 new modules + ~8 modified files + ~10 test files. Fits one focused PR.
- **Ambiguity check**: The rate-limit reading ("10/day total per user, not per intent") is explicitly stated in §4.3 and called out in §8 as the reversible decision if the operator meant otherwise.
