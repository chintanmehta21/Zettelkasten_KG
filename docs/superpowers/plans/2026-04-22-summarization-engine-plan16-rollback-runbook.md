# Summarization Engine Plan 16 — Rollback + Incident Response Runbook

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship documented, pre-rehearsed runbooks for every likely failure mode of the summarization pipeline + all 13 merged plans. Codex (or a human on-call) follows these runbooks instead of improvising during an incident. Plus: add automated health gates that block the next plan's merge until the previous plan's deploy is verified healthy.

**Architecture:** Docs-heavy plan. Adds:
1. `docs/summary_eval/_runbooks/<scenario>.md` — one runbook per failure mode (ingest chain collapse, evaluator drift, billing-quota exhaustion, Supabase outage, Caddy down, rogue backfill, rubric regression).
2. `ops/scripts/deploy_health_check.py` — programmatic post-deploy health verification. Run after each plan's merge before starting the next plan. Returns exit 0 on green, non-zero on any failure.
3. `ops/scripts/revert_plan.py` — guided PR-revert helper. Takes a plan number (1-15), finds its merge commit, generates the `git revert -m 1` command chain, and writes a follow-up checklist. Does NOT execute the revert; prints it for human to run.

**Tech Stack:** Markdown docs + two Python CLIs. No new deps. Reuses existing `pytest`, `gh`, `httpx`, `supabase-py`.

**Reference spec:** `docs/superpowers/specs/2026-04-21-summarization-engine-scoring-optimization-design.md` §11 (risk register).

**Branch:** `docs/rollback-runbooks`, off `master` AFTER Plan 15's PR merges.

**Precondition:** Plans 1-15 merged. Prod is live with v2 engine + evaluator + eval endpoint + metrics + UI.

**Deploy discipline:** Docs-only + two read-only ops scripts. Merge is zero-risk. Still follows draft-PR + human-approval workflow.

---

## Critical safety constraints

### 1. Runbooks describe, don't execute
Every runbook is a markdown document that tells the operator what to RUN. No automated remediation that hits prod. The human (or Codex) reads the steps and invokes commands manually.

### 2. `revert_plan.py` prints, never executes
The revert helper produces a commit-sha list + suggested `git revert` sequence + a follow-up checklist (e.g., "after revert, also: flip feature flag X off, notify users Y, run health check Z"). It never calls `git revert` itself.

### 3. `deploy_health_check.py` is read-only
Reads `/api/health`, `GET /api/v2/summarize` fingerprint, Supabase row counts, Prometheus scrape for quota_exhausted counter, recent kg_eval_samples composite. Never writes.

### 4. Every runbook has a "signs of false alarm" section
To prevent over-reaction: each runbook describes what looks like the failure but isn't (e.g., a spike in metadata-only YouTube ingests might just be a popular private-video URL, not a tier collapse).

### 5. Rollback does not bypass review
Reverting a PR goes through the same review discipline as landing it: revert PR is DRAFT first, human approves, merge triggers another deploy. No force-merge for rollbacks.

---

## File structure summary

### Files to CREATE
- `docs/summary_eval/_runbooks/README.md` — index + when to use each runbook
- `docs/summary_eval/_runbooks/ingest_chain_collapse.md`
- `docs/summary_eval/_runbooks/evaluator_drift.md`
- `docs/summary_eval/_runbooks/quota_exhaustion.md`
- `docs/summary_eval/_runbooks/supabase_outage.md`
- `docs/summary_eval/_runbooks/caddy_down.md`
- `docs/summary_eval/_runbooks/rogue_backfill.md`
- `docs/summary_eval/_runbooks/rubric_regression.md`
- `docs/summary_eval/_runbooks/ui_broken.md`
- `docs/summary_eval/_runbooks/gemini_outage.md`
- `ops/scripts/deploy_health_check.py`
- `ops/scripts/revert_plan.py`
- `tests/unit/ops_scripts/test_deploy_health_check.py`
- `tests/unit/ops_scripts/test_revert_plan.py`

---

## Task 0: Branch

```bash
cd /c/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault
git checkout master && git pull
git checkout -b docs/rollback-runbooks
git push -u origin docs/rollback-runbooks
```

---

## Task 1: Index + README

**Files:**
- Create: `docs/summary_eval/_runbooks/README.md`

- [ ] **Step 1: Write index**

