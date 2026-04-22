"""Site-specific newsletter DOM extractors."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup


@dataclass
class StructuredNewsletter:
    site: str = "unknown"
    title: str = ""
    subtitle: str = ""
    body_text: str = ""
    cta_links: list[str] = field(default_factory=list)
    publication_identity: str = ""


def _detect_site(url: str, soup: BeautifulSoup) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "substack.com" in host:
        return "substack"
    if "beehiiv.com" in host:
        return "beehiiv"
    if "medium.com" in host or "hackernoon.com" in host:
        return "medium"
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    if og_site and "substack" in (og_site.get("content") or "").lower():
        return "substack"
    return "unknown"


def _substack(soup: BeautifulSoup) -> StructuredNewsletter:
    title_el = soup.select_one("h1.post-title, h1.pencraft")
    subtitle_el = soup.select_one("h3.subtitle, h3.pencraft")
    body_el = soup.select_one("div.body.markup, div.body, div.available-content")
    ctas = [
        anchor.get("href", "")
        for anchor in soup.select("div.post-footer a[href], a.subscribe-btn")
    ]
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    publication = (og_site.get("content") or "").strip() if og_site else ""
    return StructuredNewsletter(
        site="substack",
        title=title_el.get_text(strip=True) if title_el else "",
        subtitle=subtitle_el.get_text(strip=True) if subtitle_el else "",
        body_text=body_el.get_text(separator="\n", strip=True) if body_el else "",
        cta_links=[cta for cta in ctas if cta],
        publication_identity=publication,
    )


def _beehiiv(soup: BeautifulSoup) -> StructuredNewsletter:
    title_el = soup.select_one("h1.post-title, h1[data-testid='post-title']")
    subtitle_el = soup.select_one("h2.post-subtitle, p.post-subtitle")
    body_el = soup.select_one("article, div.post-content")
    ctas = [
        anchor.get("href", "")
        for anchor in soup.select("a.subscribe-button, a[data-cta='subscribe']")
    ]
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    publication = (og_site.get("content") or "").strip() if og_site else ""
    return StructuredNewsletter(
        site="beehiiv",
        title=title_el.get_text(strip=True) if title_el else "",
        subtitle=subtitle_el.get_text(strip=True) if subtitle_el else "",
        body_text=body_el.get_text(separator="\n", strip=True) if body_el else "",
        cta_links=[cta for cta in ctas if cta],
        publication_identity=publication,
    )


def _medium(soup: BeautifulSoup) -> StructuredNewsletter:
    title_el = soup.select_one("h1, h1[data-testid='storyTitle']")
    subtitle_el = soup.select_one("h2, h3.graf--subtitle")
    body_el = soup.select_one("article, section[data-field='body']")
    ctas = [
        anchor.get("href", "")
        for anchor in soup.select("a.button--large, a[data-action='subscribe']")
    ]
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    publication = (og_site.get("content") or "").strip() if og_site else ""
    return StructuredNewsletter(
        site="medium",
        title=title_el.get_text(strip=True) if title_el else "",
        subtitle=subtitle_el.get_text(strip=True) if subtitle_el else "",
        body_text=body_el.get_text(separator="\n", strip=True) if body_el else "",
        cta_links=[cta for cta in ctas if cta],
        publication_identity=publication,
    )


_EXTRACTORS = {
    "substack": _substack,
    "beehiiv": _beehiiv,
    "medium": _medium,
}


def extract_structured(html: str, *, url: str) -> StructuredNewsletter:
    soup = BeautifulSoup(html, "html.parser")
    site = _detect_site(url, soup)
    if site in _EXTRACTORS:
        result = _EXTRACTORS[site](soup)
        if result.title:
            return result
    return StructuredNewsletter(site="unknown")
