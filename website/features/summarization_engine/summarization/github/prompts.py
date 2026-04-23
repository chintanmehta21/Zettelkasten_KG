"""GitHub-specific prompt templates."""
from __future__ import annotations

SOURCE_CONTEXT = (
    "You are summarizing a GitHub repository. The label MUST be exactly "
    "'owner/repo'. Cover: what the repo does in user-facing terms, core "
    "functionality, architecture (major directories/modules and their "
    "interactions in 1-3 sentences), main stack, public interfaces (API "
    "routes, CLI commands, package exports, Pages URL), and usability signals "
    "(releases, CI, docs presence). Never claim 'production-ready', 'stable', "
    "or 'battle-tested' unless the README explicitly says so. If "
    "benchmarks/tests/examples directories exist, summarize what they "
    "demonstrate."
)

STRUCTURED_EXTRACT_INSTRUCTION = (
    f"{SOURCE_CONTEXT}\n\n"
    "Return a JSON object with these exact keys:\n"
    '- "mini_title": exactly "<owner>/<repo>" (slashes intact)\n'
    '- "architecture_overview": 50-500 char prose, 1-3 sentences on modules/directories and their interaction\n'
    '- "brief_summary": 5-7 sentence paragraph covering purpose, core function, artifact type, intended use, main stack, public interfaces\n'
    '- "tags": array of 7-10 lowercase hyphenated tags; include language(s), framework(s), domain, interface type\n'
    '- "benchmarks_tests_examples": array of strings describing what they demonstrate, OR null if no such directory exists\n'
    '- "detailed_summary": array of section objects, each with "heading", "bullets", "module_or_feature", "main_stack", "public_interfaces", "usability_signals"\n\n'
    "Do NOT wrap in markdown code blocks. Return raw JSON only.\n\n"
    "SUMMARY:\n{summary_text}"
)
