"""Reddit ingestor with JSON endpoint + HTML fallback."""
from __future__ import annotations

import logging
from typing import Any

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.reddit.pullpush import (
    recover_removed_comments,
)
from website.features.summarization_engine.source_ingest.utils import (
    compact_text,
    extract_html_text,
    fetch_json,
    fetch_text,
    join_sections,
    utc_now,
)

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class RedditIngestor(BaseIngestor):
    source_type = SourceType.REDDIT

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        # Try JSON endpoint first (fast, structured)
        try:
            return await self._ingest_json(url, config)
        except Exception as exc:
            logger.warning("Reddit JSON fetch failed (%s), falling back to HTML", exc)

        # Fallback: scrape the HTML page
        return await self._ingest_html(url, config)

    async def _ingest_json(self, url: str, config: dict[str, Any]) -> IngestResult:
        json_url = url.rstrip("/") + ".json"
        headers = {"User-Agent": _BROWSER_UA}
        payload, final_url = await fetch_json(json_url, headers=headers)
        post = payload[0]["data"]["children"][0]["data"] if payload else {}
        comment_children = payload[1]["data"]["children"] if len(payload) > 1 else []
        comments = _comment_texts(
            comment_children,
            int(config.get("max_comments", 50)),
        )
        sections = {
            "Post": f"{post.get('title') or ''}\n{post.get('selftext') or ''}\n{post.get('url') or ''}",
            "Comments": "\n".join(comments),
        }
        rendered_count = len(
            [child for child in comment_children if child.get("kind") == "t1"]
        )
        num_comments = int(post.get("num_comments") or 0)
        divergence_pct = _compute_divergence(
            num_comments=num_comments,
            rendered_count=rendered_count,
        )
        pullpush_fetched = 0
        if (
            config.get("pullpush_enabled", True)
            and divergence_pct >= float(config.get("divergence_threshold_pct", 20))
            and num_comments > 0
        ):
            link_id = post.get("id")
            if link_id:
                pp = await recover_removed_comments(
                    link_id=link_id,
                    base_url=config.get("pullpush_base_url", "https://api.pullpush.io"),
                    timeout_sec=int(config.get("pullpush_timeout_sec", 10)),
                    max_recovered=int(
                        config.get("pullpush_max_recovered_comments", 25)
                    ),
                )
                if pp.success and pp.comments:
                    sections["Recovered Comments"] = "\n".join(
                        [
                            (
                                f"[u/{comment.author}, score {comment.score}, "
                                f"recovered from pullpush.io] {comment.body}"
                            )
                            for comment in pp.comments
                        ]
                    )
                    pullpush_fetched = len(pp.comments)
                else:
                    logger.info(
                        "[reddit-pullpush] no recovery for link_id=%s err=%s",
                        link_id,
                        pp.error,
                    )
        return IngestResult(
            source_type=self.source_type,
            url=final_url.removesuffix(".json"),
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata={
                "title": (post.get("title") or _title_from_url_slug(url) or "Reddit Post"),
                "subreddit": post.get("subreddit"),
                "author": post.get("author"),
                "score": post.get("score"),
                "num_comments": num_comments,
                "rendered_comment_count": rendered_count,
                "comment_divergence_pct": divergence_pct,
                "permalink": post.get("permalink"),
                "pullpush_fetched": pullpush_fetched,
                "pullpush_enabled": bool(config.get("pullpush_enabled", True)),
            },
            extraction_confidence="high",
            confidence_reason=(
                f"json endpoint ok; rendered={rendered_count}/{num_comments} "
                f"divergence={divergence_pct}%"
            ),
            fetched_at=utc_now(),
            ingestor_version="2.0.0",
        )

    async def _ingest_html(self, url: str, config: dict[str, Any]) -> IngestResult:
        # Try multiple Reddit domains
        domains_to_try = [
            url,
            url.replace("www.reddit.com", "old.reddit.com").replace("//reddit.com", "//old.reddit.com"),
        ]
        headers = {"User-Agent": _BROWSER_UA}
        html = ""
        final_url = url
        for attempt_url in domains_to_try:
            try:
                html, final_url = await fetch_text(attempt_url, headers=headers)
                if html:
                    break
            except Exception as exc:
                logger.warning("Reddit HTML fetch failed for %s: %s", attempt_url, exc)
                continue

        if not html:
            # Last resort: try Google cache or return minimal result
            return IngestResult(
                source_type=self.source_type,
                url=url,
                original_url=url,
                raw_text=f"Reddit post at {url}. Content could not be fetched (blocked by Reddit).",
                sections={"Post": f"Reddit post URL: {url}"},
                metadata={
                    "title": _title_from_url_slug(url) or "Reddit Post",
                    "subreddit": _extract_subreddit(url),
                },
                extraction_confidence="low",
                confidence_reason="Reddit blocked all fetch attempts",
                fetched_at=utc_now(),
            )

        text, metadata = extract_html_text(html)
        title = metadata.get("title", "").replace(" : ", " — ").strip()
        if not title:
            title = _title_from_url_slug(url)
        sections = {"Post": text}
        return IngestResult(
            source_type=self.source_type,
            url=url,
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata={
                "title": title,
                "subreddit": _extract_subreddit(url),
                **{k: v for k, v in metadata.items() if k != "title"},
            },
            extraction_confidence="medium",
            confidence_reason="Reddit HTML fallback (JSON blocked)",
            fetched_at=utc_now(),
        )


