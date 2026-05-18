"""Make docs/rag_eval_v2/scripts importable as a package-free module set."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "docs" / "rag_eval_v2" / "scripts"


def _load(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def run_eval_v2():
    return _load("rag_eval_v2_run", "run_eval_v2.py")


@pytest.fixture(scope="session")
def compare_baseline():
    return _load("rag_eval_v2_compare", "compare_baseline.py")
