"""One-shot architecture overview extractor, cached per repo slug."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from website.features.summarization_engine.core.cache import FsContentCache

_PROMPT_VERSION = "arch.v1"

_PROMPT = """\
Produce a 1-3 sentence (max {max_chars} chars) architecture overview of this GitHub repo.
Describe major directories or modules and how they interact. Ground strictly in the README
and top-level directory listing. No speculation. Plain prose, no markdown, no bullets.

README:
{readme}

TOP-LEVEL DIRECTORIES:
{dirs}
"""


async def extract_architecture_overview(
    *,
    client: Any,
    readme_text: str,
    top_level_dirs: list[str],
    max_chars: int,
    cache_root: Path,
    slug: str,
) -> str:
    cache = FsContentCache(root=cache_root, namespace="github_architecture")
    key = (slug, _PROMPT_VERSION)
    hit = cache.get(key)
    if hit and "overview" in hit:
        return hit["overview"]

    prompt = _PROMPT.format(
        max_chars=max_chars,
        readme=readme_text[:8000],
        dirs=", ".join(top_level_dirs) or "(none detected)",
    )
    result = await client.generate(prompt, tier="flash")
    text = (result.text or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "..."
    if len(text) < 50:
        text = (
            f"Repository {slug} architecture not clearly described in README; "
            "see source modules directly."
        )
    cache.put(key, {"overview": text})
    return text
