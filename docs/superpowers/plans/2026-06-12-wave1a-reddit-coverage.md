# Wave 1A — Reddit Coverage-Aware Consensus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Reddit's hardcoded "Consensus stayed around… / Dissent centered on…" brief/layout templates coverage-aware so representativeness claims are scoped to the fetched comment frame (or dropped) instead of asserted thread-wide, using a corrected fetched-comment denominator and a config-driven tiered claim ladder — with zero new model calls.

**Architecture:** A new pure module `website/features/summarization_engine/summarization/reddit/coverage.py` computes a `CoverageContext` (tier + counts) from ingest metadata and supplies tier-specific phrasing helpers (consensus / plurality / sample-scoped / anecdote). The corrected denominator `fetched_comment_count = rendered_comment_count + nested_reply_count` is added at the ingest seam (`source_ingest/reddit/ingest.py`). Coverage logic is injected through the existing enrichment seam `_apply_ingest_enrichments` (`reddit/summarizer.py:319-344`) which already has both ingest metadata and the validated payload; it rewrites the brief's stance sentence in place. The min-safe fallback (`reddit/summarizer.py::_build_minimum_safe_payload`) and the layout closing-remarks line (`reddit/layout.py:201`) are made non-asserting (drop the unconditional consensus claim) so the system never claims consensus on a thread it knows nothing about.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML (config loader mirrors `reddit/cluster_rebalance.py`), pytest (`asyncio_mode=auto`), stdlib only for the math (two integer ops + one float divide). No Gemini call on any new path.

---

## VERIFICATION SUMMARY (read before implementing — every seam confirmed against the live tree on 2026-06-12)

All line numbers below were read from disk, not the punch list. Where the task spec diverged from the actual code, it is **FLAGGED**.

| Seam (task spec) | Actual state on disk | Action |
|---|---|---|
| `reddit/schema.py:218-226` `_repair_brief_summary` consensus template | **CONFIRMED.** Lines 218-226 build `_as_sentence(f"Consensus stayed around {…}")` (221) + `_as_sentence(f"Dissent centered on {…}")` (222). `_consensus_phrase` at 230-237. **CRITICAL:** this function runs inside the Pydantic `model_validator` (schema.py:79-86) and has **no access to ingest metadata** — coverage is unknown here. So the coverage rewrite happens at the enrichment seam (Task 5), NOT here. This template is left structurally intact (it is the no-signal default) but Task 5 rewrites its stance sentence afterward when coverage IS known. | Touched indirectly via Task 5 rewrite; `_repair_brief_summary` itself unchanged. |
| `reddit/schema.py:282` min-safe fallback | **FLAG — WRONG FILE/LINE.** The min-safe consensus line is in **`reddit/summarizer.py:283`** (`"Consensus stayed around general discussion of the topic."`), inside `_build_minimum_safe_payload` (summarizer.py:267-316), **not** schema.py:282 (which is the `_consensus_phrase` `if reply_clusters:` branch). Task 1 fixes the real site in summarizer.py. | Task 1 → `summarizer.py`. |
| `reddit/layout.py:201` "rough consensus" | **CONFIRMED.** Line 201: `"Resolution: the thread reached rough consensus with no major unresolved questions."` in `_closing_remarks_section` (174-203). **CRITICAL:** layout is render-time, built from the *payload only* — it has **no ingest metadata / counts**. So it cannot be tiered by coverage; per the spec's "drop, don't soften" rule for the no-signal path, Task 2 replaces it with a non-asserting resolution line. | Task 2 → `layout.py`. |
| `source_ingest/reddit/ingest.py:58-60` `rendered_count` top-level `t1` only | **CONFIRMED.** Lines 58-60 count only `child.get("kind") == "t1"` at the top level. `nested_reply_count` is returned separately from `_comment_tree_texts` (49, 316, 346) and already stored at metadata key `nested_reply_count` (112). `num_comments` stored at key `num_comments` (110). No `fetched_comment_count` exists. `_compute_divergence` (349-356) uses `num_comments - rendered_count` (the measurement bug). | Task 3 adds `fetched_comment_count`; **does NOT rename `comment_divergence_pct`** (eval harness reads it — Sol-4 M2). |
| `reddit/summarizer.py:319-344` `_apply_ingest_enrichments` | **CONFIRMED.** Reads `ingest.metadata` (subreddit, `comment_divergence_pct`, `pullpush_fetched`, `rendered_comment_count`, `num_comments`) and mutates `payload.detailed_summary` (deepcopy → set `moderation_context`). Returns the payload. Called twice: (a) summarizer.py:89-90 on the min-safe fallback in the except path, (b) summarizer.py:174 on the validated payload. **This is the only seam with both metadata and payload.** | Task 5 injects coverage rewrite here. |
| `summarizer.py:330-342` divergence note | **CONFIRMED.** Builds a `Rendered comments covered only part of the thread (rendered/total visible; divergence …%)` note when `divergence >= 20`. Task 5 must not double-mutate `moderation_context`; it touches the **brief**, not the note. | Task 5 leaves the note path intact. |

**Config-loader pattern** mirrors `reddit/cluster_rebalance.py` exactly: separate YAML at `docs/summary_eval/_config/`, `REDDIT_*_YAML` env override, `@lru_cache` keyed on path-string, `{}` no-op when file missing, loud `ValueError` on malformed shape, `reset_config_cache()` test helper. Tests use `monkeypatch.setenv(<ENV>, str(_REAL_YAML))` + `reset_config_cache()` in an `autouse` fixture (see `test_cluster_rebalance.py:54-60`).

