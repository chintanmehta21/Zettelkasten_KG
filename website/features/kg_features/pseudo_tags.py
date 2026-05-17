"""Phase B P2-2 — conservative pseudo-tag derivation.

Derives a SMALL, HIGH-CONFIDENCE-ONLY set of pseudo-tags from structured
zettel metadata. These AUGMENT the user/auto tag set fed to the D-KG-1 tag
(Jaccard) signal in the KG-population hook — they never override or replace
user tags, and are intentionally low-cardinality so a single noisy domain
or modality cannot dominate the Jaccard overlap.

Rules (each emits at most one tag; absent/ambiguous signal → emit nothing):

* ``source_domain:<registrable-domain>`` — the registrable domain of the
  zettel URL (eTLD+1, e.g. ``youtube.com``, ``arxiv.org``). Deep path
  fragments / subdomains are deliberately discarded to bound cardinality:
  one tag per *site*, never per page.
* ``modality:<video|article|book|post>`` — coarse content modality mapped
  from the ``source_type`` enum only (never inferred from free text).
* ``speaker:<slug>`` — ONLY when a reliable EXPLICIT author/channel signal
  exists in structured metadata (e.g. a YouTube ``channel`` /
  ``channel_name`` / ``author`` field). Never guessed from title/summary
  prose. Slugged + length-bounded so it stays a single low-cardinality tag.

The whole result is hard-capped at ``_MAX_PSEUDO_TAGS`` so a pathological
metadata blob can never inflate the tag signal.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Cardinality guard: at most this many pseudo-tags regardless of input. Three
# rule families, one tag each, so 3 is the natural ceiling; the explicit cap
# protects the D-KG-1 tag signal if a future rule family is added.
_MAX_PSEUDO_TAGS = 3

# Multi-part public suffixes we care about (keeps eTLD+1 correct for the
# common academic/code/news hosts this corpus sees). Anything not listed
# falls back to the last-two-labels heuristic, which is correct for the
# overwhelming majority of single-label TLDs (.com/.org/.io/.dev/...).
_MULTI_PART_SUFFIXES = {
    "co.uk",
    "co.in",
    "com.au",
    "ac.uk",
    "org.uk",
    "gov.uk",
    "co.jp",
}

# source_type enum value -> coarse modality. Unknown/empty -> no modality tag.
_MODALITY_BY_SOURCE_TYPE = {
    "youtube": "video",
    "video": "video",
    "github": "article",
    "newsletter": "article",
    "substack": "article",
    "web": "article",
    "article": "article",
    "reddit": "post",
    "tweet": "post",
    "twitter": "post",
    "book": "book",
    "pdf": "book",
}

# Structured metadata keys that carry an EXPLICIT, reliable speaker/author
# identity. Free-text fields (title, description, summary) are intentionally
# excluded — a speaker is only emitted from one of these.
_SPEAKER_KEYS = (
    "channel_id",
    "channel",
    "channel_name",
    "uploader",
    "author",
    "podcast_author",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _registrable_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = [p for p in host.split(".") if p]
    if len(labels) < 2:
        # bare hostname / localhost / IP-ish — not a registrable domain.
        return None
    last_two = ".".join(labels[-2:])
    last_three = ".".join(labels[-3:]) if len(labels) >= 3 else None
    if last_two in _MULTI_PART_SUFFIXES and last_three:
        return last_three
    return last_two


def _slug(value: str, *, max_len: int = 48) -> str:
    s = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return s[:max_len].strip("-")


def _speaker_tag(metadata: dict | None, source_type: str) -> str | None:
    """Emit ``speaker:<slug>`` only from an explicit structured signal.

    Conservative: requires a non-empty value in one of ``_SPEAKER_KEYS``.
    No NLP, no title parsing — absence yields no tag (never a guess).
    """
    if not isinstance(metadata, dict):
        return None
    for key in _SPEAKER_KEYS:
        raw = metadata.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        slug = _slug(text)
        if slug:
            return f"speaker:{slug}"
    return None


def derive_pseudo_tags(
    *,
    url: str | None,
    source_type: str | None,
    metadata: dict | None = None,
) -> list[str]:
    """Return a deduplicated, cardinality-bounded list of pseudo-tags.

    Pure function: no DB / network / global state. Safe to call on every
    ingest. Never raises on malformed input — a bad URL or metadata blob
    simply yields fewer (or zero) tags.
    """
    tags: list[str] = []

    domain = _registrable_domain(url)
    if domain:
        tags.append(f"source_domain:{domain}")

    st = (source_type or "").strip().lower()
    modality = _MODALITY_BY_SOURCE_TYPE.get(st)
    if modality:
        tags.append(f"modality:{modality}")

    speaker = _speaker_tag(metadata, st)
    if speaker:
        tags.append(speaker)

    # Dedup while preserving order, then hard-cap cardinality.
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= _MAX_PSEUDO_TAGS:
            break
    return out
