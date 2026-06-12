# Wave 2 — GitHub Interface Evidence-Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the GitHub summarizer from emitting fabricated interface tokens (`/sub`, `--Please`, `/center`) by demoting README-regex output out of the must-preserve prompt slot and replacing it with a refusal-first label that flips to "verified surface" only when a real machine-readable manifest artifact (npm `bin`, Python `[project.scripts]`/`console_scripts`, Cargo `[[bin]]`, committed OpenAPI) is parsed.

**Architecture:** Three coordinated modifications across the GitHub source pipeline. A new pure-stdlib parser (`summarization/github/manifest_signals.py`) turns raw manifest bytes into a verified-interface verdict. The ingestor (`source_ingest/github/ingest.py`) reuses the root `/contents` listing it **already** fetches to detect which manifests exist at root, fetches only the present ones via the existing `_fetch_file_contents` helper (Option B / D4 — `+1–2` Contents GETs, token-gated, no new request mechanism), and stamps the verdict into `IngestResult.metadata["verified_interface"]`. The summarizer (`summarization/github/summarizer.py`) reads that metadata and the prompt builder (`summarization/github/prompts.py::_signals_slot`) renders a refusal-first label by default, lifting README-regex surfaces to corroboration-only.

**Tech Stack:** Python 3.12, Pydantic, pytest (`asyncio_mode=auto`). `tomllib` (stdlib, 3.11+) for TOML manifests; `json` (stdlib) for `package.json`/`openapi.json`; OpenAPI YAML handled by filename + light presence check (NO new YAML dependency). All HTTP stays on `api.github.com` (SSRF-safe — host is hard-coded, not user-controlled). No new runtime dependency, no new service. 2 GB / 1 vCPU droplet untouched.

**Source research (read before executing):**
- `docs/claude_audits/github_single_call_research_2026-06-09.md` — D4 verdict (Option B REST piggyback + zero-permission fine-grained `GITHUB_TOKEN`); 60/hr-anon vs 5,000/hr-auth; per-file graceful degradation; Backstage precedent.
- `docs/claude_audits/zettel_eval_solutions_research_2026-06-09.md` — Sol 3 root cause + the refusal-first / generation-time-grounding citations: CloudAPIBench (arXiv:2407.09726, intelligently-triggered grounding beats always-augment → refusal-first), OOPS (arXiv:2601.12735, 97–98% endpoint F1 from artifacts), learning-to-refuse (arXiv:2409.11242), generation-time > post-hoc grounding (arXiv:2509.21557), npm `bin` field docs, Python packaging entry-points/`console_scripts` docs.
- Parent roadmap: `docs/superpowers/plans/2026-06-09-summarization-quality-fixes.md` → "Wave 2 — GitHub interface evidence-ladder (Sol 3)".

**Decisions baked in (do NOT silently revert):**
- **D3** — editing live `website/features/summarization_engine/` is operator-approved for Waves 1–2.
- **D4** — Option B (REST piggyback on the root `/contents` listing already fetched) + a 0-permission fine-grained `GITHUB_TOKEN` the operator provisions on the droplet. NO GraphQL, NO new request mechanism, NO new dependency. With no token (anonymous), gracefully SKIP manifest verification and fall back to the refusal-first label — never fabricate, never crash.
- Gate the "verified surface" label on **artifact-PRESENCE**, NOT on `archetype.confidence` (the archetype classifier misclassifies thin-API repos).

---

## ⚠️ Seam-verification notes (confirmed against live code this session — 2026-06-12)

All file:line references below were re-read and confirmed. Where this plan's seams differ from the parent roadmap's prose, the corrected fact is stated here:

- **No pre-existing "interface label" exists.** Grep for `verified surface` / `interface_artifact` / `interface_label` across `website/` returns ZERO production hits. M1 therefore **creates** this concept; it does not modify an existing one. The label lives as a new metadata key (`verified_interface`) produced by the ingestor and rendered by the prompt builder — there is no schema field to change.
- `summarization/github/prompts.py::_signals_slot` — confirmed at **lines 106–132**. It currently builds `must_preserve` and appends `"PUBLIC SURFACE: " + " | ".join(surfaces)` where `surfaces = [s for s in signals.any_public_surface() if ...]` (lines 118–123). This is the exact must-preserve injection M2 demotes.
- `summarization/github/readme_signals.py` — `_ENDPOINT_PATH` at **line 18**, `_CLI_FLAG` at **line 20**, `any_public_surface()` at **lines 44–61** (returns decorators+endpoints+cli_flags, capped at 8). These are the fabrication source. `/sub` arises from `</sub>` → `_ENDPOINT_PATH` matching `/sub`; `--Please` from `--CLI_FLAG` matching "Please cite"; `/center` from `</center>`.
- `summarization/github/schema.py::_is_bogus_surface` — confirmed at **lines 181–192**; `_HTML_ELEMENT_PATHS` frozenset at **lines 165–172**; `_PROSE_PREFIXES` at **lines 175–178**. This is the backstop blocklist (M2 keeps it as a backstop, not the primary defense).
- `source_ingest/github/ingest.py`:
  - Token wiring: `_github_token(config)` resolved at **line 68**, `headers["Authorization"] = f"Bearer {token}"` at **line 70** (confirmed).
  - `ingest()` builds the per-repo `metadata` dict at **lines 148–160**, then `metadata.update({...})` at **lines 180–189** with the `signals` from `GitHubApiClient.fetch_all_signals`.
  - `_fetch_extra_docs` GETs the root `/contents` listing at **lines 471–475** and builds `lower_to_actual` (a `name.lower() → actual_name` map of top-level entries) at **lines 479–484**.
  - `_fetch_file_contents(client, owner, repo, path, ref)` exists at **lines 527–553** and base64-decodes (returns `""` on any failure).
  - `_optional_json` at **lines 428–435** (swallows ≥400 / exceptions → default).
  - `default_branch = repo_data.get("default_branch") or "main"` is computed at **line 119** inside the `fetch_docs` block; the manifest fetch must derive its own `default_branch` the same way (it must NOT depend on `fetch_docs` being enabled).
- `IngestResult.metadata` is `dict[str, Any] = Field(default_factory=dict)` (`core/models.py:39`) — free-form, safe to add a `verified_interface` key.
- Summarizer consumption seam: `summarization/github/summarizer.py::summarize` already reads `ingest.metadata` (e.g. `owner_login` at lines 200–207) and calls `source_context_for(verdict.archetype, signals)` at **line 114** inside `_prompt_builder`. The verdict must be threaded from `ingest.metadata["verified_interface"]` into `source_context_for`/`_signals_slot`.
- `tomllib` is stdlib in 3.12 and is **not yet imported anywhere** in `website/` (only referenced in docs). Safe to add `import tomllib`.
- Test infra: existing GitHub summarizer test (`tests/unit/summarization_engine/summarization/test_github_summarizer.py`) monkeypatches `run_dense_verify` + `StructuredExtractor.__init__`/`.extract`. `DenseVerifyResult` requires `core_argument` + `closing_hook` (confirmed `dense_verify.py:80,84`). The only in-repo httpx-mock pattern for the ingestor is the `DummyClient` monkeypatch in `tests/unit/summarization_engine/source_ingest/github/test_github_api_client.py:26-43`; the ingest-level tests below use a hand-rolled fake `httpx.AsyncClient` in the same spirit.

**FLAG — scope boundary:** This plan does NOT touch the eval harness (`docs/zettel_eval_v1/`), the Reddit/YouTube summarizers (Waves 1A/1B), or any protected infra knob. The `openapi.*` rung is **best-effort root-only** (these files are frequently nested); the plan notes this explicitly and does not add a recursive Trees call.