**THRESHOLD CALIBRATION — OPERATOR CONFIRMATION REQUIRED AT WAVE 1A.** The tiered ladder defaults below are **research-informed starting values, NOT final**. They MUST be calibrated on the 15-thread Reddit eval set during execution, and **the operator must explicitly confirm the final thresholds before this ships to production** (open decision #3 in `docs/claude_audits/zettel_eval_solutions_research_2026-06-09.md`). The defaults live in YAML precisely so calibration is a config edit, not a code change.

**FLAG — threshold divergence from the prior research doc.** `zettel_eval_solutions_research_2026-06-09.md:55` recorded the consensus gate as a single boolean `coverage ≥ 0.60 AND fetched ≥ 10`. This plan RAISES the consensus floor to `fetched ≥ 25` and introduces a *tiered* ladder (consensus / plurality / sample-scoped / anecdote) per the Wave-1A task spec. Rationale: at n=10 a 50/50 split has a ~±31 percentage-point 95% CI (PSU STAT 200 proportion sample size; MeasuringU finite-population-correction — N=100 needs ~79 read for ±5%, ~48 for ±10%), far too wide to assert "most agree". This supersedes the single-boolean note. Surface to operator with the calibration ask above.

**Citations carried into forensic comments / commits where load-bearing:**
- Tiered floors / sample size: PSU STAT 200 proportion sample size; MeasuringU FPC.
- Selection bias (top/best sort is position-biased non-probability sample): Glenski et al. 2017 (arXiv:1703.05267); Zhu et al. 2025 (arXiv:2510.05154); Huang et al. 2023 (arXiv:2306.04424).
- Phrasing assertiveness tracks coverage; state N-of-M, counts over % at small n: epistemic-marker calibration (arXiv:2505.24778); AAPOR disclosure norms.

---

## Task 1 — Min-safe fallback must not assert consensus

The min-safe payload is built when the summarizer hits an unrecoverable exception — it knows *nothing* about the thread's stance distribution, yet it currently hardcodes "Consensus stayed around general discussion of the topic." and "Dissent was not reliably identified…". Fix: replace those two sentences with sample-scoped, non-asserting copy that states only what is true (extraction degraded; minimal metadata).

**Files:**
- Modify: `website/features/summarization_engine/summarization/reddit/summarizer.py:279-285` (the `brief_sentences` list in `_build_minimum_safe_payload`)
- Test: `tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py` (Create)

Current code to replace (summarizer.py:279-286), quoted verbatim:
```python
    brief_sentences = [
        f"OP posted in r/{subreddit} about {title[:120]}.",
        "The thread contained replies that could not be fully clustered by the summarizer.",
        "Consensus stayed around general discussion of the topic.",
        "Dissent was not reliably identified in the visible replies.",
        "Caveat: structured extraction degraded; only minimal metadata is available.",
    ]
    brief = " ".join(brief_sentences)[:400]
```

### Steps

- [ ] **Write failing test** (REAL code) — create the test file and assert the min-safe brief carries no consensus/representativeness claim:
```python
# tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py
"""Wave 1A: coverage-aware Reddit consensus phrasing.

Locks that no Reddit brief asserts thread-wide consensus when coverage is
unknown or below the calibrated floors. Pure string/threshold logic — no
LLM calls.
"""
from __future__ import annotations

from datetime import datetime, timezone

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.reddit.summarizer import (
    _build_minimum_safe_payload,
)

_BANNED_REPRESENTATIVE = ("consensus", "most agree", "the thread agreed", "dissent centered")


def _ingest(metadata: dict) -> IngestResult:
    return IngestResult(
        source_type=SourceType.REDDIT,
        url="https://www.reddit.com/r/test/comments/abc/x/",
        original_url="https://www.reddit.com/r/test/comments/abc/x/",
        raw_text="",
        sections={},
        metadata=metadata,
        extraction_confidence="low",
        confidence_reason="test",
        fetched_at=datetime.now(timezone.utc),
    )


def test_min_safe_fallback_makes_no_consensus_claim():
    ingest = _ingest({"subreddit": "test", "title": "Some thread"})
    payload = _build_minimum_safe_payload("", ingest)
    brief_lower = payload.brief_summary.lower()
    for banned in _BANNED_REPRESENTATIVE:
        assert banned not in brief_lower, f"min-safe brief must not assert {banned!r}: {payload.brief_summary!r}"


def test_min_safe_fallback_stays_within_char_bound():
    ingest = _ingest({"subreddit": "test", "title": "x" * 300})
    payload = _build_minimum_safe_payload("", ingest)
    assert len(payload.brief_summary) <= 400
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py::test_min_safe_fallback_makes_no_consensus_claim -q
```
Expected: FAIL — `AssertionError: min-safe brief must not assert 'consensus'` (current line 283 contains "Consensus stayed around general discussion…").

- [ ] **Minimal impl** (REAL code) — replace summarizer.py:279-285 with non-asserting copy:
```python
    # Wave 1A: this path knows nothing about the thread's stance distribution
    # (unrecoverable extraction) — never assert consensus/dissent here.
    brief_sentences = [
        f"OP posted in r/{subreddit} about {title[:120]}.",
        "Structured extraction degraded, so the reply breakdown could not be reconstructed.",
        "No representativeness claim can be made about the thread from the available sample.",
        "Caveat: only minimal post metadata is available for this capture.",
    ]
    brief = " ".join(brief_sentences)[:400]
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py -q
```
Expected: 2 passed.

- [ ] **Commit:**
```
git commit -m "fix: min-safe reddit brief drops consensus claim"
```

### Self-review
- [ ] Brief still has ≥3 sentences (min-safe payload uses `model_construct`, bypassing the 5-7 validator, so no sentence-count gate applies here — confirmed schema.py:311 uses `model_construct`).
- [ ] No representativeness vocabulary remains; `title[:120]` slice and `[:400]` cap preserved.
- [ ] `_build_minimum_safe_payload` still returns a fully-valid `RedditStructuredPayload` (no field removed).

---

## Task 2 — Layout closing-remarks line stops asserting thread-wide consensus

`_closing_remarks_section` (layout.py:174-203) is render-time and has only the payload (no counts), so it cannot be tiered. Its `else` branch unconditionally claims "the thread reached rough consensus" whenever there are no open questions/counterarguments — a thread-wide representativeness claim the system cannot support. Per the spec's "drop, don't soften" rule for the no-signal path, replace it with a resolution line scoped to the captured discussion that makes no consensus claim.

**Files:**
- Modify: `website/features/summarization_engine/summarization/reddit/layout.py:200-201` (the `else` branch of `_closing_remarks_section`)
- Test: `tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py` (extend)

Current code to replace (layout.py:200-203), quoted verbatim:
```python
    else:
        takeaway = "Resolution: the thread reached rough consensus with no major unresolved questions."

    return DetailedSummarySection(heading="Closing remarks", bullets=[takeaway])
```

### Steps

- [ ] **Write failing test** (REAL code) — append to `test_coverage_phrasing.py`:
```python
from website.features.summarization_engine.summarization.reddit.layout import (
    compose_reddit_detailed,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)


def _payload_no_questions_no_counters() -> RedditStructuredPayload:
    detailed = RedditDetailedPayload(
        op_intent="OP shares a workflow tip.",
        reply_clusters=[RedditCluster(theme="Agreement", reasoning="Replies echoed the tip.")],
        counterarguments=[],
        unresolved_questions=[],
        moderation_context=None,
    )
    return RedditStructuredPayload(
        mini_title="r/test workflow tip shared",
        brief_summary=(
            "OP shares a workflow tip. Replies broadly echo it. "
            "A few add variants. Tooling is mentioned. No major dispute. "
            "Thread is short."
        ),
        tags=["test", "workflow", "tips", "tooling", "reddit-test", "productivity", "reddit"],
        detailed_summary=detailed,
    )


def test_layout_closing_remarks_makes_no_thread_wide_consensus_claim():
    payload = _payload_no_questions_no_counters()
    sections = compose_reddit_detailed(payload)
    closing = next(s for s in sections if s.heading == "Closing remarks")
    text = " ".join(closing.bullets).lower()
    assert "consensus" not in text, f"closing remarks must not assert consensus: {closing.bullets!r}"
    assert closing.bullets and closing.bullets[0].strip(), "closing remarks must stay non-empty"
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py::test_layout_closing_remarks_makes_no_thread_wide_consensus_claim -q
```
Expected: FAIL — `AssertionError: closing remarks must not assert consensus` (current line 201 says "rough consensus").

- [ ] **Minimal impl** (REAL code) — replace layout.py:200-201:
```python
    else:
        # Wave 1A: no counts available at render time → scope to the captured
        # discussion; never claim thread-wide consensus (unfetched tail unknown).
        takeaway = "Resolution: no major unresolved questions surfaced in the captured discussion."
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py -q
```
Expected: 4 passed.

- [ ] **Run the existing layout suite (regression — no break):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_layout_thesis.py -q
```
Expected: all pass (this task only touches the `else` branch string; `test_layout_thesis.py` asserts Overview thesis, untouched).

- [ ] **Commit:**
```
git commit -m "fix: reddit closing remarks drops consensus claim"
```

### Self-review
- [ ] `questions`/`counters` branches (layout.py:192-199) are unchanged — they already scope to a specific open question / counterpoint, no representativeness claim.
- [ ] Closing-remarks section still returns exactly one bullet, always non-empty.

---

## Task 3 — Corrected `fetched_comment_count` denominator at ingest

`rendered_count` (ingest.py:58-60) counts only top-level `t1` comments; nested replies that WERE fetched are tracked separately in `nested_reply_count`. Coverage must use the true fetched total. Add `fetched_comment_count = rendered_comment_count + nested_reply_count` to ingest metadata. **Do NOT rename `comment_divergence_pct`** (the eval harness reads that exact key — Sol-4 M2); `_compute_divergence` stays as-is for the existing moderation note.

**Files:**
- Modify: `website/features/summarization_engine/source_ingest/reddit/ingest.py:105-117` (the JSON-path `metadata={...}` block)
- Test: `tests/unit/summarization_engine/source_ingest/reddit/test_fetched_comment_count.py` (Create)

Current code (ingest.py:111-113), quoted verbatim — the keys we sit beside:
```python
                "rendered_comment_count": rendered_count,
                "nested_reply_count": nested_reply_count,
                "comment_divergence_pct": divergence_pct,
```

### Steps

- [ ] **Write failing test** (REAL code) — drive `_ingest_json` with a stubbed `fetch_json` so it is hermetic (no network):
```python
# tests/unit/summarization_engine/source_ingest/reddit/test_fetched_comment_count.py
"""Wave 1A: corrected fetched_comment_count = rendered + nested at ingest."""
from __future__ import annotations

import pytest

from website.features.summarization_engine.source_ingest.reddit import ingest as reddit_ingest
from website.features.summarization_engine.source_ingest.reddit.ingest import RedditIngestor


def _listing(num_comments: int, comment_children: list[dict]) -> list[dict]:
    post = {
        "data": {
            "children": [
                {"data": {"title": "T", "selftext": "B", "url": "", "subreddit": "test",
                          "author": "op", "score": 1, "num_comments": num_comments,
                          "id": "abc", "permalink": "/r/test/comments/abc/x/"}}
            ]
        }
    }
    comments = {"data": {"children": comment_children}}
    return [post, comments]


def _t1(author: str, body: str, replies: list[dict] | None = None) -> dict:
    data = {"author": author, "body": body}
    if replies:
        data["replies"] = {"data": {"children": replies}}
    return {"kind": "t1", "data": data}


@pytest.mark.asyncio
async def test_fetched_comment_count_sums_rendered_and_nested(monkeypatch):
    # 2 top-level comments; first has 1 nested reply -> rendered=2, nested=1, fetched=3.
    children = [
        _t1("a", "top one", replies=[_t1("b", "nested reply")]),
        _t1("c", "top two"),
    ]
    listing = _listing(num_comments=10, comment_children=children)

    async def _fake_fetch_json(url, headers=None):
        return listing, url

    monkeypatch.setattr(reddit_ingest, "fetch_json", _fake_fetch_json)
    # Keep pullpush dormant regardless of divergence.
    result = await RedditIngestor()._ingest_json(
        "https://www.reddit.com/r/test/comments/abc/x/",
        {"max_comments": 50, "comment_depth": 3, "pullpush_enabled": False},
    )
    md = result.metadata
    assert md["rendered_comment_count"] == 2
    assert md["nested_reply_count"] == 1
    assert md["fetched_comment_count"] == 3
    # Existing divergence key preserved (harness reads it), still rendered-based.
    assert md["comment_divergence_pct"] == pytest.approx(80.0)
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/source_ingest/reddit/test_fetched_comment_count.py -q
```
Expected: FAIL — `KeyError: 'fetched_comment_count'` (key not yet in metadata).

- [ ] **Minimal impl** (REAL code) — add the corrected count beside the existing keys. Insert one line after ingest.py:112 (`"nested_reply_count": nested_reply_count,`):
```python
                "nested_reply_count": nested_reply_count,
                # Wave 1A: true fetched total = top-level + nested replies.
                # Coverage gates on this; divergence stays rendered-based (harness key).
                "fetched_comment_count": rendered_count + nested_reply_count,
                "comment_divergence_pct": divergence_pct,
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/source_ingest/reddit/test_fetched_comment_count.py -q
```
Expected: 1 passed.

- [ ] **Create the test package `__init__.py` if missing** (the `tests/unit/summarization_engine/source_ingest/reddit/` dir may not exist):
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -c "import os; os.makedirs(r'tests/unit/summarization_engine/source_ingest/reddit', exist_ok=True); open(r'tests/unit/summarization_engine/source_ingest/reddit/__init__.py','a').close(); print('ok')"
```
(Run this BEFORE the run-to-fail step if the import path errors out with `ModuleNotFoundError` on the test package.)

- [ ] **Commit:**
```
git commit -m "feat: add corrected reddit fetched_comment_count"
```

### Self-review
- [ ] HTML fallback path (`_ingest_html`, 127-185) and `_pullpush_fallback` (188-232) do NOT set `fetched_comment_count` — that is intentional (no JSON tree fetched); the coverage module (Task 4) treats its absence as "coverage unknown → hedge". Confirm Task 4's fail-safe covers this.
- [ ] `comment_divergence_pct` value and key unchanged (test asserts 80.0 from rendered=2/num=10).
- [ ] No change to `_compute_divergence` signature or `_comment_tree_texts` return.

---

## Task 4 — `coverage.py`: config loader + `compute_coverage` + tiered phrasing

The deterministic heart. A pure module (no I/O except YAML load, mirroring `cluster_rebalance.py`) that turns ingest metadata into a `CoverageContext(tier, fetched, total, coverage)` and exposes phrasing helpers. Tiers: `consensus` / `plurality` / `sample_scoped` / `anecdote` / `unknown`. Fail-safe: missing/0 `num_comments` → `unknown`; `fetched > total` → clamp coverage to 1.0 but still apply absolute floors.

**Files:**
- Create: `website/features/summarization_engine/summarization/reddit/coverage.py`
- Create: `docs/summary_eval/_config/reddit_coverage.yaml`
- Test: `tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py` (extend)

### Tier ladder (DEFAULTS — calibrate on the 15-thread set; operator must confirm before prod)
| Tier | Gate | Phrasing rule |
|---|---|---|
| `consensus` | `coverage ≥ 0.60 AND fetched ≥ 25` | strong/majority language allowed, scoped to fetched frame, state N of M |
| `plurality` | `coverage ≥ 0.40 AND fetched ≥ 10` | "many"-class, scoped, state N of M |
| `sample_scoped` | `fetched ≥ 10` (below plurality gate) | describe the visible sample only, no representativeness claim |
| `anecdote` | `fetched < 10` | anecdote phrasing OR drop the stance sentence entirely |
| `unknown` | `total ≤ 0` or `fetched` missing | hedge; never assert consensus |

### Steps

- [ ] **Write failing test** (REAL code) — append to `test_coverage_phrasing.py`. These lock tier selection, the denominator edge cases, and that each tier's stance sentence carries the right assertiveness:
```python
from website.features.summarization_engine.summarization.reddit.coverage import (
    CoverageContext,
    compute_coverage,
    coverage_stance_sentence,
    reset_coverage_config_cache,
)


def _md(**kw) -> dict:
    return dict(kw)


def test_tier_consensus_requires_high_coverage_and_n_at_least_25():
    ctx = compute_coverage(_md(num_comments=50, fetched_comment_count=30))  # cov=0.60, n=30
    assert ctx.tier == "consensus"
    assert ctx.fetched == 30 and ctx.total == 50


def test_tier_plurality_band():
    ctx = compute_coverage(_md(num_comments=50, fetched_comment_count=20))  # cov=0.40, n=20
    assert ctx.tier == "plurality"


def test_tier_sample_scoped_when_below_plurality_gate_but_n_at_least_10():
    ctx = compute_coverage(_md(num_comments=500, fetched_comment_count=12))  # cov=0.024, n=12
    assert ctx.tier == "sample_scoped"


def test_tier_anecdote_when_fetched_below_10():
    ctx = compute_coverage(_md(num_comments=500, fetched_comment_count=4))
    assert ctx.tier == "anecdote"


def test_unknown_when_num_comments_zero():
    ctx = compute_coverage(_md(num_comments=0, fetched_comment_count=40))
    assert ctx.tier == "unknown"
    assert ctx.coverage is None


def test_unknown_when_fetched_count_missing():
    # HTML-scrape path never sets fetched_comment_count.
    ctx = compute_coverage(_md(num_comments=120))
    assert ctx.tier == "unknown"


def test_clamp_when_fetched_exceeds_total_but_floor_still_applies():
    # Stale num_comments: fetched 30 > total 10. Coverage clamps to 1.0,
    # n=30 >= 25 -> consensus allowed (absolute floor satisfied).
    ctx = compute_coverage(_md(num_comments=10, fetched_comment_count=30))
    assert ctx.coverage == 1.0
    assert ctx.tier == "consensus"


def test_clamp_high_coverage_but_tiny_n_is_not_consensus():
    # fetched 8 > total 5 -> clamp cov 1.0, but n=8 < 10 -> anecdote (floor wins).
    ctx = compute_coverage(_md(num_comments=5, fetched_comment_count=8))
    assert ctx.coverage == 1.0
    assert ctx.tier == "anecdote"


def test_stance_sentence_consensus_states_n_of_m_and_scopes_to_fetched():
    ctx = CoverageContext(tier="consensus", fetched=30, total=50, coverage=0.6)
    sent = coverage_stance_sentence(ctx, dominant="index funds beat stock-picking")
    low = sent.lower()
    assert "30 of 50" in sent
    assert "most-visible" in low or "most visible" in low
    assert "index funds beat stock-picking" in low
    assert sent.endswith((".", "!", "?"))


def test_stance_sentence_unknown_never_asserts_consensus():
    ctx = CoverageContext(tier="unknown", fetched=0, total=0, coverage=None)
    sent = coverage_stance_sentence(ctx, dominant="anything")
    low = sent.lower()
    assert "consensus" not in low and "most agree" not in low
    assert sent  # non-empty hedge


def test_stance_sentence_anecdote_is_dropped_or_anecdotal():
    ctx = CoverageContext(tier="anecdote", fetched=4, total=200, coverage=0.02)
    sent = coverage_stance_sentence(ctx, dominant="x")
    # spec: anecdote may DROP the sentence entirely -> empty string is valid.
    if sent:
        assert "consensus" not in sent.lower()


def test_missing_yaml_falls_back_to_baked_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("REDDIT_COVERAGE_YAML", str(tmp_path / "nope.yaml"))
    reset_coverage_config_cache()
    ctx = compute_coverage(_md(num_comments=50, fetched_comment_count=30))
    assert ctx.tier == "consensus"  # baked defaults still gate correctly
    reset_coverage_config_cache()
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named '...reddit.coverage'`.

- [ ] **Minimal impl** (REAL code) — create `reddit/coverage.py`:
```python
"""Coverage-aware stance phrasing for Reddit summaries (Wave 1A).

Turns ingest comment counts into a tiered representativeness verdict and the
exact stance sentence to use. Pure + deterministic — NO model call.

Why tiers, not a boolean: Reddit "top/best" sort is a position-biased
non-probability sample (~4x interaction bias top vs 10th — Glenski et al.
2017, arXiv:1703.05267), so "consensus among fetched" != "consensus of
thread". A threshold only narrows variance around a biased point; it cannot
remove the bias. Therefore every representativeness claim is SCOPED to the
fetched frame and assertiveness tracks coverage (plurality < majority <
consensus). Floors (n>=25 for consensus) follow proportion sample-size norms
(PSU STAT 200; MeasuringU FPC): at n=10 a 50/50 split has a ~+/-31pp 95% CI.

Config: docs/summary_eval/_config/reddit_coverage.yaml (env override
REDDIT_COVERAGE_YAML). Missing file -> baked defaults below. Thresholds are
CALIBRATION DEFAULTS pending operator confirmation on the 15-thread set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from website.features.summarization_engine.summarization.common.brief_repair import (
    as_sentence as _as_sentence,
)

_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[5]
    / "docs"
    / "summary_eval"
    / "_config"
    / "reddit_coverage.yaml"
)

# Baked calibration defaults (used when YAML missing). MUST match the YAML.
_BAKED_DEFAULTS: dict[str, Any] = {
    "consensus": {"min_coverage": 0.60, "min_fetched": 25},
    "plurality": {"min_coverage": 0.40, "min_fetched": 10},
    "sample_scoped": {"min_fetched": 10},
    # below sample_scoped.min_fetched -> anecdote
}


@dataclass(frozen=True)
class CoverageContext:
    tier: str  # consensus | plurality | sample_scoped | anecdote | unknown
    fetched: int
    total: int
    coverage: float | None  # None when total unknown


def _config_path() -> Path:
    override = os.environ.get("REDDIT_COVERAGE_YAML")
    return Path(override) if override else _DEFAULT_CONFIG_PATH


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return {k: dict(v) for k, v in _BAKED_DEFAULTS.items()}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ValueError(f"reddit_coverage.yaml is not valid YAML: {exc}") from exc
    if data is None:
        return {k: dict(v) for k, v in _BAKED_DEFAULTS.items()}
    if not isinstance(data, dict):
        raise ValueError(
            "reddit_coverage.yaml must deserialise to a mapping at the top "
            f"level (got {type(data).__name__})."
        )
    tiers = data.get("tiers", data)
    _validate_shape(tiers)
    return tiers


def _validate_shape(tiers: dict[str, Any]) -> None:
    for key in ("consensus", "plurality", "sample_scoped"):
        node = tiers.get(key)
        if not isinstance(node, dict):
            raise ValueError(f"reddit_coverage.yaml: '{key}' must be a mapping.")
    for key in ("consensus", "plurality"):
        cov = tiers[key].get("min_coverage")
        if not isinstance(cov, (int, float)) or not (0.0 <= float(cov) <= 1.0):
            raise ValueError(
                f"reddit_coverage.yaml: '{key}.min_coverage' must be in [0, 1]."
            )
    for key in ("consensus", "plurality", "sample_scoped"):
        n = tiers[key].get("min_fetched")
        if not isinstance(n, int) or n < 1:
            raise ValueError(
                f"reddit_coverage.yaml: '{key}.min_fetched' must be a positive int."
            )


def _tiers() -> dict[str, Any]:
    return _load_cached(str(_config_path()))


def reset_coverage_config_cache() -> None:
    """Test helper: drop the lru_cache so a new YAML path takes effect."""
    _load_cached.cache_clear()


def _safe_int(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def compute_coverage(metadata: dict[str, Any]) -> CoverageContext:
    """Derive the coverage tier from ingest metadata. Never raises.

    Fail-safe: total<=0 or missing fetched_comment_count -> 'unknown' (hedge).
    fetched>total (stale num_comments / nested mismatch) -> clamp coverage to
    1.0 but keep the absolute fetched floor (a clamp does not manufacture a
    larger sample).
    """
    total = _safe_int(metadata.get("num_comments"))
    has_fetched = metadata.get("fetched_comment_count") is not None
    fetched = _safe_int(metadata.get("fetched_comment_count"))

    if total <= 0 or not has_fetched:
        return CoverageContext(tier="unknown", fetched=fetched, total=max(total, 0), coverage=None)

    coverage = fetched / total
    if coverage > 1.0:
        coverage = 1.0  # clamp; floor still governs the tier

    tiers = _tiers()
    cons, plur, samp = tiers["consensus"], tiers["plurality"], tiers["sample_scoped"]

    if coverage >= float(cons["min_coverage"]) and fetched >= int(cons["min_fetched"]):
        tier = "consensus"
    elif coverage >= float(plur["min_coverage"]) and fetched >= int(plur["min_fetched"]):
        tier = "plurality"
    elif fetched >= int(samp["min_fetched"]):
        tier = "sample_scoped"
    else:
        tier = "anecdote"

    return CoverageContext(tier=tier, fetched=fetched, total=total, coverage=round(coverage, 4))


def coverage_stance_sentence(ctx: CoverageContext, *, dominant: str) -> str:
    """Return the stance sentence for this coverage tier, scoped to the fetched
    frame. Assertiveness tracks coverage; counts (N of M) are always stated at
    consensus/plurality. Anecdote MAY drop the sentence (returns "").

    ``dominant`` is the already-trimmed dominant-cluster phrase (lower-case
    fragment) the caller wants represented.
    """
    dominant = (dominant or "").strip().rstrip(".")
    if ctx.tier == "consensus":
        return _as_sentence(
            f"Among the {ctx.fetched} of {ctx.total} most-visible comments, "
            f"most converged on {dominant}"
        )
    if ctx.tier == "plurality":
        return _as_sentence(
            f"Among the {ctx.fetched} of {ctx.total} most-visible comments, "
            f"many leaned toward {dominant}"
        )
    if ctx.tier == "sample_scoped":
        return _as_sentence(
            f"In the {ctx.fetched} comments reviewed (of {ctx.total}), a recurring "
            f"thread was {dominant}"
        )
    if ctx.tier == "anecdote":
        # Too few to characterise distribution -> drop the stance sentence.
        return ""
    # unknown -> hedge, never assert representativeness.
    return _as_sentence(
        f"Within the visible replies, one recurring point was {dominant}"
    )
```

- [ ] **Create the YAML** (`docs/summary_eval/_config/reddit_coverage.yaml`):
```yaml
# Reddit coverage-aware consensus thresholds (Wave 1A).
# CALIBRATION DEFAULTS — tune on the 15-thread Reddit eval set; OPERATOR MUST
# CONFIRM before production. Plain YAML edit, no code change to re-tune.
#
# Rationale (see reddit/coverage.py docstring + 2026-06-09 solutions research):
# - Reddit top/best sort is a position-biased non-probability sample
#   (Glenski et al. 2017, arXiv:1703.05267); claims are SCOPED to the fetched
#   frame, never the whole thread, unless the consensus gate passes.
# - n>=25 floor for consensus: at n=10 a 50/50 split has a ~+/-31pp 95% CI
#   (PSU STAT 200 proportion sample size; MeasuringU finite-population
#   correction — N=100 needs ~79 read for +/-5%, ~48 for +/-10%).
version: "reddit_coverage.v1"
tiers:
  consensus:
    min_coverage: 0.60
    min_fetched: 25
  plurality:
    min_coverage: 0.40
    min_fetched: 10
  sample_scoped:
    min_fetched: 10
```

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py -q
```
Expected: all tests pass (Task-1/Task-2 tests + the ~12 new coverage tests).

- [ ] **Commit:**
```
git commit -m "feat: reddit coverage tier ladder and phrasing"
```

### Self-review
- [ ] Loader mirrors `cluster_rebalance.py` (env override, `@lru_cache`, missing-file no-op via baked defaults, loud `ValueError`, `reset_*_cache`). `parents[5]` reaches repo root (same depth as `cluster_rebalance.py:31` — verified).
- [ ] `_BAKED_DEFAULTS` and the YAML thresholds are identical, so behaviour is byte-identical whether or not the YAML is present.
- [ ] Clamp path proven by two tests: high-coverage-tiny-n → anecdote (floor wins), and stale-count → consensus only when n≥25.
- [ ] Every non-anecdote sentence ends with terminal punctuation (`as_sentence`) and scopes to "N of M most-visible / reviewed". No cross-import cycle (only imports `brief_repair`, a leaf).

---

## Task 5 — Wire coverage into `_apply_ingest_enrichments` (rewrite the brief's stance sentence)

This is the integration seam. `_apply_ingest_enrichments` already has `ingest.metadata` AND the validated payload, and runs AFTER `_repair_brief_summary` has built the brief (so the hardcoded "Consensus stayed around…" sentence already exists in `payload.brief_summary`). Replace that one stance sentence with the coverage-tiered sentence (or drop it on the anecdote tier), keeping the brief within its sentence/char bound. The dominant phrase is reused from the existing `_consensus_phrase` helper (schema.py) so wording stays consistent.

**Files:**
- Modify: `website/features/summarization_engine/summarization/reddit/summarizer.py:319-344` (`_apply_ingest_enrichments`)
- Modify: `website/features/summarization_engine/summarization/reddit/summarizer.py:50-54` (imports — add `coverage` + `_consensus_phrase`)
- Test: `tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py` (extend with an enrichment integration test)

Current import block (summarizer.py:50-54), quoted verbatim:
```python
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)
```

### Steps

- [ ] **Write failing test** (REAL code) — append to `test_coverage_phrasing.py`. Build a payload whose brief contains the hardcoded consensus sentence, run enrichment with high- and unknown-coverage metadata, assert the rewrite:
```python
from website.features.summarization_engine.summarization.reddit.summarizer import (
    _apply_ingest_enrichments,
)


