# Summarization Engine v2 — Design Spec

**Date:** 2026-04-10
**Status:** Draft for review
**Location:** `website/features/summarization_engine/`
**Supersedes (eventually):** `telegram_bot/pipeline/`, `telegram_bot/sources/` — but they remain untouched in v1

---

## 1. Overview

A dynamic, source-aware summarization engine that ingests URLs from nine distinct content sources, produces structured Zettelkasten-ready summaries via Gemini 2.5 Pro + Flash (tiered), and persists results to Supabase. URLs are fed via a batch input file (CSV or JSON) or the existing website URL textbox. The engine is a pure library — it returns structured `SummaryResult` objects and the caller composes writers.

### 1.1 Goals

1. **Coverage first.** Missing a key insight from the source is a critical failure. Minor over-inclusion is acceptable.
2. **Nine source types** with dedicated ingestion and summarization logic: GitHub, Newsletters, Reddit, YouTube, Hacker News, LinkedIn, arXiv, Podcasts, Twitter/X.
3. **Zero blast radius.** The existing `telegram_bot/` pipeline stays untouched. New engine lives at `website/features/summarization_engine/` and exposes itself via `/api/v2/*` endpoints alongside the existing `/api/summarize`.
4. **Token-efficient batch processing.** Batches ≥ 50 URLs route through the Gemini Batch API (50% discount, ~24h turnaround). Smaller batches and real-time requests use the realtime API.
5. **Multi-user** via the existing `kg_users` schema and Supabase RLS.

### 1.2 Non-goals for v1

- Audio transcription for podcasts (Whisper local or API)
- Twitter thread reconstruction via authenticated `twscrape`
- LinkedIn Playwright-authenticated extraction
- OCR for scanned arXiv PDFs
- Migrating the existing Telegram bot to call v2 engine
- Migrating existing `/api/summarize` endpoint to v2 engine
- Replacing the existing Nexus batch module
- Multi-stage Gemini Batch API pipelining (Phase 1 → 2 → 3 → 4 as separate batches)
- Automated BERTScore or G-Eval quality scoring (manual spot-check only)
- Webshare proxy integration for YouTube (env-var-optional, not required)

### 1.3 Architectural decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Engine alongside old code** | User explicitly chose "engine alongside old (no deletion)". Zero blast radius. Old bot keeps working. |
| 2 | **Tiered Gemini 2.5 Pro + Flash** | Pro for reasoning-heavy phases (CoD, self-check, patch), Flash for format-constrained extraction. ~5-7x cheaper than pure-Pro, negligible quality loss. |
| 3 | **Extend `kg_nodes` schema** | Single-table, type-safe, backwards compatible. ALTER TABLE adds `mini_title`, `brief_summary`, `detailed_summary JSONB`, telemetry fields. |
| 4 | **Best-effort degradation for hard sources** | Twitter via oEmbed + Nitter fallback; LinkedIn via Googlebot UA + JSON-LD; Podcasts via show notes only (no audio). Ships v1 with zero new paid services. |
| 5 | **Multi-user** | Reuse existing `kg_users` + RLS. Engine takes `user_id: UUID` as param. Telegram bot (when migrated later) uses a default bot-user UUID. |
| 6 | **Pure engine, composable writers** | Engine returns `SummaryResult` dict; writers (`SupabaseWriter`, `ObsidianWriter`, `GithubRepoWriter`) are separate. Callers compose. Clean separation, testable. |
| 7 | **Reuse existing key pool** | `website/features/api_key_switching/key_pool.py` is already production-hardened (10-key rotation, 429 fallback). Wrap it in a tiered client; don't rewrite. |
| 8 | **Reuse existing website** | New `/api/v2/summarize`, `/api/v2/batch` endpoints added to existing FastAPI app. Batch dashboard under `/v2/batch`. No separate server. |

---

## 2. Folder structure

```
website/features/summarization_engine/
├── __init__.py                       # Public API: summarize_url, batch_summarize, get_router
├── About.md                          # Feature description
├── config.yaml                       # Engine config (see §7)
├── core/
│   ├── __init__.py
│   ├── orchestrator.py               # Single-URL pipeline: route → ingest → summarize → return
│   ├── gemini_client.py              # Tiered Pro+Flash client wrapping api_key_switching.key_pool
│   ├── router.py                     # URL → SourceType detection
│   ├── models.py                     # Pydantic: IngestResult, SummaryResult, BatchRun, etc.
│   ├── errors.py                     # Typed exceptions
│   └── logging.py                    # Structured logger with per-URL correlation id
├── source_ingest/
│   ├── __init__.py                   # Auto-discovery registry: get_ingestor(source_type)
│   ├── base.py                       # BaseIngestor ABC: .ingest(url) -> IngestResult
│   ├── github/          ingest.py
│   ├── newsletters/     ingest.py
│   ├── reddit/          ingest.py
│   ├── youtube/         ingest.py
│   ├── hackernews/      ingest.py
│   ├── linkedin/        ingest.py
│   ├── arxiv/           ingest.py
│   ├── podcasts/        ingest.py
│   └── twitter/         ingest.py
├── summarization/
│   ├── __init__.py                   # Auto-discovery registry: get_summarizer(source_type)
│   ├── base.py                       # BaseSummarizer ABC: .summarize(ingest_result) -> SummaryResult
│   ├── common/
│   │   ├── chain_of_density.py       # Phase 1: CoD-inspired 2-pass prose densification
│   │   ├── self_check.py             # Phase 2: inverted FactScore coverage check
│   │   ├── patch.py                  # Phase 3: conditional patching
│   │   ├── structured_extract.py     # Phase 4: Flash-tier metadata extraction via response_schema
│   │   ├── prompts_base.py           # Shared prompt templates
│   │   ├── tag_utils.py              # Dedup, normalize, enforce 8-15 count
│   │   └── validators.py             # Post-hoc Pydantic validation (word counts, tag format)
│   ├── github/          summarizer.py, prompts.py
│   ├── newsletters/     summarizer.py, prompts.py
│   ├── reddit/          summarizer.py, prompts.py
│   ├── youtube/         summarizer.py, prompts.py
│   ├── hackernews/      summarizer.py, prompts.py
│   ├── linkedin/        summarizer.py, prompts.py
│   ├── arxiv/           summarizer.py, prompts.py
│   ├── podcasts/        summarizer.py, prompts.py
│   └── twitter/         summarizer.py, prompts.py
├── writers/
│   ├── __init__.py
│   ├── base.py                       # BaseWriter ABC
│   ├── supabase_writer.py            # Primary: writes to extended kg_nodes
│   ├── obsidian_writer.py            # Optional: writes .md to disk
│   └── github_repo_writer.py         # Optional: pushes .md via GitHub Contents API
├── batch/
│   ├── __init__.py
│   ├── processor.py                  # BatchProcessor: reads input → fans out → collects results
│   ├── input_loader.py               # CSV/JSON auto-detection + validation
│   ├── concurrency.py                # Semaphore + rate-limit orchestration
│   └── progress.py                   # SSE event emitter for real-time UI updates
├── api/
│   ├── __init__.py
│   └── routes.py                     # FastAPI router: /api/v2/summarize, /api/v2/batch/*
├── ui/
│   ├── index.html                    # URL textbox + CSV/JSON upload + results table
│   ├── css/engine.css                # Teal accent (no purple)
│   └── js/engine.js                  # SSE subscription + progress bar + filter/search
└── tests/
    ├── conftest.py                   # Fixtures: sample URLs, mock Gemini responses
    ├── unit/
    ├── unit/ingest/
    ├── integration/
    └── live/                         # --live flag, CI-opt-in
```

---

## 3. Data models

### 3.1 `SourceType` enum (`core/models.py`)