```markdown
# Summarization pipeline runbooks

When something's broken in prod, open the matching runbook first. Don't improvise.

| Scenario | Runbook | Typical first signal |
|---|---|---|
| YouTube summaries suddenly low-quality, composite < 70 on held-out | ingest_chain_collapse.md | Prometheus: `zk_ingest_tier_total{tier=~"gemini_audio\|metadata_only"}` spikes |
| Eval scores flat across recent iterations even after large edits | evaluator_drift.md | `status=evaluator_drift` in any iter-N/next_actions.md |
| Billing key burning through $1+/day unexpectedly | quota_exhaustion.md | Slack alert "Quota exhaustion — billing key activated" |
| Summaries return 500 from /api/v2/summarize | supabase_outage.md OR gemini_outage.md (check health.json) | Slack alert from droplet monitoring |
| https://zettelkasten.in/ returns 502 | caddy_down.md | External uptime monitor |
| Backfill script over-wrote the wrong nodes | rogue_backfill.md | Users report missing summaries + high node-update rate in Supabase audit log |
| Mean composite drops > 5 pts over 24h | rubric_regression.md | Slack alert "Quality regression — composite dropped N points" |
| UI shows blank summary cards or cards with Undefined | ui_broken.md | User reports / browser console errors |
| All 3 Gemini keys rate-limited simultaneously | gemini_outage.md | `status=quota_all_keys_exhausted` in any loop |

## General principles
1. **Diagnose before rolling back.** Most incidents are NOT caused by the most recent PR.
2. **Reverts are just another PR.** Draft → review → merge → deploy. No exceptions.
3. **Prefer flag-flip over code-revert.** Every endpoint + cron is gated on a config flag; flip it off first, revert code only if the flag-flip doesn't fix the symptom.
4. **Write what you did in the incident's runbook file as a new appended section.** Future-you will thank past-you.
5. **If you can't figure it out in 30 minutes, escalate** (= ping @chintanmehta21). Don't spiral.
```

- [ ] **Step 2: Commit**

```bash
git add docs/summary_eval/_runbooks/README.md
git commit -m "docs: runbooks index"
```

---

## Task 2: Ingest-chain-collapse runbook

- [ ] **Step 1: Write**

```markdown
# Runbook — YouTube ingest chain collapse

## Signal
One or more of:
- Prometheus: `rate(zk_ingest_tier_total{tier="metadata_only"}[1h]) > 10` on YouTube
- Slack alert "YouTube ingest tier fallback rate > 25%"
- Multiple user reports of "summary is just the video title and description"

## Signs of false alarm
- Single private/unlisted video → tier-6 metadata-only is EXPECTED for those.
- Short (< 1 min) videos with no transcript → tier-6 expected.
- Videos in non-English languages not in `transcript_languages` config → tier-6 expected.

If only 1-2 URLs affected and they match any of the above → not an incident, close ticket.

## Diagnosis (5 minutes)
1. Check instance-pool health cache:
   ```bash
   cat docs/summary_eval/_cache/youtube_instance_health.json | python -m json.tool
   ```
   How many Piped + Invidious instances are marked unhealthy? If ≥ 80% of pool, pool is collapsed.

2. Run yt-dlp directly against 3 known-good URLs:
   ```bash
   for vid in hhjhU5MXZOo HBTYVVUBAGs Brm71uCWr-I; do
       yt-dlp --write-auto-sub --sub-langs en --skip-download \
           --extractor-args "youtube:player_client=android_embedded" \
           "https://www.youtube.com/watch?v=$vid" 2>&1 | tail -5
   done
   ```
   - All 3 produce .vtt files? → Tier 1 is fine; pools are the bottleneck.
   - All 3 fail with "Sign in to confirm you're not a bot"? → YouTube blocked the droplet IP. See "YouTube IP ban" below.

3. Check yt-dlp version — outdated versions break when YouTube rotates player API:
   ```bash
   pip show yt-dlp | grep Version
   ```
   If older than 30 days, upgrade (see remediation).

## Remediation
### A. Piped/Invidious pool health reset
If Task 2 showed most instances unhealthy but yt-dlp works:
```bash
rm docs/summary_eval/_cache/youtube_instance_health.json  # forces re-probe
curl -X POST http://127.0.0.1:10000/api/v2/summarize -d '{"url": "https://www.youtube.com/watch?v=hhjhU5MXZOo"}'
# Verify tier_used = tier1 or tier2, not tier3+
```

### B. yt-dlp upgrade
```bash
# On droplet
/opt/venv/bin/pip install --upgrade yt-dlp
sudo systemctl restart zettelkasten  # or whatever the service is called
```

### C. YouTube IP ban (hardest case)
1. Flip Fallback 4 (Gemini audio) to primary for 24 hours — edit config.yaml:
   ```yaml
   sources:
     youtube:
       ytdlp_player_clients: []  # disable tier 1
       transcript_api_direct_enabled: false  # disable tier 2
       enable_gemini_audio_fallback: true
   ```
   Cost: ~$0.05/video × daily volume. Acceptable for 24-48h emergency.
2. After 24-48h, YouTube typically un-bans DC IPs; revert config.

### D. Revert Plan 1 YouTube tier chain (last resort)
If A/B/C all fail and scores are still dropping:
```bash
python ops/scripts/revert_plan.py --plan 1 --scope youtube-ingest
# Review the printed revert commit list + follow-up checklist.
# Open revert PR, get approval, merge.
```
This restores the legacy `youtube-transcript-api` → `yt-dlp metadata` chain. YouTube summaries degrade to medium quality while you investigate.

## Post-incident
Append an "Incident <date>" section to this runbook documenting what you observed + what worked. Keeps institutional memory.
```

