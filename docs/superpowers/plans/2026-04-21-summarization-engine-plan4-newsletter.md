# Summarization Engine Plan 4 — Newsletter Phase 0.5 Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Newsletter Phase 0.5 ingest improvements (site-specific selectors, preheader, CTA extraction, conclusions/recommendations detection, stance classifier) so Newsletter iteration loops 1-7 can start after merge.

**Architecture:** Newsletter ingestor currently relies on trafilatura/readability which drops structural cues (subject, preheader, CTA). Plan 4 layers site-specific DOM selectors (Substack, Beehiiv, Medium) over the generic extractor, adds a regex-based CTA detector, scans body-tail for conclusions/recommendations, and runs a one-shot Gemini Flash stance classifier (cached per URL). All additions are optional and fall back cleanly when selectors don't match.

**Tech Stack:** Python 3.12, `beautifulsoup4` (already dep via newspaper4k), Gemini Flash for stance classification. No paid services.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §7.4

**Branch:** `eval/summary-engine-v2-scoring-newsletter`, off `master` AFTER Plan 3's PR merges.

**Precondition:** Plan 3 merged. 3+ Newsletter URLs present in `docs/testing/links.txt` under `# Newsletter` header. If missing, Codex auto-discovers them via `ops/scripts/lib/url_discovery.py` (which must exist from Plan 1).

---

## File structure summary

### Files to CREATE
- `website/features/summarization_engine/source_ingest/newsletter/site_extractors.py`
- `website/features/summarization_engine/source_ingest/newsletter/preheader.py`
- `website/features/summarization_engine/source_ingest/newsletter/cta.py`
- `website/features/summarization_engine/source_ingest/newsletter/conclusions.py`
- `website/features/summarization_engine/source_ingest/newsletter/stance.py`
- `docs/summary_eval/newsletter/phase0.5-ingest/websearch-notes.md`
- `docs/summary_eval/newsletter/phase0.5-ingest/candidates/01-trafilatura-baseline.json`
- `docs/summary_eval/newsletter/phase0.5-ingest/candidates/02-site-specific-plus-structural.json`
- `docs/summary_eval/newsletter/phase0.5-ingest/decision.md`
- `ops/scripts/benchmark_newsletter_ingest.py`
- `tests/unit/summarization_engine/source_ingest/test_newsletter_site_extractors.py`
- `tests/unit/summarization_engine/source_ingest/test_newsletter_preheader.py`
- `tests/unit/summarization_engine/source_ingest/test_newsletter_cta.py`
- `tests/unit/summarization_engine/source_ingest/test_newsletter_conclusions.py`
- `tests/unit/summarization_engine/source_ingest/test_newsletter_stance.py`

### Files to MODIFY
- `website/features/summarization_engine/source_ingest/newsletter/ingest.py` — call site extractors + stance + conclusions + CTA
- `website/features/summarization_engine/config.yaml` — new `sources.newsletter.*` keys

---

## Task 0: Create Plan 4 sub-branch + verify newsletter URLs

- [ ] **Step 1: Confirm Plan 3 merged**

```bash
git checkout master && git pull
python -c "from website.features.summarization_engine.source_ingest.github.api_client import GitHubApiClient; print('OK')"
```

- [ ] **Step 2: Verify newsletter URLs**

```bash
python ops/scripts/eval_loop.py --source newsletter --list-urls
```
If output is an empty JSON array, either (a) ask the user to add 3 URLs under `# Newsletter` in `links.txt`, or (b) run `ops/scripts/lib/url_discovery.py` to auto-populate (see Plan 1 Task 30 for how).

- [ ] **Step 3: Create branch**

```bash
git checkout -b eval/summary-engine-v2-scoring-newsletter
git push -u origin eval/summary-engine-v2-scoring-newsletter
```

---

## Task 1: Newsletter config keys

**Files:**
- Modify: `website/features/summarization_engine/config.yaml`

- [ ] **Step 1: Replace the `sources.newsletter` block**