---

## TASK 1 — Manifest parser core: `parse_manifest_interface` (npm `bin` + Python entry-points)

Pure, stdlib-only functions that turn raw manifest bytes into interface command names. No network, no LLM, never raises. This is the high rung of the evidence ladder.

**Files:**
- Create: `website/features/summarization_engine/summarization/github/manifest_signals.py`
- Test: `tests/unit/summarization_engine/summarization/github/test_manifest_signals.py` (new)

- [ ] **Step 1.1 — Write the failing test (REAL code)**

```python
# tests/unit/summarization_engine/summarization/github/test_manifest_signals.py
"""Tests for deterministic manifest interface extraction (Wave 2, M3 top rung).

Each parser takes raw manifest text and returns a list of verified interface
command/entry-point names. Parsers never raise: malformed input -> []."""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.manifest_signals import (
    parse_package_json_bin,
    parse_pyproject_scripts,
    parse_setup_cfg_console_scripts,
    parse_cargo_bins,
    detect_openapi,
)


def test_package_json_bin_string_form():
    # npm: "bin": "cli.js" -> the command name defaults to the package "name".
    raw = '{"name": "eslint", "bin": "bin/eslint.js"}'
    assert parse_package_json_bin(raw) == ["eslint"]


def test_package_json_bin_object_form():
    raw = '{"name": "pkg", "bin": {"foo": "bin/foo.js", "bar": "bin/bar.js"}}'
    assert sorted(parse_package_json_bin(raw)) == ["bar", "foo"]


def test_package_json_no_bin_returns_empty():
    assert parse_package_json_bin('{"name": "lodash", "version": "4.0.0"}') == []


def test_package_json_malformed_returns_empty():
    assert parse_package_json_bin("{not json") == []
    assert parse_package_json_bin("") == []


def test_pyproject_project_scripts():
    raw = """
[project]
name = "mytool"

[project.scripts]
mytool = "mytool.cli:main"
mt = "mytool.cli:main"
"""
    assert sorted(parse_pyproject_scripts(raw)) == ["mt", "mytool"]


def test_pyproject_console_scripts_entry_points():
    # The dotted-quoted table form: [project.entry-points."console_scripts"].
    raw = """
[project]
name = "x"

[project.entry-points."console_scripts"]
xrun = "x.app:run"
"""
    assert parse_pyproject_scripts(raw) == ["xrun"]


def test_pyproject_no_scripts_returns_empty():
    assert parse_pyproject_scripts('[project]\nname = "lib"\n') == []


def test_pyproject_malformed_returns_empty():
    assert parse_pyproject_scripts("[project\nbroken = ") == []
    assert parse_pyproject_scripts("") == []


def test_setup_cfg_console_scripts():
    raw = """
[options.entry_points]
console_scripts =
    flake8 = flake8.main.cli:main
    flake8-helper = flake8.helper:run
"""
    assert sorted(parse_setup_cfg_console_scripts(raw)) == ["flake8", "flake8-helper"]


def test_setup_cfg_no_console_scripts_returns_empty():
    assert parse_setup_cfg_console_scripts("[metadata]\nname = lib\n") == []


def test_setup_cfg_malformed_returns_empty():
    assert parse_setup_cfg_console_scripts("=== not ini ===\n\x00") == []


def test_cargo_bins_explicit_table():
    raw = """
[package]
name = "ripgrep"

[[bin]]
name = "rg"
path = "src/main.rs"
"""
    assert parse_cargo_bins(raw) == ["rg"]


def test_cargo_multiple_bins():
    raw = """
[package]
name = "p"
[[bin]]
name = "a"
[[bin]]
name = "b"
"""
    assert sorted(parse_cargo_bins(raw)) == ["a", "b"]


def test_cargo_no_bin_table_returns_empty():
    assert parse_cargo_bins('[package]\nname = "lib"\n') == []


def test_cargo_malformed_returns_empty():
    assert parse_cargo_bins("[[bin\n") == []


def test_detect_openapi_by_json_content():
    assert detect_openapi("openapi.json", '{"openapi": "3.0.0", "paths": {}}') is True


def test_detect_openapi_by_swagger_key():
    assert detect_openapi("openapi.json", '{"swagger": "2.0"}') is True


def test_detect_openapi_yaml_presence_only():
    # YAML: no YAML dep -> filename + a light textual marker is enough.
    assert detect_openapi("openapi.yaml", "openapi: 3.0.1\npaths:\n  /x: {}\n") is True
    assert detect_openapi("openapi.yml", "swagger: '2.0'\n") is True


def test_detect_openapi_rejects_unrelated_json():
    assert detect_openapi("openapi.json", '{"name": "not-an-api"}') is False


def test_detect_openapi_rejects_unrelated_yaml():
    assert detect_openapi("openapi.yaml", "name: something\nversion: 1\n") is False
```

- [ ] **Step 1.2 — Run to FAIL**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/test_manifest_signals.py -v`
Expected: collection/import error — `ModuleNotFoundError: No module named '...github.manifest_signals'` (the module does not exist yet).

- [ ] **Step 1.3 — Implement minimal parsers (REAL code)**

```python
# website/features/summarization_engine/summarization/github/manifest_signals.py
"""Deterministic manifest interface extraction (Wave 2, M3 — the top rung).

Turns raw manifest bytes into verified interface command / entry-point names.
These are the ONLY interface signals strong enough to flip the refusal-first
label to "verified surface". Pure stdlib (tomllib + json + configparser), no
network, no LLM. Every parser is total: malformed input returns []/False, never
raises — a broken manifest must degrade to the refusal-first label, not crash
the ingest."""
from __future__ import annotations

import configparser
import json
import logging
import tomllib

_log = logging.getLogger(__name__)


def parse_package_json_bin(raw: str) -> list[str]:
    """npm `bin`: string form -> [package name]; object form -> its keys.

    Per npm docs, a string `bin` installs a command named after the package's
    `name` (last path segment if scoped). An object maps command-name -> path."""
    try:
        data = json.loads(raw or "")
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    bin_field = data.get("bin")
    if isinstance(bin_field, str) and bin_field.strip():
        name = str(data.get("name") or "").strip()
        # Scoped package "@scope/foo" -> command "foo".
        cmd = name.rsplit("/", 1)[-1] if name else ""
        return [cmd] if cmd else []
    if isinstance(bin_field, dict):
        return [str(k).strip() for k in bin_field if str(k).strip()]
    return []


def parse_pyproject_scripts(raw: str) -> list[str]:
    """Python `pyproject.toml`: both [project.scripts] AND the dotted-quoted
    [project.entry-points."console_scripts"] table (PEP 621 / packaging docs)."""
    try:
        data = tomllib.loads(raw or "")
    except Exception:
        return []
    out: list[str] = []
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    scripts = project.get("scripts")
    if isinstance(scripts, dict):
        out.extend(str(k).strip() for k in scripts if str(k).strip())
    entry_points = project.get("entry-points")
    if isinstance(entry_points, dict):
        console = entry_points.get("console_scripts")
        if isinstance(console, dict):
            out.extend(str(k).strip() for k in console if str(k).strip())
    # Deduplicate, preserve order.
    seen: set[str] = set()
    return [c for c in out if not (c in seen or seen.add(c))]


