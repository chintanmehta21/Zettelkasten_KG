"""Regression test: SYSTEM_PROMPT must keep the conflict-surfacing rule.

Rule 6 ("Surface disagreements explicitly when zettels conflict") is what
forces the answer to quote both sides of a contradictory pair of zettels.
If a future prompt rewrite drops it, the conflict-resolution behaviour
silently regresses — keep this assertion as a guard.
"""
import re

from website.features.rag_pipeline.generation.prompts import SYSTEM_PROMPT


def test_system_prompt_retains_conflict_rule():
    # Look for the conflict-surfacing directive (rule 6) in any phrasing
    # that includes both "Surface disagreements" and "conflict".
    assert "Surface disagreements" in SYSTEM_PROMPT
    assert "conflict" in SYSTEM_PROMPT
    # Ensure it sits in a numbered rule list (defensive against re-styling)
    assert re.search(r"6\.\s*Surface disagreements", SYSTEM_PROMPT) is not None