```yaml
  newsletter:
    extractors: ["trafilatura", "readability", "newspaper4k"]
    paywall_fallbacks: ["googlebot", "wayback", "archive_ph", "twelveft", "freedium"]
    googlebot_ua: true
    min_text_length: 500
    site_specific_selectors_enabled: true
    preheader_fallback_chars: 150
    cta_keyword_regex: "subscribe|sign up|sign-up|read more|learn more|join|try|start|continue reading"
    cta_max_count: 5
    conclusions_tail_fraction: 0.3
    conclusions_prefixes: ["i recommend", "you should", "the key takeaway", "the bottom line", "in summary", "to conclude", "what to do"]
    conclusions_max_count: 6
    stance_classifier_enabled: true
    stance_cache_ttl_days: 30
    branded_sources_yaml: "docs/summary_eval/_config/branded_newsletter_sources.yaml"
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/config.yaml
git commit -m "refactor: newsletter phase 0.5 config keys"
```

---

## Task 2: Site-specific selector extractor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/newsletter/site_extractors.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_newsletter_site_extractors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_newsletter_site_extractors.py
from website.features.summarization_engine.source_ingest.newsletter.site_extractors import (
    extract_structured, StructuredNewsletter,
)


_SUBSTACK_HTML = """
<html><head><meta property="og:site_name" content="Example Substack"></head><body>
<article>
<h1 class="post-title">The Real Question About AI Moats</h1>
<h3 class="subtitle">Why scale doesn't translate to durability</h3>
<div class="body markup">
<p>Opening paragraph here.</p>
<p>Second paragraph.</p>
</div>
<div class="post-footer">
<a href="https://example.substack.com/subscribe">Subscribe now</a>
</div>
</article>
</body></html>
"""


def test_substack_extracts_title_subtitle_body():
    result = extract_structured(_SUBSTACK_HTML, url="https://example.substack.com/p/ai-moats")
    assert isinstance(result, StructuredNewsletter)
    assert result.site == "substack"
    assert result.title == "The Real Question About AI Moats"
    assert "scale doesn't translate" in result.subtitle
    assert "Opening paragraph" in result.body_text
    assert any("subscribe" in cta.lower() for cta in result.cta_links)


def test_non_substack_returns_empty_structured():
    result = extract_structured("<html><body><p>hi</p></body></html>", url="https://random.example.com/")
    assert result.site == "unknown"
    assert result.title == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_newsletter_site_extractors.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `site_extractors.py`**

