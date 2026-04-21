# Summarization Engine Plan 5 — Polish Sources Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Phase 0.5 touch-ups + 2-3 iteration loops per polish source (HackerNews, LinkedIn, Arxiv, Podcast, Twitter, Web) so every source in the engine summarizes at ≥ 85 composite. Produce the final `cross_source_lessons.md` synthesis that carries learnings from Plans 1-4 into the polish tail.

**Architecture:** Each polish source already has an ingestor + a `DefaultSummarizer` subclass registered in Plan 1 Phase 0.B (Task 14). The `rubric_universal.yaml` covers all 6. This plan does NOT do full 7-loop cycles per source — it runs short 2-3 loop polish cycles and retroactively adds Phase 0.5 fixes ONLY if a source plateaus below 85 composite. Twitter is the one expected trouble source due to Nitter instance churn; the plan pre-wires a Nitter health-cache pool mirroring the YouTube Piped/Invidious pattern.

**Tech Stack:** Python 3.12, existing ingestors, `httpx`, Gemini Flash. No paid services.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §7.5 + §8.1

**Branch:** `eval/summary-engine-v2-scoring-polish`, off `master` AFTER Plan 4's PR merges.

**Precondition:** Plans 1-4 merged. `rubric_universal.yaml` exists. DefaultSummarizer subclasses registered for all 6 polish source types.

---

## Scope summary (per source)

| Source | Phase 0.5 fix required? | URL discovery needed? | Expected effort |
|---|---|---|---|
| HackerNews | No (Algolia API already strong) | Yes if `# HackerNews` in links.txt is empty | Low |
| LinkedIn | Maybe (authwall detection) | Yes | Medium |
| Arxiv | No (arxiv API canonical) | Yes | Low |
| Podcast | Maybe (show-notes precedence) | Yes | Medium |
| Twitter | Yes (Nitter pool health-cache) | Already 1 URL; need 2 more | Medium-high |
| Web | No (generic extractors strong) | Yes | Low |

---

## File structure summary

### Files to CREATE
- `website/features/summarization_engine/source_ingest/twitter/nitter_pool.py`
- `docs/summary_eval/polish/<source>/iter-01/` (one per source, 6 total)
- `docs/summary_eval/polish/<source>/iter-02/`
- `docs/summary_eval/polish/<source>/iter-03/` (triggered only if score < 85 after iter-02)
- `docs/summary_eval/polish/<source>/final_scorecard.md` (6 total)
- `docs/summary_eval/polish/cross_source_lessons.md`
- `tests/unit/summarization_engine/source_ingest/test_twitter_nitter_pool.py`

### Files to MODIFY
- `website/features/summarization_engine/source_ingest/twitter/ingest.py` — use Nitter pool with health-cache
- `website/features/summarization_engine/config.yaml` — expand `sources.twitter.nitter_instances`

---

## Task 0: Create Plan 5 sub-branch

- [ ] **Step 1: Confirm Plan 4 merged**

```bash
git checkout master && git pull
python -c "from website.features.summarization_engine.source_ingest.newsletter.stance import classify_stance; print('OK')"
```

- [ ] **Step 2: Create branch**

```bash
git checkout -b eval/summary-engine-v2-scoring-polish
git push -u origin eval/summary-engine-v2-scoring-polish
```

---

## Task 1: Extend Twitter Nitter instance list + add health cache

**Files:**
- Modify: `website/features/summarization_engine/config.yaml`
- Create: `website/features/summarization_engine/source_ingest/twitter/nitter_pool.py`
- Test: `tests/unit/summarization_engine/source_ingest/test_twitter_nitter_pool.py`

- [ ] **Step 1: Extend `sources.twitter` config**

