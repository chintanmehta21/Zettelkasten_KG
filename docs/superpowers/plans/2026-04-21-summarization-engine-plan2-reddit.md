# Summarization Engine Plan 2 — Reddit Phase 0.5 Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Reddit Phase 0.5 ingest improvements + Reddit iteration-loop readiness on a fresh sub-branch, so Reddit iteration loops 1-7 can start immediately after merge.

**Architecture:** Plan 1 already ships per-source Reddit summarizer + schema + `rubric_reddit.yaml`. This plan adds: (a) `num_comments` vs `rendered_count` divergence tracking so the evaluator can score the "missing/removed comments" rubric criterion, (b) `pullpush.io` free third-party archive fetch for recovering removed comment text, (c) a Phase 0.5 A/B benchmark proving the ingest captures enough signal on the 4 Reddit URLs in `links.txt`.

**Tech Stack:** Python 3.12, `httpx`, `pytest`. No paid services. No PRAW/OAuth — anonymous JSON + UA rotation is the current primary path; pullpush.io is an enrichment layer, not a replacement.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §7.2

**Branch:** `eval/summary-engine-v2-scoring-reddit`, branched **off `master` AFTER Plan 1's PR merges** (not off Plan 1's working branch). Phase 0 refactor must be live in master first.

**Precondition check:** `import website.features.summarization_engine.summarization.reddit.summarizer` must succeed (proves Plan 1 landed) and `docs/summary_eval/_config/rubric_reddit.yaml` must exist.

---

## File structure summary

### Files to CREATE
- `website/features/summarization_engine/source_ingest/reddit/pullpush.py`
- `docs/summary_eval/reddit/phase0.5-ingest/websearch-notes.md`
- `docs/summary_eval/reddit/phase0.5-ingest/candidates/01-anon-json-only.json`
- `docs/summary_eval/reddit/phase0.5-ingest/candidates/02-anon-json-plus-pullpush.json`
- `docs/summary_eval/reddit/phase0.5-ingest/decision.md`
- `ops/scripts/benchmark_reddit_ingest.py`
- `tests/unit/summarization_engine/source_ingest/test_reddit_pullpush.py`
- `tests/unit/summarization_engine/source_ingest/test_reddit_divergence.py`

### Files to MODIFY
- `website/features/summarization_engine/source_ingest/reddit/ingest.py` — add divergence tracking + pullpush enrichment
- `website/features/summarization_engine/config.yaml` — add `sources.reddit.pullpush_*` config keys

---

## Task 0: Create Plan 2 sub-branch

**Files:**
- Branch: `eval/summary-engine-v2-scoring-reddit`

- [ ] **Step 1: Confirm Plan 1 merged**

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
git checkout master && git pull
python -c "from website.features.summarization_engine.summarization.reddit.summarizer import RedditSummarizer; print('OK')"
test -f docs/summary_eval/_config/rubric_reddit.yaml && echo "rubric OK"
```
Expected: `OK` + `rubric OK`.

- [ ] **Step 2: Create branch**

```bash
git checkout -b eval/summary-engine-v2-scoring-reddit
git push -u origin eval/summary-engine-v2-scoring-reddit
```

---

## Task 1: Add Reddit config keys

**Files:**
- Modify: `website/features/summarization_engine/config.yaml`

- [ ] **Step 1: Replace the `sources.reddit` block**

```yaml
  reddit:
    prefer_oauth: false
    user_agent: "zettelkasten-engine/2.0 (by u/chintanmehta21)"
    comment_depth: 3
    max_comments: 50
    top_comment_rank: "top"
    pullpush_enabled: true
    pullpush_base_url: "https://api.pullpush.io"
    pullpush_timeout_sec: 10
    pullpush_max_recovered_comments: 25
    divergence_threshold_pct: 20  # (num_comments - rendered_count) / num_comments * 100 above which to trigger pullpush
```

- [ ] **Step 2: Commit**

```bash
git add website/features/summarization_engine/config.yaml
git commit -m "refactor: reddit pullpush config keys"
```

---

## Task 2: `num_comments` vs `rendered_count` divergence tracking

**Files:**
- Modify: `website/features/summarization_engine/source_ingest/reddit/ingest.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_reddit_divergence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_reddit_divergence.py
from website.features.summarization_engine.source_ingest.reddit.ingest import _compute_divergence


def test_divergence_zero_when_counts_equal():
    assert _compute_divergence(num_comments=50, rendered_count=50) == 0.0