```python
class SourceType(str, Enum):
    GITHUB = "github"
    NEWSLETTER = "newsletter"        # Substack, Medium, personal blogs
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    HACKERNEWS = "hackernews"
    LINKEDIN = "linkedin"
    ARXIV = "arxiv"
    PODCAST = "podcast"
    TWITTER = "twitter"
    WEB = "web"                      # generic fallback
```

### 3.2 `IngestResult` — output of `source_ingest/`

```python
class IngestResult(BaseModel):
    source_type: SourceType
    url: str                                      # normalized, post-redirect
    original_url: str                             # as provided by user
    raw_text: str                                 # canonical concatenated text for LLM
    sections: dict[str, str] = {}                 # e.g. {"readme": "...", "issues": "...", "commits": "..."}
    metadata: dict[str, Any] = {}                 # author, date, title, engagement, etc.
    extraction_confidence: Literal["high", "medium", "low"]
    confidence_reason: str                        # free text: why this level
    fetched_at: datetime
    ingestor_version: str = "2.0.0"
```

### 3.3 `SummaryResult` — output of `summarization/`

```python
class DetailedSummarySection(BaseModel):
    heading: str                                  # top-level theme
    bullets: list[str]                            # direct points
    sub_sections: dict[str, list[str]] = {}       # nested: sub-heading → bullets

class SummaryResult(BaseModel):
    mini_title: str = Field(..., max_length=60)           # post-validated ≤5 words
    brief_summary: str = Field(..., max_length=400)       # post-validated ≤50 words
    tags: list[str] = Field(..., min_length=8, max_length=15)  # lowercase-kebab
    detailed_summary: list[DetailedSummarySection]        # exhaustive nested bullets
    metadata: SummaryMetadata

class SummaryMetadata(BaseModel):
    source_type: SourceType
    url: str
    author: str | None = None
    date: datetime | None = None
    extraction_confidence: Literal["high", "medium", "low"]
    confidence_reason: str
    total_tokens_used: int
    gemini_pro_tokens: int
    gemini_flash_tokens: int
    total_latency_ms: int
    cod_iterations_used: int
    self_check_missing_count: int
    patch_applied: bool
    engine_version: str = "2.0.0"
```

### 3.4 `BatchRun` and `BatchItem`

```python
class BatchRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"

class BatchRun(BaseModel):
    id: UUID
    user_id: UUID
    status: BatchRunStatus
    input_filename: str | None
    input_format: Literal["csv", "json"] | None
    mode: Literal["realtime", "batch_api"]
    total_urls: int
    processed_count: int
    success_count: int
    skipped_count: int
    failed_count: int
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None
    config_snapshot: dict

class BatchItem(BaseModel):
    id: UUID
    run_id: UUID
    user_id: UUID
    url: str
    source_type: SourceType | None
    status: Literal["pending", "ingesting", "summarizing", "writing", "succeeded", "failed", "skipped"]
    node_id: str | None
    error_code: str | None
    error_message: str | None
    tokens_used: int | None
    latency_ms: int | None
    user_tags: list[str] = []
    user_note: str | None = None
```

---

## 4. Source ingestion strategies

Every ingestor implements:

```python
class BaseIngestor(ABC):
    source_type: ClassVar[SourceType]

    @abstractmethod
    async def ingest(self, url: str, *, config: dict) -> IngestResult:
        ...
```

Registry auto-discovery: `source_ingest/__init__.py` scans the package at import time, finds every `BaseIngestor` subclass with a `source_type` attribute, and registers it in `_REGISTRY`. `get_ingestor(source_type)` returns the registered class.

### 4.1 GitHub (`source_ingest/github/ingest.py`)

| Layer | Details |
|---|---|
| **Primary** | GitHub REST API v3. Calls in order: `/repos/{o}/{r}`, `/repos/{o}/{r}/readme`, `/repos/{o}/{r}/languages`, `/repos/{o}/{r}/topics` (Mercy preview header), `/repos/{o}/{r}/issues?state=open&sort=updated&per_page=20`, `/repos/{o}/{r}/commits?per_page=10`, `/repos/{o}/{r}/license` |
| **Monorepo detection** | Check root `/contents/` for `packages/`, `apps/`, `crates/`, `lerna.json`, `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, or `Cargo.toml` with `[workspace]`. Regex README for `\b(monorepo\|multi-package)\b`. If detected, fetch top 3 subpackage READMEs by directory size. |
| **Fallbacks** | (1) auth'd token → (2) unauth'd (60/hr per IP, tightened in May 2025) → (3) `raw.githubusercontent.com/{o}/{r}/HEAD/README.md` → (4) scrape `github.com/{o}/{r}` with trafilatura |
| **Library** | Raw `httpx` — 6-8 stateless calls, easy rate-limit observation via `X-RateLimit-Remaining` / `X-RateLimit-Reset` headers |
| **Edge cases** | 404 private/deleted → fail fast; 403 with RateLimit 0 → cooldown-and-retry; 451 DMCA → confidence=low, reason="dmca"; empty README → fetch `/contents/` as fallback body |
| **Confidence** | `high` = README ≥500 chars + topics ≥1 + languages map present<br>`medium` = README <500 chars or missing topics<br>`low` = README missing, 404, rate-limited |

### 4.2 Newsletters / Medium / Substack / Blogs (`source_ingest/newsletters/ingest.py`)

| Layer | Details |
|---|---|
| **Primary** | `trafilatura.extract(html, favor_precision=True, include_comments=False, include_tables=False, output_format='markdown')`. Benchmark F1 0.945 per 2024 SANDIA eval — highest of the pack. Set UA to `Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)` — Medium and Substack serve more to verified crawlers. |
| **Substack detection** | Parse JSON-LD `application/ld+json` for `isAccessibleForFree`. If `False`, skip direct fetch and jump to archive fallbacks immediately. Also try `/feed` per publication. |
| **Medium detection** | Full article text usually in `<article>` for crawler UAs. freedium.cfd is unreliable as of 2025/2026, skip. |
| **Fallback chain** | (1) trafilatura direct → (2) `web.archive.org/web/{url}` via Wayback memento API → (3) `archive.ph/newest/{url}` → (4) `readability-lxml` 0.8+ → (5) `newspaper4k` (note: newspaper3k is dead) |
| **Library** | `trafilatura>=2.0`, `readability-lxml>=0.8`, `newspaper4k>=0.9.3` |
| **Failure detection** | Extracted text <300 chars, or equals `og:description` verbatim, or matches paywall keywords: `"subscribe to read"`, `"sign in to continue"`, `"this post is for paid subscribers"`, `"continue reading with a free account"` |
| **Confidence** | `high` = ≥1500 chars + title + author + pub_date<br>`medium` = ≥500 chars but missing byline/date<br>`low` = <500 chars, paywall keywords matched, or Wayback-only |

### 4.3 Reddit (`source_ingest/reddit/ingest.py`)

| Layer | Details |
|---|---|
| **Primary** | Append `.json` to any Reddit URL → `old.reddit.com/{path}.json?limit=100&sort=top`. Returns `[post_listing, comments_listing]`. **Must** set `User-Agent: zettelkasten-engine/2.0 (by u/chintanmehta21)` — generic UAs get 429'd. |
| **Rate limits** | ~10 req/min per IP unauth. OAuth app: 60/min; registered client: 100/min. |
| **Fallback** | (1) `old.reddit.com/.json` → (2) `www.reddit.com/.json` → (3) PRAW 7.7.1+ with `client_credentials` grant (read-only, app-only) → (4) Wayback snapshot + trafilatura |
| **Comment tree** | Nested via `data.children[]`. Each child: `{kind: "t1", data: {..., replies: Listing}}`. **Gotcha**: `data.replies == ""` (empty string, not Listing) when no replies. Respect `comment_depth` config (default 3). |
| **Filters** | Drop `author == "[deleted]"`, `body == "[removed]"`, `stickied == True`, `author == "AutoModerator"`. Ignore `kind == "more"` listings. |
| **Library** | `httpx` for primary; `praw>=7.7.1` for fallback only |
| **Confidence** | `high` = selftext ≥200 chars OR top 5 comments total ≥1000 chars<br>`medium` = link post with rich comments but no selftext<br>`low` = [removed]/[deleted] / sparse comments |

### 4.4 YouTube (`source_ingest/youtube/ingest.py`)

| Layer | Details |
|---|---|
| **Primary** | `youtube-transcript-api` 1.x instance API: `YouTubeTranscriptApi().fetch(video_id, languages=['en', 'en-US', 'en-GB'])`. Concat segments into continuous text. Preserve chapter markers via yt-dlp metadata. |
| **⚠️ Datacenter IP blocking** | YouTube blocks AWS/GCP/Azure/DigitalOcean/Render IPs since late 2024. Primary fails from cloud. Pipeline auto-detects via `RequestBlocked`/`IpBlocked` exceptions and jumps straight to Gemini video fallback. |
| **Fallback chain** | (1) youtube-transcript-api → (2) `yt-dlp --write-auto-subs --sub-langs "en.*" --skip-download --sub-format vtt`, parse VTT → (3) **Gemini 2.5 Pro direct video URL** via `Part.from_uri(file_uri=watch_url, mime_type="video/mp4")` (bypasses IP block, Gemini servers fetch YouTube directly) → (4) oEmbed metadata only (`youtube.com/oembed?url=...`) |
| **Gemini video fallback** | `TieredGeminiClient.generate_video_summary(video_url)` — uses video understanding endpoint. Works for 2.5 Flash and Pro. Marked `extraction_confidence="medium"`, reason=`"gemini-video-fallback"`. |
| **Library** | `youtube-transcript-api>=1.0`, `yt-dlp` (pinned but updated weekly in CI — YouTube frequently breaks it) |
| **Edge cases** | `TranscriptsDisabled`, `NoTranscriptFound`, `VideoUnavailable`, `AgeRestricted`, `RequestBlocked`/`IpBlocked` — first three fall through to Gemini video; last two fail at Gemini too (age-restricted rejects direct URL) |
| **Confidence** | `high` = transcript ≥500 words + title + channel<br>`medium` = auto-generated transcript OR Gemini video summary<br>`low` = oEmbed only |

### 4.5 Hacker News (`source_ingest/hackernews/ingest.py`)

| Layer | Details |
|---|---|
| **Primary** | Algolia HN API: `https://hn.algolia.com/api/v1/items/{id}`. Returns story + full nested comment tree in one call. No auth, no documented rate limits (polite throttling at ≤2 req/s). |
| **Linked article** | Submission JSON has `url` field for external links. If non-null → fetch via Newsletter/Web ingestor. If null → self-post with text in `text` field. |
| **Comment ranking** | Algolia returns `points` on each comment. Sort `children[]` desc by points; take top 10-15 root-level; recurse one level for replies with `points > 10`. Skip `author == None` (deleted), `text.startswith("[dead]")`, `text.startswith("[flagged]")`. |
| **Fallback** | Firebase HN API `hacker-news.firebaseio.com/v0/item/{id}.json` — walks `kids[]` manually (N calls, slower but authoritative) |
| **Library** | Raw `httpx` |
| **Confidence** | `high` = linked article ≥1000 chars + ≥5 substantive comments + story points ≥50<br>`medium` = linked article failed but comments are rich<br>`low` = only title+url, <5 comments |

