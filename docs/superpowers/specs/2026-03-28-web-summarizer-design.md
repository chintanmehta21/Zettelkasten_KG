# Web Summarizer Frontend — Design Spec

**Date**: 2026-03-28
**Status**: Draft
**Goal**: Add a web UI to the Zettelkasten bot that accepts a URL, runs the existing extraction/summarization pipeline, and displays the result — all hosted on the same Render service.

---

## 1. Architecture Overview

**Stack**: FastAPI (backend) + vanilla HTML/CSS/JS (frontend, no build step)

The web frontend is a new `website/` folder at the repo root. It adds a FastAPI application that:

1. Serves a single-page web UI at `/`
2. Exposes `POST /api/summarize` for URL processing
3. Forwards Telegram webhook requests to PTB (coexistence)
4. Returns structured JSON summaries to the browser

### Why this stack

- **FastAPI**: Async-native (matches the existing async pipeline), lightweight, no new runtime needed
- **Vanilla HTML/CSS/JS**: Zero build toolchain, served as static files, keeps Docker simple
- **Single service**: Both bot and web UI run in one process on one port — critical for Render free tier (1 service limit)

---

## 2. Folder Structure

```
website/
├── app.py              # FastAPI application factory
├── api/
│   ├── __init__.py
│   └── routes.py       # API endpoints
├── core/
│   ├── __init__.py
│   └── pipeline.py     # Web-adapted pipeline wrapper
├── static/
│   ├── index.html      # Single-page UI
│   ├── css/
│   │   └── style.css   # Dark theme styles
│   └── js/
│       └── app.js      # Client-side logic
```

---

## 3. API Design

### `POST /api/summarize`

**Request**:
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}
```

**Response** (200):
```json
{
  "title": "Video Title",
  "summary": "AI-generated summary of the content...",
  "tags": ["source/youtube", "domain/music"],
  "source_type": "youtube",
  "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "brief_summary": "Short 1-2 sentence summary for preview"
}
```

**Error Response** (422/500):
```json
{
  "error": "Description of what went wrong"
}
```

### `GET /api/health`

Returns `{"status": "ok"}` — used by Render health checks.

### `GET /`

Serves `static/index.html`.

---

## 4. Pipeline Integration

`website/core/pipeline.py` wraps the existing orchestrator for web use:

1. Import `resolve_redirects`, `normalize_url` from `utils/url_utils.py`
2. Import `detect_source_type` from `sources/registry.py`
3. Import `get_extractor` from `sources/__init__.py`
4. Import `GeminiSummarizer` from `pipeline/summarizer.py`
5. Import `build_tag_list` from `pipeline/summarizer.py`

The wrapper:
- Accepts a raw URL string
- Resolves redirects → normalizes → detects source type → extracts → summarizes → builds tags
- Returns a dict (not a ProcessedNote, since we don't write to KG from the web)
- Does NOT write notes to disk or GitHub (web is read-only summarization)
- Does NOT check/update the duplicate store (web requests are stateless)

---

## 5. Coexistence Strategy

### Single-process approach

`main.py` is modified to:

1. Create the FastAPI app (from `website/app.py`)
2. Mount Telegram webhook handler at `/{bot_token}` on the FastAPI app
3. Start uvicorn serving the FastAPI app on `$WEBHOOK_PORT`

When `WEBHOOK_MODE=false` (local dev), the bot runs in polling mode and the FastAPI app runs separately on port 8000.

When `WEBHOOK_MODE=true` (Render), both share the same port via a unified ASGI app.

### Health check compatibility

Render's `healthCheckPath: /` currently expects a response from PTB's webhook listener. After this change, `/` returns the web UI HTML (200), which satisfies the health check.

---

## 6. UI Design

### Layout

Single-page design with three states:

1. **Input state**: Centered URL input + submit button, hero text "Summarize any link"
2. **Loading state**: Animated skeleton/pulse, source type indicator
3. **Result state**: Summary card with title, tags, full summary, source link

### Dark Theme

CSS custom properties:

```
--bg-primary: #0a0a0f          (deep navy-black)
--bg-secondary: #12121a        (card backgrounds)
--bg-tertiary: #1a1a2e         (input backgrounds, hover states)
--accent: #6c63ff              (purple accent — buttons, links)
--accent-hover: #7c74ff        (lighter purple for hover)
--text-primary: #e8e8f0        (main text)
--text-secondary: #8888a0      (muted text)
--text-accent: #a0a0c0         (tags, metadata)
--border: #2a2a3e              (subtle borders)
--success: #4ecdc4             (teal for success states)
--error: #ff6b6b               (red for errors)
```

### Typography

- Font: `Inter` (Google Fonts) for body, `JetBrains Mono` for code/tags
- Heading: 2.5rem hero, 1.5rem card title
- Body: 1rem, 1.6 line-height for readability

### Responsive

- Mobile-first: single column, full-width input
- Desktop: max-width 720px centered container
- Breakpoint at 768px

### Interactions

- Submit via Enter key or button click
- URL validation client-side (basic regex)
- Loading spinner with source type detection message
- Smooth fade-in for results
- Copy summary button
- "Try another" button to reset

---

## 7. Error Handling

| Scenario | Behavior |
|---|---|
| Invalid URL format | Client-side validation, red border + message |
| Extraction fails | API returns 500 with `error` message, UI shows error card |
| Gemini API down | Pipeline falls back to raw content (existing behavior) |
| Network timeout | 60s timeout on API call, UI shows timeout message |
| Empty content | API returns summary with note that content couldn't be extracted |

---

## 8. Deployment Changes

### Dockerfile

Add `website/` to the COPY step. Add `fastapi` and `uvicorn` to `requirements-prod.txt`.

### render.yaml

- `healthCheckPath` stays `/` (now served by FastAPI)
- No new services needed
- No new env vars needed (reuses existing Gemini API key)

### main.py changes

- Import and create FastAPI app
- In webhook mode: run uvicorn with the FastAPI app (which includes webhook route)
- In polling mode: optionally run FastAPI in background thread for local dev

---

## 9. Security

- No authentication on the web UI (public summarizer)
- Rate limiting: simple in-memory counter (max 10 requests/minute per IP)
- Input sanitization: URL validation, max length 2048 chars
- No user data stored — stateless summarization
- CORS: allow same-origin only (default FastAPI behavior)

---

## 10. Testing

- Unit tests for `website/core/pipeline.py` (mock extractors + summarizer)
- Integration test: POST to `/api/summarize` with test URLs
- Manual testing: YouTube, GitHub, Reddit, Newsletter, Generic URLs
- Verify Telegram bot still works after coexistence changes

---

## 11. Out of Scope

- User accounts / authentication
- Saving summaries to a database
- Summary history
- Multiple URL batch processing
- Custom summarization prompts
