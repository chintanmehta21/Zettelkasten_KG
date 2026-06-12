"""Generate the social-share (Open Graph / Twitter card) image.

One-off, reproducible. Outputs a 1200x630 PNG to website/artifacts/og-cover.png,
served at https://zettelkasten.in/artifacts/og-cover.png. Brand: teal on near-black
(matches --teal #14b8a6 / --bg #0a0b14), with a faint knowledge-graph motif.

Run:  python ops/scripts/generate_og_image.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = (10, 11, 20)        # #0a0b14
TEAL = (20, 184, 166)    # #14b8a6
WHITE = (230, 237, 243)  # #e6edf3
MUTED = (154, 166, 182)  # #9aa6b6


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    bold_paths = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    reg_paths = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in (bold_paths if bold else reg_paths):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")

    # Faint knowledge-graph motif on the right.
    nodes = [(870, 150), (1010, 110), (1085, 245), (945, 300),
             (1055, 405), (905, 470), (1125, 520)]
    edges = [(0, 1), (0, 3), (1, 2), (2, 4), (3, 4), (3, 5), (4, 6), (5, 6), (2, 6)]
    for a, b in edges:
        draw.line([nodes[a], nodes[b]], fill=(*TEAL, 55), width=2)
    for i, (x, y) in enumerate(nodes):
        r = 16 if i % 3 == 0 else 10
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(*TEAL, 85), outline=(*TEAL, 180), width=2)

    # Left accent bar.
    draw.rectangle([0, 0, 10, H], fill=TEAL)

    pad = 90
    # Eyebrow (teal dot + label).
    draw.ellipse([pad, 214, pad + 16, 230], fill=TEAL)
    draw.text((pad + 30, 206), "AI NOTES  ·  KNOWLEDGE GRAPH", font=load_font(30, bold=True), fill=TEAL)
    # Wordmark.
    draw.text((pad - 2, 248), "Zettelkasten", font=load_font(120, bold=True), fill=WHITE)
    # Tagline.
    draw.text((pad + 2, 402), "The second brain you were promised.", font=load_font(46), fill=MUTED)
    # Accent rule.
    draw.rectangle([pad + 2, 474, pad + 202, 480], fill=TEAL)
    # Domain.
    draw.text((pad + 2, 548), "zettelkasten.in", font=load_font(30), fill=MUTED)

    out = Path(__file__).resolve().parents[2] / "website" / "artifacts" / "og-cover.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"wrote {out} {img.size}")


if __name__ == "__main__":
    main()
