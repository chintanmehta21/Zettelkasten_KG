"""Newsletter CTA link extractor."""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


_BOILERPLATE = {
    "unsubscribe",
    "manage subscription",
    "update preferences",
    "view in browser",
}


@dataclass
class CTA:
    text: str
    href: str


def extract_ctas(html: str, *, keyword_regex: str, max_count: int) -> list[CTA]:
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(keyword_regex, re.IGNORECASE)
    found: list[CTA] = []

    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        if not text:
            continue
        if any(marker in text.lower() for marker in _BOILERPLATE):
            continue
        if not pattern.search(text):
            continue
        found.append(CTA(text=text, href=anchor["href"]))
        if len(found) >= max_count:
            break
    return found