def parse_setup_cfg_console_scripts(raw: str) -> list[str]:
    """setup.cfg `[options.entry_points]` console_scripts (newline-delimited
    `name = module:func` lines)."""
    parser = configparser.ConfigParser()
    try:
        parser.read_string(raw or "")
    except Exception:
        return []
    if not parser.has_section("options.entry_points"):
        return []
    try:
        block = parser.get("options.entry_points", "console_scripts")
    except Exception:
        return []
    out: list[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name:
            out.append(name)
    return out


def parse_cargo_bins(raw: str) -> list[str]:
    """Cargo.toml `[[bin]]` array-of-tables -> each table's `name`."""
    try:
        data = tomllib.loads(raw or "")
    except Exception:
        return []
    bins = data.get("bin")
    if not isinstance(bins, list):
        return []
    out: list[str] = []
    for entry in bins:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if name:
                out.append(name)
    return out


def detect_openapi(filename: str, raw: str) -> bool:
    """Best-effort committed-OpenAPI presence. JSON: parse + check the
    `openapi`/`swagger` top-level key. YAML: no YAML dep -> filename + a light
    textual marker (a leading `openapi:`/`swagger:` line) is enough. Presence is
    the signal; we do not extract paths here."""
    name = (filename or "").lower()
    text = raw or ""
    if name.endswith(".json"):
        try:
            data = json.loads(text)
        except Exception:
            return False
        return isinstance(data, dict) and ("openapi" in data or "swagger" in data)
    if name.endswith((".yaml", ".yml")):
        for line in text.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith(("openapi:", "swagger:")):
                return True
        return False
    return False
```

- [ ] **Step 1.4 — Run to PASS**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/test_manifest_signals.py -v`
Expected: PASS (all ~19 tests green).

- [ ] **Step 1.5 — Commit**

```bash
git commit -m "feat: deterministic GitHub manifest interface parsers"
```

**Self-review:**
- Every parser is total (try/except → `[]`/`False`); confirmed by the malformed-input tests.
- `tomllib` is stdlib in 3.12 (verified not previously imported in `website/`); `configparser`/`json` likewise. No new dependency.
- npm string-`bin` correctly defaults to the package name and strips a `@scope/` prefix (npm docs behavior).
- Both `[project.scripts]` AND `[project.entry-points."console_scripts"]` are covered (required by spec).
- `detect_openapi` does NOT add a YAML parser — filename + a leading marker line, presence-only (best-effort, root-only noted).

---

## TASK 2 — Verdict builder: `build_interface_verdict` (the evidence ladder)

A single entry point that takes the manifests-present-at-root (filename → raw text) and returns a structured verdict the ingestor stamps into metadata. This centralizes the rung logic so the ingestor stays thin and the summarizer reads one field.

**Files:**
- Modify: `website/features/summarization_engine/summarization/github/manifest_signals.py` (append `InterfaceVerdict` dataclass + `MANIFEST_FILENAMES` + `build_interface_verdict`)
- Test: `tests/unit/summarization_engine/summarization/github/test_manifest_signals.py` (extend)

- [ ] **Step 2.1 — Write the failing test (REAL code) — append to the Task 1 test file**

```python
# --- appended to test_manifest_signals.py ---
from website.features.summarization_engine.summarization.github.manifest_signals import (
    InterfaceVerdict,
    MANIFEST_FILENAMES,
    build_interface_verdict,
)


def test_manifest_filenames_are_the_six_root_candidates():
    # Exactly the root-level manifests we probe; lowercase for listing-map lookup.
    assert MANIFEST_FILENAMES == (
        "package.json",
        "pyproject.toml",
        "setup.cfg",
        "cargo.toml",
        "openapi.json",
        "openapi.yaml",
        "openapi.yml",
    )


def test_verdict_no_manifests_is_refusal_first():
    v = build_interface_verdict({})
    assert isinstance(v, InterfaceVerdict)
    assert v.verified is False
    assert v.commands == []
    assert v.kind == "none"
    # The label is the refusal-first wording (true + defensible).
    assert "no verified interface artifact" in v.label.lower()


def test_verdict_npm_bin_surfaces_real_command():
    v = build_interface_verdict({"package.json": '{"name": "eslint", "bin": "bin/eslint.js"}'})
    assert v.verified is True
    assert v.commands == ["eslint"]
    assert v.kind == "cli"
    assert "verified" in v.label.lower()
    assert "eslint" in v.label


def test_verdict_pyproject_scripts_cli():
    raw = '[project]\nname="t"\n[project.scripts]\nt = "t.cli:main"\n'
    v = build_interface_verdict({"pyproject.toml": raw})
    assert v.verified is True
    assert v.commands == ["t"]
    assert v.kind == "cli"


def test_verdict_cargo_bin_cli():
    raw = '[package]\nname="p"\n[[bin]]\nname="rg"\n'
    v = build_interface_verdict({"cargo.toml": raw})
    assert v.verified is True and v.commands == ["rg"] and v.kind == "cli"


def test_verdict_setup_cfg_cli():
    raw = "[options.entry_points]\nconsole_scripts =\n    f = f.main:cli\n"
    v = build_interface_verdict({"setup.cfg": raw})
    assert v.verified is True and v.commands == ["f"] and v.kind == "cli"


def test_verdict_openapi_is_http_kind_no_commands():
    v = build_interface_verdict({"openapi.json": '{"openapi": "3.0.0", "paths": {}}'})
    assert v.verified is True
    assert v.kind == "http"
    assert v.commands == []
    assert "openapi" in v.label.lower() or "http" in v.label.lower()


def test_verdict_present_but_empty_manifest_is_refusal_first():
    # A package.json with NO bin is present but proves no interface -> refusal-first.
    v = build_interface_verdict({"package.json": '{"name": "lodash"}'})
    assert v.verified is False
    assert v.kind == "none"


def test_verdict_cli_takes_precedence_over_openapi_kind():
    # If both a CLI manifest and OpenAPI are present, surface the concrete CLI
    # commands (stronger, named signal) but record http coverage too.
    manifests = {
        "package.json": '{"name": "tool", "bin": {"tool": "b.js"}}',
        "openapi.json": '{"openapi": "3.0.0"}',
    }
    v = build_interface_verdict(manifests)
    assert v.verified is True
    assert "tool" in v.commands
    assert v.kind in {"cli", "cli+http"}
```

- [ ] **Step 2.2 — Run to FAIL**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/test_manifest_signals.py -k verdict -v`
Expected: FAIL — `ImportError: cannot import name 'InterfaceVerdict'` (not yet defined).

- [ ] **Step 2.3 — Implement (REAL code) — append to `manifest_signals.py`**

```python
# --- appended to manifest_signals.py ---
from dataclasses import dataclass, field

# Root-level manifest candidates, lowercased to match the ingestor's
# lower->actual filename map. openapi.* is best-effort root-only (these files
# are frequently nested; root listing misses nested paths by design — D4).
MANIFEST_FILENAMES: tuple[str, ...] = (
    "package.json",
    "pyproject.toml",
    "setup.cfg",
    "cargo.toml",
    "openapi.json",
    "openapi.yaml",
    "openapi.yml",
)

_REFUSAL_LABEL = "library/repository overview — no verified interface artifact"


@dataclass(frozen=True)
class InterfaceVerdict:
    """Result of the evidence ladder. `verified` flips the prompt label;
    `commands` are real CLI command names; `kind` ∈ {none, cli, http, cli+http}.
    `label` is the user-safe wording rendered into the prompt."""
    verified: bool = False
    commands: list[str] = field(default_factory=list)
    kind: str = "none"
    label: str = _REFUSAL_LABEL
    source_files: list[str] = field(default_factory=list)

    def as_metadata(self) -> dict:
        return {
            "verified": self.verified,
            "commands": list(self.commands),
            "kind": self.kind,
            "label": self.label,
            "source_files": list(self.source_files),
        }


def build_interface_verdict(manifests: dict[str, str]) -> InterfaceVerdict:
    """Run the evidence ladder over the manifests found at repo root.

    `manifests` maps a lowercased filename (one of MANIFEST_FILENAMES) to its
    raw text. Empty/absent -> refusal-first verdict. CLI commands (npm bin,
    console_scripts, Cargo [[bin]]) are the strongest signal and are named in
    the label; committed OpenAPI yields an `http` verdict without command
    names. Never raises."""
    commands: list[str] = []
    source_files: list[str] = []

    pkg = manifests.get("package.json")
    if pkg:
        cmds = parse_package_json_bin(pkg)
        if cmds:
            commands.extend(cmds)
            source_files.append("package.json")

    pyproject = manifests.get("pyproject.toml")
    if pyproject:
        cmds = parse_pyproject_scripts(pyproject)
        if cmds:
            commands.extend(cmds)
            source_files.append("pyproject.toml")

    setup_cfg = manifests.get("setup.cfg")
    if setup_cfg:
        cmds = parse_setup_cfg_console_scripts(setup_cfg)
        if cmds:
            commands.extend(cmds)
            source_files.append("setup.cfg")

    cargo = manifests.get("cargo.toml")
    if cargo:
        cmds = parse_cargo_bins(cargo)
        if cmds:
            commands.extend(cmds)
            source_files.append("cargo.toml")

    has_http = False
    for oa_name in ("openapi.json", "openapi.yaml", "openapi.yml"):
        oa_raw = manifests.get(oa_name)
        if oa_raw and detect_openapi(oa_name, oa_raw):
            has_http = True
            source_files.append(oa_name)
            break

    # Deduplicate command names, preserve discovery order.
    seen: set[str] = set()
    commands = [c for c in commands if not (c in seen or seen.add(c))]

    has_cli = bool(commands)
    if not has_cli and not has_http:
        return InterfaceVerdict()  # refusal-first defaults

    if has_cli and has_http:
        kind = "cli+http"
    elif has_cli:
        kind = "cli"
    else:
        kind = "http"

    if has_cli:
        shown = ", ".join(commands[:6])
        label = f"verified CLI interface — command(s): {shown}"
        if has_http:
            label += "; committed OpenAPI specification present"
    else:
        label = "verified HTTP interface — committed OpenAPI specification present"

    return InterfaceVerdict(
        verified=True,
        commands=commands,
        kind=kind,
        label=label,
        source_files=source_files,
    )
```

- [ ] **Step 2.4 — Run to PASS**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/test_manifest_signals.py -v`
Expected: PASS (all Task 1 + Task 2 tests green).

- [ ] **Step 2.5 — Commit**

```bash
git commit -m "feat: GitHub interface evidence-ladder verdict builder"
```

**Self-review:**
- The verdict gates `verified` on artifact-PRESENCE (a parsed command or detected OpenAPI), never on `archetype.confidence` — satisfies the M1 gate requirement.
- Present-but-empty manifest (`package.json` with no `bin`) → refusal-first (`test_verdict_present_but_empty_manifest_is_refusal_first`), so `requests` (no manifest `bin`) lands on the defensible label.
- `MANIFEST_FILENAMES` is lowercased to match the ingestor's `lower_to_actual` map (Task 3).
- `as_metadata()` returns a plain dict so the verdict survives JSON round-trips in `IngestResult.metadata`.

---

## TASK 3 — Ingestor: detect + fetch present manifests (Option B), stamp `verified_interface`

Reuse the root `/contents` listing the ingestor already fetches; fetch only the manifests that exist at root via the existing `_fetch_file_contents`; build the verdict; stamp it into `metadata`. Token-gated: with no token the manifest stage is skipped (verdict stays refusal-first). `+1–2` Contents GETs typical, zero wasted GETs for absent files.

**Files:**
- Modify: `website/features/summarization_engine/source_ingest/github/ingest.py`
  - Add a module-level helper `_fetch_manifest_signals(client, owner, repo, listing, default_branch, *, token_present)` near `_fetch_extra_docs` (after line ~524).
  - Call it inside `ingest()` and merge `verified_interface` into `metadata` (after the `metadata.update(...)` block at lines 180–189).
- Test: `tests/unit/summarization_engine/source_ingest/github/test_github_manifest_ingest.py` (new)

- [ ] **Step 3.1 — Write the failing test (REAL code)**

```python
# tests/unit/summarization_engine/source_ingest/github/test_github_manifest_ingest.py
"""Tests for the Option-B manifest fetch in the GitHub ingestor (Wave 2, M3).

Verifies: (1) only manifests PRESENT in the root /contents listing are fetched
(zero wasted GETs for absent files); (2) a real package.json bin yields a
verified verdict; (3) no token -> manifest stage skipped, refusal-first verdict;
(4) a repo with no manifests -> refusal-first verdict, no manifest GETs."""
from __future__ import annotations

import base64

import pytest

from website.features.summarization_engine.source_ingest.github import ingest as gh_ingest


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Records every GET URL; serves canned /contents listing + file bodies."""

    def __init__(self, listing, file_bodies: dict[str, str]):
        self._listing = listing
        self._file_bodies = file_bodies
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/contents"):
            return _FakeResponse(200, self._listing)
        # Contents file fetch: /contents/<path>
        marker = "/contents/"
        if marker in url:
            path = url.split(marker, 1)[1]
            body = self._file_bodies.get(path)
            if body is None:
                return _FakeResponse(404, {})
            return _FakeResponse(200, {"content": _b64(body), "encoding": "base64"})
        return _FakeResponse(404, {})


@pytest.mark.asyncio
async def test_manifest_fetch_only_hits_present_files():
    listing = [
        {"name": "README.md", "type": "file"},
        {"name": "package.json", "type": "file"},
    ]
    bodies = {"package.json": '{"name": "eslint", "bin": "bin/eslint.js"}'}
    client = _FakeClient(listing, bodies)

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=True
    )

    assert verdict["verified"] is True
    assert verdict["commands"] == ["eslint"]
    # Exactly ONE manifest GET (package.json). NO GET for pyproject/cargo/etc.
    manifest_gets = [c for c in client.calls if "/contents/" in c]
    assert manifest_gets == [
        "https://api.github.com/repos/owner/repo/contents/package.json"
    ]


@pytest.mark.asyncio
async def test_absent_manifests_cause_zero_wasted_gets():
    listing = [{"name": "README.md", "type": "file"}, {"name": "LICENSE", "type": "file"}]
    client = _FakeClient(listing, {})

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=True
    )

    assert verdict["verified"] is False
    assert "no verified interface artifact" in verdict["label"].lower()
    # No /contents/<file> GET at all — we never blind-probe a missing manifest.
    assert [c for c in client.calls if "/contents/" in c] == []


@pytest.mark.asyncio
async def test_no_token_skips_manifest_fetch_refusal_first():
    listing = [{"name": "package.json", "type": "file"}]
    bodies = {"package.json": '{"name": "x", "bin": "b.js"}'}
    client = _FakeClient(listing, bodies)

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=False
    )

    assert verdict["verified"] is False
    assert verdict["kind"] == "none"
    # Anonymous: we do NOT spend the scarce 60/hr budget on manifest reads.
    assert [c for c in client.calls if "/contents/" in c] == []


@pytest.mark.asyncio
async def test_case_insensitive_filename_match():
    # GitHub preserves case; our match is via the lowercased listing map.
    listing = [{"name": "Cargo.toml", "type": "file"}]
    bodies = {"Cargo.toml": '[package]\nname="p"\n[[bin]]\nname="rg"\n'}
    client = _FakeClient(listing, bodies)

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=True
    )
    assert verdict["verified"] is True
    assert verdict["commands"] == ["rg"]
    assert client.calls[-1].endswith("/contents/Cargo.toml")
```

- [ ] **Step 3.2 — Run to FAIL**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/source_ingest/github/test_github_manifest_ingest.py -v`
Expected: FAIL — `AttributeError: module '...github.ingest' has no attribute '_fetch_manifest_signals'`.

- [ ] **Step 3.3 — Implement the helper (REAL code)**

Add this import at the top of `ingest.py` (with the other `summarization.github` is NOT currently imported in ingest; this is the first cross-import from `summarization` into `source_ingest` — FLAG: verify no circular import. `manifest_signals.py` imports only stdlib, so it is safe). Place the import alongside the existing `from website.features.summarization_engine.source_ingest...` block:

```python
from website.features.summarization_engine.summarization.github.manifest_signals import (
    MANIFEST_FILENAMES,
    build_interface_verdict,
)
```

Add the helper function immediately after `_fetch_file_contents` (after current line 553):

```python
async def _fetch_manifest_signals(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    listing: Any,
    default_branch: str,
    *,
    token_present: bool,
) -> dict[str, Any]:
    """Option B (D4): from the root /contents listing already fetched, read only
    the manifests that exist at root, parse them, and return the interface
    verdict as a plain dict for IngestResult.metadata.

    Token-gated: with no token we skip the reads entirely (the anonymous 60/hr
    budget is too scarce to spend here) and return the refusal-first verdict.
    Absent manifests cost ZERO extra GETs — we only fetch names the listing
    already proved present."""
    if not token_present:
        return build_interface_verdict({}).as_metadata()
    if not isinstance(listing, list):
        return build_interface_verdict({}).as_metadata()

    lower_to_actual = {
        entry.get("name", "").lower(): entry.get("name", "")
        for entry in listing
        if isinstance(entry, dict)
        and entry.get("type") == "file"
        and entry.get("name")
    }

    manifests: dict[str, str] = {}
    for candidate in MANIFEST_FILENAMES:
        actual = lower_to_actual.get(candidate)
        if not actual:
            continue  # absent at root -> no fetch, no waste
        body = await _fetch_file_contents(client, owner, repo, actual, default_branch)
        if body:
            manifests[candidate] = body

    return build_interface_verdict(manifests).as_metadata()
```

- [ ] **Step 3.4 — Wire the call into `ingest()` (REAL code)**

The `extra_docs` block already computes the root listing for docs, but it discards it. To keep `+1–2` calls (NOT a second `/contents` GET), capture the listing once and reuse it. Inside the `async with httpx.AsyncClient(...)` block, after the `extra_docs` fetch (current lines 117–127), the listing is fetched **inside** `_fetch_extra_docs`. To avoid a duplicate `/contents` GET, fetch the listing once at the top of the manifest+docs region and pass it down.

**Minimal, low-risk wiring (does NOT refactor `_fetch_extra_docs`):** fetch the root listing once here and run the manifest stage against it; `_fetch_extra_docs` keeps its own listing fetch (it is already `_optional_json`-guarded and only runs when `fetch_docs` is true). The net add is `+1` listing GET only when `fetch_docs` is **false**; when `fetch_docs` is true, accept the one extra listing GET as the documented `+1–2` cost (manifests + docs are independent config toggles). Replace the block at current lines 117–127:

Current code (lines 117–127):
```python
            extra_docs: list[tuple[str, str]] = []
            if config.get("fetch_docs", True):
                default_branch = repo_data.get("default_branch") or "main"
                extra_docs = await _fetch_extra_docs(
                    client,
                    owner,
                    repo,
                    default_branch,
                    max_files=int(config.get("max_docs", _MAX_EXTRA_DOCS)),
                    char_cap=int(config.get("doc_char_cap", _DOC_FILE_CHAR_CAP)),
                )
```

Replace with:
```python
            default_branch = repo_data.get("default_branch") or "main"
            extra_docs: list[tuple[str, str]] = []
            if config.get("fetch_docs", True):
                extra_docs = await _fetch_extra_docs(
                    client,
                    owner,
                    repo,
                    default_branch,
                    max_files=int(config.get("max_docs", _MAX_EXTRA_DOCS)),
                    char_cap=int(config.get("doc_char_cap", _DOC_FILE_CHAR_CAP)),
                )

            # Wave 2 (M3, Option B/D4): interface evidence-ladder. Reuse a single
            # root /contents listing to detect+read only present manifests; skip
            # entirely when no token (anonymous 60/hr budget is too scarce).
            verified_interface = build_interface_verdict({}).as_metadata()
            if config.get("verify_interface", True):
                root_listing = await _optional_json(
                    client,
                    f"https://api.github.com/repos/{owner}/{repo}/contents",
                    [],
                )
                verified_interface = await _fetch_manifest_signals(
                    client,
                    owner,
                    repo,
                    root_listing,
                    default_branch,
                    token_present=bool(token),
                )
```

Then merge into `metadata`. After the `metadata.update({...})` call (current lines 180–189), add:
```python
        metadata["verified_interface"] = verified_interface
```

**FLAG — duplicate listing GET:** when `fetch_docs` is true, `_fetch_extra_docs` fetches `/contents` AND this stage fetches `/contents` again — `+2` listing GETs worst case. The parent research (`github_single_call_research_2026-06-09.md`) budgeted `+1–2` calls, so this is within budget; an optional follow-up could thread the single listing into `_fetch_extra_docs` to drop to `+1`. Not done here to keep the diff small and `_fetch_extra_docs` untouched (lower regression risk on the verified-sources path).

- [ ] **Step 3.5 — Run to PASS**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/source_ingest/github/test_github_manifest_ingest.py -v`
Expected: PASS (4 passed).

- [ ] **Step 3.6 — Regression: existing GitHub ingest/api tests still pass**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/source_ingest/github/ -v`
Expected: PASS (existing `test_github_api_client.py` unaffected + new file green).

- [ ] **Step 3.7 — Commit**

```bash
git commit -m "feat: ingest GitHub manifests via root contents reuse"
```

**Self-review:**
- Only present manifests are fetched (`test_manifest_fetch_only_hits_present_files`, `test_absent_manifests_cause_zero_wasted_gets`) — zero blind 404 probes.
- No-token path skips the stage and returns refusal-first (`test_no_token_skips_manifest_fetch_refusal_first`) — never fabricates, never crashes.
- `default_branch` is now computed unconditionally (line moved out of the `fetch_docs` guard) so the manifest stage works even when `fetch_docs` is disabled.
- Cross-import `summarization.github.manifest_signals` → `source_ingest`: `manifest_signals` imports only stdlib, so no import cycle. (Verified: `manifest_signals.py` has no `source_ingest` / `summarizer` imports.)
- Host stays `api.github.com` (string-built URL, `owner`/`repo` from the validated route) — SSRF-safe per the existing trusted-host bypass note (ingest.py:72-74).
- New `verify_interface` config key defaults to `True` in code; Task 5 adds it to `config.yaml` for explicitness.

---

## TASK 4 — Prompt + summarizer: refusal-first label (M1) + demote regex to corroboration (M2)

Render the verified-interface verdict as the authoritative interface statement in the prompt; move README-regex `PUBLIC SURFACE` from "must-preserve" to "corroboration-only (verify against the README; omit if unsupported)". This is the actual root fix for the `/sub` / `--Please` / `/center` fabrication.

**Files:**
- Modify: `website/features/summarization_engine/summarization/github/prompts.py`
  - `_signals_slot` (lines 106–132) — add a `verified_interface` parameter; relabel the README-surface block as corroboration-only.
  - `source_context_for` (lines 135–138) — thread `verified_interface` through.
- Modify: `website/features/summarization_engine/summarization/github/summarizer.py`
  - `_prompt_builder` (line 114) — pass `ingest.metadata.get("verified_interface")` into `source_context_for`.
- Test: `tests/unit/summarization_engine/summarization/github/test_prompt_variants.py` (extend) + `tests/unit/summarization_engine/summarization/test_github_summarizer.py` (extend)

- [ ] **Step 4.1 — Write the failing prompt tests (REAL code) — append to `test_prompt_variants.py`**

```python
# --- appended to test_prompt_variants.py ---
from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
)
from website.features.summarization_engine.summarization.github.prompts import (
    _signals_slot,
    source_context_for,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    ReadmeSignals,
)