```python
"""Site-specific newsletter DOM extractors (Substack, Beehiiv, Medium)."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup


@dataclass
class StructuredNewsletter:
    site: str = "unknown"
    title: str = ""
    subtitle: str = ""
    body_text: str = ""
    cta_links: list[str] = field(default_factory=list)
    publication_identity: str = ""


def _detect_site(url: str, soup: BeautifulSoup) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "substack.com" in host:
        return "substack"
    if "beehiiv.com" in host:
        return "beehiiv"
    if "medium.com" in host or "hackernoon.com" in host:
        return "medium"
    # Fallback: meta tag detection (Substack custom domains)
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    if og_site and "substack" in (og_site.get("content") or "").lower():
        return "substack"
    return "unknown"


def _substack(soup: BeautifulSoup) -> StructuredNewsletter:
    title_el = soup.select_one("h1.post-title, h1.pencraft")
    subtitle_el = soup.select_one("h3.subtitle, h3.pencraft")
    body_el = soup.select_one("div.body.markup, div.body, div.available-content")
    ctas = [a.get("href", "") for a in soup.select("div.post-footer a[href], a.subscribe-btn")]
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    pub = (og_site.get("content") or "").strip() if og_site else ""
    return StructuredNewsletter(
        site="substack",
        title=title_el.get_text(strip=True) if title_el else "",
        subtitle=subtitle_el.get_text(strip=True) if subtitle_el else "",
        body_text=body_el.get_text(separator="\n", strip=True) if body_el else "",
        cta_links=[c for c in ctas if c],
        publication_identity=pub,
    )


def _beehiiv(soup: BeautifulSoup) -> StructuredNewsletter:
    title_el = soup.select_one("h1.post-title, h1[data-testid='post-title']")
    subtitle_el = soup.select_one("h2.post-subtitle, p.post-subtitle")
    body_el = soup.select_one("article, div.post-content")
    ctas = [a.get("href", "") for a in soup.select("a.subscribe-button, a[data-cta='subscribe']")]
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    pub = (og_site.get("content") or "").strip() if og_site else ""
    return StructuredNewsletter(
        site="beehiiv",
        title=title_el.get_text(strip=True) if title_el else "",
        subtitle=subtitle_el.get_text(strip=True) if subtitle_el else "",
        body_text=body_el.get_text(separator="\n", strip=True) if body_el else "",
        cta_links=[c for c in ctas if c],
        publication_identity=pub,
    )


def _medium(soup: BeautifulSoup) -> StructuredNewsletter:
    title_el = soup.select_one("h1, h1[data-testid='storyTitle']")
    subtitle_el = soup.select_one("h2, h3.graf--subtitle")
    body_el = soup.select_one("article, section[data-field='body']")
    ctas = [a.get("href", "") for a in soup.select("a.button--large, a[data-action='subscribe']")]
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    pub = (og_site.get("content") or "").strip() if og_site else ""
    return StructuredNewsletter(
        site="medium",
        title=title_el.get_text(strip=True) if title_el else "",
        subtitle=subtitle_el.get_text(strip=True) if subtitle_el else "",
        body_text=body_el.get_text(separator="\n", strip=True) if body_el else "",
        cta_links=[c for c in ctas if c],
        publication_identity=pub,
    )


_EXTRACTORS = {"substack": _substack, "beehiiv": _beehiiv, "medium": _medium}


def extract_structured(html: str, *, url: str) -> StructuredNewsletter:
    soup = BeautifulSoup(html, "html.parser")
    site = _detect_site(url, soup)
    if site in _EXTRACTORS:
        result = _EXTRACTORS[site](soup)
        # If site-specific didn't find a title, fall through to unknown.
        if result.title:
            return result
    return StructuredNewsletter(site="unknown")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_newsletter_site_extractors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/newsletter/site_extractors.py tests/unit/summarization_engine/source_ingest/test_newsletter_site_extractors.py
git commit -m "feat: newsletter site specific extractors"
```

---

## Task 3: Preheader extractor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/newsletter/preheader.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_newsletter_preheader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_newsletter_preheader.py
from website.features.summarization_engine.source_ingest.newsletter.preheader import extract_preheader


def test_explicit_preheader_meta_tag():
    html = '<html><head><meta name="preheader" content="This is the preheader text."></head><body><p>body</p></body></html>'
    assert extract_preheader(html, fallback_chars=150) == "This is the preheader text."


def test_fallback_first_n_chars_of_body():
    html = "<html><body><p>Opening paragraph sets context. " + "x" * 200 + "</p></body></html>"
    result = extract_preheader(html, fallback_chars=100)
    assert len(result) <= 100
    assert "Opening paragraph" in result


def test_no_body_returns_empty():
    assert extract_preheader("<html></html>", fallback_chars=150) == ""
```

- [ ] **Step 2: Create `preheader.py`**

```python
"""Newsletter preheader extractor — explicit meta first, body-prefix fallback."""
from __future__ import annotations

from bs4 import BeautifulSoup


def extract_preheader(html: str, *, fallback_chars: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Explicit meta tags some newsletter platforms inject
    for selector in [
        ("meta", {"name": "preheader"}),
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "description"}),
    ]:
        el = soup.find(*selector)
        if el and el.get("content"):
            return el["content"].strip()[:fallback_chars]
    # Fallback: first paragraph/body-text chunk
    body = soup.find("body")
    if not body:
        return ""
    text = body.get_text(separator=" ", strip=True)
    return text[:fallback_chars].rsplit(" ", 1)[0] if len(text) > fallback_chars else text
```

- [ ] **Step 3: Run test + commit**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_newsletter_preheader.py -v` → PASS.

```bash
git add website/features/summarization_engine/source_ingest/newsletter/preheader.py tests/unit/summarization_engine/source_ingest/test_newsletter_preheader.py
git commit -m "feat: newsletter preheader extractor"
```

---

## Task 4: CTA extractor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/newsletter/cta.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_newsletter_cta.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_newsletter_cta.py
from website.features.summarization_engine.source_ingest.newsletter.cta import extract_ctas


