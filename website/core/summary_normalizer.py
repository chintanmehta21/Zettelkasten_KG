"""Airtight summary normalization at the API boundary.

The zettel modal reads ``node.summary`` and expects a predictable shape. Over
the life of this project three writer paths have landed rows in
``kg_nodes.summary`` with four different shapes:

1. Canonical JSON envelope with ``detailed_summary`` as a list of structured
   sections (``[{heading, bullets, sub_sections}, ...]``) — the post-fix
   shape from ``website.core.persist`` and the new ``SupabaseWriter``.
2. Canonical envelope but ``detailed_summary`` is a **source-shaped dict**
   (e.g. newsletter ``{publication_identity, issue_thesis, sections, ...}``
   or youtube ``{thesis, format, chapters_or_segments, closing_takeaway}``).
3. Canonical envelope but ``detailed_summary`` is a **markdown string**
   with raw schema-key headings (``## thesis`` / ``## chapters_or_segments``)
   and chapter bullets serialized as ``{"timestamp": "...", "title": "...",
   "bullets": [...]}`` JSON strings.
4. A plain string that isn't JSON at all (legacy pre-envelope rows).

Rather than teaching every frontend renderer to defend against all four, we
normalize once — server-side — so the wire always carries shape (1).

This module exposes ``normalize_summary_for_wire(raw, source_type)`` which
returns the envelope's canonical JSON string back, plus
``normalize_graph_nodes(graph_dict)`` which mutates every node in place.

No LLM calls. Pure dict/string transforms. Idempotent — running it twice on
a canonical row is a no-op.
"""
from __future__ import annotations

import json
import re
from typing import Any


# Raw pipeline schema keys → human-facing labels rendered in the zettel modal.
_RAW_HEADING_MAP: dict[str, str] = {
    "thesis": "Core argument",
    "core_argument": "Core argument",
    "issue_thesis": "Core argument",
    "overview": "Overview",
    "format": "Format",
    "format_and_speakers": "Format and speakers",
    "chapters_or_segments": "Chapter walkthrough",
    "chapter_walkthrough": "Chapter walkthrough",
    "demonstrations": "Demonstrations",
    "closing_takeaway": "Closing remarks",
    "closing_remarks": "Closing remarks",
    "publication_identity": "Publication identity",
    "sections": "Sections",
    "conclusions_or_recommendations": "Conclusions & recommendations",
    "cta": "Call to action",
    "stance": "Stance",
    "op_thesis": "OP thesis",
    "dissent_cluster": "Dissent",
    "agreement_cluster": "Agreement",
}

_TIMESTAMP_PATTERNS = [
    re.compile(r"^\s*\[?\d{1,2}(?::\d{2}){1,2}\]?\s*[—\-:]\s*"),
    re.compile(r"^\s*\[?\d{1,2}(?::\d{2}){1,2}\]?\s+"),
    re.compile(r"^\s*\d{4}\s*[—\-]\s*"),  # "1852 — Title"
]

_DROP_HEADING_LOWER = {
    "format",              # surfaced as a bullet, never a section
    "moderation context",  # internal ingest signal — users don't need to see it
    "moderation_context",
}


def _pretty_heading(raw: str | None) -> str:
    if not raw:
        return ""
    key = str(raw).strip().lower()
    if key in _RAW_HEADING_MAP:
        return _RAW_HEADING_MAP[key]
    return re.sub(r"_+", " ", str(raw)).strip().capitalize()


def _strip_timestamp(label: str | None) -> str:
    if not label:
        return ""
    out = str(label)
    for pat in _TIMESTAMP_PATTERNS:
        out = pat.sub("", out)
    return out.strip()