def _payload_with_hardcoded_consensus() -> RedditStructuredPayload:
    detailed = RedditDetailedPayload(
        op_intent="OP asks whether index funds beat stock picking for beginners.",
        reply_clusters=[
            RedditCluster(theme="Index funds win", reasoning="Low fees, broad exposure."),
            RedditCluster(theme="Some prefer picking", reasoning="A minority enjoy research."),
        ],
        counterarguments=["A few argued individual picks can outperform."],
        unresolved_questions=["What time horizon assumed?"],
        moderation_context=None,
    )
    # Force the rebuild path (brief outside 5-7 / >400) so the hardcoded
    # "Consensus stayed around ..." sentence is present, mirroring production.
    return RedditStructuredPayload(
        mini_title="r/investing index funds vs picking",
        brief_summary="too short",
        tags=["investing", "index-funds", "stocks", "beginners", "reddit-investing", "money", "etf"],
        detailed_summary=detailed,
    )


def test_enrichment_rewrites_consensus_sentence_to_scoped_when_high_coverage():
    payload = _payload_with_hardcoded_consensus()
    assert "Consensus stayed around" in payload.brief_summary  # precondition from schema repair
    ingest = _ingest({"subreddit": "investing", "num_comments": 50, "fetched_comment_count": 30})
    enriched = _apply_ingest_enrichments(payload, ingest)
    low = enriched.brief_summary.lower()
    assert "consensus stayed around" not in low
    assert "30 of 50" in enriched.brief_summary
    assert "most-visible" in low or "most visible" in low
    # Brief stays within the schema char bound.
    assert len(enriched.brief_summary) <= 400


