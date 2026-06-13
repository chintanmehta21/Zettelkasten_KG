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
import tomllib
from dataclasses import dataclass, field


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