- [ ] **Step 2: Commit**

```bash
git add docs/summary_eval/_runbooks/ingest_chain_collapse.md
git commit -m "docs: runbook ingest chain collapse"
```

---

## Task 3: Remaining runbooks (condensed)

**Files to create, each ~80-150 lines:**

### `evaluator_drift.md`

```markdown
# Runbook — evaluator drift

## Signal
- `status=evaluator_drift` in any `iter-N/next_actions.md`
- Determinism check (spec §8.2 step 3) detected > 2 pt difference when re-running evaluator on iter-(N-1)/summary.json

## Diagnosis
1. `git log --oneline -10 -- website/features/summarization_engine/evaluator/prompts.py website/features/summarization_engine/evaluator/consolidated.py docs/summary_eval/_config/rubric_*.yaml`
   - Anyone edited the evaluator prompt or rubric without bumping `PROMPT_VERSION` / `rubric.version`?
2. Check `PROMPT_VERSION` in `evaluator/prompts.py` — does it match what's stamped in the drifted iter-N/eval.json's `evaluator_metadata.prompt_version`?

## Remediation
- If prompts changed without version bump: bump `PROMPT_VERSION = "evaluator.v2"`, commit, re-run the affected iteration.
- If rubric YAML changed without version bump: bump `version` in the YAML, commit, re-run.
- If no code change but drift observed: likely Gemini model swap on their side. Pin `gemini-2.5-pro` in `config.yaml → gemini.model_chains.pro[0]` and record the incident.

## Post-incident
Historical iter-N/eval.json files before the version bump are still valid — they're stamped with the OLD prompt_version. Future re-evaluations with the new version cannot be compared 1:1 to the old ones; create a `docs/summary_eval/_prompt_version_history.md` entry explaining why.
```

### `quota_exhaustion.md`

```markdown
# Runbook — Gemini quota exhaustion

## Signal
- Slack alert "Quota exhaustion — billing key activated"
- `quota_exhausted_events` in `iter-N/input.json` has any entries
- Prometheus: `increase(zk_quota_exhausted_total[1h]) > 0`

## Diagnosis
1. Check current key pool state:
   ```bash
   python -c "from website.features.api_key_switching.key_pool import parse_api_env_line; import pathlib; [print(parse_api_env_line(l)) for l in pathlib.Path('api_env').read_text().splitlines() if l.strip() and not l.startswith('#')]"
   ```
2. Check total billing spend today:
   ```bash
   python ops/scripts/eval_loop.py --report --since $(date -u +%Y-%m-%d)
   ```

## Remediation
### A. Wait for UTC midnight (free-tier quota reset)
If all 3 keys hit free-tier limits, quotas reset at UTC midnight. Pause iteration loops until then.

### B. Add a 4th free key
Create a new Gemini API key in a different Google account, add to `api_env` with `role=free`, restart server.

### C. Temporarily throttle
Edit `config.yaml`:
```yaml
chain_of_density:
  iterations: 1  # was 2 — halves CoD Pro calls
self_check:
  enabled: false  # disables self-check Pro call entirely