def test_matches_keyword_regex():
    html = """
    <a href="/sub">Subscribe now</a>
    <a href="/x">random link</a>
    <a href="/learn">Learn more</a>
    """
    ctas = extract_ctas(html, keyword_regex="subscribe|learn more", max_count=5)
    assert len(ctas) == 2
    assert any("Subscribe" in c.text for c in ctas)
    assert any("Learn more" in c.text for c in ctas)


def test_respects_max_count():
    html = "".join(f'<a href="/x{i}">Subscribe {i}</a>' for i in range(10))
    ctas = extract_ctas(html, keyword_regex="subscribe", max_count=3)
    assert len(ctas) == 3


def test_strips_boilerplate():
    html = '<a href="/unsub">Unsubscribe</a><a href="/sub">Subscribe</a>'
    ctas = extract_ctas(html, keyword_regex="subscribe", max_count=5)
    # "Unsubscribe" matches regex "subscribe" but should be filtered as boilerplate.
    assert len(ctas) == 1
    assert "Unsubscribe" not in ctas[0].text
```

- [ ] **Step 2: Create `cta.py`**

```python
"""Newsletter CTA link extractor."""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


_BOILERPLATE = {"unsubscribe", "manage subscription", "update preferences", "view in browser"}


@dataclass
class CTA:
    text: str
    href: str


def extract_ctas(html: str, *, keyword_regex: str, max_count: int) -> list[CTA]:
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(keyword_regex, re.IGNORECASE)
    found: list[CTA] = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text:
            continue
        if any(bp in text.lower() for bp in _BOILERPLATE):
            continue
        if not pattern.search(text):
            continue
        found.append(CTA(text=text, href=a["href"]))
        if len(found) >= max_count:
            break
    return found
```

- [ ] **Step 3: Run test + commit**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_newsletter_cta.py -v` → PASS.

```bash
git add website/features/summarization_engine/source_ingest/newsletter/cta.py tests/unit/summarization_engine/source_ingest/test_newsletter_cta.py
git commit -m "feat: newsletter cta extractor"
```

---

## Task 5: Conclusions/recommendations extractor

**Files:**
- Create: `website/features/summarization_engine/source_ingest/newsletter/conclusions.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_newsletter_conclusions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_newsletter_conclusions.py
from website.features.summarization_engine.source_ingest.newsletter.conclusions import extract_conclusions


def test_detects_prefixed_sentences_in_tail():
    text = ("Opening background. " * 20) + "I recommend switching to FastAPI. The key takeaway is that async matters."
    conclusions = extract_conclusions(
        text, tail_fraction=0.3,
        prefixes=["i recommend", "the key takeaway"],
        max_count=6,
    )
    assert len(conclusions) == 2
    assert any("FastAPI" in c for c in conclusions)


def test_detects_action_items_list_headers():
    text = ("Background. " * 30) + "## Takeaways\n- Do X\n- Track Y\n"
    conclusions = extract_conclusions(
        text, tail_fraction=0.3,
        prefixes=["i recommend"],  # prefix not matching; list-header path must still work
        max_count=6,
    )
    # The list-header path detects "Takeaways" heading and harvests following bullets.
    assert any("Do X" in c or "Track Y" in c for c in conclusions)


def test_empty_when_no_conclusions():
    text = "Just a normal paragraph with no action items."
    conclusions = extract_conclusions(text, tail_fraction=0.3, prefixes=["i recommend"], max_count=6)
    assert conclusions == []
```

- [ ] **Step 2: Create `conclusions.py`**