### 4.6 LinkedIn (`source_ingest/linkedin/ingest.py`)

| Layer | Details |
|---|---|
| **Reality** | LinkedIn tightened its login wall in late 2025. Without Playwright + auth cookies, full-body extraction succeeds for ~30-50% of public posts. Rest return only title + 1-3 sentences + author. |
| **Primary** | Fetch `linkedin.com/posts/{slug}` with Googlebot UA. Parse response with BeautifulSoup. |
| **Extraction order** | (1) Parse `<code id="main-content-react-state">` or `application/ld+json` scripts for `articleBody` + `author.name` + `datePublished` — cleanest → (2) `og:description` + `og:title` meta fallback → (3) trafilatura on full HTML |
| **Login wall detection** | Response contains `"authwall"`; `<title>` starts with `"Sign Up \| LinkedIn"`; body <50KB; text matches `"Join now to see what you are missing"` |
| **Fallback** | (1) Archive.org Wayback → (2) Skip 12ft.io / reader-mode proxies (broken for LinkedIn 2026) → (3) Return title + meta only with confidence=low |
| **Library** | `httpx` + `beautifulsoup4` |
| **Confidence** | `high` = JSON-LD articleBody ≥500 chars + author<br>`medium` = og:description + author + meta<br>`low` = authwall hit / title-only |

### 4.7 arXiv (`source_ingest/arxiv/ingest.py`)

| Layer | Details |
|---|---|
| **Primary metadata** | arXiv API: `http://export.arxiv.org/api/query?id_list={id}`. Atom feed parsed with `feedparser` 6.x. Extracts: title, authors, abstract, categories, primary_category, DOI, submission_date, updated_date. **Rate limit: 1 request per 3 seconds** — server-enforced burst → 503. |
| **Primary full text** | Try in order: (1) `arxiv.org/html/{id}` (official HTML, rolled out 2024, newer papers only) → (2) `ar5iv.labs.arxiv.org/html/{id}` (third-party, 1991+) → (3) PDF download + **PyMuPDF** extraction |
| **PDF parser rationale** | PyMuPDF (`fitz`) is 5-10x faster than pdfplumber and handles Unicode/math better. pdfplumber only when table extraction needed (not v1). pypdf last resort. |
| **Long paper strategy** | For papers >30 pages, use PyMuPDF's `get_toc()` to extract section boundaries. Extract abstract + introduction + method/results sections + conclusion. Skip references and appendices. Feed sectioned text (with headings) to summarizer. |
| **Library** | `arxiv>=2.1.0` (built-in 3s delay), `PyMuPDF>=1.24`, `feedparser>=6.0.11` |
| **Edge cases** | `arxiv.UnexpectedEmptyPageError` → retry once; 503 on PDF → back off 10s; OCR-needed scanned PDFs (`len(extracted) / num_pages < 100`) → confidence=low |
| **Confidence** | `high` = abstract + ≥3 sections + title + authors<br>`medium` = abstract + metadata only<br>`low` = API metadata only |

### 4.8 Podcasts (`source_ingest/podcasts/ingest.py`)

| Layer | Details |
|---|---|
| **v1 limitation** | **No audio transcription.** Show notes + metadata only. `extraction_confidence` capped at `medium`. Summarizer prompt explicitly tells Gemini this is show notes, not a transcript. |
| **Primary** | Resolve any podcast URL to canonical RSS feed via **Podcast Index API** (free self-signup, HMAC-SHA1 auth). Endpoints: `/podcasts/byitunesid`, `/episodes/byfeedid`, `/episodes/byguid`. |
| **URL resolution** | Apple Podcasts `podcasts.apple.com/.../id{id}?i={episode_id}` → iTunes Lookup `itunes.apple.com/lookup?id={episode_id}&entity=podcastEpisode` (no auth) returns `feedUrl`. Spotify `open.spotify.com/episode/{id}` → scrape og:title + og:description, then Podcast Index search by title. Overcast `overcast.fm/+XXX` → resolves to Apple/RSS. Snipd share URLs → resolves to source RSS. |
| **RSS parsing** | `feedparser` 6.x. Show notes precedence: (1) `content:encoded` (richest HTML) → (2) `itunes:summary` → (3) `description` → (4) `itunes:subtitle`. Run trafilatura on HTML to strip boilerplate. |
| **Metadata** | title, pub_date, `itunes:duration`, guest (regex in description), `itunes:episode`, chapters (`<psc:chapters>` or regex `^\d{1,2}:\d{2}(:\d{2})?\s+` in description) |
| **Library** | `python-podcastindex>=1.0.0` OR raw httpx + HMAC, `feedparser>=6.0.11`, reuse `trafilatura` |
| **Confidence** | `high` = impossible in v1 (no audio)<br>`medium` = show notes ≥500 chars + title + guest + episode number<br>`low` = title + publish date only |

