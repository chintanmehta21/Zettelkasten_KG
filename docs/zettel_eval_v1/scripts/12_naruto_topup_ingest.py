"""12_naruto_topup_ingest.py - ingest the zettel_v1 top-up URLs as Naruto.

Drives the canonical /api/zettels/add path via run_add_zettel_pipeline so each
URL flows through the production summarization engine, persistence, KG, and
RAG enrichment exactly as a real Add Zettel call would. Read-only against
auth (no password rotation); writes through the v2 service-role client per
the existing path.

Naruto's Supabase auth UUID is hard-pinned (see docs/login_details.txt):
  f2105544-b73d-4946-8329-096d82f070d3

URL list is parsed from docs/kasten_skeletons/zettel_v1_links.md. The
ingestion is idempotent: pre-existing canonicals trigger the URL-dedup gate's
same-user-noop or cross-user-hit branch, both of which short-circuit to a
cache-hit (no Gemini call). So re-running this script is safe.

Output:
  docs/zettel_eval_v1/_data/naruto_topup_ingest_report.json
    {
      "started_at": "...",
      "finished_at": "...",
      "naruto_auth_id": "f2105544-...",
      "concurrency": 4,
      "items": [
        {
          "url": "...",
          "source_section": "newsletter",
          "status": "succeeded|cache_hit|failed",
          "workspace_zettel_id": "...",
          "canonical_zettel_id": "...",
          "summary_len": 1234,
          "latency_ms": 5000,
          "error": null
        },
        ...
      ]
    }

Usage:
    python docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py
    python docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py --concurrency 4
    python docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py --section newsletter   # ingest only one section
    python docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py --dry-run
    python docs/zettel_eval_v1/scripts/12_naruto_topup_ingest.py --verify-only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

LINKS_MD = REPO_ROOT / "docs" / "kasten_skeletons" / "zettel_v1_links.md"
REPORT = REPO_ROOT / "docs" / "zettel_eval_v1" / "_data" / "naruto_topup_ingest_report.json"

NARUTO_AUTH_ID = "f2105544-b73d-4946-8329-096d82f070d3"


def _load_eval_env() -> None:
    from dotenv import load_dotenv
    for candidate in (
        REPO_ROOT / ".env",
        REPO_ROOT / ".env.v2",
        REPO_ROOT / "supabase" / ".env",
    ):
        if candidate.exists():
            load_dotenv(candidate, override=False)


# Headings look like "## Newsletter (12)" -> normalised to "newsletter".
_HEADING = re.compile(r"^##\s+([A-Za-z][\w-]*)")
# Numbered list lines look like "1. https://..." or "12. https://..."
_LIST_ITEM = re.compile(r"^\s*\d+\.\s+(https?://\S+)")


def parse_links() -> list[tuple[str, str]]:
    """Return [(section_name_lower, url), ...]."""
    items: list[tuple[str, str]] = []
    section = None
    for line in LINKS_MD.read_text(encoding="utf-8").splitlines():
        m = _HEADING.match(line)
        if m:
            section = m.group(1).lower().replace("-like", "").strip()
            continue
        m = _LIST_ITEM.match(line)
        if m and section is not None:
            items.append((section, m.group(1).strip()))
    return items


async def _ingest_one(url: str, section: str, action_id_prefix: str) -> dict:
    from website.api.module_runners.summarization import run_add_zettel_pipeline

    t0 = time.perf_counter()
    record = {
        "url": url,
        "source_section": section,
        "status": "pending",
        "workspace_zettel_id": None,
        "canonical_zettel_id": None,
        "summary_len": None,
        "latency_ms": None,
        "error": None,
    }
    try:
        result = await run_add_zettel_pipeline(
            url=url,
            client_action_id=f"{action_id_prefix}-{section}-{abs(hash(url)) % 10**8:08d}",
            persist=True,
            user={"sub": NARUTO_AUTH_ID},
            effective_user_id=UUID(NARUTO_AUTH_ID),
        )
        record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        record["status"] = result.get("status", "unknown")
        if isinstance(result.get("persistence"), dict):
            record["workspace_zettel_id"] = result["persistence"].get("workspace_zettel_id")
        else:
            record["workspace_zettel_id"] = result.get("workspace_zettel_id")
        summary = result.get("summary") or {}
        if isinstance(summary, dict):
            det = summary.get("detailed_summary") or ""
            record["summary_len"] = len(det) if isinstance(det, str) else None
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    return record


async def _bounded(coros, concurrency: int):
    sem = asyncio.Semaphore(concurrency)

    async def _runner(coro):
        async with sem:
            return await coro
    return await asyncio.gather(*[_runner(c) for c in coros], return_exceptions=False)


async def run_ingest(items: list[tuple[str, str]], concurrency: int, action_prefix: str) -> list[dict]:
    coros = [_ingest_one(url, sec, action_prefix) for sec, url in items]
    return list(await _bounded(coros, concurrency))


def verify_ingested(report_records: list[dict]) -> dict:
    """Cross-check that every wz_zettel_id surfaces in v2 + has chunks (rag) + edges (kg)."""
    from website.core.supabase_v2.client import get_v2_client
    client = get_v2_client()

    wz_ids = [r["workspace_zettel_id"] for r in report_records if r.get("workspace_zettel_id")]
    if not wz_ids:
        return {"checked": 0, "missing_zettels": [], "without_chunks": [], "kg_edge_count": 0}

    wz_resp = (
        client.schema("content")
        .table("workspace_zettels")
        .select(
            "id, canonical_zettel_id, ai_summary, deleted_at, "
            "canonical:canonical_zettels!inner(id, normalized_url, source_type, title)"
        )
        .in_("id", wz_ids)
        .execute()
    )
    wz_rows = {str(r["id"]): r for r in (wz_resp.data or [])}

    missing = [wz for wz in wz_ids if wz not in wz_rows]
    alive_wz_ids = [wz for wz, r in wz_rows.items() if r.get("deleted_at") is None]

    canonical_ids = [
        (r.get("canonical") or {}).get("id") for r in wz_rows.values()
    ]
    canonical_ids = [c for c in canonical_ids if c]
    chunk_resp = (
        client.schema("content")
        .table("canonical_chunks")
        .select("canonical_zettel_id")
        .in_("canonical_zettel_id", canonical_ids)
        .execute()
    )
    chunk_counts: dict[str, int] = {}
    for row in chunk_resp.data or []:
        cid = str(row["canonical_zettel_id"])
        chunk_counts[cid] = chunk_counts.get(cid, 0) + 1
    without_chunks = [cid for cid in canonical_ids if chunk_counts.get(str(cid), 0) == 0]

    # KG edges referencing these canonicals
    kg_resp = (
        client.schema("kg")
        .table("kg_edges")
        .select("id", count="exact")
        .in_("evidence_canonical_zettel_id", canonical_ids)
        .execute()
    )
    kg_count = getattr(kg_resp, "count", 0) or 0

    return {
        "checked": len(wz_ids),
        "alive": len(alive_wz_ids),
        "missing_zettels": missing,
        "canonicals_total": len(set(canonical_ids)),
        "without_chunks": [str(c) for c in without_chunks],
        "kg_edges_with_evidence_in_set": kg_count,
        "chunk_counts_sample": {str(k): chunk_counts[k] for k in list(chunk_counts)[:5]},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--section", type=str, default=None,
                    help="restrict to one section (newsletter|web|github|reddit|arxiv)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-only", action="store_true",
                    help="re-read the existing report and only run the verify step")
    args = ap.parse_args()

    _load_eval_env()

    items = parse_links()
    if args.section:
        items = [(sec, url) for sec, url in items if sec == args.section.lower()]
    print(f"Loaded {len(items)} URLs from {LINKS_MD.name}")
    if args.dry_run:
        for sec, url in items:
            print(f"  [{sec:10s}] {url}")
        return 0

    if args.verify_only:
        if not REPORT.exists():
            print(f"No prior report at {REPORT}")
            return 1
        prior = json.loads(REPORT.read_text(encoding="utf-8"))
        v = verify_ingested(prior.get("items", []))
        print(json.dumps(v, indent=2))
        return 0

    action_prefix = f"zettel-eval-v1-naruto-topup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    started = datetime.now(timezone.utc).isoformat()
    print(f"Starting ingest at concurrency={args.concurrency}")
    records = asyncio.run(run_ingest(items, args.concurrency, action_prefix))
    finished = datetime.now(timezone.utc).isoformat()

    succeeded = sum(1 for r in records if r["status"] == "succeeded")
    cache_hit = sum(1 for r in records if r["status"] == "cache_hit")
    failed = sum(1 for r in records if r["status"] == "failed")
    print(f"Done: {succeeded} succeeded, {cache_hit} cache-hit, {failed} failed")

    verify_payload = verify_ingested(records)
    payload = {
        "started_at": started,
        "finished_at": finished,
        "naruto_auth_id": NARUTO_AUTH_ID,
        "concurrency": args.concurrency,
        "items": records,
        "verify": verify_payload,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Report written: {REPORT}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