def _expand_json_string_bullets(section: dict[str, Any]) -> dict[str, Any]:
    """Chapter bullets sometimes arrive as JSON strings of
    ``{"timestamp": "...", "title": "...", "bullets": [...]}``. Expand each
    into a proper sub-section so the renderer never shows a JSON blob.
    """
    bullets = section.get("bullets") or []
    if not bullets:
        return section
    subs: dict[str, list[str]] = {}
    leftover: list[str] = []
    for b in bullets:
        if not isinstance(b, str):
            leftover.append(str(b))
            continue
        t = b.strip()
        if not t.startswith("{"):
            leftover.append(b)
            continue
        try:
            parsed = json.loads(t)
        except Exception:
            leftover.append(b)
            continue
        if not isinstance(parsed, dict):
            leftover.append(b)
            continue
        title = _strip_timestamp(str(parsed.get("title") or "").strip())
        if not title:
            leftover.append(b)
            continue
        nested_bullets = parsed.get("bullets") or []
        if not isinstance(nested_bullets, list):
            nested_bullets = [str(nested_bullets)]
        sub_list = [str(x).strip() for x in nested_bullets if str(x).strip()]
        if not sub_list and parsed.get("summary"):
            sub_list = [str(parsed["summary"]).strip()]
        key, idx = title, 2
        while key in subs:
            key = f"{title} ({idx})"
            idx += 1
        subs[key] = sub_list
    if not subs:
        return section
    merged: dict[str, list[str]] = {}
    existing = section.get("sub_sections") or {}
    if isinstance(existing, dict):
        for k, v in existing.items():
            merged[str(k)] = list(v) if isinstance(v, list) else [str(v)]
    for k, v in subs.items():
        merged[k] = v
    return {
        "heading": section.get("heading"),
        "bullets": leftover,
        "sub_sections": merged,
    }


def _normalize_section(section: dict[str, Any]) -> dict[str, Any] | None:
    """One pipeline-shape section → one pretty section. Returns None to drop."""
    if not isinstance(section, dict):
        return None
    raw_heading = str(section.get("heading") or "").strip()
    if raw_heading.lower() in _DROP_HEADING_LOWER:
        return None
    section = _expand_json_string_bullets(section)
    pretty_subs: dict[str, list[str]] = {}
    subs = section.get("sub_sections") or {}
    if isinstance(subs, dict):
        for k, v in subs.items():
            if not isinstance(v, list):
                v = [str(v)]
            cleaned_key = _strip_timestamp(_pretty_heading(k)) or str(k)
            pretty_subs[cleaned_key] = [str(x).strip() for x in v if str(x).strip()]
    bullets = section.get("bullets") or []
    if not isinstance(bullets, list):
        bullets = [str(bullets)]
    bullets = [str(x).strip() for x in bullets if str(x).strip()]
    pretty_heading = _strip_timestamp(raw_heading) or raw_heading
    pretty_heading = _pretty_heading(pretty_heading) or pretty_heading
    return {
        "heading": pretty_heading,
        "bullets": bullets,
        "sub_sections": pretty_subs,
    }


def _from_list(detailed: list) -> list[dict[str, Any]]:
    """Canonical list shape — just normalize each section."""
    out: list[dict[str, Any]] = []
    for s in detailed:
        ns = _normalize_section(s) if isinstance(s, dict) else None
        if ns is not None:
            out.append(ns)
    return out


def _from_newsletter_dict(d: dict[str, Any]) -> list[dict[str, Any]]:
    """Newsletter detailed_summary dict → structured sections.

    Newsletter shape: ``{publication_identity, issue_thesis, sections, stance,
    conclusions_or_recommendations, cta}``. We emit:
      * Overview section with publication + thesis as sub-sections
      * One section per entry in ``sections``
      * Conclusions section when recommendations exist
    """
    out: list[dict[str, Any]] = []
    overview_subs: dict[str, list[str]] = {}
    if d.get("publication_identity"):
        overview_subs["Publication"] = [str(d["publication_identity"]).strip()]
    if d.get("issue_thesis"):
        overview_subs["Core argument"] = [str(d["issue_thesis"]).strip()]
    if overview_subs:
        out.append({"heading": "Overview", "bullets": [], "sub_sections": overview_subs})
    for s in d.get("sections") or []:
        if not isinstance(s, dict):
            continue
        ns = _normalize_section(s)
        if ns:
            out.append(ns)
    recs = d.get("conclusions_or_recommendations") or []
    if recs and isinstance(recs, list):
        out.append({
            "heading": "Conclusions & recommendations",
            "bullets": [str(r).strip() for r in recs if str(r).strip()],
            "sub_sections": {},
        })
    if d.get("cta") and isinstance(d.get("cta"), str):
        out.append({"heading": "Call to action", "bullets": [d["cta"].strip()], "sub_sections": {}})
    return out


