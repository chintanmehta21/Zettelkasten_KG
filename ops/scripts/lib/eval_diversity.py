"""Eval-time training/held-out set diversity assertions.

These checks prevent the scoring loop from silently overfitting to a narrow
URL mix. They run at config-load time, before any summarization work, so a
diversity gap fails fast with an actionable message instead of wasting an
iteration on URLs that cannot represent the source well.

Assertions live here (eval tooling), not in production code paths. They are
only invoked from ``ops/scripts/eval_loop.py``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


# ── Public errors ───────────────────────────────────────────────────────────


class EvalConfigInsufficientDiversity(AssertionError):
    """Raised when a training/held-out URL set fails its diversity gate.

    Subclass of ``AssertionError`` so an accidental unset bypass flag still
    blocks the loop by default.
    """


# ── Reddit ──────────────────────────────────────────────────────────────────


_REDDIT_MIN_SUBREDDITS = 3
_REDDIT_MIN_POST_TYPES = 2

_REDDIT_SUBREDDIT_RE = re.compile(r"/r/([A-Za-z0-9_]+)/?", re.IGNORECASE)


@dataclass(frozen=True)
class RedditDiversityVerdict:
    subreddits: tuple[str, ...]
    post_types: tuple[str, ...]
    distinct_subreddit_count: int
    distinct_post_type_count: int


def _classify_reddit_post_type(url: str) -> str:
    """Best-effort URL-only classifier.

    Reddit URLs don't carry post-type in the path — a /comments/ URL may be
    text, link, gallery, or video. Without ingestion we can only distinguish
    ``comments`` (thread) from ``gallery``/``video``/``media`` variants that
    Reddit does expose in the path. For diversity we treat any URL whose
    path segment is ``/gallery/``, ``/media/``, or ``/video/`` as a separate
    type from the baseline ``comments`` type.
    """
    path = urlparse(url).path.lower()
    if "/gallery/" in path:
        return "gallery"
    if "/media/" in path or "/video/" in path:
        return "media"
    if "/comments/" in path:
        return "comments"
    return "unknown"


def _extract_reddit_subreddit(url: str) -> str | None:
    match = _REDDIT_SUBREDDIT_RE.search(urlparse(url).path)
    if not match:
        return None
    return match.group(1).lower()


def inspect_reddit_diversity(urls: Iterable[str]) -> RedditDiversityVerdict:
    """Return counts without raising — useful for reporting."""
    subs: list[str] = []
    types: list[str] = []
    for url in urls:
        sub = _extract_reddit_subreddit(url)
        if sub:
            subs.append(sub)
        types.append(_classify_reddit_post_type(url))
    return RedditDiversityVerdict(
        subreddits=tuple(sorted(set(subs))),
        post_types=tuple(sorted(set(types))),
        distinct_subreddit_count=len(set(subs)),
        distinct_post_type_count=len(set(types)),
    )


def check_reddit_training_diversity(
    urls: Iterable[str],
    *,
    min_subreddits: int = _REDDIT_MIN_SUBREDDITS,
    min_post_types: int = _REDDIT_MIN_POST_TYPES,
    allow_skip_env: str = "EVAL_SKIP_REDDIT_DIVERSITY",
) -> RedditDiversityVerdict:
    """Raise if the Reddit training slice lacks subreddit / post-type variety.

    ``min_subreddits`` distinct subreddits AND ``min_post_types`` distinct
    post types are required.

    Respects ``EVAL_SKIP_REDDIT_DIVERSITY=1`` as a conspicuous bypass — when
    set, returns the verdict and prints a WARN banner on stderr so an
    operator cannot miss the waiver.
    """
    verdict = inspect_reddit_diversity(urls)

    if (
        verdict.distinct_subreddit_count >= min_subreddits
        and verdict.distinct_post_type_count >= min_post_types
    ):
        return verdict

    detail = (
        f"Reddit training slice has {verdict.distinct_subreddit_count} distinct "
        f"subreddit(s) and {verdict.distinct_post_type_count} distinct post-type(s); "
        f"require >= {min_subreddits} subreddits and >= {min_post_types} post-types. "
        f"subreddits={list(verdict.subreddits)} post_types={list(verdict.post_types)}"
    )

    if os.environ.get(allow_skip_env):
        print(
            f"\n[WARN] {allow_skip_env}=1 set — bypassing Reddit diversity gate.\n"
            f"       {detail}\n",
            flush=True,
        )
        return verdict

    raise EvalConfigInsufficientDiversity(detail)


# ── GitHub ──────────────────────────────────────────────────────────────────


_GH_MIN_REPOS = 5
_GH_MIN_ARCHETYPES = 3

_GH_REPO_PATH_RE = re.compile(r"^/([^/]+)/([^/]+?)(?:\.git)?/?$")


@dataclass(frozen=True)
class GithubDiversityVerdict:
    repos: tuple[str, ...]
    archetypes: tuple[str, ...]
    distinct_repo_count: int
    distinct_archetype_count: int
    unmapped_urls: tuple[str, ...]


def _extract_gh_owner_repo(url: str) -> str | None:
    parsed = urlparse(url)
    if "github.com" not in parsed.netloc:
        return None
    match = _GH_REPO_PATH_RE.match(parsed.path)
    if not match:
        return None
    return f"{match.group(1).lower()}/{match.group(2).lower()}"


def inspect_github_diversity(
    urls: Iterable[str],
    archetype_map: dict[str, str] | None,
) -> GithubDiversityVerdict:
    """Count repos + archetypes given a URL→archetype map.

    The archetype map is keyed on ``owner/repo`` (lowercased). URLs whose
    ``owner/repo`` is missing from the map land in ``unmapped_urls`` and
    contribute 0 archetypes.
    """
    archetype_map = {k.lower(): v for k, v in (archetype_map or {}).items()}
    repos: list[str] = []
    archetypes: list[str] = []
    unmapped: list[str] = []
    for url in urls:
        repo = _extract_gh_owner_repo(url)
        if repo is None:
            unmapped.append(url)
            continue
        repos.append(repo)
        if repo in archetype_map:
            archetypes.append(archetype_map[repo])
        else:
            unmapped.append(url)
    return GithubDiversityVerdict(
        repos=tuple(sorted(set(repos))),
        archetypes=tuple(sorted(set(archetypes))),
        distinct_repo_count=len(set(repos)),
        distinct_archetype_count=len(set(archetypes)),
        unmapped_urls=tuple(unmapped),
    )


def check_github_heldout_diversity(
    urls: Iterable[str],
    archetype_map: dict[str, str] | None,
    *,
    min_repos: int = _GH_MIN_REPOS,
    min_archetypes: int = _GH_MIN_ARCHETYPES,
    allow_skip_env: str = "EVAL_SKIP_GH_DIVERSITY",
) -> GithubDiversityVerdict:
    """Raise if the GitHub held-out set lacks repo or archetype variety.

    Requires >= ``min_repos`` distinct repositories and >= ``min_archetypes``
    distinct archetypes. Archetype labels come from the caller-supplied map
    (normally ``docs/summary_eval/_config/github_heldout_archetypes.yaml``);
    unmapped repos cannot count toward archetype diversity.
    """
    verdict = inspect_github_diversity(urls, archetype_map)

    if (
        verdict.distinct_repo_count >= min_repos
        and verdict.distinct_archetype_count >= min_archetypes
    ):
        return verdict

    detail = (
        f"GitHub held-out set has {verdict.distinct_repo_count} distinct repo(s) "
        f"and {verdict.distinct_archetype_count} distinct archetype(s); "
        f"require >= {min_repos} repos and >= {min_archetypes} archetypes. "
        f"repos={list(verdict.repos)} archetypes={list(verdict.archetypes)} "
        f"unmapped={list(verdict.unmapped_urls)}"
    )

    if os.environ.get(allow_skip_env):
        print(
            f"\n[WARN] {allow_skip_env}=1 set — bypassing GitHub diversity gate.\n"
            f"       {detail}\n",
            flush=True,
        )
        return verdict

    raise EvalConfigInsufficientDiversity(detail)


# ── EvalItem-based assertions (public eval harness API) ─────────────────────
#
# These wrap the URL-only checks above with an ``EvalItem``-shaped input so the
# eval harness can pass richer records (with ingest metadata / archetype tags)
# without re-parsing URLs. They raise ``ValueError`` so callers that prefer the
# stdlib exception hierarchy get a flat contract; the underlying
# ``EvalConfigInsufficientDiversity`` is still raised by the legacy
# ``check_*_diversity`` entry points used in production.


@dataclass
class EvalItem:
    """Minimal shape the eval harness feeds to diversity assertions.

    ``metadata`` is the bag-of-fields handed back by the source ingestor (for
    Reddit: ``subreddit``, ``post_type``, ``pullpush_fetched``; for GitHub:
    ``repo``, ``archetype``). URL parsing is used as a fallback when metadata
    is missing so we can still gate on raw URL lists.
    """

    url: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _item_subreddit(item: EvalItem) -> str | None:
    meta_sub = item.metadata.get("subreddit") if isinstance(item.metadata, Mapping) else None
    if meta_sub:
        return str(meta_sub).lower()
    return _extract_reddit_subreddit(item.url)


def _item_thread_type(item: EvalItem) -> str:
    meta_type = (
        item.metadata.get("post_type")
        or item.metadata.get("thread_type")
        if isinstance(item.metadata, Mapping)
        else None
    )
    if meta_type:
        return str(meta_type).lower()
    return _classify_reddit_post_type(item.url)


def _item_repo(item: EvalItem) -> str | None:
    meta_repo = item.metadata.get("repo") if isinstance(item.metadata, Mapping) else None
    if meta_repo:
        return str(meta_repo).lower()
    return _extract_gh_owner_repo(item.url)


def _item_archetype(item: EvalItem) -> str | None:
    meta_arch = item.metadata.get("archetype") if isinstance(item.metadata, Mapping) else None
    if meta_arch:
        return str(meta_arch).lower()
    return None


def assert_reddit_diversity(
    items: list[EvalItem],
    *,
    min_subreddits: int = _REDDIT_MIN_SUBREDDITS,
    min_thread_types: int = _REDDIT_MIN_POST_TYPES,
) -> None:
    """Fail-fast assertion: the Reddit held-out set must span enough variety.

    Requires ``>= min_subreddits`` distinct subreddits AND
    ``>= min_thread_types`` distinct thread types across ``items``. Pulls the
    subreddit/thread-type from ``item.metadata`` first, then falls back to URL
    parsing so the harness works even when ingest metadata is not populated.

    Raises ``ValueError`` with an actionable message listing what we observed
    and what is required.
    """
    if not items:
        raise ValueError(
            "Reddit held-out diversity gate received 0 items; "
            f"require >= {min_subreddits} subreddits and >= {min_thread_types} thread-types."
        )
    subs: set[str] = set()
    types: set[str] = set()
    for item in items:
        sub = _item_subreddit(item)
        if sub:
            subs.add(sub)
        types.add(_item_thread_type(item))
    if len(subs) >= min_subreddits and len(types) >= min_thread_types:
        return
    raise ValueError(
        f"Reddit held-out set lacks diversity: "
        f"{len(subs)} distinct subreddit(s) (require >= {min_subreddits}), "
        f"{len(types)} distinct thread-type(s) (require >= {min_thread_types}). "
        f"subreddits={sorted(subs)} thread_types={sorted(types)}"
    )


def assert_github_diversity(
    items: list[EvalItem],
    *,
    min_repos: int = _GH_MIN_REPOS,
    min_archetypes: int = _GH_MIN_ARCHETYPES,
) -> None:
    """Fail-fast assertion: the GitHub held-out set must span enough variety.

    Requires ``>= min_repos`` distinct ``owner/repo`` pairs AND
    ``>= min_archetypes`` distinct archetype labels. Archetype is read from
    ``item.metadata['archetype']``; items missing that field do not contribute
    to archetype diversity.

    Raises ``ValueError`` with an actionable message.
    """
    if not items:
        raise ValueError(
            "GitHub held-out diversity gate received 0 items; "
            f"require >= {min_repos} repos and >= {min_archetypes} archetypes."
        )
    repos: set[str] = set()
    archetypes: set[str] = set()
    for item in items:
        repo = _item_repo(item)
        if repo:
            repos.add(repo)
        arch = _item_archetype(item)
        if arch:
            archetypes.add(arch)
    if len(repos) >= min_repos and len(archetypes) >= min_archetypes:
        return
    raise ValueError(
        f"GitHub held-out set lacks diversity: "
        f"{len(repos)} distinct repo(s) (require >= {min_repos}), "
        f"{len(archetypes)} distinct archetype(s) (require >= {min_archetypes}). "
        f"repos={sorted(repos)} archetypes={sorted(archetypes)}"
    )