```yaml
  twitter:
    use_oembed: true
    use_nitter_fallback: true
    nitter_instances:
      - "https://xcancel.com"
      - "https://nitter.poast.org"
      - "https://nitter.privacyredirect.com"
      - "https://lightbrd.com"
      - "https://nitter.space"
      - "https://nitter.tiekoetter.com"
      - "https://nitter.net"
      - "https://nitter.salastil.com"
    nitter_health_check_timeout_sec: 5
    nitter_rotation_on_failure: true
    nitter_health_ttl_hours: 1
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/summarization_engine/source_ingest/test_twitter_nitter_pool.py
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch

from website.features.summarization_engine.source_ingest.twitter.nitter_pool import (
    select_healthy_instance, mark_unhealthy, _load_health, _save_health,
)


def test_unhealthy_instance_skipped_within_ttl(tmp_path, monkeypatch):
    health_file = tmp_path / "health.json"
    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.twitter.nitter_pool._HEALTH_PATH",
        health_file,
    )
    mark_unhealthy("https://dead.example.com")
    loaded = _load_health()
    assert "https://dead.example.com" in loaded


@pytest.mark.asyncio
async def test_select_healthy_instance_returns_first_reachable():
    instances = ["https://a.example", "https://b.example", "https://c.example"]
    with patch("httpx.AsyncClient.head", new=AsyncMock()) as mock_head:
        # First instance 500, second 200, third not called.
        responses = [type("R", (), {"status_code": 500})(), type("R", (), {"status_code": 200})()]
        mock_head.side_effect = responses
        result = await select_healthy_instance(instances, timeout_sec=2, ttl_hours=1)
    assert result == "https://b.example"
```

- [ ] **Step 3: Create `nitter_pool.py`**

```python
"""Nitter instance pool with health cache."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_HEALTH_PATH = (
    Path(__file__).resolve().parents[5]
    / "docs" / "summary_eval" / "_cache" / "nitter_instance_health.json"
)


def _load_health() -> dict[str, str]:
    if not _HEALTH_PATH.exists():
        return {}
    try:
        return json.loads(_HEALTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_health(d: dict[str, str]) -> None:
    _HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HEALTH_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")


def mark_unhealthy(instance: str) -> None:
    health = _load_health()
    health[instance] = datetime.now(timezone.utc).isoformat()
    _save_health(health)


def _is_healthy(instance: str, ttl_hours: int) -> bool:
    health = _load_health()
    last_bad = health.get(instance)
    if not last_bad:
        return True
    try:
        when = datetime.fromisoformat(last_bad)
        return datetime.now(timezone.utc) - when > timedelta(hours=ttl_hours)
    except Exception:
        return True


async def select_healthy_instance(instances: list[str], *, timeout_sec: int, ttl_hours: int) -> str | None:
    """Probe instances in order, return the first one that responds 200 to HEAD /."""
    async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
        for instance in instances:
            if not _is_healthy(instance, ttl_hours):
                continue
            try:
                resp = await client.head(instance)
                if 200 <= resp.status_code < 400:
                    return instance
                mark_unhealthy(instance)
            except Exception as exc:
                logger.warning("[nitter-pool] %s failed health: %s", instance, exc)
                mark_unhealthy(instance)
    return None
```

- [ ] **Step 4: Wire `select_healthy_instance` into `TwitterIngestor`**

In `website/features/summarization_engine/source_ingest/twitter/ingest.py`, find the Nitter fallback block. Replace the "pick first instance" logic with:

```python
        from website.features.summarization_engine.source_ingest.twitter.nitter_pool import select_healthy_instance
        healthy = await select_healthy_instance(
            instances=config.get("nitter_instances", []),
            timeout_sec=int(config.get("nitter_health_check_timeout_sec", 5)),
            ttl_hours=int(config.get("nitter_health_ttl_hours", 1)),
        )
        if healthy:
            # Use `healthy` as the instance base instead of looping through instances.
            # Subagent: adapt to existing call shape (replace the instance-selection loop).
            ...
```

- [ ] **Step 5: Run tests + commit**

Run: `pytest tests/unit/summarization_engine/source_ingest/test_twitter_nitter_pool.py website/features/summarization_engine/tests/unit/ -k twitter -v` → PASS.

```bash
git add website/features/summarization_engine/source_ingest/twitter/ tests/unit/summarization_engine/source_ingest/test_twitter_nitter_pool.py website/features/summarization_engine/config.yaml
git commit -m "feat: twitter nitter pool with health cache"
```

