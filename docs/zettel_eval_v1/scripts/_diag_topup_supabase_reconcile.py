"""_diag_topup_supabase_reconcile.py - read-only diagnostic.

Identifies which of the 41 topup URLs are missing from content.canonical_zettels
(via Naruto's workspace_zettels). Output goes to:
  docs/zettel_eval_v1/_data/topup_supabase_reconcile.json

Read-only. No writes, no Gemini calls.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

LINKS_MD = REPO_ROOT / "docs" / "kasten_skeletons" / "zettel_v1_links.md"
OUT = REPO_ROOT / "docs" / "zettel_eval_v1" / "_data" / "topup_supabase_reconcile.json"
NARUTO_AUTH_ID = "f2105544-b73d-4946-8329-096d82f070d3"

_HEADING = re.compile(r"^##\s+([A-Za-z][\w-]*)")
_LIST_ITEM = re.compile(r"^\s*\d+\.\s+(https?://\S+)")


def _load_env() -> None:
    from dotenv import load_dotenv
    for candidate in (REPO_ROOT / ".env", REPO_ROOT / ".env.v2", REPO_ROOT / "supabase" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def parse_links() -> list[tuple[str, str]]:
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


def main() -> int:
    _load_env()
    from website.core.supabase_v2.client import get_v2_client
    from website.core.url_utils import normalize_url

    client = get_v2_client()
    items = parse_links()
    print(f"Loaded {len(items)} URLs from {LINKS_MD.name}", flush=True)

    # Build raw -> normalized map (the engine normalizes before dedup).
    norm_map = {url: normalize_url(url) for _sec, url in items}
    normalized_urls = sorted(set(norm_map.values()))

    # Naruto -> core.workspaces.owner_profile_id (auth/profile id are aligned).
    ws_resp = (
        client.schema("core")
        .table("workspaces")
        .select("id, owner_profile_id, is_personal, name")
        .eq("owner_profile_id", NARUTO_AUTH_ID)
        .execute()
    )
    workspace_ids = [str(w["id"]) for w in (ws_resp.data or [])]
    print(f"Naruto owns {len(workspace_ids)} workspace(s)", flush=True)

    rows = []
    chunk = 50
    for i in range(0, len(normalized_urls), chunk):
        sub = normalized_urls[i:i + chunk]
        resp = (
            client.schema("content")
            .table("workspace_zettels")
            .select(
                "id, workspace_id, ai_summary, created_at, deleted_at, "
                "canonical:canonical_zettels!inner(id, normalized_url, source_type, title, body_md, created_at)"
            )
            .in_("workspace_id", workspace_ids)
            .in_("canonical_zettels.normalized_url", sub)
            .execute()
        )
        rows.extend(resp.data or [])

    # Map normalized_url -> zettel row(s). PostgREST embeds may return rows where
    # the joined canonical doesn't match the IN filter; double-check Python-side.
    by_norm: dict[str, list[dict]] = {}
    for r in rows:
        canon = r.get("canonical") or {}
        nu = canon.get("normalized_url")
        if nu in set(normalized_urls):
            by_norm.setdefault(nu, []).append(r)

    found = []
    missing = []
    for section, url in items:
        nu = norm_map[url]
        zettel_rows = by_norm.get(nu, [])
        live_rows = [r for r in zettel_rows if r.get("deleted_at") is None]
        if live_rows:
            canon = (live_rows[0].get("canonical") or {})
            found.append({
                "url": url,
                "normalized_url": nu,
                "section": section,
                "workspace_zettel_id": str(live_rows[0].get("id")),
                "workspace_id": str(live_rows[0].get("workspace_id") or ""),
                "canonical_zettel_id": str(canon.get("id") or ""),
                "source_type": canon.get("source_type"),
                "title": canon.get("title"),
                "ai_summary_len": len(live_rows[0].get("ai_summary") or ""),
                "body_md_len": len(canon.get("body_md") or ""),
                "wz_created_at": str(live_rows[0].get("created_at") or ""),
                "canon_created_at": str(canon.get("created_at") or ""),
            })
        else:
            soft_deleted = bool(zettel_rows) and not live_rows
            missing.append({
                "url": url,
                "normalized_url": nu,
                "section": section,
                "soft_deleted_present": soft_deleted,
            })

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "naruto_auth_id": NARUTO_AUTH_ID,
        "total_topup_urls": len(items),
        "found_count": len(found),
        "missing_count": len(missing),
        "missing": missing,
        "found_sample": found[:3],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\n=== topup reconcile ===")
    print(f"  topup URLs : {len(items)}")
    print(f"  found in v2: {len(found)}")
    print(f"  MISSING    : {len(missing)}")
    print(f"\nMissing URLs:")
    for m in missing:
        print(f"  [{m['section']:10s}] {m['url']}")
    print(f"\nReport: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
