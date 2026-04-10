"""Shared helpers for source ingestors."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import SourceType

DEFAULT_TIMEOUT = 20.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compact_text(value: str, *, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "..."
    return text


def join_sections(sections: dict[str, str]) -> str:
    blocks = []
    for heading, text in sections.items():
        cleaned = compact_text(text)
        if cleaned:
            blocks.append(f"{heading}\n{cleaned}")
    return "\n\n".join(blocks)


async def fetch_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text, str(response.url)


async def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[Any, str]:
    text, final_url = await fetch_text(url, headers=headers, timeout=timeout)
    return json.loads(text), final_url


def extract_html_text(html: str) -> tuple[str, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    extracted = ""
    try:
        import trafilatura

        extracted = trafilatura.extract(html) or ""
    except Exception:
        extracted = ""

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        metadata["title"] = title

    for name in ("description", "og:description", "twitter:description"):
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", property=name)
        if tag and tag.get("content"):
            metadata[name.replace(":", "_")] = compact_text(tag["content"])

    if not extracted:
        for bad in soup(["script", "style", "noscript", "svg"]):
            bad.decompose()
        extracted = soup.get_text("\n", strip=True)

    return compact_text(extracted), metadata


def json_ld_objects(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
        elif isinstance(payload, list):
            out.extend(item for item in payload if isinstance(item, dict))
    return out


def raise_extraction(message: str, source_type: SourceType, reason: str = "") -> None:
    raise ExtractionError(message, source_type=source_type.value, reason=reason)


def query_param(url: str, key: str) -> str | None:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get(key)
    return values[0] if values else None