def _bogus_signals() -> ReadmeSignals:
    # The verified fabrication tokens, exactly as the README regex emits them.
    return ReadmeSignals(
        install_cmds=("pip install requests",),
        endpoints=("/sub", "/center"),
        cli_flags=("--Please",),
        decorators=(),
        inline_code=(),
        first_code_block="",
        stack=("Python",),
        purpose_sentence="",
    )


def test_signals_slot_demotes_surface_to_corroboration():
    """M2: README-regex surfaces must NOT be framed as 'must be preserved
    verbatim'. They become corroboration-only."""
    out = _signals_slot(_bogus_signals(), verified_interface=None)
    lowered = out.lower()
    # The must-preserve framing is gone for surfaces.
    assert "must be preserved verbatim" not in lowered
    # Corroboration framing is present (the regex output is now optional/checked).
    assert "corrobor" in lowered or "only if" in lowered or "verify against" in lowered


def test_signals_slot_refusal_first_when_no_verified_interface():
    """M1: with no verified artifact, the slot states the refusal-first label."""
    out = _signals_slot(_bogus_signals(), verified_interface=None)
    assert "no verified interface artifact" in out.lower()


def test_signals_slot_uses_verified_label_on_artifact_hit():
    """M1: a HIGH-rung manifest hit flips to the verified-surface label and
    names the real command(s)."""
    vi = {
        "verified": True,
        "commands": ["eslint"],
        "kind": "cli",
        "label": "verified CLI interface — command(s): eslint",
        "source_files": ["package.json"],
    }
    out = _signals_slot(_bogus_signals(), verified_interface=vi)
    assert "verified cli interface" in out.lower()
    assert "eslint" in out
    # Even when verified, the bogus regex tokens are never elevated to verbatim.
    assert "must be preserved verbatim" not in out.lower()