---

## Task 2: Auto-discover URLs for empty polish sources

**Files:**
- Modify: `docs/testing/links.txt` — append auto-discovered URLs
- Create: `docs/summary_eval/polish/<source>/auto_discovered_urls.md` (one per source as needed)

- [ ] **Step 1: For each polish source with < 3 URLs, run URL discovery**

```bash
for source in hackernews linkedin arxiv podcast twitter web; do
  current_count=$(python ops/scripts/eval_loop.py --source $source --list-urls 2>/dev/null | python -c "import sys,json; print(len(json.load(sys.stdin)))")
  if [ "$current_count" -lt 3 ]; then
    echo "Discovering URLs for $source (current: $current_count)..."
    python -c "
import asyncio, sys
sys.path.insert(0, '.')
from ops.scripts.lib.url_discovery import discover_urls, write_discovery_report
from website.features.summarization_engine.api.routes import _gemini_client
from pathlib import Path

async def main():
    client = _gemini_client()
    urls = await discover_urls('$source', client, count=3)
    out_path = Path('docs/summary_eval/polish/$source/auto_discovered_urls.md')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_discovery_report('$source', urls, out_path)
    # Append URLs to links.txt under the matching header
    import re
    links_path = Path('docs/testing/links.txt')
    content = links_path.read_text(encoding='utf-8')
    new_urls = '\n'.join(u.get('url', '') for u in urls if u.get('url'))
    header_source_map = {'hackernews': '# HackerNews', 'linkedin': '# LinkedIn', 'arxiv': '# Arxiv', 'podcast': '# Podcast', 'twitter': '# Twitter', 'web': '# Web'}
    header = header_source_map['$source']
    pattern = re.compile(rf'(^{re.escape(header)}\s*\n(?:.*\n)*?)(?=^#|\Z)', re.MULTILINE)
    def inject(match):
        section = match.group(1).rstrip() + '\n' + new_urls + '\n'
        return section
    content = pattern.sub(inject, content, count=1)
    links_path.write_text(content, encoding='utf-8')

asyncio.run(main())
"
  fi
done
```

- [ ] **Step 2: Verify all polish sources now have ≥ 3 URLs**

```bash
for source in hackernews linkedin arxiv podcast twitter web; do
  count=$(python ops/scripts/eval_loop.py --source $source --list-urls | python -c "import sys,json; print(len(json.load(sys.stdin)))")
  echo "$source: $count URLs"
done
```
Expected: all ≥ 3.

- [ ] **Step 3: Commit**

```bash
git add docs/testing/links.txt docs/summary_eval/polish/
git commit -m "feat: auto discover polish source urls"
```

---

## Task 3: Run polish iteration loop 1 for each source (baseline)

Loop 1 is measurement-only per spec §4.1. No tuning yet.

- [ ] **Step 1: Server up**

```bash
python run.py &
sleep 5
```

- [ ] **Step 2: For each polish source, run iter-01**

```bash
for source in hackernews linkedin arxiv podcast twitter web; do
  python ops/scripts/eval_loop.py --source $source --iter 1 --phase iter
done
```

This runs Phase A (summary + eval + manual_review_prompt emission) for each. CLI exits with `status=awaiting_manual_review` for each. The artifact tree looks like:
```
docs/summary_eval/polish/<source>/iter-01/
    summary.json
    eval.json
    manual_review_prompt.md
```

- [ ] **Step 3: For each source, Codex writes `manual_review.md`**

Read each `manual_review_prompt.md`, produce `manual_review.md` with the blind-review stamp and `estimated_composite: NN.N` final line. Honor the same rubric-scoring contract as the major sources but use `rubric_universal.yaml`.

- [ ] **Step 4: For each source, re-invoke the CLI to complete Phase B**

```bash
for source in hackernews linkedin arxiv podcast twitter web; do
  python ops/scripts/eval_loop.py --source $source --iter 1 --phase iter
done
```

CLI auto-detects `manual_review.md` exists → runs Phase B (diff + next_actions + commit).

- [ ] **Step 5: Kill server**

```bash
kill %1
```

