from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "audit_zettel_ingest_quality",
    ROOT / "ops" / "scripts" / "audit_zettel_ingest_quality.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
classify = _mod.classify
_url_variants = _mod._url_variants
_is_reserved = _mod._is_reserved
build_keep_set = _mod.build_keep_set


def _env(detailed: str, brief: str = "b") -> str:
    return json.dumps({"brief_summary": brief, "detailed_summary": detailed}, ensure_ascii=False)


def test_clean_latest_engine_well_formed() -> None:
    assert classify(_env("## Heading\n- a real bullet"), "2.0.0") == "clean"


def test_legacy_version_is_dirty() -> None:
    assert classify(_env("## Heading\n- ok"), "1.4.0") == "legacy_version"
    assert classify(_env("## Heading\n- ok"), "") == "legacy_version"
    assert classify(_env("## Heading\n- ok"), None) == "legacy_version"


def test_malformed_payloads() -> None:
    assert classify(None, "2.0.0") == "malformed"
    assert classify("", "2.0.0") == "malformed"
    assert classify("not json", "2.0.0") == "malformed"
    assert classify(json.dumps(["x"]), "2.0.0") == "malformed"


def test_markdown_leak_detected_on_latest_engine() -> None:
    assert classify(_env("Their designation is in RFC 6761. ## Availability"), "2.0.0") == "markdown_leak"


def test_degenerate_when_detailed_empty_or_equals_brief() -> None:
    assert classify(_env("", brief="only brief"), "2.0.0") == "degenerate"
    assert classify(_env("same text", brief="same text"), "2.0.0") == "degenerate"


def test_url_variants_includes_normalized_and_google_unwrapped() -> None:
    raw = "https://www.google.com/search?q=https://github.com/Psychedelic-science/awesome-psychedelic-science"
    variants = _url_variants(raw)
    assert raw in variants
    # Unwrapped inner target is in the keep set so a Zettel stored under the
    # resolved github URL is still recognised as reserved.
    assert "https://github.com/Psychedelic-science/awesome-psychedelic-science" in variants


def test_is_reserved_matches_raw_and_normalized(tmp_path) -> None:
    md = tmp_path / "kasten.md"
    md.write_text(
        "Youtube:-\n  1. [t](https://www.youtube.com/watch?v=hhjhU5MXZOo)\n",
        encoding="utf-8",
    )
    keep = build_keep_set([md])
    assert _is_reserved("https://www.youtube.com/watch?v=hhjhU5MXZOo", keep) is True
    assert _is_reserved("https://www.youtube.com/watch?v=DIFFERENT", keep) is False
    assert _is_reserved(None, keep) is False


def test_markdown_leak_is_repairable_not_purgeable() -> None:
    assert "markdown_leak" not in _mod.PURGEABLE_BUCKETS
    assert _mod.PURGEABLE_BUCKETS == {"legacy_version", "malformed", "degenerate"}
