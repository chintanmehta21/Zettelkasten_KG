# Summarization Engine Plan 3 — GitHub Phase 0.5 Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land GitHub Phase 0.5 ingest enhancements so GitHub iteration loops 1-7 can start immediately after merge. Fills the rubric-critical signal gaps (Pages URL, workflows, releases, language composition, benchmarks/tests/examples directory scan, architecture overview).

**Architecture:** GitHub's REST API is authenticated + free (5000 req/hr). Plan 1 ships the GitHub summarizer + schema + `rubric_github.yaml`. This plan extends `GitHubIngestor` with 5 additional API calls to capture rubric signals, plus an architecture-overview prompt pass on the README using Gemini Flash (one-shot, cached).

**Tech Stack:** Python 3.12, `httpx`, existing `GitHubIngestor`, Gemini Flash (for architecture overview). No paid services.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §7.3

**Branch:** `eval/summary-engine-v2-scoring-github`, off `master` AFTER Plan 2's PR merges.

**Precondition:** Plan 2 merged. `GITHUB_TOKEN` env var set to a PAT with `public_repo` scope (existing project convention).

---

## File structure summary

### Files to CREATE
- `website/features/summarization_engine/source_ingest/github/api_client.py`
- `website/features/summarization_engine/source_ingest/github/architecture.py`
- `docs/summary_eval/github/phase0.5-ingest/websearch-notes.md`
- `docs/summary_eval/github/phase0.5-ingest/candidates/01-readme-only.json`
- `docs/summary_eval/github/phase0.5-ingest/candidates/02-full-signals.json`
- `docs/summary_eval/github/phase0.5-ingest/decision.md`
- `ops/scripts/benchmark_github_ingest.py`
- `tests/unit/summarization_engine/source_ingest/test_github_api_client.py`
- `tests/unit/summarization_engine/source_ingest/test_github_architecture.py`

### Files to MODIFY
- `website/features/summarization_engine/source_ingest/github/ingest.py` — call new APIs + fill extra metadata
- `website/features/summarization_engine/config.yaml` — new `sources.github.*` keys

---

## Task 0: Create Plan 3 sub-branch

- [ ] **Step 1: Confirm Plan 2 merged + GitHub URLs present in links.txt**

```bash
git checkout master && git pull
python -c "from website.features.summarization_engine.summarization.github.summarizer import GitHubSummarizer; print('OK')"
grep -A5 "^# GitHub" docs/testing/links.txt | grep -E "^https" | wc -l
```
Expected: `OK`. If GitHub URL count is `< 3`, ask the user to add them to `docs/testing/links.txt` under `# GitHub` before proceeding — Phase 0.5 benchmark needs 3.

- [ ] **Step 2: Create branch**

```bash
git checkout -b eval/summary-engine-v2-scoring-github
git push -u origin eval/summary-engine-v2-scoring-github
```

---

## Task 1: Add GitHub config keys

**Files:**
- Modify: `website/features/summarization_engine/config.yaml`

- [ ] **Step 1: Replace the `sources.github` block**

```yaml
  github:
    github_token_env: "GITHUB_TOKEN"
    fetch_issues: true
    max_issues: 20
    fetch_commits: true
    max_commits: 10
    fetch_prs: false
    fetch_pages: true
    fetch_workflows: true
    fetch_releases: true
    max_releases: 5
    fetch_languages: true
    fetch_root_dir_listing: true
    architecture_overview_enabled: true
    architecture_overview_max_chars: 500
    api_base_url: "https://api.github.com"
    api_timeout_sec: 15
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/config.yaml
git commit -m "refactor: github phase 0.5 config keys"
```

---

## Task 2: `api_client.py` — thin wrapper over GitHub REST