- [ ] **Step 6: Record baseline scores**

For each source, open `docs/summary_eval/polish/<source>/iter-01/eval.json`, note the `composite_score`. If any source scored ≥ 85 at baseline, it's already polish-ready — mark converged in `final_scorecard.md` and skip iters 2-3.

---

## Task 4: Polish iteration loop 2 (targeted tune, only for sources < 85)

For any polish source where iter-01 composite < 85, Codex reads `next_actions.md` and applies edits. Allowed edit surfaces (same as §8.3 of the spec):

- `website/features/summarization_engine/source_ingest/<source>/ingest.py`
- `website/features/summarization_engine/summarization/default/summarizer.py` (touch only with a cross-source impact note in the commit)
- `website/features/summarization_engine/summarization/common/prompts.py` `SOURCE_CONTEXT[<source>]` string
- `docs/summary_eval/_config/rubric_universal.yaml` (misspecification fixes only)

Churn protection from spec §8.4 applies.

- [ ] **Step 1: Server up**

```bash
python run.py &
sleep 5
```

- [ ] **Step 2: For each sub-85 source, run iter-02**

```bash
# Example: suppose linkedin and twitter scored < 85 at iter-01
for source in linkedin twitter; do
  python ops/scripts/eval_loop.py --source $source --iter 2 --phase iter
done
```

- [ ] **Step 3: Codex writes manual_review.md for each; re-invokes CLI for Phase B**

Same protocol as Task 3.

- [ ] **Step 4: Record iter-02 scores**

If ≥ 85, mark converged. Else proceed to iter-03.

---

## Task 5: Polish iteration loop 3 (only if iter-02 still < 85)

Per spec: "if scores plateau below 85 on any of them, that source gets a retroactive Phase 0.5 added before its extension loops". Task 5 implements that retroactive Phase 0.5 for stubborn sources.

- [ ] **Step 1: For each stubborn source, run WebSearch + design Phase 0.5 fix**

Codex websearches:
- **LinkedIn**: "linkedin public post bypass authwall 2026"
- **Podcast**: "Podcast Index API free key 2026", "show notes scraper 2026"
- **Twitter**: "Nitter alternatives 2026 mass shutdown"

Produces `docs/summary_eval/polish/<source>/phase0.5-retroactive/websearch-notes.md` + `decision.md`.

- [ ] **Step 2: Implement the retroactive Phase 0.5 fix**

Scope: source-specific, must stay inside that source's `source_ingest/<source>/ingest.py` + its section in `config.yaml`. No cross-cutting changes.

- [ ] **Step 3: Re-run iter-03 to verify the fix moves the score**

```bash
python run.py &
sleep 5
python ops/scripts/eval_loop.py --source <stubborn_source> --iter 3 --phase iter
# ... Codex writes manual_review.md, re-invokes CLI ...
kill %1
```

- [ ] **Step 4: If STILL < 85, mark as `degraded` in final_scorecard.md**

Per spec §8.1, sources that fail polish thresholds after retroactive fixes are marked `degraded` with a documented root cause. The program does not block on one source failing.

---

## Task 6: Write per-source `final_scorecard.md`

**Files:**
- Create: `docs/summary_eval/polish/<source>/final_scorecard.md` (6 total)

- [ ] **Step 1: For each polish source, write final_scorecard.md**

Template:

```markdown
# <Source> — Polish Final Scorecard

## Baseline (iter-01)
- composite_score: <from iter-01/eval.json>
- Gemini/Codex divergence: <from iter-01/manual_review.md>

## Final (iter-02 or iter-03)
- composite_score: <final>
- held-out coverage: 3/3 URLs
- status: **converged** | **degraded**

## Delta analysis
- What moved: <criterion_id: Δ>
- What didn't: <criterion_id: Δ, reason>

## Retroactive Phase 0.5 (if applied)
- What was added: <one-paragraph summary>
- Reference: docs/summary_eval/polish/<source>/phase0.5-retroactive/decision.md

## Open issues for future iteration
- <short bullets>
```

- [ ] **Step 2: Commit**

