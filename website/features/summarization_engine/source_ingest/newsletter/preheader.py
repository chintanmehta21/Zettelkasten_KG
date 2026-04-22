"""Newsletter preheader extractor."""
from __future__ import annotations

from bs4 import BeautifulSoup


def extract_preheader(html: str, *, fallback_chars: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        ("meta", {"name": "preheader"}),
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "description"}),
    ):
        element = soup.find(*selector)
        content = (element.get("content") or "").strip() if element else ""
        if content:
            return content[:fallback_chars]

    body = soup.find("body")
    if not body:
        return ""

    text = body.get_text(separator=" ", strip=True)
    if len(text) <= fallback_chars:
        return text
    trimmed = text[:fallback_chars].rsplit(" ", 1)[0]
    return trimmed or text[:fallback_chars]
