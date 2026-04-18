"""RAG end-to-end evaluation harness.

Package layout:
- ``corpus``: cluster Naruto's zettels into Kastens.
- ``questions``: load/validate the 120-Q YAML dataset.
- ``rubric_b``: active 4-axis 0-5 judging (Claude Sonnet via Anthropic API).
- ``rubric_c``: RAGAS scaffold (raises NotImplementedError until ground-truth answers exist).
- ``judge``: Anthropic client wrapper, isolated from the Gemini key pool.
- ``runner``: drive the 120-Q run against /api/rag/adhoc.
- ``scorecard``: JSON report -> markdown.
"""

from .types import AxisScore, JudgeResult, Kasten, Question, RunReport

__all__ = [
    "AxisScore",
    "JudgeResult",
    "Kasten",
    "Question",
    "RunReport",
]
