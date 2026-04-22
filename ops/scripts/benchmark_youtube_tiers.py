"""Benchmark each YouTube transcript tier on 3 URLs; emit candidate JSONs."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.source_ingest.youtube.tiers import (
    TierName,
    tier_gemini_audio,
    tier_invidious_pool,
    tier_metadata_only,
    tier_piped_pool,
    tier_transcript_api_direct,
    tier_ytdlp_player_rotation,
)

TIERS = [
    ("01-ytdlp-player-rotation", TierName.YTDLP_PLAYER_ROTATION, tier_ytdlp_player_rotation),
    ("02-transcript-api-direct", TierName.TRANSCRIPT_API_DIRECT, tier_transcript_api_direct),
    ("03-piped-pool", TierName.PIPED_POOL, tier_piped_pool),
    ("04-invidious-pool", TierName.INVIDIOUS_POOL, tier_invidious_pool),
    ("05-gemini-audio", TierName.GEMINI_AUDIO, tier_gemini_audio),
    ("06-metadata-only", TierName.METADATA_ONLY, tier_metadata_only),
]


async def _benchmark() -> None:
    cfg = load_config()
    yt_cfg = cfg.sources.get("youtube", {})
    url_ids = ["hhjhU5MXZOo", "HBTYVVUBAGs", "Brm71uCWr-I"]
    out_root = Path("docs/summary_eval/youtube/phase0.5-ingest/candidates")
    out_root.mkdir(parents=True, exist_ok=True)

    for filename, tier_name, fn in TIERS:
        per_url = []
        for vid in url_ids:
            result = await fn(vid, yt_cfg)
            per_url.append(
                {
                    "video_id": vid,
                    "success": result.success,
                    "confidence": result.confidence,
                    "transcript_chars": len(result.transcript),
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                    "extra": result.extra,
                }
            )
        aggregate = {
            "tier": tier_name.value,
            "success_rate": sum(1 for item in per_url if item["success"]) / len(per_url),
            "mean_chars": sum(item["transcript_chars"] for item in per_url) / len(per_url),
            "mean_latency_ms": sum(item["latency_ms"] for item in per_url) / len(per_url),
        }
        payload = {
            "strategy": tier_name.value,
            "urls_tested": url_ids,
            "per_url": per_url,
            "aggregate": aggregate,
        }
        (out_root / f"{filename}.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        print(
            f"{filename}: success_rate={aggregate['success_rate']:.2f} "
            f"mean_chars={aggregate['mean_chars']:.0f}"
        )


if __name__ == "__main__":
    asyncio.run(_benchmark())