def test_source_context_threads_verified_interface():
    vi = {"verified": True, "commands": ["rg"], "kind": "cli",
          "label": "verified CLI interface — command(s): rg", "source_files": ["cargo.toml"]}
    ctx = source_context_for(RepoArchetype.CLI_TOOL, _bogus_signals(), verified_interface=vi)
    assert "rg" in ctx
    assert "verified cli interface" in ctx.lower()


def test_source_context_refusal_first_default():
    ctx = source_context_for(RepoArchetype.LIBRARY_THIN, _bogus_signals(), verified_interface=None)
    assert "no verified interface artifact" in ctx.lower()
```

- [ ] **Step 4.2 — Run to FAIL**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/test_prompt_variants.py -k "signals_slot or source_context" -v`
Expected: FAIL — `TypeError: _signals_slot() got an unexpected keyword argument 'verified_interface'` (and `source_context_for` likewise).

- [ ] **Step 4.3 — Implement `_signals_slot` + `source_context_for` (REAL code)**

Replace `_signals_slot` (current lines 106–132) with:

```python
def _signals_slot(
    signals: ReadmeSignals | None,
    *,
    verified_interface: dict | None = None,
) -> str:
    """Build the README-signal + verified-interface slot.

    M1: the interface label is refusal-first by default ("library/repository
    overview — no verified interface artifact") and flips to the verified label
    ONLY on a machine-parsed manifest hit (verified_interface["verified"]).
    M2: README-regex surfaces are CORROBORATION-ONLY — never "must-preserve" —
    so HTML scraps (`/sub`, `/center`) and prose tokens (`--Please`) can no
    longer be echoed as documented interfaces (the verified root cause)."""
    parts: list[str] = []

    # --- Interface verdict (authoritative; refusal-first) ---
    vi = verified_interface or {}
    if vi.get("verified"):
        parts.append(
            "VERIFIED INTERFACE (parsed from a committed manifest — state this "
            "as the repository's interface): " + str(vi.get("label", ""))
        )
        cmds = [c for c in (vi.get("commands") or []) if c]
        if cmds:
            parts.append(
                "These command name(s) are machine-verified and may be stated "
                "verbatim: " + " | ".join(cmds)
            )
    else:
        parts.append(
            "INTERFACE: library/repository overview — no verified interface "
            "artifact. Do NOT assert a CLI command or HTTP route as the "
            "repository's interface unless the README explicitly documents it; "
            "prefer the grounded library-overview framing."
        )

    if signals is None:
        return _join_slot(parts)

    # Install commands remain a reliable, low-fabrication signal.
    clean_installs = [c for c in signals.install_cmds if c and not _is_bogus_surface(c)]
    if clean_installs:
        parts.append("INSTALL: " + " | ".join(clean_installs))

    # M2: README-regex surfaces are corroboration-only. The _is_bogus_surface
    # blocklist stays as a backstop, but framing — not the blocklist — is now
    # the primary defense against echoing fabricated tokens.
    surfaces = [
        s for s in signals.any_public_surface()
        if s and not _is_bogus_surface(s) and not _is_install_cmd(s)
    ]
    if surfaces:
        parts.append(
            "POSSIBLE SURFACE TOKENS (heuristic, from README text — include ONLY "
            "if the README clearly documents them as user-facing; otherwise OMIT, "
            "do NOT treat as verified): " + " | ".join(surfaces)
        )

    if signals.stack:
        parts.append("STACK: " + ", ".join(signals.stack))

    return _join_slot(parts)


def _join_slot(parts: list[str]) -> str:
    if not parts:
        return ""
    return "\n\nREPOSITORY SIGNALS:\n- " + "\n- ".join(parts)
```

