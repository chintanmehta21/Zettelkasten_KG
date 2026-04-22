"""Benchmark GitHub ingest: README-only versus README plus signals."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.links_parser import parse_links_file
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.source_ingest.github.ingest import (
    GitHubIngestor,
)

STRATEGIES = [
    (
        "01-readme-only",
        {
            "fetch_pages": False,
            "fetch_workflows": False,
            "fetch_releases": False,
            "fetch_languages": False,
            "fetch_root_dir_listing": False,
            "architecture_overview_enabled": False,
        },
    ),
    (
        "02-full-signals",
        {
            "fetch_pages": True,
            "fetch_workflows": True,
            "fetch_releases": True,
            "fetch_languages": True,
            "fetch_root_dir_listing": True,
            "architecture_overview_enabled": True,
        },
    ),
]


async def _benchmark() -> None:
    cfg = load_config()
    base_cfg = cfg.sources.get("github", {})
    urls = parse_links_file(Path("docs/testing/links.txt")).get("github", [])[:3]
    if not urls:
        print("No GitHub URLs; add 3 under '# GitHub' in docs/testing/links.txt")
        return

    out_root = Path("docs/summary_eval/github/phase0.5-ingest/candidates")
    out_root.mkdir(parents=True, exist_ok=True)
    ingestor = GitHubIngestor()

    for filename, overrides in STRATEGIES:
        merged = {**base_cfg, **overrides}
        per_url = []
        for url in urls:
            try:
                result = await ingestor.ingest(url, config=merged)
                per_url.append(
                    {
                        "url": url,
                        "success": True,
                        "extraction_confidence": result.extraction_confidence,
                        "raw_text_chars": len(result.raw_text),
                        "has_pages_url": bool(result.metadata.get("pages_url")),
                        "has_workflows": result.metadata.get("has_workflows", False),
                        "releases_count": len(result.metadata.get("releases", []) or []),
                        "languages_count": len(
                            result.metadata.get("languages", []) or []
                        ),
                        "architecture_overview_len": len(
                            result.metadata.get("architecture_overview", "") or ""
                        ),
                    }
                )
            except Exception as exc:
                per_url.append({"url": url, "success": False, "error": str(exc)})
        aggregate = {
            "strategy": filename,
            "mean_chars": sum(item.get("raw_text_chars", 0) for item in per_url)
            / max(len(per_url), 1),
            "signal_coverage_pct": sum(
                1
                for item in per_url
                if item.get("has_pages_url")
                or item.get("has_workflows")
                or item.get("releases_count", 0) > 0
            )
            / max(len(per_url), 1)
            * 100.0,
        }
        payload = {
            "strategy": filename,
            "urls_tested": urls,
            "per_url": per_url,
            "aggregate": aggregate,
        }
        (out_root / f"{filename}.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        print(
            f"{filename}: mean_chars={aggregate['mean_chars']:.0f} "
            f"signal_coverage={aggregate['signal_coverage_pct']:.1f}%"
        )


if __name__ == "__main__":
    asyncio.run(_benchmark())
