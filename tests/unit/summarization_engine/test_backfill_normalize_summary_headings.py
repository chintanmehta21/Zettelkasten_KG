from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "backfill_normalize_summary_headings",
    ROOT / "ops" / "scripts" / "backfill_normalize_summary_headings.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_normalize_payload = _mod._normalize_payload


def test_json_envelope_inline_heading_is_split_shape_preserved() -> None:
    raw = json.dumps(
        {
            "brief_summary": "A one liner.",
            "detailed_summary": "Their designation is in RFC 6761. ## Availability ###",
        },
        ensure_ascii=False,
    )

    out = json.loads(_normalize_payload(raw))

    assert out["brief_summary"] == "A one liner."
    assert out["detailed_summary"] == "Their designation is in RFC 6761.\n\n## Availability"


def test_unbalanced_backtick_row_is_repaired() -> None:
    raw = json.dumps(
        {"brief_summary": "", "detailed_summary": "'.join(items)}\"`). ### Comments"},
        ensure_ascii=False,
    )

    out = json.loads(_normalize_payload(raw))

    assert out["detailed_summary"] == "'.join(items)}\"`).\n\n### Comments"


def test_idempotent_clean_row_unchanged_byte_identical() -> None:
    clean = json.dumps(
        {"brief_summary": "Clean.", "detailed_summary": "## Heading\n- a bullet"},
        ensure_ascii=False,
    )

    assert _normalize_payload(clean) == clean
    assert _normalize_payload(_normalize_payload(clean)) == clean


def test_bare_string_legacy_row_preserved_as_string() -> None:
    out = _normalize_payload("Format and speakers ## Chapter walkthrough")

    assert out == "Format and speakers\n\n## Chapter walkthrough"


def test_unparseable_or_unexpected_shape_returned_unchanged() -> None:
    assert _normalize_payload("[1, 2, 3]") == "[1, 2, 3]"