def _extract_subreddit(url: str) -> str | None:
    import re
    match = re.search(r"/r/([^/]+)", url)
    return match.group(1) if match else None


_ACRONYMS = {"cmv", "aita", "til", "eli5", "dae", "tifu", "yta", "nta", "ama", "iama", "psa"}
_TAIL_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "for", "with", "from", "at", "on", "in", "by", "as",
    "and", "or", "but", "so", "that", "this", "it", "its", "they", "them",
    "when", "while", "if", "then", "than", "about", "into", "onto", "over",
    "do", "does", "did", "you", "i", "we", "my", "your", "our",
}


def _title_from_url_slug(url: str, max_chars: int = 44) -> str:
    """Derive a human-readable title from a Reddit URL slug when server-side
    title extraction failed (anti-bot wall, 403s). The slug at
    ``/r/<sub>/comments/<id>/<slug>/`` is the original thread title in
    snake_case — the most accurate short label available without the HTML/API.

    Returns a title-cased, acronym-preserving string truncated at a word
    boundary to fit ``max_chars`` (default 44 leaves room for
    ``"r/<subreddit> "`` inside the 60-char mini_title contract). Drops
    trailing stopwords so the title never ends on ``"to"``/``"is"``/etc.
    Returns empty string when no slug is present.
    """
    import re
    match = re.search(r"/comments/[^/]+/([^/?#]+)", url)
    if not match:
        return ""
    raw = match.group(1).strip("_-").replace("-", "_")
    words = [w for w in raw.split("_") if w]
    if not words:
        return ""
    formatted = [w.upper() if w.lower() in _ACRONYMS else w.capitalize() for w in words]
    full = " ".join(formatted)
    if len(full) <= max_chars:
        return _strip_tail_stopwords(formatted)
    # Word-boundary truncation: accumulate until adding the next word would
    # overflow; never cut mid-word, never emit a fragment.
    kept: list[str] = []
    for w in formatted:
        candidate_len = len(" ".join(kept + [w]))
        if candidate_len > max_chars:
            break
        kept.append(w)
    if not kept:
        # Single first word longer than budget — truncate it hard as last resort.
        return formatted[0][:max_chars]
    return _strip_tail_stopwords(kept)


def _strip_tail_stopwords(words: list[str]) -> str:
    """Drop trailing low-content words (``"to"``, ``"is"``, ``"the"``, etc.)
    so the derived title never ends on a preposition/article/auxiliary. Keeps
    at least one word so we never return empty."""
    out = list(words)
    while len(out) > 1 and out[-1].lower() in _TAIL_STOPWORDS:
        out.pop()
    return " ".join(out)


def _comment_texts(children: list[dict[str, Any]], limit: int) -> list[str]:
    out: list[str] = []
    for child in children:
        if len(out) >= limit:
            break
        data = child.get("data") or {}
        body = compact_text(data.get("body") or "", max_chars=700)
        if body:
            out.append(f"{data.get('author') or 'unknown'}: {body}")
    return out


def _compute_divergence(*, num_comments: int, rendered_count: int) -> float:
    """Return the share of comments missing from the rendered JSON tree."""
    if num_comments <= 0:
        return 0.0
    missing = num_comments - rendered_count
    if missing <= 0:
        return 0.0
    return round((missing / num_comments) * 100.0, 2)
