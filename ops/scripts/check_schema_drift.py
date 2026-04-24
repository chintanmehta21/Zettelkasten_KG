"""Structured-payload schema drift detector.

Compares the live pydantic ``model_json_schema()`` output for the four per-source
structured payloads against baseline JSON snapshots committed under
``ops/snapshots/``. Exits non-zero on any drift so CI fails fast instead of
shipping a silent prompt-layer regression.

Usage:
    python ops/scripts/check_schema_drift.py             # verify
    python ops/scripts/check_schema_drift.py --update    # rewrite snapshots

The ``--update`` flag is the ONLY supported way to mutate snapshots. Any drift
detected without ``--update`` is treated as a regression.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Ensure the repo root is importable when this script is invoked directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from website.features.summarization_engine.summarization.github.schema import (  # noqa: E402
    GitHubStructuredPayload,
)
from website.features.summarization_engine.summarization.newsletter.schema import (  # noqa: E402
    NewsletterStructuredPayload,
)
from website.features.summarization_engine.summarization.reddit.schema import (  # noqa: E402
    RedditStructuredPayload,
)
from website.features.summarization_engine.summarization.youtube.schema import (  # noqa: E402
    YouTubeStructuredPayload,
)


@dataclass(frozen=True)
class SchemaEntry:
    name: str
    payload: type


SCHEMAS: tuple[SchemaEntry, ...] = (
    SchemaEntry("newsletter", NewsletterStructuredPayload),
    SchemaEntry("youtube", YouTubeStructuredPayload),
    SchemaEntry("reddit", RedditStructuredPayload),
    SchemaEntry("github", GitHubStructuredPayload),
)


def snapshot_path(entry: SchemaEntry) -> Path:
    return _REPO_ROOT / "ops" / "snapshots" / f"{entry.name}_schema.json"


def live_schema(entry: SchemaEntry) -> dict[str, Any]:
    """Return the live pydantic schema as a plain JSON-round-tripped dict.

    The round-trip normalizes ordering and type handling so the comparison
    only catches semantic drift, never pydantic-internal representation
    differences.
    """
    raw = entry.payload.model_json_schema()
    return json.loads(json.dumps(raw, sort_keys=True))


def load_snapshot(entry: SchemaEntry) -> dict[str, Any] | None:
    path = snapshot_path(entry)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"snapshot {path} is not valid JSON: {exc}")


def write_snapshot(entry: SchemaEntry, schema: dict[str, Any]) -> None:
    path = snapshot_path(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def detect_drift() -> list[str]:
    """Return a list of human-readable drift descriptions. Empty => clean."""
    drifts: list[str] = []
    for entry in SCHEMAS:
        live = live_schema(entry)
        stored = load_snapshot(entry)
        if stored is None:
            drifts.append(
                f"{entry.name}: missing snapshot at {snapshot_path(entry)}"
            )
            continue
        if stored != live:
            drifts.append(f"{entry.name}: schema drift detected vs {snapshot_path(entry)}")
    return drifts


def update_snapshots() -> list[SchemaEntry]:
    updated: list[SchemaEntry] = []
    for entry in SCHEMAS:
        write_snapshot(entry, live_schema(entry))
        updated.append(entry)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite every snapshot from the live pydantic schema.",
    )
    args = parser.parse_args()

    if args.update:
        updated = update_snapshots()
        for entry in updated:
            print(f"wrote {snapshot_path(entry)}")
        return 0

    drifts = detect_drift()
    if drifts:
        print("Schema drift detected:", file=sys.stderr)
        for item in drifts:
            print(f"  - {item}", file=sys.stderr)
        print(
            "\nIf this change is intentional, regenerate snapshots with:\n"
            "    python ops/scripts/check_schema_drift.py --update",
            file=sys.stderr,
        )
        return 1
    print("Schema snapshots up to date: " + ", ".join(e.name for e in SCHEMAS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