Replace `source_context_for` (current lines 135–138) with:

```python
def source_context_for(
    archetype: RepoArchetype,
    signals: ReadmeSignals | None = None,
    *,
    verified_interface: dict | None = None,
) -> str:
    """Build the full GitHub source context string for a given archetype."""
    guidance = _ARCHETYPE_GUIDANCE.get(archetype, _ARCHETYPE_GUIDANCE[RepoArchetype.UNKNOWN])
    slot = _signals_slot(signals, verified_interface=verified_interface)
    return f"{_BASE_CONTEXT}\n\n{guidance}{slot}"
```

- [ ] **Step 4.4 — Wire the summarizer to pass the verdict (REAL code)**

In `summarizer.py::summarize`, before `_prompt_builder` is defined (it closes over `verdict`/`signals`), capture the verdict from metadata. Add after `signals = extract_signals(...)` (current lines 81–84):

```python
        verified_interface = (ingest.metadata or {}).get("verified_interface")
```

Then change the `source_context_for(...)` call inside `_prompt_builder` (current line 114) from:
```python
                f"{source_context_for(verdict.archetype, signals)}\n\n"
```
to:
```python
                f"{source_context_for(verdict.archetype, signals, verified_interface=verified_interface)}\n\n"
```

- [ ] **Step 4.5 — Write the failing summarizer integration test (REAL code) — append to `test_github_summarizer.py`**