```python
"""Conclusions / action-item detector for newsletters."""
from __future__ import annotations

import re


_HEADER_PATTERN = re.compile(
    r"(?im)^\s*#{0,3}\s*(takeaways?|what to do|action items?|key points?|conclusion)\s*:?\s*$"
)


def extract_conclusions(text: str, *, tail_fraction: float, prefixes: list[str], max_count: int) -> list[str]:
    if not text:
        return []
    tail_start = int(len(text) * (1.0 - tail_fraction))
    tail = text[tail_start:]

    out: list[str] = []
    # Path 1: sentences starting with a conclusion-prefix.
    for sentence in re.split(r"(?<=[.!?])\s+", tail):
        s = sentence.strip()
        if not s:
            continue
        s_lower = s.lower()
        if any(s_lower.startswith(p) for p in prefixes):
            out.append(s)
            if len(out) >= max_count:
                return out

    # Path 2: bullets/lines immediately following a Takeaways/Action-Items header.
    lines = tail.splitlines()
    i = 0
    while i < len(lines):
        if _HEADER_PATTERN.match(lines[i]):
            i += 1
            while i < len(lines) and (lines[i].strip().startswith(("-", "*", "•")) or lines[i].strip().startswith(tuple(f"{n}." for n in range(10)))):
                line = lines[i].strip().lstrip("-*•0123456789. ").strip()
                if line:
                    out.append(line)
                    if len(out) >= max_count:
                        return out
                i += 1
        else:
            i += 1
    return out
```

- [ ] **Step 3: Run test + commit**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_newsletter_conclusions.py -v` → PASS.

```bash
git add website/features/summarization_engine/source_ingest/newsletter/conclusions.py tests/unit/summarization_engine/source_ingest/test_newsletter_conclusions.py
git commit -m "feat: newsletter conclusions extractor"
```

---

## Task 6: Stance classifier (Gemini Flash, cached)

**Files:**
- Create: `website/features/summarization_engine/source_ingest/newsletter/stance.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_newsletter_stance.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_newsletter_stance.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from website.features.summarization_engine.source_ingest.newsletter.stance import classify_stance