### 4.9 Twitter / X (`source_ingest/twitter/ingest.py`)

| Layer | Details |
|---|---|
| **Primary** | oEmbed: `https://publish.twitter.com/oembed?url={tweet_url}&omit_script=1&hide_thread=false`. Returns JSON with `html`, `author_name`, `author_url`. Parse blockquote `<p>` for tweet text. **Verified unauthenticated as of April 2026.** |
| **Limitations** | Single tweet only. No metrics. No media URLs. No thread reconstruction. |
| **Thread fallback** | Nitter instances with HEAD health check + rotation. Instance order: `xcancel.com`, `nitter.poast.org`, `nitter.privacyredirect.com`, `lightbrd.com`, `nitter.space`. Fetch `/{user}/status/{id}`; parse `.timeline-item .tweet-content`. **Degraded in 2026** — most public instances rate-limited; fail-fast with fallback to "root tweet only". |
| **twscrape?** | snscrape successor, but requires **account cookies**. Not truly no-auth. Skipped for v1 to avoid ToS risk. |
| **Library** | `httpx` + `beautifulsoup4`. No dedicated SDK. |
| **Edge cases** | oEmbed 404 (deleted/protected/suspended) → fail; oEmbed 403 (rate limit) → backoff 60s; Nitter "Instance has been rate limited" banner → rotate instance |
| **Confidence** | `high` = oEmbed success + tweet text ≥50 chars + author<br>`medium` = thread partially reconstructed via Nitter<br>`low` = author + id only |

### 4.10 Generic Web (`source_ingest/web/` — fallback)

Same stack as Newsletters (trafilatura → Wayback → readability → newspaper4k). Confidence capped at `medium` unless ≥1500 chars + title + author.

---

## 5. Summarization pipeline

### 5.1 Four-phase pipeline per URL

```
IngestResult
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1 — Exhaustive Dense Prose Summary                    │
│   Model: Gemini 2.5 Pro                                     │
│   Technique: CoD-inspired 2-pass densification              │
│   • Pass 1: initial dense summary (~200 words prose)        │
│   • Pass 2: identify missing entities, re-densify at same   │
│     length                                                  │
│   • Early stop: if Pass 2 adds <2 entities, use Pass 1      │
│   Output: { pass_1, pass_2 } JSON                           │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2 — Coverage Self-Check (inverted FactScore)          │
│   Model: Gemini 2.5 Pro                                     │
│   • Extract 8-12 atomic claims from SOURCE                  │
│   • Mark each COVERED/MISSING in the summary                │
│   • Return critical_missing (top-5 missing claims)          │
│   Output: { claims, missing_count, critical_missing } JSON  │
└─────────────────────────────────────────────────────────────┘
    │
    ├─── if missing_count < 3 ───► skip Phase 3
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3 — Patch (conditional)                               │
│   Model: Gemini 2.5 Pro                                     │
│   • Rewrite summary fusing in critical_missing claims       │
│   • Same length, no loss of existing content                │
│   • Runs ONCE — never loops                                 │
│   Output: { summary, included_claims } JSON                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 4 — Structured Metadata Extraction                    │
│   Model: Gemini 2.5 Flash (format-constrained, cheap)       │
│   • response_mime_type="application/json"                   │
│   • response_schema=SummaryResultSchema (Pydantic)          │
│   • Takes final dense prose + url + source_type + title     │
│   • Produces: mini_title, brief_summary, tags,              │
│     detailed_summary (nested bullet structure)              │
│   • Post-validation: word counts, tag format; 1 retry       │
│   Output: SummaryResultSchema instance                      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
SummaryResult
```

### 5.2 Research grounding

- **Chain-of-Density: 2 iterations, not 5** — peer-reviewed replications (PromptHub, Yugen.ai) confirm quality peaks at steps 2-3. Step 5 over-compresses and human evaluators rate it worst.
- **Prose during CoD, bullets at extraction** — forcing bullet output during CoD breaks the density mechanic (structural tokens distort "same length" constraint). Phases 1-3 operate on prose; Phase 4 re-projects into nested bullets.
- **Self-check = inverted FactScore, not Reflexion** — pure Reflexion/CRITIC self-critique edits style instead of adding content for open-ended summarization. FactScore's atomic-claim decomposition, inverted to score the summary against source, detects missing insights reliably.
- **Single conditional Patch, no loop** — >1 rewrite round degrades (self-correction surveys).
- **Structured extract separated from reasoning** — Gemini cookbook issue #354 documents that `response_schema` during reasoning steps degrades output (keys returned alphabetically break CoT). Two calls, clean separation.
- **No hierarchical summarization needed** — Gemini 2.5 Pro's 2M context handles any single source under 200K tokens without chunking.

Full citation list at §5.8.

### 5.3 Phase 1 prompt template (`summarization/common/chain_of_density.py`)

```python
PHASE_1_SYSTEM = """You are a knowledge-management assistant producing summaries
for a personal Zettelkasten. Coverage is the top priority — missing a key insight
from the source is a critical failure. Minor over-inclusion is acceptable."""

PHASE_1_USER = """You will summarize the following {source_type} in 2 progressive passes.

{source_context_block}

SOURCE:
<<<
{source_content}
>>>

INSTRUCTIONS:

Pass 1 — Write an exhaustive dense summary of the source in ~{pass1_word_target}
words (prose, not bullets). Cover:
- Main thesis, argument, or purpose
- ALL key entities (people, orgs, products, numbers, named concepts)
- Mechanisms and reasoning (not just claims)
- Supporting evidence, examples, quotes
- Conclusions, recommendations, or takeaways
- Notable counterpoints or caveats the source itself raises

Pass 2 — Rewrite Pass 1 at the SAME LENGTH but denser. Identify 3-5 salient items
from the source that are MISSING from Pass 1 (new named entities, numerical facts,
causal mechanisms, or named concepts) and fuse them in. Compress generic phrasing
to make room. Every entity from Pass 1 MUST still appear in Pass 2. Do not
fabricate — if you can't find 3-5 missing items, say so and keep Pass 1.

Return ONLY this JSON (no code fences, no prose before or after):
{{
  "pass_1": {{
    "summary": "...",
    "covered_entities": ["..."]
  }},
  "pass_2": {{
    "summary": "...",
    "newly_added": ["..."],
    "covered_entities": ["..."]
  }}
}}"""
```

**Source context blocks** (injected per source type — `summarization/{source}/prompts.py`):

```python
SOURCE_CONTEXT_BLOCKS = {
    "youtube": "This is a YouTube transcript. Speaker attribution may be imperfect (auto-captions). Preserve numeric claims verbatim. Note timestamps where known.",
    "github": "This is a GitHub repository digest (README + metadata + top issues). Preserve code identifiers, dependency names, version numbers, and architectural decisions exactly. Identify the tech stack explicitly.",
    "reddit": "This is a Reddit thread — original post plus top comments. Distinguish the OP's claims from community consensus. Note when comments substantively disagree with or correct the OP.",
    "hackernews": "This is a Hacker News submission — the linked article AND the HN discussion. Summarize them SEPARATELY: first the article's argument, then the discussion's most substantive/contrarian points.",
    "newsletter": "This is a long-form essay or newsletter article. Extract the central thesis, the key supporting arguments in order, the evidence cited, and actionable takeaways (if any).",
    "linkedin": "This is a LinkedIn post. Extract the core professional insight or argument. Note engagement signals if present. Flag if extraction appears incomplete due to login wall.",
    "arxiv": "This is an academic paper (arXiv). Follow academic summarization: problem statement → methodology → key results (with numbers) → limitations → implications. Do NOT hallucinate technical claims — if unclear, say so.",
    "podcast": "This is podcast SHOW NOTES (no audio transcript available). Summarize only what is explicitly in the notes; do not fabricate discussion points or speculate about unspoken content.",
    "twitter": "This is a Twitter/X tweet or thread. Reconstruct the argument arc. Identify the core claim and supporting points. If only the root tweet is available, note that context may be missing.",
    "web": "This is a generic web article. Extract thesis, key arguments, evidence, and conclusions."
}
```

