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

# Cardinality guard: at most this many pseudo-tags regardless of input. Three
# rule families, one tag each, so 3 is the natural ceiling; the explicit cap
# protects the D-KG-1 tag signal if a future rule family is added.
_MAX_PSEUDO_TAGS = 3

# Phase 4 / Task 4.4 (X7): replaced the hand-rolled `_MULTI_PART_SUFFIXES`
# dict with the canonical Public Suffix List via `tldextract`. The PSL
# snapshot is bundled in the tldextract wheel; `suffix_list_urls=()` blocks
# any runtime network fetch (no async DNS, no I/O on first call), so the
# import and first invocation are both fully offline. The
# `cache_dir="/tmp/tldextract"` lets multiple processes share the parsed
# tree via COW after the lifespan-pre-warm in app.py.
import tldextract  # noqa: E402

_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir="/tmp/tldextract")

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
    """X7 (Phase 4 / Task 4.4): registrable domain via the Public Suffix List.

    Replaces the hand-rolled `_MULTI_PART_SUFFIXES` heuristic with tldextract's
    canonical PSL. Correct for every multi-label TLD (`.co.uk`, `.gov.in`,
    `.com.au`, etc.) without an explicit allow-list, and resilient to new
    public suffixes added to the PSL (tldextract ships a snapshot per release).

    Returns None for bare hostnames, IPs, or empty input — preserves the
    prior contract so callers don't have to change their None-checks.
    """
    if not url:
        return None
    try:
        result = _extract(url.strip())
    except Exception:
        return None
    return result.registered_domain or None


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
