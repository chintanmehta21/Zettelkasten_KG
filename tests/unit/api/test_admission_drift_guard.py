"""iter-10 drift guard for admission wrapping.

Catches the iter-04..iter-09 silent-bug class where ``_run_answer`` was
unwrapped from ``acquire_rerank_slot`` for 5 iters before iter-09 RES-4 fixed
it. Any ``@router.post`` decorated function that calls
``runtime.orchestrator.answer`` (directly or via a helper in the same file)
must reach an ``acquire_rerank_slot`` call somewhere in the inspected span.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROUTES_DIR = REPO / "website" / "api"
ALLOWED_WRAPPERS = ("acquire_rerank_slot",)


def test_no_router_post_invokes_orchestrator_answer_without_admission():
    offenders: list[str] = []
    for path in sorted(ROUTES_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        chunks = re.split(r"@router\.post\(", src)
        for i, chunk in enumerate(chunks[1:], start=1):
            window = "\n".join(chunk.split("\n")[:120])
            mentions_orchestrator = (
                "orchestrator.answer" in window
                or "_run_answer" in window
                or "_stream_answer" in window
            )
            if not mentions_orchestrator:
                continue
            helpers_called = re.findall(r"\b(_run_answer|_stream_answer\w*)\s*\(", window)
            spans_to_check = [window]
            for helper in set(helpers_called):
                m = re.search(
                    rf"async def {helper}\b.*?(?=\nasync def |\ndef |\Z)",
                    src,
                    re.DOTALL,
                )
                if m:
                    spans_to_check.append(m.group(0))
            wrapped = any(
                any(w in span for w in ALLOWED_WRAPPERS)
                for span in spans_to_check
            )
            if not wrapped:
                offenders.append(f"{path.name}@route#{i}")
    assert not offenders, (
        "Routes calling orchestrator.answer without acquire_rerank_slot wrap: "
        + ", ".join(offenders)
        + ". This is the iter-04..iter-09 silent-bug class."
    )