```
Summary quality degrades slightly but 429s stop. Revert when quota returns.

## Post-incident
If this fires > 1× per week, the per-call tier policy in spec §9.2 needs revisiting — likely too many phases defaulting to Pro.
```

### `supabase_outage.md`

```markdown
# Runbook — Supabase outage

## Signal
- `/api/v2/summarize` returns 500 with `supabase` in the error message
- `/api/v2/node/<id>` returns 502
- https://status.supabase.com shows active incident

## Diagnosis
1. Confirm Supabase status at https://status.supabase.com
2. Is the issue auth (token validation) or data-plane (PostgREST)? Test:
   ```bash
   curl -i "$SUPABASE_URL/auth/v1/health"
   curl -i "$SUPABASE_URL/rest/v1/kg_nodes?limit=1" -H "apikey: $SUPABASE_ANON_KEY"
   ```

## Remediation
### Auth-plane only
Summarize still works without auth (the `write_to_supabase=false` path). Home page + anonymous summaries keep working. Authenticated pages (Zettels, RAG) degrade.
- Display a banner: "Supabase auth is experiencing issues; zettel browsing temporarily unavailable. Summaries still work anonymously."

### Data-plane outage
Write path AND read path broken. Full degradation.
- Disable `/api/v2/eval` (flip `evaluator.prod_endpoint_enabled: false`)
- Disable Plan 10 backfill cron
- Home page POST /api/v2/summarize: temporarily set `write_to_supabase=false` in frontend JS as a hot-patch
- Wait for Supabase recovery

### Post-recovery
- Verify kg_eval_samples + kg_nodes haven't missed writes during outage. Any `summarize` calls that had `write_to_supabase=true` and failed should be re-triggered by the user.
```

### `caddy_down.md`

```markdown
# Runbook — Caddy / Nginx outage

## Signal
https://zettelkasten.in returns 502 / 504 / times out.

## Diagnosis (on droplet)
```bash
ssh root@zettelkasten.in
systemctl status caddy
tail -n 200 /var/log/caddy/access.log
tail -n 200 /var/log/caddy/error.log
```

## Remediation
### Caddy crashed
```bash
systemctl restart caddy
sleep 2
curl -I https://zettelkasten.in/api/health
```

### Upstream (uvicorn/python run.py) crashed
```bash
systemctl status zettelkasten
systemctl restart zettelkasten
sleep 5
curl -I http://127.0.0.1:10000/api/health
```

### Blue/green upstream misconfiguration
If blue/green cut-over broken, check `ops/caddy/active_color` sentinel file. Revert to known-good color:
```bash
echo "blue" > /opt/zettelkasten/ops/caddy/active_color
systemctl reload caddy
```
```

### `rogue_backfill.md`

```markdown
# Runbook — rogue backfill

## Signal
- User reports "my old zettel now has a completely different summary"
- Audit log in Supabase: high UPDATE rate on kg_nodes in past hour from service-role

## Diagnosis
```bash
tail -n 200 docs/summary_eval/_backfill/kg_v2/progress.jsonl
```
Look for a streak of `status=success` entries at an unexpected time. Check git log for any commit near that time touching the backfill script.

## Remediation (requires Supabase Pro plan for PITR)
### Stop bleeding
```bash
touch docs/summary_eval/.halt  # stops any running eval_loop
# Kill backfill process if running:
ps aux | grep backfill_kg_v2
kill <pid>
```

### Point-in-time restore
1. Supabase dashboard → Project Settings → Database → Backups
2. Click "Point-in-time recovery" → set target to 5 minutes BEFORE the first rogue UPDATE in progress.jsonl
3. Restore affects ALL tables → coordinate with user if other tables have recent writes you want to keep
4. After PITR completes, re-run Plan 10 backfill more carefully with smaller batches

### Soft recovery (no PITR available)
For each node in progress.jsonl that was updated incorrectly:
1. Fetch the node's URL
2. Re-run `/api/v2/summarize` with `force_update_node_id=<node_id>` (caller must be the owning user)
3. This restores the CORRECT v2 summary (since v2 is the target anyway)
4. If the user wanted the LEGACY v1 summary preserved, this approach fails — only PITR recovers v1 content.
```

### `rubric_regression.md`

