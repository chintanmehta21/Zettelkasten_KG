"""Download 30 DiceBear SVG avatars for user profile pictures.

Run once: python ops/scripts/generate_avatars.py
"""

import os
import urllib.request

STYLES = [
    "adventurer", "bottts", "fun-emoji", "notionists",
    "thumbs", "big-ears", "lorelei",
]
COUNT = 30
OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "website", "artifacts", "avatars"
)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for i in range(COUNT):
        style = STYLES[i % len(STYLES)]
        seed = f"zettel_avatar_{i}"
        url = f"https://api.dicebear.com/9.x/{style}/svg?seed={seed}"
        out_path = os.path.join(OUTPUT_DIR, f"avatar_{i:02d}.svg")
        print(f"[{i+1}/{COUNT}] {style} -> avatar_{i:02d}.svg")
        urllib.request.urlretrieve(url, out_path)
    print(f"Done. {COUNT} avatars saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