### 5.4 Phase 2 prompt template (`summarization/common/self_check.py`)

```python
PHASE_2_SYSTEM = """You are auditing a summary against its source for coverage
gaps. Your job is to find missing key insights, not to edit or rewrite."""

PHASE_2_USER = """SOURCE:
<<<
{source_content}
>>>

SUMMARY (the thing being audited):
<<<
{summary}
>>>

TASK:
1. From the SOURCE, list the 8-12 most important ATOMIC CLAIMS. An atomic claim
   is a single standalone factual statement (one subject, one predicate, one
   object). Rank them 1 = most central to the source's argument, 12 = least.

2. For each claim, mark:
   - COVERED if the summary contains the same information (exact wording not
     required — just the fact)
   - MISSING if absent from the summary
   - A claim that is only "partially covered" counts as MISSING.

3. List the MISSING claims ranked 1-5 as `critical_missing`.

Return ONLY this JSON:
{{
  "claims": [
    {{"rank": 1, "claim": "...", "status": "COVERED"}},
    {{"rank": 2, "claim": "...", "status": "MISSING"}},
    ...
  ],
  "missing_count": <int>,
  "critical_missing": ["<claim text>", "..."]
}}"""
```

### 5.5 Phase 3 prompt template (`summarization/common/patch.py`)

```python
PHASE_3_SYSTEM = """You rewrite summaries to incorporate missing claims while
preserving everything that's already there."""

PHASE_3_USER = """The following summary was audited and found to be missing
critical claims. Rewrite it at the SAME LENGTH, preserving all existing facts,
while fusing in the missing claims below. Do not add filler; compress existing
phrasing if you need room.

CURRENT SUMMARY:
<<<
{summary}
>>>

MISSING CLAIMS TO INCLUDE:
{critical_missing_bulleted}

Return ONLY this JSON:
{{
  "summary": "...",
  "included_claims": ["...", "..."]
}}"""
```

### 5.6 Phase 4 prompt template (`summarization/common/structured_extract.py`)

```python
PHASE_4_SYSTEM = """You extract structured metadata from a dense summary.
Be concise and use the source's own terminology where possible."""

PHASE_4_USER = """DENSE SUMMARY:
<<<
{final_summary}
>>>

SOURCE URL: {url}
SOURCE TYPE: {source_type}
SOURCE TITLE: {source_title}

Extract structured metadata and produce the exhaustive nested-bullet
detailed_summary that captures everything in the dense summary organized by
theme. The detailed_summary must be a PERMANENT REPLACEMENT for re-reading
the source.

REQUIREMENTS:
- mini_title: Under 5 words. Must be SPECIFIC to this content. Never generic
  like "Interesting AI Article". Think: what would a Zettelkasten note title
  look like for this? Examples of good titles:
    * "LoRA fine-tuning for medical QA"
    * "Rust async runtime comparison 2025"
    * "Kahneman on attention economics"
  Examples of BAD titles:
    * "AI research paper"
    * "Tech discussion"
    * "Blog post about coding"

- brief_summary: ≤50 words, single paragraph. Answers three questions:
  what is this, who made it, why does it matter.

- tags: 8-15 tags, flat list, lowercase-kebab. Mix granular (e.g.
  "lora-fine-tuning") with broad (e.g. "machine-learning"). Include: entities,
  concepts, technologies, domains, people, themes.

- detailed_summary: Nested bullet structure. Top-level = major themes/sections;
  each has `bullets` (direct points) and optional `sub_sections` (nested dict
  of sub-heading → bullet list). This must be EXHAUSTIVE — a future reader
  should not need to re-read the source."""
```

**Paired Pydantic schema** (passed as `response_schema`):

```python
class DetailedSummarySection(BaseModel):
    heading: str
    bullets: list[str]
    sub_sections: dict[str, list[str]] = {}

class SummaryResultSchema(BaseModel):
    mini_title: str = Field(..., max_length=60)       # ≤5 words post-validation
    brief_summary: str = Field(..., max_length=400)   # ≤50 words post-validation
    tags: list[str] = Field(..., min_length=8, max_length=15)
    detailed_summary: list[DetailedSummarySection]
```

**Post-validation** (`summarization/common/validators.py`):

- `mini_title`: split by whitespace → assert ≤5 tokens
- `brief_summary`: split by whitespace → assert ≤50 tokens
- `tags`: each matches `^[a-z][a-z0-9-]*$`, deduped after lowercase-kebab normalization
- `detailed_summary`: assert ≥3 top-level headings

On validation failure, retry Phase 4 once with the validation error fed back to Gemini.

### 5.7 Tiered Gemini client (`core/gemini_client.py`)

```python
MODEL_TIERS = {
    "pro":   ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "flash": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
}

class TieredGeminiClient:
    """Wraps GeminiKeyPool to add Pro/Flash tiering with automatic model fallback."""

    def __init__(self, key_pool: GeminiKeyPool, config: EngineConfig):
        self._pool = key_pool
        self._config = config

    async def generate(
        self,
        prompt: str,
        *,
        tier: Literal["pro", "flash"] = "pro",
        response_schema: type[BaseModel] | None = None,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> GenerateResult:
        """Generate content via Gemini with tiered model fallback.

        On 429 for the starting model, the underlying GeminiKeyPool tries the
        next of the 10 keys (same model) before falling through to the next
        model in the tier chain. Reuses the existing pool's cooldown logic.
        """
```

**Phase → tier mapping** (configurable in `config.yaml`):

| Phase | Tier | Rationale |
|---|---|---|
| 1 — CoD Densify | **pro** | Core reasoning, quality-critical |
| 2 — Self-Check | **pro** | Requires careful claim extraction + matching |
| 3 — Patch | **pro** | Preserve-all-content rewrite is hard |
| 4 — Structured Extract | **flash** | Format-constrained, ~10x cheaper, negligible quality loss |

### 5.8 Token + cost budget per URL

Assumptions: typical 8K-token input source, 50% patch trigger rate.

| Phase | Input tok | Output tok | Tier |
|---|---|---|---|
| 1. CoD Densify | 8.5K | 1.2K | Pro |
| 2. Self-Check | 8.6K | 0.7K | Pro |
| 3. Patch (50%) | 1.0K × 0.5 = 0.5K | 0.5K × 0.5 = 0.25K | Pro |
| 4. Structured Extract | 0.7K | 1.0K | Flash |

**Averages:** Pro 17.6K in / 2.15K out; Flash 0.7K in / 1.0K out.

**Gemini 2.5 pricing (verified April 2026):**

| Tier | Mode | Input / 1M | Output / 1M |
|---|---|---|---|
| Pro | realtime | $1.25 | $10.00 |
| Pro | batch | $0.625 | $5.00 |
| Flash | realtime | $0.30 | $2.50 |
| Flash | batch | $0.15 | $1.25 |

**Per-URL cost:**

| Mode | Pro | Flash | Total |
|---|---|---|---|
| Realtime tiered | $0.044 | $0.003 | **$0.047** |
| Batch tiered | $0.022 | $0.001 | **$0.023** |