**Files:**
- Create: `website/features/summarization_engine/source_ingest/github/api_client.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_github_api_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_github_api_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from website.features.summarization_engine.source_ingest.github.api_client import (
    GitHubApiClient, RepoSignals,
)


@pytest.mark.asyncio
async def test_fetch_languages_returns_sorted_percentages():
    client = GitHubApiClient(token="x", base_url="https://api.github.com", timeout_sec=5)
    with patch.object(client, "_get", new=AsyncMock()) as mock_get:
        mock_get.return_value = {"Python": 10000, "Rust": 5000, "Shell": 500}
        langs = await client.fetch_languages("a/b")
    assert langs[0][0] == "Python"
    assert round(langs[0][1], 1) == 64.5
    assert langs[-1][0] == "Shell"


@pytest.mark.asyncio
async def test_fetch_root_dir_detects_benchmarks_tests_examples():
    client = GitHubApiClient(token="x", base_url="https://api.github.com", timeout_sec=5)
    with patch.object(client, "_get", new=AsyncMock()) as mock_get:
        mock_get.return_value = [
            {"name": "src", "type": "dir"},
            {"name": "tests", "type": "dir"},
            {"name": "benchmarks", "type": "dir"},
            {"name": "README.md", "type": "file"},
        ]
        signals = await client.fetch_root_dir_signals("a/b")
    assert signals["has_tests"] is True
    assert signals["has_benchmarks"] is True
    assert signals["has_examples"] is False


@pytest.mark.asyncio
async def test_fetch_pages_handles_404_as_no_pages():
    client = GitHubApiClient(token="x", base_url="https://api.github.com", timeout_sec=5)
    with patch.object(client, "_get", new=AsyncMock(side_effect=_HttpError(404))):
        pages = await client.fetch_pages_url("a/b")
    assert pages is None


class _HttpError(Exception):
    def __init__(self, status):
        self.status = status
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_github_api_client.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `api_client.py`**

```python
"""Thin GitHub REST API wrapper for Phase 0.5 signal enrichment."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RepoSignals:
    pages_url: str | None = None
    has_workflows: bool = False
    workflow_count: int = 0
    releases: list[dict] = field(default_factory=list)
    languages: list[tuple[str, float]] = field(default_factory=list)
    root_dir_flags: dict[str, bool] = field(default_factory=dict)


class GitHubApiClient:
    def __init__(self, *, token: str, base_url: str, timeout_sec: int) -> None:
        self._token = token
        self._base = base_url.rstrip("/")
        self._timeout = timeout_sec
        self._headers = {
            "Authorization": f"Bearer {token}" if token else "",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base}{path}", headers={k: v for k, v in self._headers.items() if v})
            if resp.status_code == 404:
                raise _HttpError(404)
            resp.raise_for_status()
            return resp.json()

    async def fetch_pages_url(self, slug: str) -> str | None:
        try:
            data = await self._get(f"/repos/{slug}/pages")
        except Exception:
            return None
        return (data or {}).get("html_url")

    async def fetch_workflows(self, slug: str) -> tuple[bool, int]:
        try:
            data = await self._get(f"/repos/{slug}/actions/workflows")
        except Exception:
            return False, 0
        count = int((data or {}).get("total_count", 0))
        return count > 0, count

    async def fetch_releases(self, slug: str, max_count: int) -> list[dict]:
        try:
            data = await self._get(f"/repos/{slug}/releases?per_page={max_count}")
        except Exception:
            return []
        out = []
        for r in (data or [])[:max_count]:
            out.append({
                "tag_name": r.get("tag_name"),
                "name": r.get("name"),
                "published_at": r.get("published_at"),
                "prerelease": r.get("prerelease", False),
            })
        return out

    async def fetch_languages(self, slug: str) -> list[tuple[str, float]]:
        try:
            data = await self._get(f"/repos/{slug}/languages")
        except Exception:
            return []
        total = sum(data.values()) or 1
        pairs = [(lang, bytes_ / total * 100.0) for lang, bytes_ in data.items()]
        return sorted(pairs, key=lambda p: p[1], reverse=True)

    async def fetch_root_dir_signals(self, slug: str) -> dict[str, bool]:
        try:
            entries = await self._get(f"/repos/{slug}/contents")
        except Exception:
            return {}
        names = {e["name"].lower() for e in entries if e.get("type") == "dir"}
        return {
            "has_tests": "tests" in names or "test" in names,
            "has_benchmarks": "benchmarks" in names or "benchmark" in names or "bench" in names,
            "has_examples": "examples" in names or "example" in names,
            "has_demo": "demo" in names or "demos" in names,
            "has_docs_dir": "docs" in names or "doc" in names,
        }

    async def fetch_all_signals(self, slug: str, cfg: dict) -> RepoSignals:
        signals = RepoSignals()
        if cfg.get("fetch_pages", True):
            signals.pages_url = await self.fetch_pages_url(slug)
        if cfg.get("fetch_workflows", True):
            signals.has_workflows, signals.workflow_count = await self.fetch_workflows(slug)
        if cfg.get("fetch_releases", True):
            signals.releases = await self.fetch_releases(slug, int(cfg.get("max_releases", 5)))
        if cfg.get("fetch_languages", True):
            signals.languages = await self.fetch_languages(slug)
        if cfg.get("fetch_root_dir_listing", True):
            signals.root_dir_flags = await self.fetch_root_dir_signals(slug)
        return signals


class _HttpError(Exception):
    def __init__(self, status: int):
        self.status = status
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_github_api_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/github/api_client.py tests/unit/summarization_engine/source_ingest/test_github_api_client.py
git commit -m "feat: github api client for phase 0.5 signals"
```

---

## Task 3: `architecture.py` — Gemini Flash one-shot architecture overview

**Files:**
- Create: `website/features/summarization_engine/source_ingest/github/architecture.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_github_architecture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_github_architecture.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from website.features.summarization_engine.source_ingest.github.architecture import (
    extract_architecture_overview,
)


@pytest.mark.asyncio
async def test_extract_architecture_returns_prose(tmp_path: Path):
    client = MagicMock()
    client.generate = AsyncMock(return_value=MagicMock(
        text="The repo has modules A, B, C that interact via a central bus.",
        input_tokens=100, output_tokens=40,
    ))
    overview = await extract_architecture_overview(
        client=client, readme_text="# My repo\n## Architecture...",
        top_level_dirs=["src", "tests", "docs"], max_chars=500,
        cache_root=tmp_path, slug="a/b",
    )
    assert "modules A, B, C" in overview
    assert len(overview) <= 500


@pytest.mark.asyncio
async def test_extract_architecture_cache_hit(tmp_path: Path):
    from website.features.summarization_engine.core.cache import FsContentCache
    cache = FsContentCache(root=tmp_path, namespace="github_architecture")
    cache.put(("a/b", "arch.v1"), {"overview": "cached overview text"})
    client = MagicMock()
    client.generate = AsyncMock()
    overview = await extract_architecture_overview(
        client=client, readme_text="...",
        top_level_dirs=["src"], max_chars=500,
        cache_root=tmp_path, slug="a/b",
    )
    assert overview == "cached overview text"
    client.generate.assert_not_called()
```

- [ ] **Step 2: Create `architecture.py`**

```python
"""One-shot architecture overview extractor, cached per repo slug."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from website.features.summarization_engine.core.cache import FsContentCache


