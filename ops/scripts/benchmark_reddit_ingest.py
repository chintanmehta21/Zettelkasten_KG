"""Benchmark Reddit ingest strategies on the Reddit URLs in links.txt."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.links_parser import parse_links_file
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.source_ingest.reddit.ingest import (
    RedditIngestor,
)

STRATEGIES = [
    ("01-anon-json-only", {"pullpush_enabled": False}),
    (
        "02-anon-json-plus-pullpush",
        {"pullpush_enabled": True, "divergence_threshold_pct": 20},
    ),
]


async def _benchmark() -> None:
    cfg = load_config()
    base_reddit_cfg = cfg.sources.get("reddit", {})
    urls = parse_links_file(Path("docs/testing/links.txt")).get("reddit", [])[:4]
    if not urls:
        print("No Reddit URLs; add 3+ under '# Reddit' in docs/testing/links.txt")
        return

    out_root = Path("docs/summary_eval/reddit/phase0.5-ingest/candidates")
    out_root.mkdir(parents=True, exist_ok=True)

    for filename, overrides in STRATEGIES:
        per_url = []
        merged_cfg = {**base_reddit_cfg, **overrides}
        ingestor = RedditIngestor()
        for url in urls:
            try:
                result = await ingestor.ingest(url, config=merged_cfg)
                per_url.append(
                    {
                        "url": url,
                        "success": True,
                        "extraction_confidence": result.extraction_confidence,
                        "raw_text_chars": len(result.raw_text),
                        "num_comments": result.metadata.get("num_comments"),
                        "rendered_comment_count": result.metadata.get(
                            "rendered_comment_count"
                        ),
                        "comment_divergence_pct": result.metadata.get(
                            "comment_divergence_pct"
                        ),
                        "pullpush_fetched": result.metadata.get("pullpush_fetched", 0),
                    }
                )
            except Exception as exc:
                per_url.append({"url": url, "success": False, "error": str(exc)})
        aggregate = {
            "strategy": filename,
            "success_rate": sum(1 for item in per_url if item.get("success"))
            / max(len(per_url), 1),
            "mean_chars": sum(item.get("raw_text_chars", 0) for item in per_url)
            / max(len(per_url), 1),
            "total_pullpush_fetched": sum(
                item.get("pullpush_fetched", 0)
                for item in per_url
                if item.get("success")
            ),
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
            f"{filename}: success={aggregate['success_rate']:.2f} "
            f"mean_chars={aggregate['mean_chars']:.0f} "
            f"pullpush_total={aggregate['total_pullpush_fetched']}"
        )


if __name__ == "__main__":
    asyncio.run(_benchmark())