**At scale:**

| URLs | Realtime | Batch |
|---|---|---|
| 100 | $4.70 | $2.30 |
| 500 | $23.50 | $11.50 |
| 1000 | $47.00 | $23.00 |

### 5.9 Research citations

- [arXiv 2309.04269 — Chain of Density](https://arxiv.org/abs/2309.04269) — Adams et al. 2023
- [arXiv 2305.14251 — FactScore](https://arxiv.org/abs/2305.14251) — Min et al. 2023
- [arXiv 2303.16634 — G-Eval](https://arxiv.org/pdf/2303.16634) — Liu et al. 2023
- [arXiv 2303.11366 — Reflexion](https://arxiv.org/abs/2303.11366) — Shinn et al. 2023
- [arXiv 2305.11738 — CRITIC](https://arxiv.org/abs/2305.11738) — Gou et al. 2023
- [arXiv 2111.09525 — SummaC](https://arxiv.org/abs/2111.09525) — Laban et al. 2022
- [arXiv 2406.01297 — Self-Correction survey](https://arxiv.org/html/2406.01297v3)
- [arXiv 2412.05579 — LLMs-as-Judges survey](https://arxiv.org/html/2412.05579v2)
- [PromptHub — Chain of Density in production](https://www.prompthub.us/blog/better-summarization-with-chain-of-density-prompting)
- [Yugen.ai — CoD evaluation](https://medium.com/yugen-ai-technology-blog/evaluating-chain-of-density-method-for-better-llm-summarization-2a4f32695821)
- [Gemini — Structured Output docs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini cookbook issue #354 — JSON key ordering breaks CoT](https://github.com/google-gemini/cookbook/issues/354)
- [Dylan Castillo — Gemini structured outputs tradeoffs](https://dylancastillo.co/posts/gemini-structured-outputs.html)

---

## 6. Supabase schema migration

**File:** `supabase/website/kg_public/migrations/2026-04-10-summarization-engine-v2.sql`

```sql
-- Extend kg_nodes with new summarization engine fields
ALTER TABLE public.kg_nodes
    ADD COLUMN IF NOT EXISTS mini_title TEXT,
    ADD COLUMN IF NOT EXISTS brief_summary TEXT,
    ADD COLUMN IF NOT EXISTS detailed_summary JSONB,
    ADD COLUMN IF NOT EXISTS extraction_confidence TEXT
        CHECK (extraction_confidence IN ('high', 'medium', 'low')),
    ADD COLUMN IF NOT EXISTS confidence_reason TEXT,
    ADD COLUMN IF NOT EXISTS engine_version TEXT DEFAULT 'v2.0.0',
    ADD COLUMN IF NOT EXISTS total_tokens_used INT,
    ADD COLUMN IF NOT EXISTS gemini_pro_tokens INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS gemini_flash_tokens INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_latency_ms INT,
    ADD COLUMN IF NOT EXISTS cod_iterations_used INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS self_check_missing_count INT,
    ADD COLUMN IF NOT EXISTS patch_applied BOOLEAN DEFAULT FALSE;

-- Expand source_type CHECK
ALTER TABLE public.kg_nodes
    DROP CONSTRAINT IF EXISTS kg_nodes_source_type_check;
ALTER TABLE public.kg_nodes
    ADD CONSTRAINT kg_nodes_source_type_check CHECK (
        source_type IN (
            'youtube', 'reddit', 'github', 'twitter', 'substack', 'medium',
            'web', 'generic', 'hackernews', 'linkedin', 'arxiv', 'podcast',
            'newsletter'
        )
    );

-- New indexes for v2 queries
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_confidence
    ON public.kg_nodes(user_id, extraction_confidence);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_engine_version
    ON public.kg_nodes(engine_version);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_mini_title_trgm
    ON public.kg_nodes USING gin (mini_title gin_trgm_ops);

-- Batch run tracking
CREATE TABLE IF NOT EXISTS public.summarization_batch_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.kg_users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'completed', 'partial_success', 'failed', 'cancelled'
    )),
    input_filename TEXT,
    input_format TEXT CHECK (input_format IN ('csv', 'json')),
    total_urls INT NOT NULL DEFAULT 0,
    processed_count INT NOT NULL DEFAULT 0,
    success_count INT NOT NULL DEFAULT 0,
    skipped_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'realtime' CHECK (mode IN ('realtime', 'batch_api')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    config_snapshot JSONB
);

CREATE INDEX IF NOT EXISTS idx_batch_runs_user_status
    ON public.summarization_batch_runs(user_id, status, started_at DESC);

-- Per-URL batch item results
CREATE TABLE IF NOT EXISTS public.summarization_batch_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.summarization_batch_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.kg_users(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    source_type TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'ingesting', 'summarizing', 'writing', 'succeeded', 'failed', 'skipped'
    )),
    node_id TEXT,
    error_code TEXT,
    error_message TEXT,
    tokens_used INT,
    latency_ms INT,
    user_tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    user_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_batch_items_run
    ON public.summarization_batch_items(run_id, status);

-- RLS policies (match existing kg_public pattern)
ALTER TABLE public.summarization_batch_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.summarization_batch_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY batch_runs_user_access ON public.summarization_batch_runs
    FOR ALL
    USING (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    )
    WITH CHECK (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    );

CREATE POLICY batch_items_user_access ON public.summarization_batch_items
    FOR ALL
    USING (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    )
    WITH CHECK (
        user_id::text = current_setting('request.jwt.claims', true)::json->>'render_user_id'
        OR auth.role() = 'service_role'
    );
```

---

## 7. Configuration

**File:** `website/features/summarization_engine/config.yaml`

```yaml
engine:
  version: "2.0.0"
  default_tier: "tiered"    # tiered | pro_only | flash_only

gemini:
  reuse_existing_pool: true  # uses website/features/api_key_switching/key_pool.py

  model_chains:
    pro:
      - gemini-2.5-pro
      - gemini-2.5-flash
      - gemini-2.5-flash-lite
    flash:
      - gemini-2.5-flash
      - gemini-2.5-flash-lite

  phase_tiers:
    cod_densify: "pro"
    self_check: "pro"
    patch: "pro"
    structured_extract: "flash"

  temperature: 0.3
  max_output_tokens: 8192
  response_mime_type: "application/json"

  batch_api:
    enabled: true
    threshold: 50              # use Batch API for batches >= 50 URLs
    poll_interval_sec: 60
    max_turnaround_hours: 24

chain_of_density:
  enabled: true
  iterations: 2                # research: 2-3 is quality peak; 5 over-compresses
  early_stop_if_few_new_entities: 2
  pass1_word_target: 200

self_check:
  enabled: true
  max_atomic_claims: 12
  patch_threshold: 3           # trigger patch if missing_count >= this
  max_patch_rounds: 1

structured_extract:
  validation_retries: 1
  mini_title_max_words: 5
  brief_summary_max_words: 50
  tags_min: 8
  tags_max: 15

sources:
  github:
    github_token_env: "GITHUB_TOKEN"
    fetch_issues: true
    max_issues: 20
    fetch_commits: true
    max_commits: 10
    fetch_prs: false
  newsletter:
    extractors: ["trafilatura", "readability", "newspaper4k"]
    paywall_fallbacks: ["wayback", "archive_ph"]
    googlebot_ua: true
    min_text_length: 500
  reddit:
    prefer_oauth: false
    user_agent: "zettelkasten-engine/2.0 (by u/chintanmehta21)"
    comment_depth: 3
    max_comments: 50
    top_comment_rank: "top"
  youtube:
    transcript_languages: ["en", "en-US", "en-GB"]
    use_ytdlp_fallback: true
    use_gemini_video_fallback: true
    webshare_proxy_env: "WEBSHARE_PROXY_URL"
  hackernews:
    api: "algolia"
    max_comments: 100
    comment_min_points: 5
    include_linked_article: true
  linkedin:
    googlebot_ua: true
    parse_json_ld: true
    use_wayback_fallback: true
    login_wall_keywords:
      - "authwall"
      - "Join now to see"
      - "Sign in to LinkedIn"
  arxiv:
    api_base: "http://export.arxiv.org/api/query"
    prefer_html_version: true
    pdf_parser: "pymupdf"
    long_paper_threshold_pages: 30
    rate_limit_delay_sec: 3.0
  podcast:
    podcast_index_key_env: "PODCAST_INDEX_KEY"
    podcast_index_secret_env: "PODCAST_INDEX_SECRET"
    use_itunes_lookup: true
    show_notes_precedence:
      - "content:encoded"
      - "itunes:summary"
      - "description"
      - "itunes:subtitle"
    audio_transcription: false
  twitter:
    use_oembed: true
    use_nitter_fallback: true
    nitter_instances:
      - "https://xcancel.com"
      - "https://nitter.poast.org"
      - "https://nitter.privacyredirect.com"
      - "https://lightbrd.com"
      - "https://nitter.space"
    nitter_health_check_timeout_sec: 5
    nitter_rotation_on_failure: true

batch:
  max_concurrency: 3
  max_input_size_mb: 10
  supported_input_formats: ["csv", "json"]
  progress_event_interval: 1

writers:
  supabase:
    enabled: true
  obsidian:
    enabled: false
    kg_directory_env: "KG_DIRECTORY"
  github_repo:
    enabled: false
    token_env: "GITHUB_TOKEN"
    repo_env: "GITHUB_REPO"
    branch_env: "GITHUB_BRANCH"

logging:
  level: "INFO"
  per_url_correlation_id: true
  log_token_counts: true

rate_limiting:
  api_v2_summarize: "10/minute"
  api_v2_batch: "2/minute"
```

---

## 8. API routes

**File:** `website/features/summarization_engine/api/routes.py`, mounted as `/api/v2` in `website/app.py`.

```python
from fastapi import APIRouter, UploadFile, Form, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/v2", tags=["summarization-engine-v2"])

@router.post("/summarize")
async def summarize_one(
    body: SummarizeRequest,   # {url, user_id: UUID | None, tier: str | None}
    user: AuthenticatedUser = Depends(get_current_user),
) -> SummaryResponse:
    """Real-time single URL summarization.
    Returns: { summary: SummaryResult, kg_node_id: str, tokens_used: int, latency_ms: int }
    """

@router.post("/batch")
async def start_batch(
    file: UploadFile,         # CSV or JSON
    use_batch_api: bool = Form(default=True),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BatchRunCreated:
    """Upload a batch file. Returns { run_id, total_urls, mode, started_at }."""

@router.get("/batch/{run_id}")
async def get_batch_status(
    run_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> BatchRunStatus:
    """Polled batch status: { run, items, progress }."""

@router.get("/batch/{run_id}/stream")
async def stream_batch_progress(
    run_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> EventSourceResponse:
    """SSE stream of batch progress events."""

@router.get("/batch")
async def list_batches(
    limit: int = 20,
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[BatchRunSummary]:
    """List recent batch runs for the authenticated user."""

@router.post("/batch/{run_id}/cancel")
async def cancel_batch(
    run_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> BatchRunStatus:
    """Cancel a running batch. Items in progress finish; pending items are skipped."""
```

The old `/api/summarize` endpoint is untouched. It keeps calling `website/core/pipeline.py` against the old extractors.

---

## 9. Batch processor

**File:** `website/features/summarization_engine/batch/processor.py`

```python
class BatchProcessor:
    def __init__(
        self,
        user_id: UUID,
        config: EngineConfig,
        supabase_client: SupabaseClient,
    ):
        self._user_id = user_id
        self._config = config
        self._sb = supabase_client
        self._sem = asyncio.Semaphore(config.batch.max_concurrency)

    async def run(
        self,
        input_path: Path | None = None,
        input_bytes: bytes | None = None,
        input_format: Literal["csv", "json"] | None = None,
        *,
        mode: Literal["realtime", "batch_api", "auto"] = "auto",
        progress_callback: Callable[[BatchProgressEvent], Awaitable[None]] | None = None,
    ) -> BatchRun:
        """Orchestrate a batch run end-to-end."""
        items = self._load_input(input_path, input_bytes, input_format)
        effective_mode = self._resolve_mode(mode, len(items))  # auto: batch_api if >= 50
        run = self._create_run_record(items, mode=effective_mode)

        if effective_mode == "batch_api":
            await self._run_via_gemini_batch_api(run, items, progress_callback)
        else:
            await self._run_realtime(run, items, progress_callback)

        self._finalize_run(run)
        return run

    async def _run_realtime(self, run, items, cb):
        tasks = [self._process_one(run, item, cb) for item in items]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_one(self, run, item, cb):
        async with self._sem:
            # route → ingest → summarize → write → update batch_item → emit SSE
            ...

    async def _run_via_gemini_batch_api(self, run, items, cb):
        # v1 approach:
        #   (1) Ingest all URLs (realtime, cheap/fast)
        #   (2) Build Gemini Batch API job for Phase 1 (CoD Densify) across all items
        #   (3) Poll until complete
        #   (4) Run Phases 2/3/4 realtime against the Pro pool for each item
        # v2 (future): multi-stage batching for Phases 1→2→3→4
        ...
```

### 9.1 Input formats

**CSV** (detected by `.csv` extension):

```csv
url,user_tags,user_note
https://arxiv.org/abs/2310.11511,"llm,retrieval","for my RAG research"
https://news.ycombinator.com/item?id=40123456,"ai-safety",""
https://youtube.com/watch?v=dQw4w9WgXcQ,"",""
```

Required column: `url`. Optional columns: `user_tags` (comma-separated), `user_note` (free text). Extra columns ignored.

**JSON** (detected by `.json` extension):

```json
[
  "https://arxiv.org/abs/2310.11511",
  "https://news.ycombinator.com/item?id=40123456",
  {
    "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "user_tags": ["music", "classic"],
    "user_note": "reference video"
  }
]
```

Supports mixed: bare URL strings OR objects with `url` + optional `user_tags` / `user_note`.

**Validation** (`batch/input_loader.py`):

- Max file size: `batch.max_input_size_mb` (default 10MB)
- Max URL count: 10,000 per file
- Each URL validated with SSRF protection (reuse `telegram_bot/utils/url_utils.validate_url`)
- Duplicates deduped within file
- Invalid URLs logged and skipped with reason

---

## 10. UI

Mounted at `/v2/batch` in `website/app.py`, following existing `user_home` / `user_zettels` pattern.

**File:** `website/features/summarization_engine/ui/index.html`

Layout:
- Header: "Summarization Engine v2 — Batch Dashboard"
- Single-URL form (URL textbox → `POST /api/v2/summarize` → result card)
- Batch upload form (drag-drop CSV/JSON → `POST /api/v2/batch` → run_id)
- Active runs panel: subscribes to SSE `/api/v2/batch/{run_id}/stream`, shows progress bar + per-URL status table
- Filter/search: by source type, tags, date, confidence
- Results table: paginated list of recent batch runs with status + stats

**JS** (`ui/js/engine.js`): vanilla fetch + EventSource for SSE (no framework).
**CSS** (`ui/css/engine.css`): teal accent (`--accent-color: #16A89C`). **No purple, violet, or lavender** anywhere (per project CLAUDE.md rule).

---

## 11. Testing strategy

### 11.1 Unit tests (fast, no network)

```
tests/unit/
├── test_router.py               # Detects all 9 source types, shortener resolution, edge cases
├── test_schema.py               # SummaryResultSchema Pydantic validation (word counts, tag format)
├── test_input_loader.py         # CSV/JSON parsing, format detection, validation, dedup
├── test_cod_iteration.py        # Phase 1 + early-stop logic (mocked Gemini)
├── test_self_check.py           # Phase 2 gap-detection parsing, critical_missing extraction
├── test_patch.py                # Phase 3 conditional trigger logic
├── test_structured_extract.py   # Phase 4 Pydantic validation, retry on fail
├── test_tag_utils.py            # Dedup, normalize, min/max count enforcement
├── test_gemini_client.py        # Tiered model chain fallback (mocked pool)
└── test_batch_processor.py      # Sequential + concurrent execution, error handling, progress events
```

### 11.2 Ingestor tests (mocked HTTP via pytest-httpx)

```
tests/unit/ingest/
├── test_github_ingest.py        # Monorepo detection, rate-limit handling, fallbacks
├── test_newsletter_ingest.py    # Trafilatura, Substack paywall, Medium Googlebot UA
├── test_reddit_ingest.py        # .json endpoint, comment tree, deleted content
├── test_youtube_ingest.py       # Transcript → yt-dlp → Gemini video fallback chain
├── test_hackernews_ingest.py    # Algolia API, linked article, comment ranking
├── test_linkedin_ingest.py      # JSON-LD parsing, authwall detection
├── test_arxiv_ingest.py         # API metadata, ar5iv, PDF parsing
├── test_podcast_ingest.py       # Podcast Index, iTunes Lookup, RSS precedence
└── test_twitter_ingest.py       # oEmbed, Nitter rotation, thread fallback
```

### 11.3 Integration tests (end-to-end, mocked network)

```
tests/integration/
├── test_pipeline_github.py      # Full orchestrator with recorded HTTP + mocked Gemini
├── test_pipeline_youtube.py
├── ... one per source
└── test_batch_end_to_end.py     # CSV upload → batch processor → mocked Supabase writes
```

### 11.4 Live tests (opt-in `--live` flag, CI-weekly + on-demand)

```
tests/live/
├── test_live_github.py          # Real public repos, real Gemini
├── test_live_newsletter.py      # Known public Substack/Medium articles
├── ...
└── test_live_batch.py           # Small batch (5 URLs), real Gemini Pro
```

Live tests require `api_env` with at least 1 valid Gemini key. Fail gracefully if missing.

**Cost budget:** ~$0.05/test Pro realtime → ~$0.50/full suite → ~$2/month weekly CI.

---

## 12. Dependencies

### 12.1 New dependencies (add to `ops/requirements.txt`)

```
feedparser>=6.0.11         # RSS/Atom parsing (podcasts, arXiv)
PyMuPDF>=1.24              # arXiv PDF extraction (fitz)
arxiv>=2.1.0               # arXiv API wrapper (built-in 3s delay)
newspaper4k>=0.9.3         # Newsletter fallback (newspaper3k is dead)
python-podcastindex>=1.0.0 # Podcast Index API (optional; raw httpx also works)
sse-starlette>=2.0         # SSE support for batch streaming
pytest-httpx>=0.34         # HTTP cassette mocking for tests
```

### 12.2 Already installed (reused)

`httpx`, `beautifulsoup4`, `trafilatura>=2.0`, `praw>=7.7.1`, `google-genai>=1.0`, `youtube-transcript-api>=1.0`, `yt-dlp`, `fastapi>=0.115`, `supabase>=2.0`, `pydantic-settings>=2.0`, `cryptography>=43.0`

---

## 13. Deployment considerations

- **Engine runs alongside existing website.** No new service, no new port. Mounts under existing FastAPI app.
- **YouTube IP block on cloud deployments.** Auto-detected via `RequestBlocked`/`IpBlocked` exceptions; Gemini video fallback takes over. Documented in `About.md` for the feature.
- **Optional env vars for enhanced extraction:**
  - `GITHUB_TOKEN` — raises GitHub rate limit from 60/hr to 5000/hr
  - `WEBSHARE_PROXY_URL` — residential proxy for reliable YouTube transcripts from cloud
  - `PODCAST_INDEX_KEY`, `PODCAST_INDEX_SECRET` — free self-signup at api.podcastindex.org
- **Gemini key pool reused** from existing `api_env` file. No new credentials required.
- **Supabase migration**: manual `psql` execution of the migration SQL, or `supabase db push` via CLI.
- **Zero downtime**: old telegram bot + old `/api/summarize` keep running against old pipeline. New engine lives at `/api/v2/*`.

---

## 14. Scope boundaries

### 14.1 In scope for v1

- All 9 source ingestors with best-effort degradation for Twitter/LinkedIn/Podcasts
- 4-phase summarization pipeline (CoD → Self-Check → Patch → Structured Extract)
- Tiered Pro + Flash orchestration reusing existing key pool
- Extended kg_nodes schema + new batch tracking tables
- `/api/v2/summarize` and `/api/v2/batch*` endpoints
- Batch processor with CSV/JSON input and Gemini Batch API routing
- Minimal dashboard UI at `/v2/batch`
- Unit + integration + live test suites
- Supabase primary writer; Obsidian + GitHub writers as opt-in

### 14.2 Deferred to v2

- Audio transcription for podcasts (local Whisper or API)
- Twitter thread reconstruction via authenticated twscrape
- LinkedIn Playwright-authenticated extraction
- OCR for scanned arXiv PDFs
- Migration of existing telegram bot to call v2 engine
- Migration of existing `/api/summarize` to v2 engine
- Replacement of existing Nexus batch module
- Multi-stage Gemini Batch API pipelining (Phase 1 → 2 → 3 → 4 as separate batches)
- Automated BERTScore or G-Eval quality scoring

---

## 15. Open questions / risks

1. **Nitter reliability in production** — public instances may all be down on a given day. Mitigation: health-check on startup, cache working-instance list for 1 hour, fail gracefully to "root tweet only" via oEmbed.
2. **YouTube Gemini video fallback quota** — Gemini video understanding is more expensive per invocation. For batches heavy in YouTube, cost may exceed estimates. Mitigation: config flag to disable video fallback in batch mode.
3. **Podcast Index API outages** — free tier has no SLA. Mitigation: cache RSS URLs per iTunes ID in a local dict (7-day TTL).
4. **Schema migration on existing production data** — existing `kg_nodes` rows will have NULL `mini_title`/`brief_summary`/`detailed_summary`/`extraction_confidence`. Mitigation: all new fields nullable; queries default to old `summary` field when v2 fields absent.
5. **CoD-inspired prompt drift over time** — Gemini model updates may change optimal densification behavior. Mitigation: weekly live test catches regressions; prompt templates versioned in config for A/B testing.

---

## 16. Handoff to `writing-plans`

Once approved, the next step is `superpowers:writing-plans` to produce a phased implementation plan. Expected phases:

1. **Foundation** — core/ (orchestrator, gemini_client, router, models, errors), auto-discovery registries, Pydantic schemas, tests for schema/router
2. **Ingestors (batch 1)** — GitHub, HackerNews, arXiv (most reliable APIs, least risky)
3. **Ingestors (batch 2)** — Newsletters, Reddit, YouTube (medium complexity, fallback chains)
4. **Ingestors (batch 3)** — LinkedIn, Podcasts, Twitter (best-effort, most fragile)
5. **Summarization common** — chain_of_density, self_check, patch, structured_extract modules + base summarizer
6. **Summarization per source** — 9 thin wrappers with source-specific prompts
7. **Supabase schema migration** — SQL file + manual verification
8. **Writers** — SupabaseWriter (primary), ObsidianWriter + GithubRepoWriter (opt-in)
9. **Batch processor** — input loader, concurrency, Gemini Batch API integration, progress events
10. **API routes** — `/api/v2/*` endpoints + FastAPI integration
11. **UI** — batch dashboard
12. **Live test suite + CI workflow**
