"""Backfill kg_node_chunks for existing KG nodes that have zero chunks.

Designed to run inside the production container via ``docker exec`` where
GEMINI_API_KEY* and Supabase credentials are available as environment variables.

Usage examples
--------------
# Backfill all nodes in a Kasten (dry-run):
python ops/scripts/backfill_chunks.py --kasten 06854ee7-aab0-40d2-99e6-6d3cbe973b1b --dry-run

# Backfill all zero-chunk nodes for a user (cap at 20, 3 concurrent):
python ops/scripts/backfill_chunks.py --user-id <uuid> --limit 20 --concurrency 3

# Backfill specific nodes for a user:
python ops/scripts/backfill_chunks.py --user-id <uuid> --node-id yt-attention --node-id gh-llama

# Backfill with live source re-extraction (produces real long-form text):
python ops/scripts/backfill_chunks.py --user-id <uuid> --refetch-source

Exit codes
----------
0  all target nodes processed (per-node hook failures are logged but non-fatal)
1  Supabase query failure or bad arguments
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

# ---------------------------------------------------------------------------
# Bootstrap env: mirror the pattern in website/core/supabase_kg/client.py so
# the script finds credentials whether run locally or inside the container.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bootstrap_env() -> None:
    """Load env vars from local secret files (no-op if already set)."""
    try:
        from dotenv import load_dotenv  # type: ignore[import]
    except ImportError:
        return  # python-dotenv not available — rely on the shell env

    load_dotenv(_PROJECT_ROOT / "supabase" / ".env", override=False)
    load_dotenv(_PROJECT_ROOT / ".env", override=False)

    # Render secret-file paths (prod container)
    for candidate in (
        Path("/etc/secrets/nexus_env"),
        Path("/etc/secrets/api_env"),
        _PROJECT_ROOT / "supabase" / "website" / "nexus" / "nexus_env",
    ):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().lstrip("export").strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip().strip("'").strip('"')


_bootstrap_env()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_chunks")


# ---------------------------------------------------------------------------
# Source-type mapping: kg_nodes.source_type strings → SourceType enum
# kg_nodes can store values the SourceType enum doesn't have (e.g. "substack",
# "medium") — map them explicitly; unknowns fall back to WEB.
# ---------------------------------------------------------------------------

def _map_source_type(raw: str):
    """Return the SourceType enum member for a kg_nodes source_type string.

    Returns None if the telegram_bot package is not importable (non-prod env).
    """
    from telegram_bot.models.capture import SourceType  # noqa: PLC0415

    aliases: dict[str, SourceType] = {
        "youtube": SourceType.YOUTUBE,
        "github": SourceType.GITHUB,
        "reddit": SourceType.REDDIT,
        "newsletter": SourceType.NEWSLETTER,
        "substack": SourceType.NEWSLETTER,  # Substack uses the newsletter extractor
        "medium": SourceType.WEB,           # No dedicated extractor; generic fetch
        "web": SourceType.WEB,
        "generic": SourceType.WEB,
    }
    normalized = (raw or "").strip().lower()
    return aliases.get(normalized, SourceType.WEB)


async def _refetch_content(node: dict[str, Any]) -> "ExtractedContent | None":
    """Re-extract raw content from the node's source URL using the extractor plugin.

    Returns an ExtractedContent on success, None on any failure (caller falls
    back to node["summary"]).
    """
    url = (node.get("url") or "").strip()
    source_type_raw = (node.get("source_type") or "web").strip().lower()

    if not url:
        logger.warning(
            "refetch skip: node %s has no url — falling back to summary", node["id"]
        )
        return None

    try:
        from telegram_bot.sources import get_extractor  # noqa: PLC0415
        from telegram_bot.config.settings import get_settings  # noqa: PLC0415
        from telegram_bot.models.capture import ExtractedContent  # noqa: PLC0415 # type: ignore[assignment]
    except ImportError as exc:
        logger.warning(
            "refetch skip: telegram_bot package not importable (%s) — "
            "falling back to summary for node %s",
            exc,
            node["id"],
        )
        return None

    try:
        source_type = _map_source_type(source_type_raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refetch skip: cannot map source_type %r for node %s: %s",
            source_type_raw,
            node["id"],
            exc,
        )
        return None

    # Guard Reddit: warn and skip early if credentials are absent so we don't
    # waste a network call that will fail with an auth error.
    if source_type_raw == "reddit":
        reddit_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
        reddit_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
        if not reddit_id or not reddit_secret:
            logger.warning(
                "refetch skip: REDDIT_CLIENT_ID/SECRET not set — "
                "falling back to summary for node %s (%s)",
                node["id"],
                url,
            )
            return None

    try:
        settings = get_settings()
    except SystemExit:
        logger.warning(
            "refetch skip: get_settings() failed (missing required env vars) — "
            "falling back to summary for node %s",
            node["id"],
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refetch skip: get_settings() raised %s — falling back to summary for node %s",
            exc,
            node["id"],
        )
        return None

    try:
        extractor = get_extractor(source_type, settings)
    except (KeyError, Exception) as exc:  # noqa: BLE001
        logger.warning(
            "refetch skip: no extractor for %s (%s): %s — falling back to summary for node %s",
            source_type_raw,
            url,
            exc,
            node["id"],
        )
        return None

    try:
        content = await extractor.extract(url)
        char_count = len(content.body) if content and content.body else 0
        logger.info(
            "refetch: %s %s → %d chars", source_type_raw, url, char_count
        )
        return content
    except Exception as exc:  # noqa: BLE001
        logger.warning("refetch failed: %s %s: %s", source_type_raw, url, exc)
        return None


# ---------------------------------------------------------------------------
# Supabase client (service-role; falls back to anon key if service role absent)
# ---------------------------------------------------------------------------

def _get_supabase():
    """Return a Supabase Client using service-role or anon key."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )
    if not url or not key:
        logger.error(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) "
            "must be set. Add them to supabase/.env or export them."
        )
        sys.exit(1)

    try:
        from supabase import create_client  # type: ignore[import]
    except ImportError:
        logger.error("supabase package not installed. Run: pip install supabase")
        sys.exit(1)

    return create_client(url, key)


