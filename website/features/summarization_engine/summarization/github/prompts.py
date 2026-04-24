"""GitHub-specific prompt templates.

We adapt the prompt by repository archetype so framework repos, CLI tools, thin
libraries, docs-heavy projects, and example apps each receive guidance matched
to their README shape. Signals extracted deterministically from the README
(install commands, endpoints, decorators, CLI flags) are passed as a
must-preserve slot so the model cannot invent or drop them.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    ReadmeSignals,
)
from website.features.summarization_engine.summarization.github.schema import (
    _is_bogus_surface,
    _is_install_cmd,
)


_BASE_CONTEXT = (
    "You are summarizing a GitHub repository. The label MUST be exactly "
    "'owner/repo'. Never claim 'production-ready', 'stable', or "
    "'battle-tested' unless the README explicitly says so. If "
    "benchmarks/tests/examples directories exist, summarize what they "
    "demonstrate. Preserve exact names (endpoints, decorators, flags, "
    "function names) verbatim — do not paraphrase them. "
    "FAITHFULNESS IS CRITICAL: never fabricate features, integrations, "
    "plugins, capabilities, or public interfaces. If the README does not "
    "explicitly mention something (an IDE plugin, a linter integration, a "
    "benchmark suite, a specific decorator or function name), OMIT it "
    "rather than invent it. When unsure whether a fact is in the source, "
    "leave it out — a shorter, grounded summary is always better than a "
    "longer, invented one. Do not generalize from code snippets: only "
    "names the README surfaces as user-facing APIs belong in the "
    "public interface. "
    "BRIEF SUMMARY must include: (1) what the repo is, (2) its main stack "
    "/ underlying libraries, (3) how modules fit together at a high level, "
    "(4) how users adopt it (install + canonical import/command), and "
    "(5) the core public surface names the README documents. Only name "
    "specific decorators, endpoints, functions, or CLI commands when the "
    "README explicitly documents them — never list interfaces drawn from "
    "source files or issue trackers. "
    "DETAILED SUMMARY must cover: an Overview, Architecture / Modules, "
    "Public API / Interfaces (only README-documented names), Operational "
    "guidance (install, configure, run), and Tests / Benchmarks / Examples "
    "when the README or repo metadata references them. Prefer fewer, "
    "accurate sections over wider but invented coverage. "
    "Guidelines: put install commands (pip install, poetry add, npm "
    "install, cargo install, etc.) in `usability_signals`, not in "
    "`public_interfaces`. Do not put the repository's own package name "
    "into `main_stack` — `main_stack` lists underlying dependencies. Only "
    "include decorators, endpoints, flags, or class names the README "
    "actually shows; do not copy examples from these instructions into the "
    "output if the README does not contain them."
)


_ARCHETYPE_GUIDANCE: dict[RepoArchetype, str] = {
    RepoArchetype.FRAMEWORK_API: (
        "This repository is a WEB FRAMEWORK / API toolkit. Emphasize request "
        "routing, middleware, dependency injection, and documentation "
        "surfaces that the README actually mentions. Only name specific "
        "decorators, endpoints, or classes if the README shows them "
        "verbatim — do not invent routes or decorators. State the "
        "underlying stack (e.g. ASGI/WSGI base, templating engine) only "
        "when the README shows it."
    ),
    RepoArchetype.CLI_TOOL: (
        "This repository is a COMMAND-LINE TOOL. Emphasize the entry-point "
        "command, notable subcommands, and flags that the README shows. "
        "State installation via pip/brew/cargo as documented, and name the "
        "CLI framework used (argparse, click, typer) when evident. The "
        "public surface is CLI commands and flags, not HTTP routes — put "
        "install commands in usability_signals, not public_interfaces."
    ),
    RepoArchetype.LIBRARY_THIN: (
        "This repository is a LIBRARY / SDK with a focused public API. "
        "Emphasize the small set of top-level functions or classes (e.g. "
        "`requests.get`, `requests.post`) that users call. Name the install "
        "command and the canonical import. Do NOT invent modules or "
        "subsystems that the README does not describe — a small API surface "
        "is the correct summary."
    ),
    RepoArchetype.DOCS_HEAVY: (
        "This repository is DOCUMENTATION-HEAVY. Emphasize the organization "
        "of the docs/ tree, the canonical documentation site when mentioned, "
        "and the high-level modules each section covers. The README is "
        "typically a pointer into the docs site — treat it as an index."
    ),
    RepoArchetype.APP_EXAMPLE: (
        "This repository is an EXAMPLE / STARTER / DEMO app. Emphasize the "
        "scenario it demonstrates, the frameworks it combines, and the run "
        "instructions. Do not oversell it as a library or framework."
    ),
    RepoArchetype.UNKNOWN: (
        "The archetype is unclear. Describe the repo strictly from README "
        "evidence — what it is, what it does, how it is used — without "
        "inventing framework or CLI concepts that are not present."
    ),
}


def _signals_slot(signals: ReadmeSignals | None) -> str:
    if signals is None:
        return ""
    must_preserve: list[str] = []
    clean_installs = [c for c in signals.install_cmds if c and not _is_bogus_surface(c)]
    if clean_installs:
        must_preserve.append("INSTALL: " + " | ".join(clean_installs))
    # Filter signal-derived surfaces so HTML scraps (`/div`) and code-fragment
    # tokens (`except DuplicateRuleError`, `provide_automatic_options`) do not
    # leak into the prompt's must-preserve slot. Leaking them causes the LLM
    # to dutifully echo them as "documented public surfaces" in brief_summary,
    # triggering invented_public_interface anti-pattern (hallucination_cap=60).
    surfaces = [
        s for s in signals.any_public_surface()
        if s and not _is_bogus_surface(s) and not _is_install_cmd(s)
    ]
    if surfaces:
        must_preserve.append("PUBLIC SURFACE: " + " | ".join(surfaces))
    if signals.stack:
        must_preserve.append("STACK: " + ", ".join(signals.stack))
    if not must_preserve:
        return ""
    return (
        "\n\nREADME SIGNALS (must be preserved verbatim in detailed_summary, "
        "and where relevant in brief_summary):\n- "
        + "\n- ".join(must_preserve)
    )


def source_context_for(archetype: RepoArchetype, signals: ReadmeSignals | None = None) -> str:
    """Build the full GitHub source context string for a given archetype."""
    guidance = _ARCHETYPE_GUIDANCE.get(archetype, _ARCHETYPE_GUIDANCE[RepoArchetype.UNKNOWN])
    return f"{_BASE_CONTEXT}\n\n{guidance}{_signals_slot(signals)}"


# Archetype-tuned focus blocks. Prepended to STRUCTURED_EXTRACT_INSTRUCTION so
# they shape how the model interprets the schema instruction that follows
# (front-loaded prompt steering). Each block references only fields that exist
# on `GitHubStructuredPayload` / `GitHubDetailedSection` — no schema redefinition,
# no new instruction primitives. Stays under 80 words per block.
_ARCHETYPE_FOCUS: dict[str, str] = {
    "library_thin": (
        "FOCUS (library_thin): Highlight the small public API surface — 1-2 "
        "key top-level functions or classes the README documents. Place the "
        "canonical install command in usability_signals and the documented "
        "import or call site in public_interfaces. Keep architecture_overview "
        "minimal: a thin library has few modules, not a subsystem."
    ),
    "framework_api": (
        "FOCUS (framework_api): Emphasize the architecture in "
        "architecture_overview — request lifecycle, middleware, routing layer "
        "— and list documented extension points (decorators, base classes, "
        "router objects) in public_interfaces. Record the underlying ASGI/WSGI "
        "or HTTP stack in main_stack only when the README names it."
    ),
    "cli_tool": (
        "FOCUS (cli_tool): Emphasize the entry-point command, documented "
        "subcommands, and flags in public_interfaces. Place install commands "
        "and a representative invocation in usability_signals. Name the CLI "
        "framework (argparse, click, typer) in main_stack only when the README "
        "shows it. Do not list HTTP routes — this is a CLI, not a service."
    ),
    "docs_heavy": (
        "FOCUS (docs_heavy): Treat the README as an index. In "
        "architecture_overview, describe the docs/ tree organization and the "
        "canonical documentation site when mentioned. Use detailed_summary "
        "sections to mirror the documented topical structure. List documented "
        "module entry points in public_interfaces, never source-tree guesses."
    ),
    "app_example": (
        "FOCUS (app_example): Emphasize what is deployable and the combined "
        "tech stack in main_stack. Place run/deploy commands and required "
        "environment setup in usability_signals. Keep public_interfaces "
        "limited to user-facing endpoints or scripts the README documents. "
        "Do not oversell the example as a reusable library or framework."
    ),
}


def select_github_prompt(archetype: str | None) -> str:
    """Return the structured-extract instruction tuned for a GitHub archetype.

    The archetype-specific focus block (see :data:`_ARCHETYPE_FOCUS`) is
    prepended to :data:`STRUCTURED_EXTRACT_INSTRUCTION` so it shapes how the
    model interprets the schema instructions that follow. Unknown archetypes
    (including ``"unknown"``, ``None``, empty strings, or labels not in the
    map) fall through to the base instruction unchanged.
    """
    # Validate the input belongs to the enum to surface typos early; unknown
    # values fall through to the default prompt rather than raising.
    label = (archetype or "").strip().lower()
    try:
        RepoArchetype(label)
    except ValueError:
        pass
    focus = _ARCHETYPE_FOCUS.get(label, "")
    if not focus:
        return STRUCTURED_EXTRACT_INSTRUCTION
    return f"{focus}\n\n{STRUCTURED_EXTRACT_INSTRUCTION}".strip()


# Backward-compatible generic context used by any legacy call sites.
SOURCE_CONTEXT = _BASE_CONTEXT


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
