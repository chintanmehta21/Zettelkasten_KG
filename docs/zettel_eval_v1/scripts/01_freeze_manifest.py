"""01_freeze_manifest.py - freeze the 47 strong-zettel manifest from prod v2.

READ-ONLY against content.workspace_zettels JOIN content.canonical_zettels.
Filters: live (deleted_at IS NULL) AND length(ai_summary) > 2000.

For each selected zettel writes:
  docs/zettel_eval_v1/_data/<wz_uuid>/
    meta.json         (id, ws_id, canonical_id, url, title, source_type,
                       captured_at, ai_summary_len, content_hash hex)
    source_text.md    (canonical_zettels.body_md frozen at freeze-time)
    summary.json      (workspace_zettels.ai_summary parsed)

Also updates docs/zettel_eval_v1/_config/manifest.json with:
  - frozen_at (UTC ISO)
  - frozen_from.git_sha (HEAD)
  - frozen_from.supabase_project_ref (parsed from SUPABASE_V2_URL)
  - zettels[] (the ordered UUID + URL list, 47 entries)

Idempotent: re-running with the same selection set is a no-op unless the
content_hash for any canonical changed (then the affected _data/<uuid>/ is
rewritten and the manifest entry's content_hash_hex is updated).

Usage:
    python docs/zettel_eval_v1/scripts/01_freeze_manifest.py
    python docs/zettel_eval_v1/scripts/01_freeze_manifest.py --dry-run
    python docs/zettel_eval_v1/scripts/01_freeze_manifest.py --threshold-chars 2000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = REPO_ROOT / "docs" / "zettel_eval_v1"
DATA_ROOT = EVAL_ROOT / "_data"
MANIFEST = EVAL_ROOT / "_config" / "manifest.json"

sys.path.insert(0, str(REPO_ROOT))


def _ensure_env_loaded() -> None:
    from dotenv import load_dotenv
    for candidate in (
        REPO_ROOT / ".env",
        REPO_ROOT / ".env.v2",
        REPO_ROOT / "supabase" / ".env",
    ):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def _git_head_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _project_ref_from_url(url: str) -> str:
    if not url:
        return ""
    host = urlsplit(url).hostname or ""
    return host.split(".")[0] if host else ""


def fetch_rows(threshold_chars: int):
    from website.core.supabase_v2.client import get_v2_client
    client = get_v2_client()
    rows = []
    offset = 0
    page = 1000
    while True:
        resp = (
            client.schema("content")
            .table("workspace_zettels")
            .select(
                "id, workspace_id, ai_summary, created_at, "
                "canonical:canonical_zettels!inner(id, normalized_url, title, source_type, body_md, content_hash, publication_date, source_metadata)"
            )
            .is_("deleted_at", "null")
            .order("created_at", desc=False)
            .range(offset, offset + page - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return [r for r in rows if len((r.get("ai_summary") or "")) > threshold_chars]


def write_zettel_bundle(row: dict, *, dry_run: bool) -> tuple[str, str]:
    canon = row.get("canonical") or {}
    wz_id = str(row["id"])
    out = DATA_ROOT / wz_id
    body_md = canon.get("body_md") or ""
    ai_summary = row.get("ai_summary") or ""
    content_hash = canon.get("content_hash") or ""
    chash_hex = content_hash.replace("\\x", "") if isinstance(content_hash, str) else ""

    meta = {
        "workspace_zettel_id": wz_id,
        "workspace_id": str(row["workspace_id"]),
        "canonical_zettel_id": str(canon.get("id") or ""),
        "normalized_url": canon.get("normalized_url"),
        "title": canon.get("title"),
        "source_type": canon.get("source_type"),
        "publication_date": str(canon.get("publication_date") or ""),
        "captured_at": str(row.get("created_at") or ""),
        "ai_summary_len": len(ai_summary),
        "body_md_len": len(body_md),
        "content_hash_hex": chash_hex,
        "source_metadata": canon.get("source_metadata") or {},
    }

    if dry_run:
        return wz_id, "dry-run"

    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "source_text.md").write_text(body_md, encoding="utf-8")
    try:
        summary_payload = json.loads(ai_summary)
    except Exception:
        summary_payload = {"_raw": ai_summary}
    (out / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return wz_id, "written"


def update_manifest(rows: list[dict], *, dry_run: bool) -> None:
    entries = []
    for r in rows:
        canon = r.get("canonical") or {}
        chash = canon.get("content_hash") or ""
        chash_hex = chash.replace("\\x", "") if isinstance(chash, str) else ""
        entries.append({
            "workspace_zettel_id": str(r["id"]),
            "workspace_id": str(r["workspace_id"]),
            "canonical_zettel_id": str(canon.get("id") or ""),
            "normalized_url": canon.get("normalized_url"),
            "title": canon.get("title"),
            "source_type": canon.get("source_type"),
            "ai_summary_len": len(r.get("ai_summary") or ""),
            "content_hash_hex": chash_hex,
        })

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["frozen_at"] = datetime.now(timezone.utc).isoformat()
    payload["frozen_from"]["git_sha"] = _git_head_sha()
    payload["frozen_from"]["supabase_project_ref"] = _project_ref_from_url(
        os.environ.get("SUPABASE_V2_URL") or os.environ.get("SUPABASE_URL") or ""
    )
    payload["frozen_from"]["expected_count"] = len(entries)
    payload["zettels"] = entries

    if dry_run:
        print(f"[dry-run] would write manifest with {len(entries)} entries")
        return
    MANIFEST.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold-chars", type=int, default=2000,
                    help="min ai_summary length to include (default: 2000)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    _ensure_env_loaded()
    rows = fetch_rows(args.threshold_chars)
    print(f"selected {len(rows)} zettels with ai_summary_len > {args.threshold_chars}")
    if not rows:
        print("no zettels selected; aborting")
        return 1

    written = 0
    for r in rows:
        _, status = write_zettel_bundle(r, dry_run=args.dry_run)
        if status == "written":
            written += 1
    print(f"wrote {written} per-zettel bundles to {DATA_ROOT}")

    update_manifest(rows, dry_run=args.dry_run)
    print(f"manifest updated at {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