```python
# --- appended to test_github_summarizer.py ---
@pytest.mark.asyncio
async def test_summarizer_threads_verified_interface_into_prompt(monkeypatch):
    """The verdict stamped by the ingestor must reach the structured-extract
    prompt so the LLM is told the machine-verified interface (M1/M3 end-to-end)."""
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
        structured,
    )
    from website.features.summarization_engine.summarization.github import (
        summarizer as gh_mod,
    )

    async def _fake_run_dense_verify(*, client, ingest, precomputed_dense=None, cache=None):  # noqa: ARG001
        return dense_verify.DenseVerifyResult(
            dense_text="dense", missing_facts=[], stance=None, archetype=None,
            format_label=None, core_argument="x", closing_hook="y",
        )

    monkeypatch.setattr(gh_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()

    captured_prompt = {}

    async def fake_extract(self, ingest, text, **kwargs):
        from website.features.summarization_engine.core.models import (
            DetailedSummarySection, SummaryMetadata, SummaryResult,
        )
        # Render the prompt the summarizer built so we can assert on it.
        captured_prompt["text"] = self._prompt_builder(ingest, text, "{}")
        return SummaryResult(
            mini_title="ow/repo", brief_summary="b",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
            metadata=SummaryMetadata(
                source_type=SourceType.GITHUB, url=ingest.url,
                extraction_confidence="high", confidence_reason="ok",
                total_tokens_used=0, total_latency_ms=0,
            ),
        )

    # Keep the real __init__ so self._prompt_builder is the summarizer's builder.
    monkeypatch.setattr(structured.StructuredExtractor, "extract", fake_extract)

    ingest = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/ow/repo",
        original_url="https://github.com/ow/repo",
        raw_text="README\n# X\n</sub> Please cite </center>",
        extraction_confidence="high", confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
        metadata={"verified_interface": {
            "verified": True, "commands": ["mytool"], "kind": "cli",
            "label": "verified CLI interface — command(s): mytool",
            "source_files": ["pyproject.toml"],
        }},
    )

    await GitHubSummarizer(mock_gemini_client_inst(), {}).summarize(ingest)

    prompt = captured_prompt["text"].lower()
    assert "verified cli interface" in prompt
    assert "mytool" in captured_prompt["text"]
    # The fabricated tokens are never framed as must-preserve.
    assert "must be preserved verbatim" not in prompt


def mock_gemini_client_inst():
    from unittest.mock import AsyncMock

    class Client:
        generate = AsyncMock()

    return Client()
```

- [ ] **Step 4.6 — Run to FAIL (summarizer test)**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/test_github_summarizer.py -k verified_interface -v`
Expected: FAIL before Step 4.4 wiring (verdict not threaded → `verified cli interface` absent). After Steps 4.3–4.4 it should pass; if you run it before implementing, it fails as expected.

- [ ] **Step 4.7 — Run to PASS (prompt + summarizer)**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/test_prompt_variants.py tests/unit/summarization_engine/summarization/test_github_summarizer.py -v`
Expected: PASS. **GOTCHA:** the existing `test_focus_block_is_prepended_not_appended` / `test_unknown_archetype_returns_base_unchanged` tests assert on `select_github_prompt` / `STRUCTURED_EXTRACT_INSTRUCTION`, which this task does NOT change — they must stay green. If `_signals_slot`'s renamed header (`REPOSITORY SIGNALS:` vs the old `READMESIGNALS`) breaks any existing assertion, FLAG and adapt the test, but no existing test asserts on the old slot header (verified — only `test_prompt_variants.py` exercises `select_github_prompt`, not `_signals_slot`).

- [ ] **Step 4.8 — Commit**

```bash
git commit -m "fix: refusal-first GitHub interface label, demote README regex"
```

**Self-review:**
- The must-preserve framing for README surfaces is gone (`test_signals_slot_demotes_surface_to_corroboration`) — this is the verified root fix.
- Refusal-first is the default; verified label only on artifact presence (`test_signals_slot_refusal_first_when_no_verified_interface` / `..._uses_verified_label_on_artifact_hit`).
- The verdict threads ingest → summarizer → prompt (`test_summarizer_threads_verified_interface_into_prompt`).
- `_is_bogus_surface` is retained as a backstop (still filters `surfaces`), satisfying "blocklist is a backstop, not the primary defense".
- Existing `select_github_prompt` contract tests are untouched and remain green.

---

## TASK 5 — End-to-end fabrication-suppression test + config key + final lint

