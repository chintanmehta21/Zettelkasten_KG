"""pullpush.io client for recovering removed Reddit comments."""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx


@dataclass
class PullPushComment:
    id: str
    body: str
    author: str
    score: int


@dataclass
class PullPushResult:
    comments: list[PullPushComment] = field(default_factory=list)
    success: bool = True
    error: str | None = None


async def recover_removed_comments(
    *,
    link_id: str,
    base_url: str,
    timeout_sec: int,
    max_recovered: int,
) -> PullPushResult:
    """Fetch archived comments for a Reddit thread."""
    url = f"{base_url.rstrip('/')}/reddit/search/comment/"
    params = {
        "link_id": f"t3_{link_id}",
        "size": max_recovered,
        "sort": "score",
        "sort_type": "score",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return PullPushResult(
                    success=False,
                    error=f"pullpush HTTP {resp.status_code}",
                )
            data = resp.json()
    except httpx.TimeoutException as exc:
        return PullPushResult(success=False, error=f"timeout: {exc}")
    except Exception as exc:
        return PullPushResult(success=False, error=f"unexpected: {exc}")

    raw = (data or {}).get("data") or []
    comments: list[PullPushComment] = []
    for entry in raw[:max_recovered]:
        body = (entry.get("body") or "").strip()
        if not body or body in {"[removed]", "[deleted]"}:
            continue
        comments.append(
            PullPushComment(
                id=entry.get("id", ""),
                body=body,
                author=entry.get("author", "[unknown]"),
                score=int(entry.get("score") or 0),
            )
        )
    return PullPushResult(comments=comments, success=True)