def test_divergence_percent_correct():
    # 50 total, 40 rendered -> 20%
    assert _compute_divergence(num_comments=50, rendered_count=40) == 20.0


def test_divergence_clamped_to_zero_when_rendered_exceeds_total():
    # Reddit sometimes over-reports; never return negative.
    assert _compute_divergence(num_comments=10, rendered_count=12) == 0.0


def test_divergence_handles_zero_total():
    assert _compute_divergence(num_comments=0, rendered_count=0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_reddit_divergence.py -v`
Expected: FAIL with `ImportError` on `_compute_divergence`.

- [ ] **Step 3: Add `_compute_divergence` to `ingest.py`**

Append near the bottom of `website/features/summarization_engine/source_ingest/reddit/ingest.py` (outside the `RedditIngestor` class):

```python
def _compute_divergence(*, num_comments: int, rendered_count: int) -> float:
    """Return the percentage of comments visible on the thread that are NOT rendered.

    Reddit's `num_comments` is the thread's total including removed/deleted comments;
    the rendered JSON tree only contains what moderators left visible. Divergence
    signals removed/deleted content the summarizer should mention per rubric.
    """
    if num_comments <= 0:
        return 0.0
    missing = num_comments - rendered_count
    if missing <= 0:
        return 0.0
    return round((missing / num_comments) * 100.0, 2)
```

- [ ] **Step 4: Wire divergence into metadata**

In `RedditIngestor._ingest_json`, after the existing `metadata=...` block, compute and record divergence. Find the `sections = {...}` block in the method and replace the subsequent `return IngestResult(...)` block with:

```python
        rendered_count = len([c for c in payload[1]["data"]["children"] if c.get("kind") == "t1"]) if len(payload) > 1 else 0
        num_comments = int(post.get("num_comments") or 0)
        divergence_pct = _compute_divergence(num_comments=num_comments, rendered_count=rendered_count)

        return IngestResult(
            source_type=self.source_type,
            url=final_url.removesuffix(".json"),
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata={
                "subreddit": post.get("subreddit"),
                "author": post.get("author"),
                "score": post.get("score"),
                "num_comments": num_comments,
                "rendered_comment_count": rendered_count,
                "comment_divergence_pct": divergence_pct,
                "permalink": post.get("permalink"),
            },
            extraction_confidence="high",
            confidence_reason=f"json endpoint ok; rendered={rendered_count}/{num_comments} divergence={divergence_pct}%",
            fetched_at=utc_now(),
            ingestor_version="2.0.0",
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_reddit_divergence.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add website/features/summarization_engine/source_ingest/reddit/ingest.py tests/unit/summarization_engine/source_ingest/test_reddit_divergence.py
git commit -m "feat: reddit comment count divergence tracking"
```

---

## Task 3: `pullpush.py` module for removed-comment recovery

**Files:**
- Create: `website/features/summarization_engine/source_ingest/reddit/pullpush.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_reddit_pullpush.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_reddit_pullpush.py
import pytest
from unittest.mock import AsyncMock, patch

from website.features.summarization_engine.source_ingest.reddit.pullpush import (
    recover_removed_comments, PullPushResult,
)


@pytest.mark.asyncio
async def test_recover_removed_comments_returns_list():
    mock_response = {
        "data": [
            {"id": "c1", "body": "Removed comment 1", "author": "[deleted]", "score": 5},
            {"id": "c2", "body": "Removed comment 2", "author": "user2", "score": 12},
        ]
    }
    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        mock_get.return_value.json = lambda: mock_response
        mock_get.return_value.status_code = 200
        result = await recover_removed_comments(
            link_id="abc123", base_url="https://api.pullpush.io",
            timeout_sec=5, max_recovered=50,
        )
    assert isinstance(result, PullPushResult)
    assert len(result.comments) == 2
    assert result.comments[0].body == "Removed comment 1"


@pytest.mark.asyncio
async def test_recover_removed_comments_handles_timeout():
    import httpx
    with patch("httpx.AsyncClient.get", side_effect=httpx.ReadTimeout("slow")):
        result = await recover_removed_comments(
            link_id="abc123", base_url="https://api.pullpush.io",
            timeout_sec=1, max_recovered=50,
        )
    assert result.success is False
    assert "timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_recover_respects_max_cap():
    mock_response = {"data": [{"id": f"c{i}", "body": f"b{i}", "author": "u", "score": 1} for i in range(60)]}
    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        mock_get.return_value.json = lambda: mock_response
        mock_get.return_value.status_code = 200
        result = await recover_removed_comments(
            link_id="x", base_url="https://api.pullpush.io", timeout_sec=5, max_recovered=25,
        )
    assert len(result.comments) == 25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_reddit_pullpush.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `pullpush.py`**

```python
"""pullpush.io client — recovers removed Reddit comments from the free archive.

pullpush.io is a free, no-auth, rate-limited (60 req/min) archive that preserves
comment text after moderator removal. We query it only when the Reddit JSON
response shows a comment-count divergence > threshold, to avoid hammering it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PullPushComment:
    id: str
    body: str
    author: str
    score: int


@dataclass
class PullPushResult:
    comments: list[PullPushComment] = field(default_factory=list)
    success: bool = True
    error: str | None = None


async def recover_removed_comments(
    *, link_id: str, base_url: str, timeout_sec: int, max_recovered: int,
) -> PullPushResult:
    """Fetch archived comments for a Reddit thread.

    Args:
        link_id: the Reddit submission's base36 id (e.g. "1getc4l") WITHOUT the "t3_" prefix.
        base_url: pullpush.io base (configurable for testing).
        timeout_sec: per-request timeout.
        max_recovered: cap on comments returned.
    """
    url = f"{base_url.rstrip('/')}/reddit/search/comment/"
    params = {"link_id": f"t3_{link_id}", "size": max_recovered, "sort": "score", "sort_type": "score"}
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return PullPushResult(success=False, error=f"pullpush HTTP {resp.status_code}")
            data = resp.json()
    except httpx.TimeoutException as exc:
        return PullPushResult(success=False, error=f"timeout: {exc}")
    except Exception as exc:
        return PullPushResult(success=False, error=f"unexpected: {exc}")

    raw = (data or {}).get("data") or []
    comments: list[PullPushComment] = []
    for entry in raw[:max_recovered]:
        body = (entry.get("body") or "").strip()
        if not body or body in {"[removed]", "[deleted]"}:
            continue
        comments.append(PullPushComment(
            id=entry.get("id", ""),
            body=body,
            author=entry.get("author", "[unknown]"),
            score=int(entry.get("score") or 0),
        ))
    return PullPushResult(comments=comments, success=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_reddit_pullpush.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add website/features/summarization_engine/source_ingest/reddit/pullpush.py tests/unit/summarization_engine/source_ingest/test_reddit_pullpush.py
git commit -m "feat: pullpush archived comment recovery"
```

---

## Task 4: Wire pullpush enrichment into `RedditIngestor`

**Files:**
- Modify: `website/features/summarization_engine/source_ingest/reddit/ingest.py`

- [ ] **Step 1: Import + conditional enrichment inside `_ingest_json`**

Add at the top of `ingest.py`:

```python
from website.features.summarization_engine.source_ingest.reddit.pullpush import recover_removed_comments
```

After computing `divergence_pct` (Task 2's changes), and BEFORE the `return IngestResult(...)` block, add:

```python
        # Pullpush enrichment: recover removed comment bodies when divergence exceeds threshold.
        recovered_section = ""
        pullpush_fetched = 0
        if (
            config.get("pullpush_enabled", True)
            and divergence_pct >= float(config.get("divergence_threshold_pct", 20))
            and num_comments > 0
        ):
            link_id = post.get("id")
            if link_id:
                pp = await recover_removed_comments(
                    link_id=link_id,
                    base_url=config.get("pullpush_base_url", "https://api.pullpush.io"),
                    timeout_sec=int(config.get("pullpush_timeout_sec", 10)),
                    max_recovered=int(config.get("pullpush_max_recovered_comments", 25)),
                )
                if pp.success and pp.comments:
                    lines = [
                        f"[u/{c.author}, score {c.score}, recovered from pullpush.io] {c.body}"
                        for c in pp.comments
                    ]
                    recovered_section = "\n".join(lines)
                    pullpush_fetched = len(pp.comments)
                    sections["Recovered Comments"] = recovered_section
                else:
                    logger.info("[reddit-pullpush] no recovery for link_id=%s err=%s", link_id, pp.error)
```

Update the `metadata` block in the return to include:

```python
                "pullpush_fetched": pullpush_fetched,
                "pullpush_enabled": bool(config.get("pullpush_enabled", True)),
```

And update `raw_text` to include the recovered section (it's already in `sections`, but `join_sections` composes them in insertion order — that's fine, just ensure the write order is `Post → Comments → Recovered Comments`).

- [ ] **Step 2: Run the existing Reddit tests to ensure no regression**

Run: `pytest website/features/summarization_engine/tests/unit/ -k reddit -v` (and any integration tests with `--live` flag off).
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add website/features/summarization_engine/source_ingest/reddit/ingest.py
git commit -m "feat: reddit pullpush enrichment conditional"
```

---

## Task 5: Phase 0.5 benchmark runner

**Files:**
- Create: `ops/scripts/benchmark_reddit_ingest.py`

- [ ] **Step 1: Create the benchmark script**

```python
"""Benchmark Reddit ingest strategies on the 4 Reddit URLs in links.txt."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.links_parser import parse_links_file
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.source_ingest.reddit.ingest import RedditIngestor


STRATEGIES = [
    ("01-anon-json-only", {"pullpush_enabled": False}),
    ("02-anon-json-plus-pullpush", {"pullpush_enabled": True, "divergence_threshold_pct": 20}),
]


async def _benchmark():
    cfg = load_config()
    base_reddit_cfg = cfg.sources.get("reddit", {})
    urls = parse_links_file(Path("docs/testing/links.txt")).get("reddit", [])[:4]
    if not urls:
        print("No Reddit URLs; add 3+ under '# Reddit' in docs/testing/links.txt")
        return

    out_root = Path("docs/summary_eval/reddit/phase0.5-ingest/candidates")
    out_root.mkdir(parents=True, exist_ok=True)

    for filename, overrides in STRATEGIES:
        per_url = []
        merged_cfg = {**base_reddit_cfg, **overrides}
        ingestor = RedditIngestor()
        for url in urls:
            try:
                result = await ingestor.ingest(url, config=merged_cfg)
                per_url.append({
                    "url": url,
                    "success": True,
                    "extraction_confidence": result.extraction_confidence,
                    "raw_text_chars": len(result.raw_text),
                    "num_comments": result.metadata.get("num_comments"),
                    "rendered_comment_count": result.metadata.get("rendered_comment_count"),
                    "comment_divergence_pct": result.metadata.get("comment_divergence_pct"),
                    "pullpush_fetched": result.metadata.get("pullpush_fetched", 0),
                })
            except Exception as exc:
                per_url.append({"url": url, "success": False, "error": str(exc)})
        agg = {
            "strategy": filename,
            "success_rate": sum(1 for u in per_url if u.get("success")) / max(len(per_url), 1),
            "mean_chars": sum(u.get("raw_text_chars", 0) for u in per_url) / max(len(per_url), 1),
            "total_pullpush_fetched": sum(u.get("pullpush_fetched", 0) for u in per_url if u.get("success")),
        }
        payload = {"strategy": filename, "urls_tested": urls, "per_url": per_url, "aggregate": agg}
        (out_root / f"{filename}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"{filename}: success={agg['success_rate']:.2f} mean_chars={agg['mean_chars']:.0f} pullpush_total={agg['total_pullpush_fetched']}")


if __name__ == "__main__":
    asyncio.run(_benchmark())
```

- [ ] **Step 2: Run the benchmark**

```bash
python ops/scripts/benchmark_reddit_ingest.py
```

Expected: Two candidate JSON files written under `docs/summary_eval/reddit/phase0.5-ingest/candidates/`. The `02-anon-json-plus-pullpush` file should show `total_pullpush_fetched > 0` on the two `r/IAmA` heroin threads (both contain removed comments per the spec).

- [ ] **Step 3: Commit**

```bash
git add ops/scripts/benchmark_reddit_ingest.py docs/summary_eval/reddit/phase0.5-ingest/candidates/
git commit -m "test: reddit ingest phase 0.5 benchmark"
```

---

## Task 6: Write `decision.md` + `websearch-notes.md`

**Files:**
- Create: `docs/summary_eval/reddit/phase0.5-ingest/websearch-notes.md`
- Create: `docs/summary_eval/reddit/phase0.5-ingest/decision.md`

- [ ] **Step 1: Write `websearch-notes.md`**

```markdown
# Reddit ingest landscape — 2026-04-21

(Codex: if benchmark shows <50% pullpush recovery rate on expected-removed-comments URLs, websearch for "pullpush.io rate limit 2026", "reddit removed comment archive alternatives", "pushshift.io migration". Paste findings below.)

## Key decisions
- Anonymous JSON endpoint stays primary (fast, no auth, reliable from datacenter IPs).
- pullpush.io kept as ENRICHMENT only — only triggers when `comment_divergence_pct >= 20`.
  Rationale: avoids hammering the free archive on threads with no removed content.
- PRAW / OAuth path NOT used. It requires user-level credentials, offers no advantage over
  anonymous JSON for read-only flows, and adds auth complexity. Flagged as a fallback-of-last-resort
  if Reddit ever blocks anonymous JSON globally (not current 2026 behavior).
```

- [ ] **Step 2: Write `decision.md`**

```markdown
# Reddit Phase 0.5 — decision

## Chain (ordered)
1. Anonymous JSON endpoint `<permalink>.json` with UA rotation. Always primary.
2. `pullpush.io/reddit/search/comment/?link_id=t3_<id>` for removed-comment recovery.
   Triggers when `(num_comments - rendered_count) / num_comments >= 20%`.
3. HTML fallback (existing; unchanged).
4. On full failure: `extraction_confidence="low"` + rubric composite auto-capped at 75.

## Acceptance bar (per spec §7.2)
- All 4 Reddit URLs in links.txt return `extraction_confidence >= medium`.
- Both `r/IAmA` heroin URLs (known to contain removed comments) yield `pullpush_fetched > 0`.
- Divergence percentages are recorded in metadata so the evaluator can score the
  "missing/removed comments" rubric criterion (rubric_reddit.yaml → detailed.moderation_context).

## Benchmark outcome
(Codex: paste summary line from each candidate JSON's aggregate block.)
```

- [ ] **Step 3: Commit**

```bash
git add docs/summary_eval/reddit/phase0.5-ingest/websearch-notes.md docs/summary_eval/reddit/phase0.5-ingest/decision.md
git commit -m "docs: reddit phase 0.5 decision and notes"
```

---

## Task 7: End-to-end smoke — summarize one Reddit URL via `/api/v2/summarize`

**Files:**
- Append to: `docs/summary_eval/reddit/phase0-smoke.md`

- [ ] **Step 1: Start the local server + hit the API**

```bash
python run.py &
sleep 5
curl -X POST http://127.0.0.1:10000/api/v2/summarize \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and/"}' \
  | python -m json.tool > /tmp/reddit-smoke.json
kill %1
```

- [ ] **Step 2: Validate the response**

Open `/tmp/reddit-smoke.json`. Verify:
- `summary.mini_title` matches regex `^r/[^ ]+ .+$` (per `RedditStructuredPayload`).
- `summary.detailed_summary.op_intent` is non-empty.
- `summary.detailed_summary.reply_clusters` has ≥ 1 entry.
- `summary.metadata.extraction_confidence` is `"high"` or `"medium"`.

- [ ] **Step 3: Create `phase0-smoke.md`**

```markdown
# Reddit Phase 0.5 smoke — 2026-04-21

## Exit criteria (per spec §7.2 + §6.1)
- [ ] POST /api/v2/summarize returns RedditStructuredPayload with r/<sub> + title label
- [ ] reply_clusters is non-empty (≥ 1)
- [ ] If source had removed comments, `pullpush_fetched > 0` in metadata
- [ ] `comment_divergence_pct` present in metadata

## Results
(Codex: paste output of curl above, trimmed.)
```

- [ ] **Step 4: Commit**

```bash
git add docs/summary_eval/reddit/phase0-smoke.md
git commit -m "test: reddit smoke api summarize"
```

---

## Task 8: Push branch + open draft PR

- [ ] **Step 1: Push and open draft PR**

```bash
git push origin eval/summary-engine-v2-scoring-reddit
gh pr create --draft --title "feat: reddit phase 0.5 pullpush plus divergence" \
  --body "Plan 2 of 5. Adds pullpush.io enrichment + num_comments/rendered_count divergence. Ready for Reddit iteration loops 1-7 after merge. Plan: docs/superpowers/plans/2026-04-21-summarization-engine-plan2-reddit.md"
```

---

## Self-review checklist
- [ ] `_compute_divergence` covers zero-total + rendered>total edge cases
- [ ] pullpush enrichment is CONDITIONAL (only fires on divergence ≥ threshold) — not hammering the free archive
- [ ] `config.yaml` has all new `pullpush_*` keys with sensible defaults
- [ ] Benchmark runner writes 2 candidate JSONs + both use the 4 Reddit URLs from links.txt
- [ ] No PRAW / OAuth dependency — purely anonymous + free pullpush
- [ ] `extraction_confidence` stays at `high` for JSON-successful ingests even when pullpush fails