Lock the verified-token behavior at the summarizer boundary (the spec's headline test), add the `verify_interface` config key for operator visibility, and run one consolidated lint pass.

**Files:**
- Modify: `website/features/summarization_engine/config.yaml` (add `verify_interface: true` under `sources.github`, near line 71)
- Test: `tests/unit/summarization_engine/summarization/test_github_fallback.py` (extend with the fabricated-token + `requests`-overview cases) OR a new `test_github_interface_ladder.py`. Use a new file to keep concerns separate.
- Test (new): `tests/unit/summarization_engine/summarization/github/test_interface_ladder_e2e.py`

- [ ] **Step 5.1 — Write the failing E2E test (REAL code)**

```python
# tests/unit/summarization_engine/summarization/github/test_interface_ladder_e2e.py
"""Headline Wave-2 tests (Sol 3): the verified fabricated tokens are never
elevated to 'must-preserve'; a real manifest bin surfaces real commands; a
thin-API library lands on the defensible refusal-first overview."""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
)
from website.features.summarization_engine.summarization.github.manifest_signals import (
    build_interface_verdict,
)
from website.features.summarization_engine.summarization.github.prompts import (
    source_context_for,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    extract_signals,
)

# A README that produces the verified fabrication tokens via the regexes.
_TOXIC_README = """Repository
ow/thin
README
# Thin

<sub>note</sub> <center>logo</center>

Please cite this work. See /center for details.
"""


def test_fabricated_tokens_not_must_preserve_for_thin_api_repo():
    signals = extract_signals(raw_text=_TOXIC_README, metadata={"language": "Python"})
    # No manifest -> refusal-first verdict.
    verdict = build_interface_verdict({}).as_metadata()
    ctx = source_context_for(RepoArchetype.LIBRARY_THIN, signals, verified_interface=verdict)
    lowered = ctx.lower()
    # The fabricated tokens must NOT be framed as must-preserve / verbatim.
    assert "must be preserved verbatim" not in lowered
    # If a fabricated token leaks into the heuristic block at all, it is
    # explicitly labelled optional ("include ONLY if ... otherwise OMIT").
    if "/sub" in ctx or "--please" in lowered or "/center" in ctx:
        assert "include only if" in lowered
    # And the authoritative interface statement is refusal-first.
    assert "no verified interface artifact" in lowered


def test_real_package_json_bin_surfaces_real_command():
    verdict = build_interface_verdict(
        {"package.json": '{"name": "eslint", "bin": "bin/eslint.js"}'}
    ).as_metadata()
    ctx = source_context_for(RepoArchetype.CLI_TOOL, None, verified_interface=verdict)
    assert "eslint" in ctx
    assert "verified cli interface" in ctx.lower()


def test_requests_like_library_lands_on_defensible_overview():
    # `requests`: real HTTP library, NO manifest bin -> refusal-first overview.
    requests_readme = """Repository
psf/requests
README
# Requests
Requests is a simple, yet elegant, HTTP library.
```python
import requests
r = requests.get('https://example.com')
```
Install with `pip install requests`.
"""
    signals = extract_signals(raw_text=requests_readme, metadata={"language": "Python"})
    verdict = build_interface_verdict({}).as_metadata()  # no machine-verified CLI/HTTP artifact
    ctx = source_context_for(RepoArchetype.LIBRARY_THIN, signals, verified_interface=verdict)
    lowered = ctx.lower()
    assert "no verified interface artifact" in lowered
    # Install command is still surfaced (legitimate, low-fabrication signal).
    assert "pip install requests" in ctx
```

- [ ] **Step 5.2 — Run to FAIL**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/test_interface_ladder_e2e.py -v`
Expected: PASS if Tasks 1–4 are complete (this task adds no new production code — it is the acceptance lock). If run **before** Tasks 1–4, it fails at import (`manifest_signals` missing) or on the refusal-first assertion. Run it now to confirm it is green on top of Tasks 1–4; if any assertion fails, the regression is in Tasks 1–4 — fix there, do not weaken the assertion.

- [ ] **Step 5.3 — Add the config key (REAL change)**

In `website/features/summarization_engine/config.yaml`, under `sources.github` (after `doc_char_cap: 4000`, current line 73), add:

```yaml
    # Wave 2 (M3, Option B/D4): parse committed manifests (package.json bin,
    # pyproject [project.scripts]/console_scripts, setup.cfg, Cargo [[bin]],
    # OpenAPI) to ground the interface label. Token-gated: skipped when no
    # GITHUB_TOKEN (anonymous). +1-2 Contents GETs per repo.
    verify_interface: true
```

- [ ] **Step 5.4 — Final consolidated lint (batch, per project convention)**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m ruff check website/features/summarization_engine/summarization/github/manifest_signals.py website/features/summarization_engine/summarization/github/prompts.py website/features/summarization_engine/summarization/github/summarizer.py website/features/summarization_engine/source_ingest/github/ingest.py`
Expected: `All checks passed!` (fix any unused-import / line-length finding here, not per-task).

- [ ] **Step 5.5 — Full GitHub suite regression**

Run: `cd "C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.claude\worktrees\thirsty-dirac-c3a180" && python -m pytest tests/unit/summarization_engine/summarization/github/ tests/unit/summarization_engine/summarization/test_github_summarizer.py tests/unit/summarization_engine/summarization/test_github_fallback.py tests/unit/summarization_engine/summarization/test_github_schema.py tests/unit/summarization_engine/source_ingest/github/ -v`
Expected: PASS (all GitHub unit tests, old + new).

- [ ] **Step 5.6 — Commit**

```bash
git commit -m "test: lock GitHub interface-ladder fabrication suppression"
```

**Self-review:**
- The three verified fabricated tokens (`/sub`, `--Please`, `/center`) are never must-preserve for a thin-API repo (`test_fabricated_tokens_not_must_preserve_for_thin_api_repo`).
- A real `package.json` `bin` surfaces its real command (`test_real_package_json_bin_surfaces_real_command`).
- `requests` (real HTTP library, no manifest `bin`) → refusal-first overview while still surfacing `pip install requests` (`test_requests_like_library_lands_on_defensible_overview`).
- No-token / anonymous path and zero-wasted-GET behavior are covered in Task 3; `pyproject [project.scripts]` + `console_scripts`, Cargo `[[bin]]`, and `setup.cfg` console_scripts are covered in Tasks 1–2.
- `verify_interface` config key is operator-visible and defaults to the same `True` the code uses; lint is one final pass per the batch-ruff convention.

---

## Overall Self-review (whole plan)

- **Required-test coverage (all six mapped):**
  1. Fabricated `/sub` / `--Please` / `/center` NOT emitted for thin-API repos → Task 5 `test_fabricated_tokens_not_must_preserve_for_thin_api_repo` + Task 4 `test_signals_slot_demotes_surface_to_corroboration`.
  2. Real `package.json` `bin` surfaces real command → Task 1 `test_package_json_bin_*`, Task 2 `test_verdict_npm_bin_surfaces_real_command`, Task 5 `test_real_package_json_bin_surfaces_real_command`.
  3. `requests` (real HTTP lib, no manifest bin) → defensible "no machine-verified CLI/HTTP artifact" → Task 5 `test_requests_like_library_lands_on_defensible_overview`.
  4. No-token / anonymous → manifest verification SKIPPED + refusal-first, no fabrication/crash → Task 3 `test_no_token_skips_manifest_fetch_refusal_first`.
  5. Manifest absent from root listing → ZERO wasted fetch calls → Task 3 `test_absent_manifests_cause_zero_wasted_gets` + `test_manifest_fetch_only_hits_present_files`.
  6. `pyproject [project.scripts]` AND `console_scripts` both detected; Cargo `[[bin]]`; setup.cfg console_scripts → Task 1 `test_pyproject_project_scripts` / `test_pyproject_console_scripts_entry_points` / `test_cargo_*` / `test_setup_cfg_console_scripts`.
- **M1/M2/M3 mapped:** M1 (refusal-first, gated on artifact-presence not archetype.confidence) → Task 2 verdict + Task 4 `_signals_slot`. M2 (demote regex out of must-preserve, blocklist as backstop) → Task 4. M3 (parse manifests via Option B from the already-fetched root listing) → Tasks 1–3.
- **D4 honored:** reuses the root `/contents` listing pattern (Option B), fetches only present manifests via the existing `_fetch_file_contents`, no GraphQL, no new request mechanism, `+1–2` Contents GETs, token-gated, stdlib `tomllib`/`json` only, stays on `api.github.com`. The `+2`-listing-GET worst case (when `fetch_docs` is also on) is FLAGGED and within the researched `+1–2` budget.
- **Seam accuracy:** all file:line seams re-read this session (prompts.py 106–138, readme_signals.py 18/20/44, schema.py 181–192, ingest.py 68/70/119/148–189/471–484/527–553, summarizer.py 81–84/114/200–207, config.yaml 53–73). The parent roadmap's "interface label" is confirmed to NOT pre-exist; M1 creates it as a metadata key + prompt rendering (FLAGGED at top).
- **No placeholders:** every code step shows real, runnable code; every run step shows the exact `cd … && python -m pytest …` and the expected fail/pass.
- **Production discipline:** no protected knob touched (no GUNICORN/timeout/preload/rerank/SSE/Caddy/schema-gate/allowlist change; teal/amber UI untouched). Backward compatible — `verified_interface` is an additive metadata key, `verify_interface` defaults to current behavior plus the new (safe, graceful-degrading) stage. Forensic comments kept to ≤1–2 lines. Commits are 5–10 words with `feat:`/`fix:`/`test:` prefixes, no AI/tool names, no `Co-Authored-By`.
- **Residual risk / FLAGs:** (a) `openapi.*` is best-effort root-only (nested specs missed by design — noted, no recursive Trees call added); (b) `+2` listing GETs when both `verify_interface` and `fetch_docs` are on (within budget; optional follow-up to thread one listing); (c) cross-import `summarization.github.manifest_signals` into `source_ingest` is cycle-safe because `manifest_signals` imports only stdlib (verified) — re-confirm at implementation time if either module gains new imports; (d) the operator must provision the zero-permission fine-grained `GITHUB_TOKEN` on the droplet for the verified path to engage at scale (independent of this plan; absence degrades gracefully to refusal-first).