# ---------------------------------------------------------------------------
# Node enumeration helpers
# ---------------------------------------------------------------------------

_NODE_COLUMNS = "id, user_id, name, summary, source_type, tags, url, metadata"


def _fetch_kasten_nodes(client, kasten_id: str, limit: int) -> list[dict[str, Any]]:
    """Return node rows for all members of a rag_sandbox (Kasten)."""
    # Step 1: member list
    members_resp = (
        client.table("rag_sandbox_members")
        .select("node_id, user_id")
        .eq("sandbox_id", kasten_id)
        .execute()
    )
    members: list[dict[str, Any]] = members_resp.data or []
    if not members:
        return []

    # Step 2: fetch node rows grouped by user_id to minimise round-trips.
    # rag_sandbox_members can theoretically span users but in practice all
    # members share the sandbox owner's user_id — still handle multi-user
    # gracefully.
    from collections import defaultdict

    by_user: dict[str, list[str]] = defaultdict(list)
    for m in members:
        by_user[m["user_id"]].append(m["node_id"])

    nodes: list[dict[str, Any]] = []
    for uid, node_ids in by_user.items():
        # PostgREST: in_ filter; batch to avoid URL length limits
        resp = (
            client.table("kg_nodes")
            .select(_NODE_COLUMNS)
            .eq("user_id", uid)
            .in_("id", node_ids)
            .limit(limit)
            .execute()
        )
        nodes.extend(resp.data or [])

    return nodes[:limit]


def _fetch_specific_nodes(
    client, user_id: str, node_ids: list[str]
) -> list[dict[str, Any]]:
    """Return specific node rows for a given user."""
    resp = (
        client.table("kg_nodes")
        .select(_NODE_COLUMNS)
        .eq("user_id", user_id)
        .in_("id", node_ids)
        .execute()
    )
    return resp.data or []


