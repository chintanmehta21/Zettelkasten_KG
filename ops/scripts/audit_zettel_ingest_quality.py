# ruff: noqa: E402  (sys.path bootstrap must precede website.* imports)
"""READ-ONLY audit: classify every ``content.workspace_zettels`` row by how
well the *latest* summarization engine (v2, ``engine_version == "2.0.0"``)
ingested it. Writes a JSON report + a candidate-id list. **Never mutates data.**

Taxonomy (mutually exclusive, first match wins):
    clean            engine 2.0.0, JSON envelope, non-empty detailed,
                     no inline-heading leak, detailed != brief fallback
    legacy_version   ai_summary_engine_version is a non-empty marker that is
                     not the latest engine (e.g. 'legacy-v1-backfill'). EMPTY
                     version is NOT legacy (website path never stamps it).
    malformed        ai_summary null/empty or not the JSON envelope shape
    markdown_leak    latest engine but normalize_markdown_headings() would
                     change detailed_summary (inline ## / ### leaked)
    degenerate       detailed_summary empty or identical to brief (fallback)

Concurrent-PR reservation: any Zettel whose canonical ``normalized_url``
matches a link in the ``--keep-md`` skeleton files (the other PR's Kastens) is
ALWAYS kept, even when dirty. URL matching is deliberately generous (raw +
``normalize_url`` + Google-redirect-unwrapped target) so a reserved Zettel is
never purged because of a redirect/normalization mismatch.

Purge candidates are restricted to the unrecoverable buckets
(``legacy_version``, ``malformed``, ``degenerate``). ``markdown_leak`` rows are
listed separately as REPAIRABLE (fix via backfill_normalize_summary_headings),
never purge candidates.

Usage:
    python ops/scripts/audit_zettel_ingest_quality.py \
        --keep-md docs/kasten_skeletons/kasten1.md docs/kasten_skeletons/kasten2.md \
        --out zettel_ingest_audit.json

Requires ``SUPABASE_V2_DATABASE_URL`` (read-only use). DSN never logged.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "supabase" / ".env")
load_dotenv(ROOT / ".env", override=False)

from website.core.supabase_v2.client import get_v2_database_url
from website.core.url_utils import normalize_url
from website.features.summarization_engine.post_summary_transformation import (
    normalize_markdown_headings,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("audit_zettel_quality")

LATEST_ENGINE_VERSION = "2.0.0"
PURGEABLE_BUCKETS = {"legacy_version", "malformed", "degenerate"}

# Join canonical to get the stored normalized_url for keep-list matching.
_SELECT = (
    "SELECT wz.id, wz.workspace_id, wz.canonical_zettel_id, wz.ai_summary, "
    "wz.ai_summary_engine_version, wz.added_via, wz.created_at, cz.normalized_url "
    "FROM content.workspace_zettels wz "
    "JOIN content.canonical_zettels cz ON cz.id = wz.canonical_zettel_id "
    "WHERE wz.deleted_at IS NULL ORDER BY wz.created_at ASC"
)

_URL_RE = re.compile(r"https?://[^\s)\"'>\]]+")


def _url_variants(raw: str) -> set[str]:
    """Generous variant set so a reserved Zettel is never mis-purged: the raw
    URL, its ``normalize_url`` form, and (for Google-redirect wrappers) the
    unwrapped inner target plus its normalized form.
    """

    variants: set[str] = set()
    for candidate in (raw.strip(),):
        if not candidate:
            continue
        variants.add(candidate)
        try:
            variants.add(normalize_url(candidate))
        except Exception:  # pragma: no cover - normalize is defensive
            pass
        parsed = urllib.parse.urlparse(candidate)
        if "google." in parsed.netloc and parsed.path.startswith("/search"):
            inner = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            if inner.startswith("http"):
                variants.add(inner)
                try:
                    variants.add(normalize_url(inner))
                except Exception:  # pragma: no cover
                    pass
    return {v for v in variants if v}


def build_keep_set(md_paths: list[Path]) -> set[str]:
    keep: set[str] = set()
    for path in md_paths:
        text = path.read_text(encoding="utf-8")
        for raw in _URL_RE.findall(text):
            keep |= _url_variants(raw)
    return keep


def _is_reserved(normalized_url: str | None, keep: set[str]) -> bool:
    if not normalized_url:
        return False
    if normalized_url in keep:
        return True
    try:
        if normalize_url(normalized_url) in keep:
            return True
    except Exception:  # pragma: no cover
        pass
    return False


def classify(ai_summary: str | None, engine_version: str | None) -> str:
    # The website Add-Zettel write path does not stamp ai_summary_engine_version
    # (persist.py writes "" when the payload omits it), so an EMPTY version is
    # the normal state and says nothing about ingest quality. Only an explicit
    # non-empty marker that is not the latest engine (e.g. 'legacy-v1-backfill')
    # is a genuine legacy ingest. Everything else is judged on content health.
    ev = (engine_version or "").strip()
    if ev and ev != LATEST_ENGINE_VERSION:
        return "legacy_version"
    if not ai_summary or not ai_summary.strip():
        return "malformed"
    try:
        decoded = json.loads(ai_summary)
    except (ValueError, TypeError):
        return "malformed"
    if not (isinstance(decoded, dict) and "detailed_summary" in decoded):
        return "malformed"
    detailed = decoded.get("detailed_summary") or ""
    brief = decoded.get("brief_summary") or ""
    if not str(detailed).strip() or str(detailed).strip() == str(brief).strip():
        return "degenerate"
    if normalize_markdown_headings(str(detailed)) != str(detailed):
        return "markdown_leak"
    return "clean"


def _connect(dsn: str):
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit("psycopg (v3) is required: pip install 'psycopg[binary]'") from exc
    return psycopg.connect(dsn, autocommit=True, connect_timeout=15)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-md",
        nargs="+",
        required=True,
        help="Skeleton .md files whose links are reserved by a concurrent PR (always kept).",
    )
    parser.add_argument("--out", default="zettel_ingest_audit.json", help="Report output path.")
    args = parser.parse_args()

    dsn = get_v2_database_url()
    if not dsn:
        logger.error("SUPABASE_V2_DATABASE_URL is unset; cannot run audit.")
        return 2

    keep = build_keep_set([Path(p) for p in args.keep_md])
    logger.info("Connecting read-only to v2 DB (DSN hidden). Keep-URL variants: %d.", len(keep))

    conn = _connect(dsn)
    counts: Counter[str] = Counter()
    reserved_kept = 0
    purge_candidates: list[dict] = []
    repairable: list[dict] = []
    total = 0
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT)
            for (
                row_id,
                ws_id,
                canon_id,
                ai_summary,
                engine_version,
                added_via,
                created_at,
                normalized_url,
            ) in cur:
                total += 1
                bucket = classify(ai_summary, engine_version)
                counts[bucket] += 1
                if bucket == "clean":
                    continue
                record = {
                    "id": str(row_id),
                    "workspace_id": str(ws_id),
                    "canonical_zettel_id": str(canon_id),
                    "bucket": bucket,
                    "added_via": added_via,
                    "created_at": created_at.isoformat() if created_at else None,
                    "normalized_url": normalized_url,
                }
                if _is_reserved(normalized_url, keep):
                    reserved_kept += 1
                    continue
                if bucket == "markdown_leak":
                    repairable.append(record)  # fix via backfill, never purge
                elif bucket in PURGEABLE_BUCKETS:
                    purge_candidates.append(record)
    finally:
        conn.close()

    dirty_total = total - counts["clean"]
    report = {
        "total_zettels": total,
        "by_bucket": dict(counts),
        "clean": counts["clean"],
        "dirty": dirty_total,
        "reserved_kept_concurrent_pr": reserved_kept,
        "repairable_via_backfill": len(repairable),
        "purge_candidates": len(purge_candidates),
        "latest_engine_version": LATEST_ENGINE_VERSION,
        "purgeable_buckets": sorted(PURGEABLE_BUCKETS),
        "candidates": purge_candidates,
        "repairable": repairable,
    }
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info(
        "Total=%d clean=%d dirty=%d reserved_kept=%d repairable=%d purge_candidates=%d",
        total, counts["clean"], dirty_total, reserved_kept, len(repairable), len(purge_candidates),
    )
    for bucket, n in sorted(counts.items()):
        logger.info("  %-15s %d", bucket, n)
    logger.info("Read-only. Full report -> %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