def test_enrichment_drops_consensus_sentence_when_coverage_unknown():
    payload = _payload_with_hardcoded_consensus()
    ingest = _ingest({"subreddit": "investing", "num_comments": 0})  # unknown
    enriched = _apply_ingest_enrichments(payload, ingest)
    low = enriched.brief_summary.lower()
    assert "consensus stayed around" not in low
    assert "consensus" not in low  # unknown tier never asserts


def test_enrichment_brief_stays_within_sentence_bound_after_drop():
    payload = _payload_with_hardcoded_consensus()
    ingest = _ingest({"subreddit": "investing", "num_comments": 200, "fetched_comment_count": 4})  # anecdote
    enriched = _apply_ingest_enrichments(payload, ingest)
    from website.features.summarization_engine.summarization.common.brief_repair import sentence_split
    n = len(sentence_split(enriched.brief_summary))
    assert 3 <= n <= 7, f"brief sentence count out of bound after drop: {n}"
```

- [ ] **Run to FAIL:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py::test_enrichment_rewrites_consensus_sentence_to_scoped_when_high_coverage -q
```
Expected: FAIL — `assert 'consensus stayed around' not in low` (enrichment does not yet touch the brief).

- [ ] **Minimal impl — part A** (imports). Replace summarizer.py:50-54 with:
```python
from website.features.summarization_engine.summarization.reddit.coverage import (
    compute_coverage,
    coverage_stance_sentence,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
    _consensus_phrase,
)
from website.features.summarization_engine.summarization.common.brief_repair import (
    sentence_split as _sentence_split,
    trim_fragment as _trim_fragment,
)
```
**FLAG:** `_consensus_phrase` is currently module-private in `schema.py` (defined at schema.py:230) and already imported-by-test elsewhere is not the case — importing a leading-underscore name across modules is allowed in this codebase (e.g. summarizer.py already imports `_normalize_tags` from `common.structured` at line 46). No `__all__` in schema.py restricts it. Confirmed safe.