_PROMPT_VERSION = "arch.v1"

_PROMPT = """\
Produce a 1-3 sentence (max {max_chars} chars) architecture overview of this GitHub repo.
Describe major directories/modules and how they interact. Ground strictly in the README
and top-level directory listing. No speculation. Plain prose, no markdown, no bullets.

README:
{readme}

TOP-LEVEL DIRECTORIES:
{dirs}
"""


async def extract_architecture_overview(
    *, client: Any, readme_text: str, top_level_dirs: list[str],
    max_chars: int, cache_root: Path, slug: str,
) -> str:
    cache = FsContentCache(root=cache_root, namespace="github_architecture")
    key = (slug, _PROMPT_VERSION)
    hit = cache.get(key)
    if hit and "overview" in hit:
        return hit["overview"]
    prompt = _PROMPT.format(
        max_chars=max_chars,
        readme=readme_text[:8000],
        dirs=", ".join(top_level_dirs) or "(none detected)",
    )
    result = await client.generate(prompt, tier="flash")
    text = (result.text or "").strip()
    # Enforce max_chars cap
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    # Enforce min_length so schema validation doesn't reject
    if len(text) < 50:
        text = f"Repository {slug} architecture not clearly described in README; see source code modules directly."
    cache.put(key, {"overview": text})
    return text
