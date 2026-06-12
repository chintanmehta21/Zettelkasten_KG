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
import re
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


# --- Sol 1 / D2: true-source evidence from the production ingest cache ---
# The cache lives at docs/summary_eval/_cache/ingests/*.json (FsContentCache of
# IngestResult). Join is by normalized URL, NOT by the cache filename hash.
INGEST_CACHE_DIR = REPO_ROOT / "docs" / "summary_eval" / "_cache" / "ingests"
# Cap to bound git size; largest real prod raw_text is ~513KB (one ytdlp transcript).
MAX_EVIDENCE_BYTES = 600_000


def _norm_url(u: str | None) -> str:
    """Normalize a URL for cache joins. Mirrors _d2_cache_check.norm() exactly:
    drop scheme + leading www., strip trailing slash, lowercase."""
    return re.sub(r"^https?://(www\.)?", "", (u or "").rstrip("/").lower())


def _load_ingest_cache_index(cache_dir: Path) -> dict[str, dict]:
    """Build {normalized_url: ingest_dict} from the prod ingest cache. Files with
    no usable raw_text are skipped so they can never masquerade as true source.
    On a duplicate normalized URL the most-recently fetched record wins."""
    index: dict[str, dict] = {}
    if not cache_dir.exists():
        return index
    for f in sorted(cache_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or not (d.get("raw_text") or "").strip():
            continue
        for url_key in ("url", "original_url", "normalized_url", "source_url"):
            raw = d.get(url_key)
            if isinstance(raw, str) and raw.startswith("http"):
                nu = _norm_url(raw)
                prev = index.get(nu)
                if prev is None or (d.get("fetched_at") or "") >= (prev.get("fetched_at") or ""):
                    index[nu] = d
    return index


_INGEST_INDEX_CACHE: dict[str, dict] | None = None


def _ingest_index() -> dict[str, dict]:
    """Lazy, run-scoped cache of the ingest index (built once, reused per zettel)."""
    global _INGEST_INDEX_CACHE
    if _INGEST_INDEX_CACHE is None:
        _INGEST_INDEX_CACHE = _load_ingest_cache_index(INGEST_CACHE_DIR)
    return _INGEST_INDEX_CACHE


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

    # Sol 1 / D2: choose the TRUE raw source. Cache hit -> production_ingest_cache;
    # miss -> body_md_fallback (flagged so circular items are EXCLUDABLE, not scored).
    norm_url = _norm_url(canon.get("normalized_url"))
    hit = _ingest_index().get(norm_url)
    if hit is not None:
        evidence_source = "production_ingest_cache"
        raw_text_full = hit.get("raw_text") or ""
        ingestor_version = hit.get("ingestor_version") or ""
        fetched_at = hit.get("fetched_at") or ""
    else:
        evidence_source = "body_md_fallback"
        raw_text_full = body_md
        ingestor_version = ""
        fetched_at = ""

    raw_bytes = raw_text_full.encode("utf-8")
    truncated = len(raw_bytes) > MAX_EVIDENCE_BYTES
    raw_text = raw_bytes[:MAX_EVIDENCE_BYTES].decode("utf-8", errors="ignore") if truncated else raw_text_full
    content_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

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
        # Sol 1 provenance: lets a consumer exclude circular (body_md_fallback) items.
        "evidence_source": evidence_source,
        "content_digest": content_digest,
    }

    if dry_run:
        return wz_id, "dry-run"

    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "source_text.md").write_text(body_md, encoding="utf-8")
    source_evidence = {
        "evidence_source": evidence_source,
        "raw_text": raw_text,
        "content_digest": content_digest,
        "ingestor_version": ingestor_version,
        "fetched_at": fetched_at,
        "raw_text_truncated": truncated,
        "raw_text_full_len": len(raw_text_full),
    }
    (out / "source_evidence.json").write_text(
        json.dumps(source_evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    try:
        summary_payload = json.loads(ai_summary)
    except Exception:
        summary_payload = {"_raw": ai_summary}
    (out / "summary.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # 2nd element = evidence label (was "written") so main() can tally true-source %.
    return wz_id, evidence_source


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
    n_true_source = 0
    n_fallback = 0
    for r in rows:
        _, status = write_zettel_bundle(r, dry_run=args.dry_run)
        if status == "dry-run":
            continue
        written += 1
        if status == "production_ingest_cache":
            n_true_source += 1
        elif status == "body_md_fallback":
            n_fallback += 1
    print(f"wrote {written} per-zettel bundles to {DATA_ROOT}")
    if written:
        pct = 100.0 * n_true_source / written
        # Harness-health (Sol 1): faithfulness is trustworthy only on true-source items;
        # body_md_fallback items are circular and should be EXCLUDED from faithfulness stats.
        print(f"true-source coverage: {n_true_source}/{written} ({pct:.0f}%) "
              f"via production_ingest_cache; {n_fallback} body_md_fallback (EXCLUDABLE)")

    update_manifest(rows, dry_run=args.dry_run)
    print(f"manifest updated at {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