- [ ] **Minimal impl — part B** (rewrite logic). Add a helper and call it inside `_apply_ingest_enrichments`. Insert this helper directly above `_apply_ingest_enrichments` (above summarizer.py:319):
```python
# Wave 1A: the brief's stance sentence is a hardcoded template built in
# schema._repair_brief_summary BEFORE enrichment runs (it has no ingest
# counts). Here we DO have counts, so we replace that one sentence with a
# coverage-scoped claim — or drop it (anecdote/unknown). Selection bias means
# "consensus among fetched" != thread consensus, so claims are scoped to the
# fetched frame (Glenski 2017, arXiv:1703.05267).
_STANCE_SENTENCE_MARKERS = ("consensus stayed around", "most converged on", "many leaned toward")


def _rewrite_stance_sentence(brief: str, payload: RedditStructuredPayload, ingest: IngestResult) -> str:
    sentences = _sentence_split(brief)
    if not sentences:
        return brief
    ctx = compute_coverage(ingest.metadata)
    dominant = _trim_fragment(
        _consensus_phrase(payload.detailed_summary.reply_clusters,
                          payload.detailed_summary.counterarguments),
        12,
    )
    replacement = coverage_stance_sentence(ctx, dominant=dominant)
    kept = [s for s in sentences if not any(m in s.lower() for m in _STANCE_SENTENCE_MARKERS)]
    if replacement:
        # Reinsert at the original stance position (index 2 in the rebuilt
        # template: OP / dominant / [stance]); fall back to append.
        insert_at = min(2, len(kept))
        kept = kept[:insert_at] + [replacement] + kept[insert_at:]
    rebuilt = " ".join(kept).strip()
    # Keep within the schema bound the repair function enforces (<=400 chars,
    # 5-7 sentences when rebuilt; dropping one keeps us >=3 which the min-safe
    # path already tolerates).
    if len(rebuilt) > 400:
        from website.features.summarization_engine.summarization.common.brief_repair import (
            clip_to_sentence_window,
        )
        rebuilt = clip_to_sentence_window(_sentence_split(rebuilt), max_sentences=7, max_chars=400)
    return rebuilt or brief
```
Then inside `_apply_ingest_enrichments`, immediately before `return payload` (currently summerizer.py:344), add:
```python
    payload.brief_summary = _rewrite_stance_sentence(payload.brief_summary, payload, ingest)
    return payload
```
(Replace the bare `    return payload` at line 344 with the two lines above.)

