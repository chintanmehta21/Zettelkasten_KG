import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "apply_iter08_migrations",
    Path(__file__).resolve().parents[3] / "ops" / "scripts" / "apply_iter08_migrations.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_wrap_transactional_adds_begin_commit():
    wrapped = _mod._wrap_transactional("CREATE TYPE foo AS ENUM ('a');")
    assert wrapped.startswith("BEGIN;")
    assert wrapped.rstrip().endswith("COMMIT;")
    assert "CREATE TYPE foo AS ENUM ('a');" in wrapped


def test_idempotency_ok_recognises_already_exists():
    assert _mod._is_idempotency_ok('type "kg_link_relation" already exists')
    assert _mod._is_idempotency_ok('column "relation_type" already exists')
    assert _mod._is_idempotency_ok('duplicate object')
    assert not _mod._is_idempotency_ok('syntax error at or near "FROM"')