```

- [ ] **Step 3: Run test to verify pass**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_github_architecture.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add website/features/summarization_engine/source_ingest/github/architecture.py tests/unit/summarization_engine/source_ingest/test_github_architecture.py
git commit -m "feat: github architecture overview extractor cached"
```

---

## Task 4: Wire enrichment into `GitHubIngestor`

**Files:**
- Modify: `website/features/summarization_engine/source_ingest/github/ingest.py`

- [ ] **Step 1: Read the current `GitHubIngestor.ingest` method**

(Subagent: read the file to locate the existing return-of-`IngestResult` at the end of `ingest(...)`.)

- [ ] **Step 2: Wire in the new API client + architecture extractor**

At the top of `ingest.py`, add:

```python
from pathlib import Path
from website.features.summarization_engine.source_ingest.github.api_client import GitHubApiClient
from website.features.summarization_engine.source_ingest.github.architecture import extract_architecture_overview
```

Before the existing `return IngestResult(...)` in `GitHubIngestor.ingest`, insert signal fetching and architecture overview generation:

```python
        owner_repo = f"{owner}/{repo}"
        api_client = GitHubApiClient(
            token=os.environ.get(config.get("github_token_env", "GITHUB_TOKEN"), ""),
            base_url=config.get("api_base_url", "https://api.github.com"),
            timeout_sec=int(config.get("api_timeout_sec", 15)),
        )
        signals = await api_client.fetch_all_signals(owner_repo, config)

        metadata.update({
            "pages_url": signals.pages_url,
            "has_workflows": signals.has_workflows,
            "workflow_count": signals.workflow_count,
            "releases": signals.releases,
            "languages": signals.languages,
            **{k: v for k, v in signals.root_dir_flags.items()},
        })

        # Append a signal-summary section to raw_text so the summarizer has the info inline.
        signal_lines = [
            f"Pages URL: {signals.pages_url or 'none'}",
            f"GitHub Actions workflows: {signals.workflow_count}",
            f"Recent releases: {', '.join(r.get('tag_name', '?') for r in signals.releases) or 'none'}",
            f"Language composition: {', '.join(f'{l}={p:.1f}%' for l, p in signals.languages[:5]) or 'none'}",
            f"Root dirs: " + ", ".join(k.replace("has_", "") for k, v in signals.root_dir_flags.items() if v),
        ]
        sections["Repository signals"] = "\n".join(signal_lines)

        # Architecture overview (Gemini Flash, cached per slug).
        if config.get("architecture_overview_enabled", True):
            try:
                from website.features.summarization_engine.api.routes import _gemini_client
                client = _gemini_client()
                cache_root = Path(__file__).resolve().parents[5] / "docs" / "summary_eval" / "_cache"
                arch_overview = await extract_architecture_overview(
                    client=client,
                    readme_text=readme_text or "",
                    top_level_dirs=[k.replace("has_", "") for k, v in signals.root_dir_flags.items() if v],
                    max_chars=int(config.get("architecture_overview_max_chars", 500)),
                    cache_root=cache_root,
                    slug=owner_repo,
                )
                sections["Architecture overview"] = arch_overview
                metadata["architecture_overview"] = arch_overview
            except Exception as exc:
                logger.warning("[gh-ingest] architecture overview failed for %s: %s", owner_repo, exc)
```

(Where `readme_text` is the existing README variable in the current ingest flow — subagent: inspect current code to match its variable name; use that.)

Rebuild `raw_text` after these modifications:
```python
        raw_text = join_sections(sections)
```

- [ ] **Step 3: Run existing github ingest tests**

Run: `pytest website/features/summarization_engine/tests/unit/ -k github -v`
Expected: PASS (existing tests should still pass; new signals layer is additive).

- [ ] **Step 4: Commit**

```bash
git add website/features/summarization_engine/source_ingest/github/ingest.py
git commit -m "feat: github ingest fetch phase 0.5 signals"
```

---

## Task 5: Phase 0.5 benchmark runner

**Files:**
- Create: `ops/scripts/benchmark_github_ingest.py`