def _from_youtube_dict(d: dict[str, Any]) -> list[dict[str, Any]]:
    """YouTube detailed_summary dict → structured sections.

    Shape: ``{thesis, format, chapters_or_segments: [{timestamp, title,
    bullets}], demonstrations, closing_takeaway}``. Timestamps are dropped
    per product decision.
    """
    out: list[dict[str, Any]] = []
    overview_subs: dict[str, list[str]] = {}
    if d.get("thesis"):
        overview_subs["Core argument"] = [str(d["thesis"]).strip()]
    if overview_subs:
        out.append({"heading": "Overview", "bullets": [], "sub_sections": overview_subs})
    chapter_subs: dict[str, list[str]] = {}
    for chap in d.get("chapters_or_segments") or []:
        if not isinstance(chap, dict):
            continue
        title = _strip_timestamp(str(chap.get("title") or "").strip())
        if not title:
            continue
        bullets = chap.get("bullets") or []
        if not isinstance(bullets, list):
            bullets = [str(bullets)]
        clean = [str(b).strip() for b in bullets if str(b).strip()]
        key, idx = title, 2
        while key in chapter_subs:
            key = f"{title} ({idx})"
            idx += 1
        chapter_subs[key] = clean
    if chapter_subs:
        out.append({"heading": "Chapter walkthrough", "bullets": [], "sub_sections": chapter_subs})
    demos = d.get("demonstrations") or []
    if demos:
        out.append({
            "heading": "Demonstrations",
            "bullets": [str(x).strip() for x in demos if str(x).strip()],
            "sub_sections": {},
        })
    if d.get("closing_takeaway"):
        takeaway = str(d["closing_takeaway"]).strip()
        bullet = takeaway if takeaway.lower().startswith("recap") else f"Recap: {takeaway}"
        out.append({"heading": "Closing remarks", "bullets": [bullet], "sub_sections": {}})
    return out


def _from_generic_dict(d: dict[str, Any]) -> list[dict[str, Any]]:
    """Unknown dict shape — convert each top-level key into a section."""
    out: list[dict[str, Any]] = []
    for k, v in d.items():
        if v is None:
            continue
        heading = _pretty_heading(k)
        if isinstance(v, str):
            out.append({"heading": heading, "bullets": [v.strip()], "sub_sections": {}})
        elif isinstance(v, list):
            bullets: list[str] = []
            subs: dict[str, list[str]] = {}
            for item in v:
                if isinstance(item, str):
                    bullets.append(item.strip())
                elif isinstance(item, dict):
                    ns = _normalize_section(item)
                    if ns:
                        subs[ns["heading"] or f"Item {len(subs)+1}"] = ns["bullets"]
            section: dict[str, Any] = {"heading": heading, "bullets": bullets, "sub_sections": subs}
            out.append(section)
        elif isinstance(v, dict):
            nested = _from_generic_dict(v)
            if nested:
                # Fold children into sub_sections so we don't explode the outline
                subs = {n["heading"] or "—": n["bullets"] for n in nested}
                out.append({"heading": heading, "bullets": [], "sub_sections": subs})
        else:
            out.append({"heading": heading, "bullets": [str(v)], "sub_sections": {}})
    return out


def _from_markdown(md: str) -> list[dict[str, Any]]:
    """Parse ``## heading`` / ``### sub`` / ``- bullet`` markdown into sections."""
    lines = md.split("\n")
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    sub_heading: str | None = None

    def ensure() -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = {"heading": "Overview", "bullets": [], "sub_sections": {}}
            sections.append(current)
        return current

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        m2 = re.match(r"^##\s+(.*)$", line)
        m3 = re.match(r"^###\s+(.*)$", line)
        mb = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m2:
            current = {"heading": m2.group(1).strip(), "bullets": [], "sub_sections": {}}
            sections.append(current)
            sub_heading = None
            continue
        if m3:
            sub_heading = m3.group(1).strip()
            ensure()
            continue
        sec = ensure()
        text = mb.group(1).strip() if mb else line.strip()
        if sub_heading is not None:
            sec["sub_sections"].setdefault(sub_heading, []).append(text)
        else:
            sec["bullets"].append(text)
    # Normalize each section (heading remap, timestamp strip, JSON-bullet expand)
    normalized: list[dict[str, Any]] = []
    for s in sections:
        ns = _normalize_section(s)
        if ns is not None:
            normalized.append(ns)
    return normalized


