from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "purge_dirty_zettels", ROOT / "ops" / "scripts" / "purge_dirty_zettels.py"
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_derive_candidates = _mod._derive_candidates


def _env(detailed: str, brief: str = "b") -> str:
    return json.dumps({"brief_summary": brief, "detailed_summary": detailed}, ensure_ascii=False)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_a, **_k):
        return None

    def fetchall(self):
        return self._rows


def _row(rid, ai, ev, url):
    now = dt.datetime(2026, 5, 18, tzinfo=dt.timezone.utc)
    return (rid, "ws", "canon", ai, ev, "website", now, url)


def test_derive_only_purges_unrecoverable_and_spares_reserved() -> None:
    rows = [
        _row("clean1", _env("## H\n- ok"), "", "https://example.com/clean"),
        _row("empty1", None, "", "https://example.com/empty"),  # malformed
        _row("degen1", _env("x", brief="x"), "", "https://example.com/degen"),  # degenerate
        _row("leak1", _env("text. ## Leaked"), "", "https://example.com/leak"),  # markdown_leak -> spared
        _row("legacy1", _env("## H\n- ok"), "legacy-v1-backfill", "https://e.com/legacy"),
        _row("reserved1", None, "", "https://www.youtube.com/watch?v=KEEPME"),  # reserved -> spared
    ]
    keep = {"https://www.youtube.com/watch?v=KEEPME"}

    out = _derive_candidates(_FakeCursor(rows), keep)
    ids = {c["id"] for c in out}

    assert ids == {"empty1", "degen1", "legacy1"}
    assert "clean1" not in ids  # clean kept
    assert "leak1" not in ids  # repairable, never purged
    assert "reserved1" not in ids  # concurrent-PR, always kept
    assert all(c["bucket"] in {"malformed", "degenerate", "legacy_version"} for c in out)