- [ ] **Step 1: Create benchmark script**

```python
"""Benchmark GitHub ingest: README-only vs README+signals."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.links_parser import parse_links_file
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.source_ingest.github.ingest import GitHubIngestor


STRATEGIES = [
    ("01-readme-only", {
        "fetch_pages": False, "fetch_workflows": False, "fetch_releases": False,
        "fetch_languages": False, "fetch_root_dir_listing": False,
        "architecture_overview_enabled": False,
    }),
    ("02-full-signals", {
        "fetch_pages": True, "fetch_workflows": True, "fetch_releases": True,
        "fetch_languages": True, "fetch_root_dir_listing": True,
        "architecture_overview_enabled": True,
    }),
]


async def _benchmark():
    cfg = load_config()
    base_cfg = cfg.sources.get("github", {})
    urls = parse_links_file(Path("docs/testing/links.txt")).get("github", [])[:3]
    if not urls:
        print("No GitHub URLs; add 3 under '# GitHub' in docs/testing/links.txt")
        return

    out_root = Path("docs/summary_eval/github/phase0.5-ingest/candidates")
    out_root.mkdir(parents=True, exist_ok=True)
    ingestor = GitHubIngestor()

    for filename, overrides in STRATEGIES:
        merged = {**base_cfg, **overrides}
        per_url = []
        for url in urls:
            try:
                result = await ingestor.ingest(url, config=merged)
                per_url.append({
                    "url": url,
                    "success": True,
                    "extraction_confidence": result.extraction_confidence,
                    "raw_text_chars": len(result.raw_text),
                    "has_pages_url": bool(result.metadata.get("pages_url")),
                    "has_workflows": result.metadata.get("has_workflows", False),
                    "releases_count": len(result.metadata.get("releases", []) or []),
                    "languages_count": len(result.metadata.get("languages", []) or []),
                    "architecture_overview_len": len(result.metadata.get("architecture_overview", "") or ""),
                })
            except Exception as exc:
                per_url.append({"url": url, "success": False, "error": str(exc)})
        agg = {
            "strategy": filename,
            "mean_chars": sum(u.get("raw_text_chars", 0) for u in per_url) / max(len(per_url), 1),
            "signal_coverage_pct": sum(
                (1 for u in per_url if u.get("has_pages_url") or u.get("has_workflows") or u.get("releases_count", 0) > 0)
            ) / max(len(per_url), 1) * 100.0,
        }
        payload = {"strategy": filename, "urls_tested": urls, "per_url": per_url, "aggregate": agg}
        (out_root / f"{filename}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"{filename}: mean_chars={agg['mean_chars']:.0f} signal_coverage={agg['signal_coverage_pct']:.1f}%")


if __name__ == "__main__":
    asyncio.run(_benchmark())
```

- [ ] **Step 2: Run the benchmark**

```bash
python ops/scripts/benchmark_github_ingest.py
```

Expected: `02-full-signals` shows higher `mean_chars` and `signal_coverage_pct ≥ 66%` (at least 2 of 3 repos expose Pages or workflows or releases).

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/benchmark_github_ingest.py docs/summary_eval/github/phase0.5-ingest/candidates/
git commit -m "test: github phase 0.5 ingest benchmark"
```

---

## Task 6: `decision.md` + `websearch-notes.md`

**Files:**
- Create: `docs/summary_eval/github/phase0.5-ingest/websearch-notes.md`
- Create: `docs/summary_eval/github/phase0.5-ingest/decision.md`

- [ ] **Step 1: Create `websearch-notes.md`**

```markdown
# GitHub ingest landscape — 2026-04-21

## References
- GitHub REST API v2022-11-28, 5000 req/hr on PAT. Authenticated path is free.
- `/repos/{slug}/pages`, `/actions/workflows`, `/releases`, `/languages`, `/contents` — all stable + documented.

## Key decisions
- No WebSearch needed; GitHub REST API is canonical + well-documented.
- Architecture overview is one Gemini Flash call, cached per slug forever. Changes to repo README
  do not invalidate the cache unless Codex bumps `arch.v1` → `arch.v2` in architecture.py.
