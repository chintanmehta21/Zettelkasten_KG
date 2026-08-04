"""Steps 2-4 of the memory remediation (2026-08-05).

The droplet's app cgroup sits with ``mem_current + swap_current`` at almost
exactly ``memory.max`` (1.6 GiB), held there by continuous swap eviction, and
had OOM-killed two processes. These are the cheap, reversible footprint
reductions that defend the 2-worker + ``--preload`` design rather than
abandoning it.

Step 2 (ORT session options) was already implemented in iter-03; the tests here
pin it so it cannot silently regress.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _main_ast() -> ast.Module:
    return ast.parse((REPO_ROOT / "website/main.py").read_text(encoding="utf-8"))


# --- step 2: ONNX Runtime session options (pin the existing iter-03 work) ---


def _cascade_src() -> str:
    return (
        REPO_ROOT / "website/features/rag_pipeline/rerank/cascade.py"
    ).read_text(encoding="utf-8")


def test_ort_session_is_single_threaded():
    """1 vCPU: ORT thread pools are pure memory + contention overhead."""
    src = _cascade_src()
    assert "opts.intra_op_num_threads = 1" in src
    assert "opts.inter_op_num_threads = 1" in src


def test_ort_cpu_mem_arena_disabled():
    """Arena holds the session-lifetime high-water mark; we cap at per-call.

    This is also why arena_extend_strategy is irrelevant for us — with the
    arena off there is no extend strategy to tune.
    """
    src = _cascade_src()
    assert "opts.enable_cpu_mem_arena = False" in src
    assert "opts.enable_mem_pattern = False" in src


def test_ort_debug_buffers_suppressed():
    src = _cascade_src()
    assert "opts.log_severity_level = 3" in src
    assert "opts.enable_profiling = False" in src


# --- step 3: gc.freeze() before fork ---------------------------------------


def test_gc_freeze_runs_at_module_scope_prefork():
    """Must be module-level in main.py — that IS the pre-fork point under --preload.

    Moving it inside the lifespan would run it per-worker POST-fork, which both
    misses the COW benefit entirely and risks freezing request-time state.
    """
    tree = _main_ast()
    assert any(
        isinstance(n, ast.FunctionDef) and n.name == "_freeze_preloaded_heap"
        for n in tree.body
    ), "gc.freeze() helper missing — COW is broken by gen-2 scans"

    # Walk only MODULE-level statements. A call reachable from here runs in the
    # master pre-fork; one nested in a function/lifespan would run per-worker
    # post-fork, missing the COW benefit entirely.
    called_at_module_scope = {
        n.func.id
        for stmt in tree.body
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for n in ast.walk(stmt)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_freeze_preloaded_heap" in called_at_module_scope, (
        "gc.freeze call site is not at module scope — it would run post-fork"
    )


def test_gc_freeze_collects_before_freezing():
    """Freezing before collecting would make genuine garbage permanent.

    Compares AST statement order, not string offsets — the docstring mentions
    ``gc.freeze()`` before the real call and defeats a naive text search.
    """
    fn = next(
        n
        for n in _main_ast().body
        if isinstance(n, ast.FunctionDef) and n.name == "_freeze_preloaded_heap"
    )
    order = [
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "gc"
    ]
    assert "gc.collect" in order and "gc.freeze" in order
    assert order.index("gc.collect") < order.index("gc.freeze"), (
        f"gc.collect() must precede gc.freeze(); got {order}"
    )


def test_gc_freeze_is_operator_reversible():
    src = (REPO_ROOT / "website/main.py").read_text(encoding="utf-8")
    assert "GC_FREEZE_PREFORK" in src, "no kill-switch for A/B-ing the COW effect"


def test_gc_freeze_never_blocks_boot():
    src = (REPO_ROOT / "website/main.py").read_text(encoding="utf-8")
    guard = src[src.index("GC_FREEZE_PREFORK") :]
    assert "except Exception" in guard, "an optimisation must not be able to fail boot"


def test_freeze_helper_actually_freezes(monkeypatch):
    """Behavioural check, not just a source grep."""
    import gc

    from website import main as main_mod

    baseline = gc.get_freeze_count()
    try:
        stats = main_mod._freeze_preloaded_heap()
        assert stats["frozen"] >= baseline
        assert gc.get_freeze_count() > 0
    finally:
        gc.unfreeze()


# --- step 4: MALLOC_ARENA_MAX ----------------------------------------------


def test_malloc_arena_max_is_an_image_env():
    """glibc reads this at first malloc — it cannot be set from Python later."""
    dockerfile = (REPO_ROOT / "ops/Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"MALLOC_ARENA_MAX=2", dockerfile), (
        "MALLOC_ARENA_MAX not set in the image; per-arena fragmentation slack "
        "returns on the next build"
    )


def test_malloc_arena_max_is_in_the_runtime_stage():
    """Setting it only in the builder stage would do nothing at runtime."""
    dockerfile = (REPO_ROOT / "ops/Dockerfile").read_text(encoding="utf-8")
    # Last FROM starts the runtime stage; the ENV must come after it.
    last_from = dockerfile.rindex("\nFROM ")
    assert "MALLOC_ARENA_MAX" in dockerfile[last_from:], (
        "MALLOC_ARENA_MAX is set before the final FROM — it won't reach runtime"
    )
