"""Build ``tests/fixtures/engine_baseline_composites.json`` from the latest
per-source eval iter folders.

Captures purely structural signals from stored ``summary.json`` payloads — no
LLM calls, no evaluator dependency. Each entry in the output is a dict the
structural-regression gate (``tests/unit/summarization_engine/
test_structural_parity.py``) loads and compares against new outputs.

Captured fields per sample:
  - source_type
  - fixture_id  (the held_out hash or the iter folder stem)
  - schema_keys (top-level keys in summary.json)
  - detailed_headings (ordered list of section headings)
  - has_core_argument_or_thesis (bool — covers both "Core Argument" and legacy "Thesis")
  - has_closing_remarks (bool)
  - sentinel_tag_present (bool — ``_schema_fallback_`` etc.)
  - brief_token_count (whitespace-split)
  - bullet_counts_per_section (list[int])
  - unterminated_bullets (count of bullets not ending in .!?)
  - tag_count
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]

ITER_ROOTS = {
    "reddit": _REPO_ROOT / "docs" / "summary_eval" / "reddit" / "iter-09",
    "newsletter": _REPO_ROOT / "docs" / "summary_eval" / "newsletter" / "iter-09",
    "youtube": _REPO_ROOT / "docs" / "summary_eval" / "youtube" / "iter-19",
    "github": _REPO_ROOT / "docs" / "summary_eval" / "github" / "iter-22",
}

FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "engine_baseline_composites.json"

_SENTINEL_TAG_RE = re.compile(r"^_[a-z][a-z0-9_]*_$")
_TERMINAL_RE = re.compile(r"[.!?\)\]\"']\s*$")


def _collect_summary_files(root: Path) -> list[Path]:
    files = list(root.rglob("summary.json"))
    return sorted(files)


def _extract_bullets(section: Any) -> list[str]:
    if not isinstance(section, dict):
        return []
    out: list[str] = []
    for bullet in section.get("bullets") or []:
        if isinstance(bullet, str):
            out.append(bullet)
    subs = section.get("sub_sections") or {}
    if isinstance(subs, dict):
        for bullets in subs.values():
            if isinstance(bullets, list):
                for bullet in bullets:
                    if isinstance(bullet, str):
                        out.append(bullet)
    return out


def _fingerprint(source_type: str, summary_path: Path) -> dict[str, Any]:
    data = json.loads(summary_path.read_text(encoding="utf-8"))

    detailed = data.get("detailed_summary") or []
    detailed_headings: list[str] = []
    bullet_counts: list[int] = []
    unterminated = 0
    has_core = False
    has_closing = False

    if isinstance(detailed, list):
        for section in detailed:
            heading = ""
            if isinstance(section, dict):
                heading = str(section.get("heading") or "")
            detailed_headings.append(heading)
            low = heading.strip().lower()
            if "core argument" in low or "thesis" in low:
                has_core = True
            if "closing" in low or "takeaway" in low or "bottom line" in low or "conclusion" in low:
                has_closing = True
            bullets = _extract_bullets(section)
            bullet_counts.append(len(bullets))
            for bullet in bullets:
                stripped = bullet.strip()
                if stripped and not _TERMINAL_RE.search(stripped):
                    unterminated += 1

    # Also inspect brief_summary for closing / core signal when the detailed
    # section list is source-shaped (e.g. newsletter issue_thesis key).
    brief = str(data.get("brief_summary") or "")
    brief_tokens = len(brief.split()) if brief else 0

    tags = data.get("tags") or []
    sentinel_present = any(
        _SENTINEL_TAG_RE.match(str(t)) for t in tags if isinstance(t, str)
    )

    fixture_id = summary_path.parent.name
    return {
        "source_type": source_type,
        "fixture_id": fixture_id,
        "summary_relpath": str(summary_path.relative_to(_REPO_ROOT)).replace("\\", "/"),
        "schema_keys": sorted(data.keys()),
        "detailed_headings": detailed_headings,
        "has_core_argument_or_thesis": has_core,
        "has_closing_remarks": has_closing,
        "sentinel_tag_present": sentinel_present,
        "brief_token_count": brief_tokens,
        "bullet_counts_per_section": bullet_counts,
        "unterminated_bullets": unterminated,
        "tag_count": len(tags) if isinstance(tags, list) else 0,
    }


def build() -> dict[str, Any]:
    out: dict[str, Any] = {"baselines": []}
    for source_type, root in ITER_ROOTS.items():
        if not root.is_dir():
            raise SystemExit(f"missing iter root: {root}")
        summary_files = _collect_summary_files(root)
        if not summary_files:
            raise SystemExit(f"no summary.json under {root}")
        for summary_path in summary_files:
            out["baselines"].append(_fingerprint(source_type, summary_path))
    out["baselines"].sort(key=lambda e: (e["source_type"], e["fixture_id"]))
    return out


def main() -> int:
    payload = build()
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {FIXTURE_PATH} ({len(payload['baselines'])} baselines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