@pytest.mark.asyncio
async def test_classify_stance_returns_valid_enum(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock(return_value=MagicMock(text='{"stance": "skeptical", "confidence": 0.8}'))
    stance = await classify_stance(
        client=client, body_text="The whole AI hype is overblown.",
        cache_root=tmp_path, url="https://example.com/x",
    )
    assert stance == "skeptical"


@pytest.mark.asyncio
async def test_classify_stance_cache_hit(tmp_path: Path):
    from website.features.summarization_engine.core.cache import FsContentCache
    cache = FsContentCache(root=tmp_path, namespace="newsletter_stance")
    cache.put(("https://example.com/x", "stance.v1"), {"stance": "cautionary"})
    client = MagicMock()
    client.generate = AsyncMock()
    stance = await classify_stance(
        client=client, body_text="...",
        cache_root=tmp_path, url="https://example.com/x",
    )
    assert stance == "cautionary"
    client.generate.assert_not_called()


@pytest.mark.asyncio
async def test_classify_stance_invalid_enum_falls_back_to_neutral(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock(return_value=MagicMock(text='{"stance": "bullish", "confidence": 0.3}'))
    stance = await classify_stance(
        client=client, body_text="...", cache_root=tmp_path, url="https://example.com/y",
    )
    assert stance == "neutral"
```

- [ ] **Step 2: Create `stance.py`**

```python
"""Newsletter stance classifier — one Gemini Flash call, cached per URL."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from website.features.summarization_engine.core.cache import FsContentCache


_PROMPT_VERSION = "stance.v1"
_VALID = {"optimistic", "skeptical", "cautionary", "neutral", "mixed"}


_PROMPT = """\
Classify the overall stance of this newsletter body. Return JSON with keys "stance" (one of:
optimistic, skeptical, cautionary, neutral, mixed) and "confidence" (0.0-1.0). Base purely on
tone markers; do NOT infer from topic. No preamble, JSON only.

BODY:
{body}
"""


async def classify_stance(
    *, client: Any, body_text: str, cache_root: Path, url: str,
) -> Literal["optimistic", "skeptical", "cautionary", "neutral", "mixed"]:
    cache = FsContentCache(root=cache_root, namespace="newsletter_stance")
    key = (url, _PROMPT_VERSION)
    hit = cache.get(key)
    if hit and hit.get("stance") in _VALID:
        return hit["stance"]

    prompt = _PROMPT.format(body=body_text[:8000])
    try:
        result = await client.generate(prompt, tier="flash")
        parsed = json.loads(result.text.strip())
        stance = parsed.get("stance", "neutral")
    except Exception:
        stance = "neutral"
    if stance not in _VALID:
        stance = "neutral"
    cache.put(key, {"stance": stance})
    return stance
```

- [ ] **Step 3: Run test + commit**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_newsletter_stance.py -v` → PASS.

```bash
git add website/features/summarization_engine/source_ingest/newsletter/stance.py tests/unit/summarization_engine/source_ingest/test_newsletter_stance.py
git commit -m "feat: newsletter stance classifier cached"
```

---

## Task 7: Wire everything into `NewsletterIngestor`

**Files:**
- Modify: `website/features/summarization_engine/source_ingest/newsletter/ingest.py`

- [ ] **Step 1: Imports at the top**

```python
from pathlib import Path
from website.features.summarization_engine.source_ingest.newsletter.site_extractors import extract_structured
from website.features.summarization_engine.source_ingest.newsletter.preheader import extract_preheader
from website.features.summarization_engine.source_ingest.newsletter.cta import extract_ctas
from website.features.summarization_engine.source_ingest.newsletter.conclusions import extract_conclusions
from website.features.summarization_engine.source_ingest.newsletter.stance import classify_stance
```

- [ ] **Step 2: After the existing ingest pipeline produces `html` + `body_text`, augment:**

Find the place in `NewsletterIngestor.ingest` where `body_text` (the cleaned article text) is computed. Right before the `return IngestResult(...)`, add:

```python
        structured = extract_structured(html, url=url) if config.get("site_specific_selectors_enabled", True) else None
        preheader = extract_preheader(html, fallback_chars=int(config.get("preheader_fallback_chars", 150)))
        ctas = extract_ctas(
            html,
            keyword_regex=config.get("cta_keyword_regex", "subscribe|learn more"),
            max_count=int(config.get("cta_max_count", 5)),
        )
        conclusions = extract_conclusions(
            body_text,
            tail_fraction=float(config.get("conclusions_tail_fraction", 0.3)),
            prefixes=config.get("conclusions_prefixes", []),
            max_count=int(config.get("conclusions_max_count", 6)),
        )

        detected_stance = "neutral"
        if config.get("stance_classifier_enabled", True) and body_text:
            try:
                from website.features.summarization_engine.api.routes import _gemini_client
                client = _gemini_client()
                cache_root = Path(__file__).resolve().parents[5] / "docs" / "summary_eval" / "_cache"
                detected_stance = await classify_stance(
                    client=client, body_text=body_text,
                    cache_root=cache_root, url=url,
                )
            except Exception as exc:
                logger.warning("[newsletter] stance classify failed: %s", exc)

        # Merge site-specific signals into sections + metadata.
        if structured and structured.site != "unknown":
            sections["Title"] = structured.title
            if structured.subtitle:
                sections["Subtitle"] = structured.subtitle
            # Prefer site-specific body over generic extractor body if longer
            if len(structured.body_text) > len(body_text or ""):
                sections["Body"] = structured.body_text
                body_text = structured.body_text

        if preheader:
            sections["Preheader"] = preheader
        if ctas:
            sections["CTAs"] = "\n".join(f"- {c.text} ({c.href})" for c in ctas)
        if conclusions:
            sections["Conclusions"] = "\n".join(f"- {c}" for c in conclusions)

        metadata.update({
            "site": (structured.site if structured else "unknown"),
            "publication_identity": (structured.publication_identity if structured else ""),
            "preheader": preheader,
            "cta_count": len(ctas),
            "conclusions_count": len(conclusions),
            "detected_stance": detected_stance,
        })
```

(`body_text`, `sections`, `metadata`, `html` are the existing variables in the current ingest flow — subagent: inspect current code to match names.)

Update `raw_text = join_sections(sections)` to pick up the new sections.

- [ ] **Step 3: Run existing newsletter tests**

Run: `pytest website/features/summarization_engine/tests/unit/ -k newsletter -v`
Expected: PASS (existing tests should pass — additions are purely additive).

- [ ] **Step 4: Commit**

```bash
git add website/features/summarization_engine/source_ingest/newsletter/ingest.py
git commit -m "feat: newsletter ingest wire phase 0.5 signals"
```

---

## Task 8: Phase 0.5 benchmark

**Files:**
- Create: `ops/scripts/benchmark_newsletter_ingest.py`

- [ ] **Step 1: Create benchmark script**

```python
"""Benchmark newsletter ingest: baseline trafilatura vs site-specific+structural."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.links_parser import parse_links_file
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.source_ingest.newsletter.ingest import NewsletterIngestor


STRATEGIES = [
    ("01-trafilatura-baseline", {
        "site_specific_selectors_enabled": False,
        "stance_classifier_enabled": False,
    }),
    ("02-site-specific-plus-structural", {
        "site_specific_selectors_enabled": True,
        "stance_classifier_enabled": True,
    }),
]


async def _benchmark():
    cfg = load_config()
    base_cfg = cfg.sources.get("newsletter", {})
    urls = parse_links_file(Path("docs/testing/links.txt")).get("newsletter", [])[:3]
    if not urls:
        print("No Newsletter URLs; add 3 under '# Newsletter' in docs/testing/links.txt")
        return

    out_root = Path("docs/summary_eval/newsletter/phase0.5-ingest/candidates")
    out_root.mkdir(parents=True, exist_ok=True)
    ingestor = NewsletterIngestor()

    for filename, overrides in STRATEGIES:
        merged = {**base_cfg, **overrides}
        per_url = []
        for url in urls:
            try:
                result = await ingestor.ingest(url, config=merged)
                per_url.append({
                    "url": url,
                    "success": True,
                    "raw_text_chars": len(result.raw_text),
                    "extraction_confidence": result.extraction_confidence,
                    "site": result.metadata.get("site"),
                    "has_preheader": bool(result.metadata.get("preheader")),
                    "cta_count": result.metadata.get("cta_count", 0),
                    "conclusions_count": result.metadata.get("conclusions_count", 0),
                    "detected_stance": result.metadata.get("detected_stance"),
                    "publication_identity": result.metadata.get("publication_identity", ""),
                })
            except Exception as exc:
                per_url.append({"url": url, "success": False, "error": str(exc)})
        agg = {
            "strategy": filename,
            "mean_chars": sum(u.get("raw_text_chars", 0) for u in per_url) / max(len(per_url), 1),
            "signal_coverage": sum(
                1 for u in per_url
                if u.get("has_preheader") or u.get("cta_count", 0) > 0 or u.get("conclusions_count", 0) > 0
            ),
        }
        payload = {"strategy": filename, "urls_tested": urls, "per_url": per_url, "aggregate": agg}
        (out_root / f"{filename}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"{filename}: mean_chars={agg['mean_chars']:.0f} signal_coverage={agg['signal_coverage']}/{len(per_url)}")


if __name__ == "__main__":
    asyncio.run(_benchmark())
```

- [ ] **Step 2: Run benchmark**

```bash
python ops/scripts/benchmark_newsletter_ingest.py
```
Expected: `02-site-specific-plus-structural` shows higher `mean_chars` and at least 2/3 URLs with preheader/cta/conclusions populated.

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/benchmark_newsletter_ingest.py docs/summary_eval/newsletter/phase0.5-ingest/candidates/
git commit -m "test: newsletter phase 0.5 ingest benchmark"
```

---

## Task 9: `decision.md` + `websearch-notes.md`

**Files:**
- Create: `docs/summary_eval/newsletter/phase0.5-ingest/websearch-notes.md`
- Create: `docs/summary_eval/newsletter/phase0.5-ingest/decision.md`

- [ ] **Step 1: Create `websearch-notes.md`**

```markdown
# Newsletter ingest landscape — 2026-04-21

## Site selector references
- Substack: `h1.post-title`, `h3.subtitle`, `div.body.markup`, `div.post-footer a[href]`
- Beehiiv: `h1.post-title`, `h2.post-subtitle`, `article`, `a.subscribe-button`
- Medium: `h1[data-testid='storyTitle']`, `section[data-field='body']`

## Stance classifier
- Single Gemini Flash call per URL, cached 30 days (config: `stance_cache_ttl_days`).
- Enum locked to 5 values; invalid LLM output falls back to `neutral`.
```

- [ ] **Step 2: Create `decision.md`**

```markdown
# Newsletter Phase 0.5 — decision

## Chain
1. Existing extractor chain (trafilatura → readability → newspaper4k → paywall fallbacks). Baseline body_text.
2. Site-specific DOM selectors (Substack / Beehiiv / Medium). If longer body or structured title/subtitle,
   replaces the baseline fields.
3. Preheader extraction (meta tag first, body-prefix fallback).
4. CTA extraction (regex-filtered anchor tags, boilerplate stripped).
5. Conclusions extraction (sentence-prefix + list-header detection on body tail).
6. Stance classifier (Gemini Flash, cached per URL).
7. All signals populate `IngestResult.metadata` + `sections` so rubric criteria
   (conclusions_or_recommendations, cta, stance) are directly fillable by the summarizer.

## Acceptance (per spec §7.4)
- All 3 newsletter URLs return `extraction_confidence=high`.
- `detected_stance` populated on all 3.
- At least 2/3 URLs have `cta_count > 0` OR `conclusions_count > 0`.

## Outcome
(Codex: paste aggregate summary from each candidate JSON.)
```

- [ ] **Step 3: Commit**

```bash
git add docs/summary_eval/newsletter/phase0.5-ingest/websearch-notes.md docs/summary_eval/newsletter/phase0.5-ingest/decision.md
git commit -m "docs: newsletter phase 0.5 decision and notes"
```

---

## Task 10: E2E smoke — POST /api/v2/summarize

**Files:**
- Create: `docs/summary_eval/newsletter/phase0-smoke.md`

- [ ] **Step 1: Run smoke test**

```bash
python run.py &
sleep 5
curl -X POST http://127.0.0.1:10000/api/v2/summarize \
  -H "Content-Type: application/json" \
  -d '{"url":"<FIRST_NEWSLETTER_URL_FROM_LINKS_TXT>"}' | python -m json.tool > /tmp/nl-smoke.json
kill %1
```

- [ ] **Step 2: Validate**

Open `/tmp/nl-smoke.json`. Verify:
- `summary.detailed_summary.publication_identity` non-empty
- `summary.detailed_summary.stance` ∈ {optimistic, skeptical, cautionary, neutral, mixed}
- `summary.detailed_summary.conclusions_or_recommendations` list populated when source has takeaways
- If the URL host is in `branded_newsletter_sources.yaml`, `summary.mini_title` must contain the publication name

- [ ] **Step 3: Write `phase0-smoke.md`**

```markdown
# Newsletter Phase 0.5 smoke — 2026-04-21

## Exit criteria
- [ ] POST /api/v2/summarize returns NewsletterStructuredPayload
- [ ] detected_stance populated (one of the 5 enum values)
- [ ] conclusions_or_recommendations list present (may be empty if source has none)
- [ ] cta field populated if source has a CTA
- [ ] Branded sources: mini_title contains publication name

## Results
(Codex: paste trimmed curl output.)
```

- [ ] **Step 4: Commit**

```bash
git add docs/summary_eval/newsletter/phase0-smoke.md
git commit -m "test: newsletter smoke api summarize"
```

---

## Task 11: Push + draft PR

```bash
git push origin eval/summary-engine-v2-scoring-newsletter
gh pr create --draft --title "feat: newsletter phase 0.5 site selectors plus stance" \
  --body "Plan 4 of 5. Adds Substack/Beehiiv/Medium DOM selectors + preheader + CTA + conclusions + Gemini Flash stance classifier (cached). Ready for Newsletter iteration loops 1-7 after merge."
```

---

## Self-review checklist
- [ ] All 5 new modules (site_extractors, preheader, cta, conclusions, stance) have unit tests green
- [ ] Stance classifier caches per URL — re-ingest doesn't re-spend Flash quota
- [ ] CTA regex includes "unsubscribe"-safe filter (boilerplate list)
- [ ] Conclusions extractor handles BOTH sentence-prefix path AND list-header path
- [ ] Site-specific extractor returns `site="unknown"` gracefully on unsupported hosts
- [ ] Branded sources YAML path read via `config.branded_sources_yaml` (not hardcoded)
- [ ] Newsletter schema validator enforces branded publications include publication name in label