def _fetch_zero_chunk_nodes(
    client, user_id: str, limit: int
) -> list[dict[str, Any]]:
    """Return all nodes for a user that currently have zero chunk rows.

    Uses a LEFT JOIN expressed as two separate queries because the supabase-py
    client does not support arbitrary SQL JOINs via the table API. We fetch
    node IDs that *do* have chunks and exclude them.
    """
    # Fetch node IDs that already have at least one chunk
    chunks_resp = (
        client.table("kg_node_chunks")
        .select("node_id")
        .eq("user_id", user_id)
        .execute()
    )
    chunked_ids: set[str] = {r["node_id"] for r in (chunks_resp.data or [])}

    # Fetch all nodes for the user
    nodes_resp = (
        client.table("kg_nodes")
        .select(_NODE_COLUMNS)
        .eq("user_id", user_id)
        .limit(limit * 10)  # over-fetch; we'll filter and cap below
        .execute()
    )
    all_nodes: list[dict[str, Any]] = nodes_resp.data or []

    unchunked = [n for n in all_nodes if n["id"] not in chunked_ids]
    return unchunked[:limit]


# ---------------------------------------------------------------------------
# Main async runner
# ---------------------------------------------------------------------------

async def _process_node(
    node: dict[str, Any],
    idx: int,
    total: int,
    sem: asyncio.Semaphore,
    ingest_fn: Any,
    dry_run: bool,
    refetch_source: bool = False,
) -> dict[str, Any]:
    """Process a single node under the semaphore. Returns a result dict."""
    short_name = (node.get("name") or node["id"])[:40]
    result = {
        "node_id": node["id"],
        "name": short_name,
        "chunks_written": 0,
        "status": "dry-run" if dry_run else "pending",
        "refetched": False,
    }

    if dry_run:
        print(f"  [{idx}/{total}] {node['id']:<30}  {short_name}")
        return result

    # Attempt source re-extraction when requested; fall back to summary on any failure.
    extracted = None
    if refetch_source:
        extracted = await _refetch_content(node)

    # Stub rejection: extractors sometimes return useless placeholders
    # (e.g. "Transcript not available for this video" from the YouTube
    # oEmbed fallback, paywall redirect bodies, etc). Prefer the stored
    # summary when the refetched body is a known stub or shorter than it.
    _STUB_MARKERS = (
        "transcript not available",
        "not available for this video",
        "video unavailable",
        "content unavailable",
        "403 forbidden",
        "access denied",
        "paywall",
    )
    refetched_body = extracted.body if extracted and extracted.body else ""
    summary_text = node.get("summary") or ""
    refetched_lower = refetched_body.lower()
    is_stub = (
        len(refetched_body.strip()) < 200
        or any(m in refetched_lower for m in _STUB_MARKERS)
    )
    if is_stub and len(summary_text) > len(refetched_body):
        refetched_body = ""  # discard stub; fall through to summary

    refetched_flag = bool(refetched_body)
    result["refetched"] = refetched_flag

    raw_text = refetched_body or summary_text or ""
    payload = {
        "title": (extracted.title if extracted and extracted.title else None)
                 or node.get("name") or node["id"],
        "summary": node.get("summary") or "",
        "raw_text": raw_text,
        "source_type": node.get("source_type") or "web",
        "tags": node.get("tags") or [],
        "raw_metadata": (extracted.metadata if extracted and extracted.metadata else None)
                        or node.get("metadata") or {},
    }

    refetch_label = f"refetched={len(raw_text)}c " if refetch_source else ""

    async with sem:
        try:
            chunks = await ingest_fn(
                payload=payload,
                user_uuid=UUID(node["user_id"]),
                node_id=node["id"],
            )
            result["chunks_written"] = chunks
            result["status"] = "ok"
            print(
                f"  [{idx}/{total}] {node['id']:<30}  {short_name:<44}"
                f"  {refetch_label}chunks={chunks} ok"
            )
        except Exception as exc:  # noqa: BLE001
            result["status"] = f"error: {exc}"
            logger.warning("Node %s failed: %s", node["id"], exc)
            print(
                f"  [{idx}/{total}] {node['id']:<30}  {short_name:<44}"
                f"  {refetch_label}FAILED: {exc}"
            )

    return result