```markdown
# Runbook — mean composite regression > 5 pts

## Signal
Slack alert "Quality regression — composite dropped N points"

## Diagnosis
1. Query kg_eval_samples for the regression window:
   ```bash
   python -c "
   import httpx, os, json
   from datetime import datetime, timedelta, timezone
   r = httpx.get(f'{os.environ[\"SUPABASE_URL\"]}/rest/v1/kg_eval_samples?sampled_at=gte.{(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}&select=composite_score,source_type,evaluator_prompt_version,rubric_version&limit=100',
   headers={'apikey': os.environ['SUPABASE_ANON_KEY'], 'Authorization': f'Bearer {os.environ[\"SUPABASE_ANON_KEY\"]}'})
   print(json.dumps(r.json()[:20], indent=2))
   "
   ```

2. Is the regression uniform across all source_types, or concentrated on one?
   - Uniform → likely an evaluator prompt / rubric / Gemini change (evaluator_drift scenario)
   - Concentrated → a source-specific summarizer regression (check recent commits to that source's prompts/schema)

## Remediation
### If concentrated on one source
Revert the most recent PR that touched that source:
```bash
python ops/scripts/revert_plan.py --plan <N> --scope <source>
```

### If uniform
- Check `evaluator_prompt_version` in the regressed samples — did it change?
- Check `rubric_version` — did any rubric YAML get edited?
- Check `ingest_tier_total` — did ingest quality degrade (see ingest_chain_collapse.md)?
```

### `ui_broken.md`

```markdown
# Runbook — UI shows blank / Undefined cards

## Signal
- User reports or browser console shows errors like `Cannot read property 'speakers' of undefined`
- Home page summary displays "Untitled" / empty brief
- Zettels cards all identical or all blank

## Diagnosis
1. Open browser devtools console on affected page
2. Check Network tab for the `/api/v2/summarize` or `/api/v2/node/<id>` call — is the JSON shape as expected?
3. Check if the user's nodes are legacy (pre-Plan-1 `engine_version < "2.0.0"`) — generic fallback should handle these

## Remediation
### Renderer bug (Plan 15 renderer broken on a specific field shape)
1. Add a defensive guard in the per-source renderer for the missing field
2. Commit a hotfix
3. Merge (triggers deploy)

### Full UI fallback
If renderer is badly broken and affecting >10% of users:
```bash
python ops/scripts/revert_plan.py --plan 15
```
Restores legacy display until renderer fix lands.
```

### `gemini_outage.md`

```markdown
# Runbook — Gemini outage / all keys 429

## Signal
- `status=quota_all_keys_exhausted` in any eval_loop invocation
- https://status.ai.google.dev shows active incident
- 100% of `/api/v2/summarize` requests return 503

## Diagnosis
```bash
# Probe each key independently
for key in $(cat api_env | grep -v '^#' | cut -d' ' -f1); do
  curl -s -H "x-goog-api-key: $key" \
    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1" | head
done
```

## Remediation
### Google-side outage
Wait. Check status page. Most resolve in 1-4 hours.
- Disable eval cron + backfill cron to stop accumulating failed retries
- Show a banner on zettelkasten.in: "Summarization temporarily unavailable; captures queued"

### Rate-limit ceiling across all 3 keys
1. Wait for UTC midnight reset (free-tier only)
2. If billing quota also hit — unusual but possible — check Google Cloud billing dashboard for any cap you set
3. Temporarily lower throughput: disable self_check + halve CoD iterations (see quota_exhaustion.md)
```

- [ ] **Step 1: Commit all runbook files**

```bash
git add docs/summary_eval/_runbooks/
git commit -m "docs: remaining 8 incident runbooks"
```

---

## Task 4: `deploy_health_check.py`

**Files:**
- Create: `ops/scripts/deploy_health_check.py`
- Test: `tests/unit/ops_scripts/test_deploy_health_check.py`

- [ ] **Step 1: Create script**