- Every Phase 0.5 ingest runs all 5 enrichment API calls regardless of repo (5/5000 budget each).
```

- [ ] **Step 2: Create `decision.md`**

```markdown
# GitHub Phase 0.5 — decision

## Enrichment API calls (all required)
1. `GET /repos/{slug}/pages` → Pages deployment URL (rubric: "important public-facing surface")
2. `GET /repos/{slug}/actions/workflows` → CI presence (proxy for usability_signals)
3. `GET /repos/{slug}/releases?per_page=5` → maturity signal
4. `GET /repos/{slug}/languages` → language composition percentages
5. `GET /repos/{slug}/contents` → root directory listing for benchmarks/tests/examples detection

Plus 1 Gemini Flash call: architecture overview (cached per slug, ~150 tokens).

## Acceptance (per spec §7.3)
- 3 GitHub URLs in links.txt all return `extraction_confidence=high`.
- `has_pages_url` / `has_workflows` / `releases_count > 0` / `languages_count > 0` — at least 2/3 URLs have 2+ of these populated.
- `architecture_overview` non-empty and ≥ 50 chars on all 3 URLs.

## Outcome
(Codex: paste aggregate summary from each candidate JSON.)
```

- [ ] **Step 3: Commit**

```bash
git add docs/summary_eval/github/phase0.5-ingest/websearch-notes.md docs/summary_eval/github/phase0.5-ingest/decision.md
git commit -m "docs: github phase 0.5 decision and notes"
```

---

## Task 7: E2E smoke — POST /api/v2/summarize for 1 GitHub URL

**Files:**
- Create: `docs/summary_eval/github/phase0-smoke.md`

- [ ] **Step 1: Start server + hit API**

```bash
python run.py &
sleep 5
curl -X POST http://127.0.0.1:10000/api/v2/summarize \
  -H "Content-Type: application/json" \
  -d '{"url":"<FIRST_GITHUB_URL_FROM_LINKS_TXT>"}' | python -m json.tool > /tmp/gh-smoke.json
kill %1
```

- [ ] **Step 2: Validate**

Open `/tmp/gh-smoke.json`. Verify:
- `summary.mini_title` matches `^[^/]+/[^/]+$` (owner/repo)
- `summary.architecture_overview` present, length ≥ 50
- `summary.benchmarks_tests_examples` is `null` OR array of strings
- `summary.detailed_summary[].public_interfaces` non-empty
- `summary.metadata.extraction_confidence == "high"`

- [ ] **Step 3: Write `phase0-smoke.md`**

```markdown
# GitHub Phase 0.5 smoke — 2026-04-21

## Exit criteria
- [ ] POST /api/v2/summarize returns GitHubStructuredPayload with owner/repo label
- [ ] architecture_overview present (≥ 50 chars)
- [ ] detailed_summary has public_interfaces populated
- [ ] metadata has pages_url / has_workflows / releases / languages
- [ ] extraction_confidence="high"

## Results
(Codex: paste trimmed curl output.)
```

- [ ] **Step 4: Commit**

```bash
git add docs/summary_eval/github/phase0-smoke.md
git commit -m "test: github smoke api summarize"
```

---

## Task 8: Push + draft PR

```bash
git push origin eval/summary-engine-v2-scoring-github
gh pr create --draft --title "feat: github phase 0.5 signals plus architecture" \
  --body "Plan 3 of 5. Adds pages/workflows/releases/languages/root-dir signals + Gemini-Flash architecture overview. Ready for GitHub iteration loops 1-7 after merge."
```

---

## Self-review checklist
- [ ] All 5 GitHub REST API calls land under 5000 req/hr budget (5 per ingest × ~20 ingests during benchmark = 100)
- [ ] `architecture_overview` cached per slug so re-ingests don't redo the Gemini call
- [ ] `benchmarks_tests_examples` is populated only when the directory exists (null otherwise — rubric won't penalize for absent dirs)
- [ ] `fetch_all_signals` handles 404 gracefully per API (Pages commonly missing)
- [ ] `language composition percentages` sum to ~100% (small drift ok due to Linguist)