async def run(args: argparse.Namespace) -> int:
    client = _get_supabase()

    # ---- enumerate target nodes ------------------------------------------
    try:
        if args.kasten:
            nodes = _fetch_kasten_nodes(client, args.kasten, args.limit)
            scope_label = f"kasten={args.kasten}"
        elif args.node_id:
            nodes = _fetch_specific_nodes(client, args.user_id, args.node_id)
            scope_label = f"user={args.user_id}, nodes={args.node_id}"
        else:
            # --user-id only: backfill zero-chunk nodes
            nodes = _fetch_zero_chunk_nodes(client, args.user_id, args.limit)
            scope_label = f"user={args.user_id}, zero-chunk"
    except Exception as exc:  # noqa: BLE001
        logger.error("Supabase query failed: %s", exc)
        return 1

    total = len(nodes)
    if total == 0:
        print("No target nodes found. Nothing to do.")
        return 0

    print(
        f"Processing {total} node{'s' if total != 1 else ''} ({scope_label})"
        f" with concurrency={args.concurrency} …"
    )

    if args.dry_run:
        for i, node in enumerate(nodes, start=1):
            short_name = (node.get("name") or node["id"])[:44]
            print(f"  [{i}/{total}] {node['id']:<30}  {short_name}")
        print(f"\nDry-run complete. {total} node(s) would be processed.")
        return 0

    # ---- live run: import hook (deferred so dry-run works without prod deps)
    try:
        from website.features.rag_pipeline.ingest.hook import ingest_node_chunks
    except ImportError as exc:
        logger.error(
            "Cannot import ingest hook (expected inside the prod container): %s", exc
        )
        return 1

    sem = asyncio.Semaphore(args.concurrency)
    tasks = [
        _process_node(
            node=node,
            idx=i,
            total=total,
            sem=sem,
            ingest_fn=ingest_node_chunks,
            dry_run=False,
            refetch_source=args.refetch_source,
        )
        for i, node in enumerate(nodes, start=1)
    ]
    results = await asyncio.gather(*tasks)

    # ---- summary table ---------------------------------------------------
    total_chunks = sum(r["chunks_written"] for r in results)
    failed = sum(1 for r in results if r["status"] != "ok")
    refetched_count = sum(1 for r in results if r.get("refetched"))

    refetch_summary = (
        f" Refetched: {refetched_count}/{total}." if args.refetch_source else ""
    )
    print(
        f"\nDone. Total chunks written: {total_chunks}."
        f" Failed nodes: {failed}.{refetch_summary}"
    )
    if failed:
        print("Failed node IDs:")
        for r in results:
            if r["status"] != "ok":
                print(f"  {r['node_id']}  {r['status']}")

    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill kg_node_chunks for KG nodes that have zero chunk rows. "
            "Run inside the production container via `docker exec`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--kasten",
        metavar="UUID",
        help="Backfill all nodes that are members of this rag_sandbox.",
    )
    scope.add_argument(
        "--user-id",
        metavar="UUID",
        dest="user_id",
        help=(
            "Target user UUID. Required when using --node-id. "
            "Without --node-id: backfills all zero-chunk nodes for this user."
        ),
    )

    parser.add_argument(
        "--node-id",
        metavar="NODE_ID",
        dest="node_id",
        action="append",
        default=[],
        help="Node ID to backfill (repeatable). Requires --user-id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate target nodes and print them; do NOT call ingest or touch the DB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of nodes to process in one run (default 50).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Number of concurrent ingest_node_chunks coroutines (default 3).",
    )
    parser.add_argument(
        "--refetch-source",
        action="store_true",
        dest="refetch_source",
        help=(
            "Re-extract raw content from each node's source URL using the "
            "telegram_bot extractor plugins before chunking. Falls back to the "
            "stored summary when the URL is missing, the extractor fails, or "
            "credentials (e.g. REDDIT_CLIENT_ID/SECRET) are absent. "
            "Requires telegram_bot to be importable (production container)."
        ),
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Validate arg combinations
    if args.node_id and not args.user_id:
        parser.error("--node-id requires --user-id")
    if not args.kasten and not args.user_id:
        parser.error("Provide --kasten OR --user-id (optionally with --node-id).")
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
