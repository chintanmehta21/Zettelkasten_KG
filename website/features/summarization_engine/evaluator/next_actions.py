"""Synthesize next_actions.md with a Flash call."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from website.features.summarization_engine.evaluator.prompts import NEXT_ACTIONS_PROMPT


async def synthesize_next_actions(
    *,
    client: Any,
    eval_result_json: dict,
    manual_review_md: str,
    diff_md: str,
    out_path: Path,
    status: str = "continue",
) -> None:
    prompt = NEXT_ACTIONS_PROMPT.format(
        eval_json=json.dumps(eval_result_json, indent=2),
        manual_review_md=manual_review_md,
        diff_md=diff_md,
    )
    result = await client.generate(prompt, tier="flash")
    body = f"status: {status}\n\n" + result.text.strip()
    out_path.write_text(body, encoding="utf-8")