def _detect_detailed_shape(detailed: Any) -> str:
    if isinstance(detailed, list):
        return "list"
    if isinstance(detailed, dict):
        keys = set(detailed.keys())
        if {"publication_identity", "issue_thesis"} & keys:
            return "newsletter_dict"
        if {"thesis", "chapters_or_segments"} & keys or {"thesis", "format"} & keys:
            return "youtube_dict"
        return "generic_dict"
    if isinstance(detailed, str):
        trimmed = detailed.strip()
        if trimmed.startswith("[") or trimmed.startswith("{"):
            try:
                parsed = json.loads(trimmed)
                # Recurse into the parsed value
                return f"json_{_detect_detailed_shape(parsed)}"
            except Exception:
                pass
        if "## " in trimmed or "### " in trimmed:
            return "markdown"
        return "plain_string"
    return "unknown"


def _normalize_detailed(detailed: Any) -> list[dict[str, Any]]:
    shape = _detect_detailed_shape(detailed)
    if shape == "list":
        return _from_list(detailed)
    if shape == "newsletter_dict":
        return _from_newsletter_dict(detailed)
    if shape == "youtube_dict":
        return _from_youtube_dict(detailed)
    if shape == "generic_dict":
        return _from_generic_dict(detailed)
    if shape == "markdown":
        return _from_markdown(detailed)
    if shape.startswith("json_"):
        # detailed is a JSON string of a known shape — parse and recurse
        try:
            parsed = json.loads(detailed.strip())
            return _normalize_detailed(parsed)
        except Exception:
            return []
    return []


def normalize_summary_for_wire(raw: Any, source_type: str | None = None) -> str:
    """Return the canonical JSON envelope string for ``raw``.

    Input can be any historical shape (string, dict, JSON-in-string). Output
    is a JSON string with keys ``mini_title``, ``brief_summary``,
    ``detailed_summary`` (always a list of structured sections),
    ``closing_remarks``. Safe to run on already-canonical rows.
    """
    del source_type  # reserved for future per-source wording tweaks
    envelope: dict[str, Any] = {
        "mini_title": "",
        "brief_summary": "",
        "detailed_summary": [],
        "closing_remarks": "",
    }
    if raw is None:
        return json.dumps(envelope, ensure_ascii=False)
    # Attempt to parse an envelope from ``raw``
    source: dict[str, Any] | None = None
    if isinstance(raw, dict):
        source = raw
    elif isinstance(raw, str):
        trimmed = raw.strip()
        if trimmed.startswith("{"):
            try:
                parsed = json.loads(trimmed)
                if isinstance(parsed, dict):
                    source = parsed
            except Exception:
                source = None
        if source is None:
            # Legacy plain-text brief — no detailed content available
            envelope["brief_summary"] = raw.strip()
            return json.dumps(envelope, ensure_ascii=False)
    else:
        envelope["brief_summary"] = str(raw)
        return json.dumps(envelope, ensure_ascii=False)

    envelope["mini_title"] = str(source.get("mini_title") or "").strip()
    envelope["brief_summary"] = str(source.get("brief_summary") or source.get("summary") or "").strip()
    envelope["closing_remarks"] = str(source.get("closing_remarks") or source.get("closing_takeaway") or "").strip()
    detailed_raw = source.get("detailed_summary")
    envelope["detailed_summary"] = _normalize_detailed(detailed_raw) if detailed_raw is not None else []
    return json.dumps(envelope, ensure_ascii=False)


def normalize_graph_nodes(graph_dict: dict[str, Any]) -> dict[str, Any]:
    """Mutate each node's ``summary`` to the canonical envelope string."""
    for node in graph_dict.get("nodes") or []:
        raw = node.get("summary")
        source_type = node.get("source_type")
        try:
            node["summary"] = normalize_summary_for_wire(raw, source_type)
        except Exception:
            # Never fail graph fetch because of one bad row — keep raw form
            continue
    return graph_dict
