"""Benchmark newsletter ingest: baseline body extraction vs structural signals."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.scripts.lib.links_parser import parse_links_file
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.source_ingest.newsletter.ingest import (
    NewsletterIngestor,
)

STRATEGIES = [
    (
        "01-trafilatura-baseline",
        {
            "site_specific_selectors_enabled": False,
            "stance_classifier_enabled": False,
            "cta_max_count": 0,
            "conclusions_max_count": 0,
        },
    ),
    (
        "02-site-specific-plus-structural",
        {
            "site_specific_selectors_enabled": True,
            "stance_classifier_enabled": True,
        },
    ),
]


async def _benchmark() -> None:
    cfg = load_config()
    base_cfg = cfg.sources.get("newsletter", {})
    urls = parse_links_file(Path("docs/testing/links.txt")).get("newsletter", [])[:3]
    if not urls:
        print("No Newsletter URLs; add 3 under '# Newsletter' in docs/testing/links.txt")
        return

    out_root = Path("docs/summary_eval/newsletter/phase0.5-ingest/candidates")
    out_root.mkdir(parents=True, exist_ok=True)
    ingestor = NewsletterIngestor()

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
                        "raw_text_chars": len(result.raw_text),
                        "extraction_confidence": result.extraction_confidence,
                        "site": result.metadata.get("site"),
                        "has_preheader": bool(result.metadata.get("preheader")),
                        "cta_count": result.metadata.get("cta_count", 0),
                        "conclusions_count": result.metadata.get(
                            "conclusions_count",
                            0,
                        ),
                        "detected_stance": result.metadata.get("detected_stance"),
                        "publication_identity": result.metadata.get(
                            "publication_identity",
                            "",
                        ),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                per_url.append({"url": url, "success": False, "error": str(exc)})
        aggregate = {
            "strategy": filename,
            "mean_chars": sum(item.get("raw_text_chars", 0) for item in per_url)
            / max(len(per_url), 1),
            "signal_coverage": sum(
                1
                for item in per_url
                if item.get("has_preheader")
                or item.get("cta_count", 0) > 0
                or item.get("conclusions_count", 0) > 0
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
            f"{filename}: mean_chars={aggregate['mean_chars']:.0f} "
            f"signal_coverage={aggregate['signal_coverage']}/{len(per_url)}"
        )


if __name__ == "__main__":
    asyncio.run(_benchmark())
