"""Phase 8.0 Rev+ CI gate for repeatable v2 migrations.

Repeatable migrations live in supabase/website/_v2/repeatable/ and are
named R__<slug>.sql. They re-run on every deploy when their checksum
changes, so they MUST be idempotent. This module enforces that contract
statically: every R__ file must contain only CREATE OR REPLACE /
DROP IF EXISTS-style constructs — no CREATE TABLE, no INSERT, no ALTER
that would error on second apply.

If a repeatable migration must do anything destructive or one-shot, it
should be a versioned migration instead.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
REPEATABLE_DIR = ROOT / "supabase" / "website" / "_v2" / "repeatable"

# Patterns that are NOT safe to re-apply unconditionally. We deliberately
# allow CREATE INDEX IF NOT EXISTS and DROP ... IF EXISTS.
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bCREATE\s+TABLE\b(?!\s+IF\s+NOT\s+EXISTS)", "CREATE TABLE without IF NOT EXISTS"),
    (r"\bINSERT\s+INTO\b", "INSERT (use ON CONFLICT DO NOTHING in a versioned file)"),
    (r"\bUPDATE\s+[a-zA-Z_.]+\s+SET\b", "UPDATE (destructive — make it a versioned file)"),
    (r"\bDELETE\s+FROM\b", "DELETE (destructive — make it a versioned file)"),
    (r"\bALTER\s+TABLE\b", "ALTER TABLE (use a versioned migration)"),
    (r"\bDROP\s+TABLE\b(?!\s+IF\s+EXISTS)", "DROP TABLE without IF EXISTS"),
    (r"\bCREATE\s+TYPE\b(?!\s+IF\s+NOT\s+EXISTS)", "CREATE TYPE without IF NOT EXISTS"),
)

# Filename regex must mirror apply_migrations._V2_REPEATABLE_NAME_RE.
_REPEATABLE_NAME_RE = re.compile(r"^R__[a-z0-9_]+\.sql$")


def _strip_noise(sql: str) -> str:
    """Remove line/block comments AND dollar-quoted bodies before scanning.

    The forbidden-construct scan targets *top-level* statements executed at
    migration apply time. DML inside a ``CREATE OR REPLACE FUNCTION ... $$ ...
    $$`` body runs only when the function is later *called*, not at apply
    time, and re-applying the CREATE OR REPLACE is itself idempotent. Without
    stripping the body, a perfectly idempotent code-object repeatable (e.g. an
    upsert RPC whose plpgsql body contains INSERT/UPDATE) false-fails. We still
    catch genuine top-level INSERT/UPDATE/DELETE/ALTER/CREATE TABLE.
    """
    stripped = re.sub(r"--[^\n]*", "", sql)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
    # Dollar-quoted blocks: $$...$$ or $tag$...$tag$ (tag backref).
    stripped = re.sub(r"\$(\w*)\$.*?\$\1\$", " ", stripped, flags=re.DOTALL)
    return stripped


def _repeatable_files() -> list[Path]:
    if not REPEATABLE_DIR.is_dir():
        return []
    return sorted(REPEATABLE_DIR.glob("*.sql"))


def test_repeatable_dir_present() -> None:
    """The repeatable/ subdir must exist once Rev+ has shipped."""
    assert REPEATABLE_DIR.is_dir(), (
        f"Expected repeatable migration dir at {REPEATABLE_DIR}"
    )


@pytest.mark.parametrize("path", _repeatable_files(), ids=lambda p: p.name)
def test_repeatable_filename_shape(path: Path) -> None:
    assert _REPEATABLE_NAME_RE.match(path.name), (
        f"{path.name} does not match R__<slug>.sql"
    )


@pytest.mark.parametrize("path", _repeatable_files(), ids=lambda p: p.name)
def test_repeatable_body_is_idempotent(path: Path) -> None:
    """Static check: no non-idempotent DDL/DML in a repeatable file."""
    sql = path.read_text(encoding="utf-8")
    stripped = _strip_noise(sql)
    for pattern, label in _FORBIDDEN_PATTERNS:
        if re.search(pattern, stripped, flags=re.IGNORECASE):
            pytest.fail(
                f"Repeatable migration {path.name} contains forbidden "
                f"non-idempotent construct: {label}. Move this to a "
                "versioned migration (NN_<slug>.sql)."
            )


@pytest.mark.parametrize("path", _repeatable_files(), ids=lambda p: p.name)
def test_repeatable_uses_create_or_replace_or_drop_if_exists(path: Path) -> None:
    """Every repeatable file must contain at least one idempotent definition."""
    sql = path.read_text(encoding="utf-8").upper()
    assert any(
        token in sql
        for token in (
            "CREATE OR REPLACE",
            "CREATE INDEX IF NOT EXISTS",
            "DROP FUNCTION IF EXISTS",
            "DROP INDEX IF EXISTS",
            "NOTIFY ",  # pgrst reload-only files are fine
        )
    ), (
        f"{path.name} has no idempotent definition (CREATE OR REPLACE, "
        "CREATE INDEX IF NOT EXISTS, DROP ... IF EXISTS, or NOTIFY)."
    )


def _has_forbidden(sql: str) -> bool:
    s = _strip_noise(sql)
    return any(
        re.search(p, s, flags=re.IGNORECASE) for p, _ in _FORBIDDEN_PATTERNS
    )


def test_guard_still_catches_top_level_dml() -> None:
    """Regression: stripping function bodies must NOT weaken the guard for
    genuine top-level non-idempotent statements."""
    assert _has_forbidden("INSERT INTO content.seed (a) VALUES (1);")
    assert _has_forbidden("UPDATE content.foo SET x = 1;")
    assert _has_forbidden("DELETE FROM content.foo;")
    assert _has_forbidden("ALTER TABLE content.foo ADD COLUMN z int;")
    assert _has_forbidden("CREATE TABLE content.foo (id int);")


def test_guard_allows_dml_inside_function_body() -> None:
    """A CREATE OR REPLACE FUNCTION is idempotent regardless of the DML its
    plpgsql body performs at call-time — must not false-fail."""
    fn = (
        "CREATE OR REPLACE FUNCTION content.f() RETURNS void "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "INSERT INTO content.t (a) VALUES (1) ON CONFLICT DO NOTHING; "
        "UPDATE content.t SET a = 2; DELETE FROM content.t; "
        "END $$;\nNOTIFY pgrst, 'reload schema';"
    )
    assert not _has_forbidden(fn)
    # Tagged dollar-quote variant must also be stripped.
    fn_tag = fn.replace("$$", "$body$")
    assert not _has_forbidden(fn_tag)
