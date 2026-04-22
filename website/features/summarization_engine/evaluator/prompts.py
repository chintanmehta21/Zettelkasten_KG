"""Evaluator prompt templates. Bump PROMPT_VERSION on any edit."""
from __future__ import annotations

PROMPT_VERSION = "evaluator.v2"

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

Return a JSON object matching EXACTLY this shape (no extra keys, no nesting beyond what is shown):

{{
  "g_eval": {{
    "coherence": 0.0,       // float 0.0-5.0
    "consistency": 0.0,     // float 0.0-5.0
    "fluency": 0.0,         // float 0.0-5.0
    "relevance": 0.0,       // float 0.0-5.0
    "reasoning": ""         // brief prose
  }},
  "finesure": {{
    "faithfulness": {{ "score": 0.0, "items": [] }},   // score 0.0-1.0; items list factual errors
    "completeness": {{ "score": 0.0, "items": [] }},   // score 0.0-1.0; items list missed important facts
    "conciseness":  {{ "score": 0.0, "items": [] }}    // score 0.0-1.0; items list redundant spans
  }},
  "summac_lite": {{
    "score": 0.0,                          // float 0.0-1.0 = entailed_sentences / total_sentences
    "contradicted_sentences": [],           // each: {{ "sentence": "...", "reason": "..." }}
    "neutral_sentences": []                 // each: {{ "sentence": "...", "reason": "..." }}
  }},
  "rubric": {{
    "components": [                         // ARRAY — one entry per rubric component
      {{
        "id": "brief.thesis_capture",
        "score": 0.0,                       // 0.0 to max_points
        "max_points": 10,
        "criteria_fired": [],
        "criteria_missed": []
      }}
    ],
    "caps_applied": {{
      "hallucination_cap": null,            // int or null
      "omission_cap": null,
      "generic_cap": null
    }},
    "anti_patterns_triggered": []            // each: {{ "id": "...", "source_region": "...", "auto_cap": null }}
  }},
  "maps_to_metric_summary": {{
    "g_eval": 0.0,                          // FLAT float 0-100 (aggregate of g_eval criteria)
    "finesure": 0.0,                        // FLAT float 0-100
    "qafact": 0.0,                          // FLAT float 0-100
    "summac": 0.0                           // FLAT float 0-100
  }},
  "editorialization_flags": [],             // each: {{ "sentence": "...", "flag_type": "added_stance|added_judgment|added_framing", "explanation": "..." }}
  "evaluator_metadata": {{}}                // leave empty; filled in by the harness
}}

RULES:
- For every criterion in the rubric, check whether the summary satisfies its description; tally scores per component into `rubric.components`.
- For every anti_pattern in the rubric: if triggered, add to `rubric.anti_patterns_triggered` AND set the matching key in `caps_applied` to its cap value.
- For `summac_lite.score`: classify each summary sentence as entailed / neutral / contradicted vs source; score = entailed_count / total.
- For `editorialization_flags`: list summary sentences that introduce stance/judgment/framing absent from source.
- For `maps_to_metric_summary`: aggregate rubric criterion scores by their `maps_to_metric` tags into 4 composites, each a FLAT float 0-100 (not a nested dict).
- Output JSON ONLY. No markdown fences, no commentary, no prose outside the JSON object.
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
