"""Manual-review prompt emission and verification helpers."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from website.features.summarization_engine.evaluator.prompts import (
    MANUAL_REVIEW_PROMPT_TEMPLATE,
)


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manual_review_prompt(
    *,
    out_path: Path,
    rubric_yaml: dict[str, Any],
    summary: dict[str, Any],
    atomic_facts: list[dict],
    source_text: str,
    eval_json_path: Path,
) -> str:
    """Emit the manual review prompt and return the eval.json hash."""
    eval_hash = _sha256_of_file(eval_json_path)
    body = MANUAL_REVIEW_PROMPT_TEMPLATE.format(
        rubric_yaml=yaml.safe_dump(rubric_yaml, sort_keys=False),
        summary_json=yaml.safe_dump(summary, sort_keys=False),
        atomic_facts=yaml.safe_dump(atomic_facts, sort_keys=False),
        source_text=source_text[:20000],
        eval_json_hash=eval_hash,
    )
    out_path.write_text(body, encoding="utf-8")
    return eval_hash


_HASH_PATTERN = re.compile(r'eval_json_hash_at_review:\s*"([^"]+)"')
_COMPOSITE_PATTERN = re.compile(r"estimated_composite:\s*([0-9.]+)\s*$", re.MULTILINE)


def verify_manual_review(path: Path) -> tuple[bool, float | None]:
    """Check the blind-review stamp and extract the composite score."""
    text = path.read_text(encoding="utf-8")
    hash_match = _HASH_PATTERN.search(text)
    if not hash_match or hash_match.group(1) != "NOT_CONSULTED":
        return False, None

    composite_match = _COMPOSITE_PATTERN.search(text)
    composite = float(composite_match.group(1)) if composite_match else None
    return True, composite
