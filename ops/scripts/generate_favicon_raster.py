"""Rasterize the brand favicon SVG to PNG/ICO for SERP + legacy favicon support.

Faithful raster of ``website/static/favicon.svg`` (NO new design) via headless
Chromium (Playwright, for correct SVG path rendering) + Pillow for downscale and
.ico packaging. Outputs:
  website/artifacts/zettelkasten-logo-512.png  square logo for Organization JSON-LD
  website/artifacts/favicon-48.png             rel=icon raster for Google SERP
  website/static/favicon.ico                   multi-size 16/32/48 for /favicon.ico + legacy

Run: python ops/scripts/generate_favicon_raster.py
(One-off; commit the generated assets. Requires `playwright install chromium`.)
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "website" / "static" / "favicon.svg"
ART = ROOT / "website" / "artifacts"
STATIC = ROOT / "website" / "static"


def render_master(size: int = 512) -> Image.Image:
    """Render the SVG faithfully at ``size``x``size`` on a transparent canvas."""
    svg = SVG.read_text(encoding="utf-8")
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>*{margin:0;padding:0}html,body{background:transparent}"
        f"svg{{width:{size}px;height:{size}px;display:block}}</style></head>"
        f"<body>{svg}</body></html>"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=2)
        page.set_content(html, wait_until="networkidle")
        png = page.screenshot(omit_background=True)
        browser.close()
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> None:
    master = render_master(512)  # device_scale_factor=2 → 1024px actual, crisp
    ART.mkdir(parents=True, exist_ok=True)

    master.resize((512, 512), Image.LANCZOS).save(ART / "zettelkasten-logo-512.png", "PNG")
    master.resize((48, 48), Image.LANCZOS).save(ART / "favicon-48.png", "PNG")
    master.save(STATIC / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    print(f"wrote {ART / 'zettelkasten-logo-512.png'}")
    print(f"wrote {ART / 'favicon-48.png'}")
    print(f"wrote {STATIC / 'favicon.ico'}")


if __name__ == "__main__":
    main()