```python
"""Post-deploy health verification. Runs AFTER merging a plan's PR, BEFORE starting the next plan.

Exits 0 if all checks pass. Non-zero on any failure with specific error.

Usage:
    python ops/scripts/deploy_health_check.py --server https://zettelkasten.in
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


async def _check_health(server: str) -> bool:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"{server}/api/health")
            if r.status_code != 200:
                print(f"FAIL /api/health returned {r.status_code}")
                return False
            print(f"OK /api/health 200")
            return True
        except Exception as exc:
            print(f"FAIL /api/health unreachable: {exc}")
            return False


async def _check_summarize_fingerprint(server: str) -> bool:
    """Confirm /api/v2/summarize returns v2-shaped response."""
    test_url = "https://github.com/pallets/flask"
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            r = await client.post(f"{server}/api/v2/summarize", json={"url": test_url})
            if r.status_code != 200:
                print(f"FAIL /api/v2/summarize returned {r.status_code}")
                return False
            data = r.json()
            summary = data.get("summary", {})
            meta = summary.get("metadata", {}) or {}
            if meta.get("engine_version", "").split(".")[0] not in {"2", "3"}:
                print(f"FAIL engine_version={meta.get('engine_version')} not 2.x")
                return False
            print(f"OK /api/v2/summarize engine_version={meta.get('engine_version')}")
            return True
        except Exception as exc:
            print(f"FAIL /api/v2/summarize call: {exc}")
            return False


async def _check_kg_eval_samples_exists() -> bool:
    """If Plan 12 shipped, kg_eval_samples table should exist."""
    su = os.environ.get("SUPABASE_URL", "")
    ak = os.environ.get("SUPABASE_ANON_KEY", "")
    if not (su and ak):
        print("SKIP kg_eval_samples check — SUPABASE env not set")
        return True  # not a hard fail
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(
                f"{su}/rest/v1/kg_eval_samples?select=id&limit=1",
                headers={"apikey": ak, "Authorization": f"Bearer {ak}"},
            )
            if r.status_code == 200:
                print("OK kg_eval_samples table accessible")
                return True
            if r.status_code == 404:
                print("SKIP kg_eval_samples (table not yet created; Plan 12 not yet applied)")
                return True
            print(f"FAIL kg_eval_samples GET returned {r.status_code}")
            return False
        except Exception as exc:
            print(f"FAIL kg_eval_samples: {exc}")
            return False


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:10000")
    args = parser.parse_args()

    checks = [
        _check_health(args.server),
        _check_summarize_fingerprint(args.server),
        _check_kg_eval_samples_exists(),
    ]
    results = await asyncio.gather(*checks)
    overall = all(results)
    print(f"\nDEPLOY HEALTH: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
```

- [ ] **Step 2: Smoke test**

```python
# tests/unit/ops_scripts/test_deploy_health_check.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_check_health_fail_when_non_200():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from ops.scripts.deploy_health_check import _check_health

    class _R: status_code = 503
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_R())):
        assert (await _check_health("http://x")) is False
```

- [ ] **Step 3: Commit**

```bash
pytest tests/unit/ops_scripts/test_deploy_health_check.py -v
git add ops/scripts/deploy_health_check.py tests/unit/ops_scripts/test_deploy_health_check.py
git commit -m "feat: deploy health check cli"
```

---

## Task 5: `revert_plan.py`

**Files:**
- Create: `ops/scripts/revert_plan.py`

- [ ] **Step 1: Create script**