```bash
git add docs/summary_eval/polish/
git commit -m "docs: polish sources final scorecards"
```

---

## Task 7: Write `cross_source_lessons.md`

**Files:**
- Create: `docs/summary_eval/polish/cross_source_lessons.md`

- [ ] **Step 1: Draft the synthesis**

```markdown
# Cross-source lessons learned — 2026-04-21

Synthesized across all 10 sources (YouTube, Reddit, GitHub, Newsletter + 6 polish sources).

## Patterns that consistently moved the score

### 1. Per-source Pydantic schema strictness
The single biggest lever across every source was making `StructuredSummaryPayload` per-source with
typed required fields. The LLM cannot omit `speakers` (YouTube), `op_intent` (Reddit), `architecture_overview`
(GitHub), `conclusions_or_recommendations` (Newsletter) when the schema requires them.

### 2. Anti-pattern cap dominance
`anti_patterns_triggered` with `auto_cap=60` is the strongest guard against hallucination. When a summary
triggered any anti-pattern, no amount of prompt tuning could raise its composite above 60 — this forced
every tuning loop to address the root cause rather than paper over it.

### 3. Ingest signal completeness precedes prompt tuning
Sources where Phase 0.5 captured more signal (GitHub's 5 API calls, Newsletter's stance + conclusions,
YouTube's 5-tier transcript chain) showed higher baseline scores at iter-01 than Reddit (which relied on
Plan 1's schema alone). Signal completeness matters more than prompt wording.

### 4. Cross-model isolation catches bias
Gemini standard evaluator vs Codex manual review diverged by > 10 points on <X%> of iterations.
<Summary of common divergence patterns: e.g., Codex more strict on editorialization, Gemini more lenient
on tag specificity; or vice versa.>

### 5. Rubric criteria that were hardest to score consistently
- Rubric criteria where Gemini/Codex disagreed most often: <list>
- Anti-patterns that triggered spuriously: <list>

## Patterns that did NOT move the score

- <e.g., extending the CoD densifier from 2 to 3 iterations gave +0.3 composite, not worth the +1 Pro call per iteration>
- <e.g., per-source system prompts beyond what's in SOURCE_CONTEXT didn't help>

## Open questions for future sessions

- <e.g., RAGAS AspectCritic vs consolidated Gemini call — which agrees more with human review?>
- <e.g., Should SummaC-lite be split out into its own Gemini Pro call when rubric-faithfulness < 0.85?>

## Follow-up items (post-merge)

1. Migrate `telegram_bot/` capture handler to use v2 `summarize_url` so Telegram bot benefits from this work.
2. Backfill existing Supabase KG nodes via the new engine.
3. Promote `evaluator/` to `website/features/evaluation/` for reuse in RAG response evaluation.
4. Expose eval scoring via `POST /api/v2/eval` so prod can self-monitor daily captured summaries.
```

- [ ] **Step 2: Commit**

```bash
git add docs/summary_eval/polish/cross_source_lessons.md
git commit -m "docs: cross source lessons learned synthesis"
```

---

## Task 8: Push + draft PR

```bash
git push origin eval/summary-engine-v2-scoring-polish
gh pr create --draft --title "feat: polish sources and cross source lessons" \
  --body "Plan 5 of 5 — final PR. Adds Twitter Nitter pool + auto-discovered polish URLs + 2-3 polish iteration loops per source + cross_source_lessons.md synthesis. Closes the 5-PR sequence."
```

---

## Self-review checklist
- [ ] All 6 polish sources have ≥ 3 URLs in `links.txt` (user-added or auto-discovered)
- [ ] Twitter Nitter pool has 8+ instances and health-cache TTL = 1hr
- [ ] Each polish source has a `final_scorecard.md` stamped `converged` or `degraded`
- [ ] At least 5 of 6 polish sources reach `composite ≥ 85` (the 6th may be `degraded` with documented cause)
- [ ] `cross_source_lessons.md` synthesizes findings across ALL 10 sources (4 majors + 6 polish)
- [ ] No paid services introduced anywhere
- [ ] Every source-specific Phase 0.5 retroactive fix is self-contained (no cross-source edits)