- [ ] **Run to PASS:**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py -q
```
Expected: all pass.

- [ ] **Full Reddit regression (no behavioural break elsewhere):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/reddit/ -q
```
Expected: all pass (cluster_rebalance + layout_thesis + coverage). The enrichment rewrite is gated on the stance markers, so payloads whose brief has no stance sentence (e.g. the held-out 5-7-sentence brief that passes schema repair unchanged at schema.py:209) are left byte-identical.

- [ ] **Commit:**
```
git commit -m "feat: wire reddit coverage into brief enrichment"
```

### Self-review
- [ ] The divergence `moderation_context` note (summarizer.py:330-343) is untouched — this task edits `brief_summary` only; no double-mutation.
- [ ] Both enrichment call sites benefit: (a) min-safe path (summarizer.py:89-90) — its brief has no stance marker after Task 1, so the rewriter is a no-op there (kept == sentences, replacement may still inject a scoped/unknown sentence; verify the min-safe test still passes — if injection on the unknown tier is undesirable on the min-safe brief, guard with `if any(marker in brief.lower())`). **DECISION FLAG:** choose at execution whether the unknown-tier hedge sentence should be ADDED to a brief that never had a stance sentence; default = only rewrite when a stance marker is present (gate the whole helper on `if not any(m in brief.lower() for m in _STANCE_SENTENCE_MARKERS): return brief`). Add this guard if the Task-1 min-safe test regresses.
- [ ] `_consensus_phrase` import does not create a cycle (schema.py does not import summarizer.py).
- [ ] Brief never exceeds 400 chars (clip fallback) and never drops below 3 sentences on the anecdote/drop path (test_enrichment_brief_stays_within_sentence_bound_after_drop).
- [ ] Selection-bias scoping holds: consensus/plurality sentences say "N of M most-visible", never "the thread agreed".