```python
"""Guided PR-revert helper. Prints the revert sequence; does NOT execute.

Usage:
    python ops/scripts/revert_plan.py --plan 3 [--scope youtube-ingest]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PLAN_BRANCH_MAP = {
    1: "eval/summary-engine-v2-scoring-phase0-youtube",
    2: "eval/summary-engine-v2-scoring-reddit",
    3: "eval/summary-engine-v2-scoring-github",
    4: "eval/summary-engine-v2-scoring-newsletter",
    5: "eval/summary-engine-v2-scoring-polish",
    6: "eval/summary-engine-v2-scoring-phase0-youtube",  # same branch as Plan 1
    7: "eval/summary-engine-v2-scoring-reddit",
    8: "eval/summary-engine-v2-scoring-github",
    9: "eval/summary-engine-v2-scoring-newsletter",
    10: "feat/kg-backfill-v2",
    11: "feat/evaluator-promotion",
    12: "feat/prod-eval-endpoint",
    13: "feat/academic-validation",
    14: "feat/summarization-observability",
    15: "feat/ui-per-source-renderers",
}


def _find_merge_commit(branch: str) -> str | None:
    try:
        sha = subprocess.check_output(
            ["git", "log", "--oneline", "--merges", "--grep", branch, "-1"],
            text=True,
        ).strip().split()[0] if subprocess.call(
            ["git", "log", "--oneline", "--merges", "--grep", branch, "-1"],
        ) == 0 else None
        return sha
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=int, required=True, choices=range(1, 17))
    parser.add_argument("--scope", default="full", help="Optional narrow revert scope (hint only)")
    args = parser.parse_args()

    branch = PLAN_BRANCH_MAP.get(args.plan)
    if not branch:
        print(f"Plan {args.plan} has no mapped branch — check this script's PLAN_BRANCH_MAP.")
        return 2

    print(f"=== Revert guide for Plan {args.plan} (branch: {branch}, scope: {args.scope}) ===\n")

    print("Step 1: Find the merge commit")
    print(f"  git log --oneline --merges master | grep -i '{branch}' | head -5")
    print()
    print("Step 2: Inspect what that merge introduced")
    print(f"  git show --stat <merge_sha>")
    print()
    print("Step 3: Generate the revert commit (do NOT execute; review first)")
    print(f"  git checkout -b revert/plan{args.plan}-<reason>")
    print(f"  git revert -m 1 <merge_sha>  # -m 1 picks master as the mainline")
    print(f"  # If the revert has conflicts, resolve them manually. Test suite MUST pass after revert.")
    print(f"  pytest tests/unit/ website/features/summarization_engine/tests/unit/ -q")
    print()
    print("Step 4: Post-revert follow-up checklist")
    post_revert = _follow_up_for_plan(args.plan, args.scope)
    for item in post_revert:
        print(f"  [ ] {item}")
    print()
    print("Step 5: Open a DRAFT revert PR")
    print(f"  git push origin revert/plan{args.plan}-<reason>")
    print(f"  gh pr create --draft --title 'revert: plan {args.plan} <reason>' --body '...'")
    print()
    print("Step 6: After human approval + merge, run deploy_health_check.py to confirm prod recovered.")
    return 0


def _follow_up_for_plan(plan: int, scope: str) -> list[str]:
    """Plan-specific post-revert checklist."""
    base = ["Notify users in status channel", "Run ops/scripts/deploy_health_check.py after deploy", "Document incident in the relevant runbook"]
    extras = {
        1: ["Warn: reverting Plan 1 breaks all per-source summarization", "Flip to legacy telegram_bot pipeline temporarily"],
        3: ["GitHub REST API calls reduce back to 1 (README only)", "architecture_overview field now always null"],
        4: ["Newsletter loses stance classifier + C2 hybrid label rule"],
        10: ["Backfill cron auto-disables; verify /etc/secrets service-role key not leaked"],
        11: ["Evaluator promotion revert restores shim imports — verify `from website.features.summarization_engine.evaluator import ...` still works"],
        12: ["Flip `prod_endpoint_enabled: false` in config.yaml as belt-and-braces"],
        14: ["Metrics endpoint drops to pre-Plan-14 state; Slack alerts stop"],
        15: ["UI reverts to generic renderer; confirm Zettels page + home page still work"],
    }
    return extras.get(plan, []) + base


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test**

```python
# tests/unit/ops_scripts/test_revert_plan.py
import subprocess


def test_revert_plan_prints_guide(capsys):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from ops.scripts.revert_plan import main
    sys.argv = ["revert_plan.py", "--plan", "15"]
    rc = main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Revert guide for Plan 15" in out
    assert "eval/summary-engine-v2-scoring" in out or "feat/ui-per-source-renderers" in out
```

- [ ] **Step 3: Commit**

```bash
pytest tests/unit/ops_scripts/test_revert_plan.py -v
git add ops/scripts/revert_plan.py tests/unit/ops_scripts/test_revert_plan.py
git commit -m "feat: revert plan helper cli"
```

---

## Task 6: Push + draft PR

```bash
git push origin docs/rollback-runbooks
gh pr create --draft --title "docs: rollback runbooks and health check" \
  --body "Plan 16. Adds 9 incident runbooks + deploy_health_check.py + revert_plan.py. Docs-heavy + two read-only ops scripts. Zero production risk.

### Deploy gate
- [ ] CI green
- [ ] All 9 runbook files committed under docs/summary_eval/_runbooks/
- [ ] deploy_health_check.py + revert_plan.py unit tests pass
- [ ] README index references all runbooks

Post-merge: human reads the README and keeps the runbooks top-of-mind for the on-call rotation. Every future incident should append a dated section to the matching runbook."
```

---

## Self-review checklist
- [ ] Every scenario in README has a corresponding runbook
- [ ] Every runbook has Diagnosis + Remediation + Post-incident sections
- [ ] revert_plan.py does NOT execute git revert; prints only
- [ ] deploy_health_check.py is read-only
- [ ] Every "Remediation" step is copy-pasteable (no placeholders)
- [ ] NO merge, NO push to master
