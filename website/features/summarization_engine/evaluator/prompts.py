"""Evaluator prompt templates. Bump PROMPT_VERSION on any edit."""
from __future__ import annotations

PROMPT_VERSION = "evaluator.v1"

CONSOLIDATED_SYSTEM = (
    "You are a summary quality evaluator. Be strict, source-grounded, and terse. "
    "Use temperature 0.0 judgment. Do not editorialize. Output JSON only."
)

CONSOLIDATED_USER_TEMPLATE = """\
Evaluate the following summary against the source. Return a JSON object matching the given schema.

RUBRIC:
{rubric_yaml}

ATOMIC FACTS (from source, importance-ranked):
{atomic_facts}

SOURCE:
{source_text}

SUMMARY:
{summary_json}

Produce a JSON object with exactly these top-level keys: g_eval, finesure, summac_lite, rubric, maps_to_metric_summary, editorialization_flags, evaluator_metadata.

For every criterion in the rubric, check: does the summary satisfy its description? Tally scores per component.
For every anti_pattern in the rubric, check: is it triggered? If yes, list in rubric.anti_patterns_triggered AND set the matching caps_applied field.
For summac_lite, classify each summary sentence as entailed / neutral / contradicted vs source; score = entailed_count / total.
For editorialization_flags, list summary sentences that introduce stance/judgment/framing absent from source.
For maps_to_metric_summary, aggregate rubric criterion scores by their maps_to_metric tags into 4 composites (g_eval, finesure, qafact, summac), each 0-100.
"""

ATOMIC_FACTS_PROMPT = """\
Extract importance-ranked source-grounded claims from the following source. Return a JSON array of up to 30 items,
each with keys "claim" (string) and "importance" (1-5). Rank by importance descending.

SOURCE:
{source_text}
"""

NEXT_ACTIONS_PROMPT = """\
Given this eval and manual review, propose concrete edits for the next iteration.

EVAL JSON:
{eval_json}

MANUAL REVIEW:
{manual_review_md}

DIFF:
{diff_md}

For every rubric criterion scoring below full credit, and every module in the engine that could plausibly affect
that criterion, list one concrete edit. Rank the full list by expected impact x implementation cost. Do NOT cap the count.
Allowed edit surfaces (absolute paths):
- website/features/summarization_engine/summarization/<source>/prompts.py
- website/features/summarization_engine/summarization/<source>/schema.py
- website/features/summarization_engine/summarization/<source>/summarizer.py
- website/features/summarization_engine/summarization/common/*.py
- website/features/summarization_engine/source_ingest/<source>/ingest.py
- website/features/summarization_engine/config.yaml
- docs/summary_eval/_config/rubric_<source>.yaml

Return markdown with a status= field, then a ranked list. Each entry: target file, intended criterion improvement,
rationale (1-2 sentences), impact class (high|medium|speculative), dependencies, risks.
"""

MANUAL_REVIEW_PROMPT_TEMPLATE = """\
You are an INDEPENDENT rubric reviewer, blind to any prior evaluator's scoring. Do NOT read eval.json.

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of your manual_review.md.

RUBRIC:
{rubric_yaml}

SUMMARY:
{summary_json}

ATOMIC FACTS:
{atomic_facts}

SOURCE:
{source_text}

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): {eval_json_hash}
"""
