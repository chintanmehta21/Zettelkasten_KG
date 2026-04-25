"""Cross-LLM blind reviewer dispatcher."""
from __future__ import annotations

import re
from pathlib import Path


class BlindReviewError(Exception):
    pass


# IMPORTANT: this prompt MUST NOT mention the evaluator output filenames
# (the bare strings "eval.json" / "ablation_eval.json"). The reviewer must
# stay blind to evaluator output. The whitelist of files the reviewer may
# read is enforced by the caller via `dispatch_blind_reviewer`'s
# `allowed_files` argument.
_PROMPT_TEMPLATE = """\
You are an INDEPENDENT cross-LLM reviewer for a RAG evaluation iteration.
You MUST be blind to the evaluator's output. Do NOT read any evaluator score
artifacts (the auto-scored JSON files in this iter directory).

You may read ONLY these files in iter-{iter_num:02d}/:
- manual_review_prompt.md (this file's full prompt)
- queries.json
- answers.json
- kasten.json
- kg_snapshot.json

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of manual_review.md you write.

For each of the queries, read the question, the system's answer, the citations, and the gold/reference.
Estimate the composite score from your honest reading. Be specific:
- Did the right Zettel get cited?
- Was the answer faithful to the source?
- Were any hallucinations present?
- Was the answer comprehensive against the reference?

Schema for manual_review.md:

```
# iter-{iter_num:02d} manual review — {source} — <date>

eval_json_hash_at_review: "NOT_CONSULTED"
estimated_composite: <0-100>
estimated_retrieval: <0-100>
estimated_synthesis: <0-100>

## Per-query observations
- Q1: ...
- Q2: ...
- Q3: ...
- Q4: ...
- Q5: ...

## Per-stage observations
- Chunking: ...
- Retrieval: ...
- Reranking: ...
- Synthesis: ...
- KG signal (graph_lift): unknown without evaluator scores - leave blank
```

Write the file to: {iter_dir}/manual_review.md
Do NOT compute exact scores; estimate as a human reviewer would.
Be honest about uncertainty.
"""


def build_review_prompt(iter_dir: Path, *, source: str, iter_num: int) -> str:
    return _PROMPT_TEMPLATE.format(source=source, iter_num=iter_num, iter_dir=iter_dir)


_STAMP_RE = re.compile(r'eval_json_hash_at_review:\s*"NOT_CONSULTED"')
_COMPOSITE_RE = re.compile(r"estimated_composite:\s*([\d.]+)")


def verify_review_stamp(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not _STAMP_RE.search(text):
        raise BlindReviewError(
            'manual_review.md must stamp eval_json_hash_at_review: "NOT_CONSULTED"'
        )
    m = _COMPOSITE_RE.search(text)
    if not m:
        raise BlindReviewError("manual_review.md missing estimated_composite")
    return {"estimated_composite": float(m.group(1))}


async def dispatch_blind_reviewer(
    *,
    iter_dir: Path,
    source: str,
    iter_num: int,
    agent_runner,
) -> Path:
    """Dispatch a Claude subagent (caller injects agent_runner)."""
    prompt = build_review_prompt(iter_dir, source=source, iter_num=iter_num)
    transcript = await agent_runner(
        prompt=prompt,
        allowed_files=[
            iter_dir / "manual_review_prompt.md",
            iter_dir / "queries.json",
            iter_dir / "answers.json",
            iter_dir / "kasten.json",
            iter_dir / "kg_snapshot.json",
        ],
    )
    transcript_path = iter_dir / "_review_subagent_transcript.json"
    transcript_path.write_text(transcript, encoding="utf-8")
    return iter_dir / "manual_review.md"
