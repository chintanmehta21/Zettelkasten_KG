"""Tests for deterministic manifest interface extraction (Wave 2, M3 top rung).

Each parser takes raw manifest text and returns a list of verified interface
command/entry-point names. Parsers never raise: malformed input -> []."""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.manifest_signals import (
    InterfaceVerdict,
    MANIFEST_FILENAMES,
    build_interface_verdict,
    detect_openapi,
    parse_cargo_bins,
    parse_package_json_bin,
    parse_pyproject_scripts,
    parse_setup_cfg_console_scripts,
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