---

## Task 6 — Final batch lint + full-suite gate

Per the repo convention (batch ruff at end of plan), run one lint pass and the broader summarization suite to confirm no import/regression fallout.

**Files:** none (verification only)

### Steps

- [ ] **Ruff (only the files this plan touched):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m ruff check website/features/summarization_engine/summarization/reddit/coverage.py website/features/summarization_engine/summarization/reddit/summarizer.py website/features/summarization_engine/summarization/reddit/layout.py website/features/summarization_engine/source_ingest/reddit/ingest.py tests/unit/summarization_engine/summarization/reddit/test_coverage_phrasing.py tests/unit/summarization_engine/source_ingest/reddit/test_fetched_comment_count.py
```
Expected: no errors (fix any import-order / unused-import findings in place).

- [ ] **Summarization-engine unit suite (regression gate):**
```
cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/ -q -m "not live"
```
Expected: all pass; specifically the existing `test_cluster_rebalance.py` held-out preservation test must remain green (proves the iter-09 reference brief is byte-identical — the stance rewriter is a no-op when no marker is present).

- [ ] **Commit (only if ruff applied fixes):**
```
git commit -m "chore: lint wave1a reddit coverage"
```

### Self-review
- [ ] No protected knob touched (pure string/threshold; no model call, no infra). Confirmed against CLAUDE.md "Critical Infra Decision Guardrails".
- [ ] `comment_divergence_pct` key and value unchanged across the diff (Sol-4 M2 — eval harness reads it).
- [ ] Thresholds live in YAML; calibration + operator confirmation outstanding (surfaced at top of plan, open decision #3).

---

## Residual risk & operator decisions (surface before merge)

1. **Threshold calibration (open decision #3).** The 0.60/25, 0.40/10, 10 floors are research-informed defaults, NOT calibrated. Run the 15-thread Reddit eval set during execution, tune the YAML, and get explicit operator confirmation before prod. The plan ships the mechanism; the numbers are a config edit away.
2. **Threshold floor raised vs prior research note.** This plan uses `fetched ≥ 25` for consensus (tiered ladder), superseding the single boolean `≥ 10` in `zettel_eval_solutions_research_2026-06-09.md:55`. Statistically justified (±31pp CI at n=10) but it is a deliberate change from the recorded research — confirm acceptable.
3. **Eval comparability.** Lowering unsupported-consensus claims will (correctly) shift Reddit faithfulness scores; this is part of the Wave-0 eval version bump already flagged (solutions research, open decision #1). Gate behind the frozen-81 CI bootstrap; no axis should regress.
4. **Min-safe unknown-tier injection (Task 5 self-review).** Decide at execution whether the unknown-tier hedge sentence is added to a brief that never had a stance sentence; default = gate the rewriter on stance-marker presence (no-op otherwise).
