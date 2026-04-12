"""Backfill kg_node_chunks for existing Zettels from Obsidian markdown files.

This is not part of the v1 pipeline. Run it manually when older summary-only
nodes need chunk-level retrieval support.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill kg_node_chunks for existing markdown Zettels.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the intended work without writing anything.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of markdown files to inspect in one run.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    mode = "dry-run" if args.dry_run else "live-run"
    print(f"backfill_chunks skeleton invoked in {mode} mode with limit={args.limit}")
    print(
        "TODO: iterate KG_DIRECTORY markdown files, extract raw text, chunk with "
        "ZettelChunker, embed with ChunkEmbedder, and call upsert_chunks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
