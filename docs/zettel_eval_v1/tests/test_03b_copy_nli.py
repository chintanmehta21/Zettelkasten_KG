"""Tests for 03b_copy_nli_across_iters.py.

WIRED 2026-05-29. All fixtures use sandbox iter_ids that MUST NOT collide
with real iter_ids in judges.yaml::run_matrix (per the lesson from the
2026-05-29 test-pollution incident on iter-003-nli).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "03b_copy_nli_across_iters.py"
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"

# Sandbox iter_ids — verified non-colliding via test_sandbox_iter_ids_safe below
SRC_ITER = "iter-test-03b-src"
DST_ITER_A = "iter-test-03b-dst-a"
DST_ITER_B = "iter-test-03b-dst-b"


def _make_per_zettel(wz: str, source_type: str, *, nli: dict | None = None) -> dict:
    payload = {
        "g_eval": {"coherence": {"score": 2}, "fluency": {"score": 2}},
        "rubric": {"components": [], "anti_patterns_triggered": [],
                    "caps_applied": {"hallucination_cap": None,
                                      "omission_cap": None, "generic_cap": None}},
        "_meta": {"wz_zettel_id": wz, "source_type": source_type},
    }
    if nli is not None:
        payload["nli"] = nli
    return payload


def _write_zettel(iter_id: str, wz: str, source_type: str, payload: dict) -> None:
    overall = RUNS / iter_id / "_overall" / "per_zettel"
    by_src = RUNS / iter_id / source_type / "per_zettel"
    overall.mkdir(parents=True, exist_ok=True)
    by_src.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    (overall / f"{wz}.json").write_text(text, encoding="utf-8")
    (by_src / f"{wz}.json").write_text(text, encoding="utf-8")


def _cleanup():
    for it in (SRC_ITER, DST_ITER_A, DST_ITER_B):
        d = RUNS / it
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolate_sandbox():
    _cleanup()
    yield
    _cleanup()


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


def _real_nli_block(mean_ent: float = 0.78, n_claims: int = 12) -> dict:
    """A nontrivial nli block that we can fingerprint after copy."""
    return {
        "n_claims": n_claims,
        "mean_entailment": mean_ent,
        "max_contradict": 0.42,
        "hard_fail_flagged": False,
        "per_claim": [
            {"claim": f"c{i}", "entail_prob": 0.81, "contradict_prob": 0.11,
             "neutral_prob": 0.08, "verdict": "entailed"}
            for i in range(n_claims)
        ],
        "nli_model": "lytang/MiniCheck-DeBERTa-v3-Large",
        "nli_model_revision": "stub",
    }


def test_sandbox_iter_ids_safe():
    """Defense-in-depth: assert the sandbox iter_ids are NOT real iters."""
    import yaml as _yaml
    judges = REPO_ROOT / "docs" / "zettel_eval_v1" / "_config" / "judges.yaml"
    if not judges.exists():
        pytest.skip("judges.yaml not present")
    real_ids = {r.get("iter_id") for r in
                 _yaml.safe_load(judges.read_text(encoding="utf-8")).get("run_matrix", [])}
    for sandbox in (SRC_ITER, DST_ITER_A, DST_ITER_B):
        assert sandbox not in real_ids, (
            f"Sandbox {sandbox!r} collides with run matrix — rename before running."
        )


def test_copies_nli_block_to_destination():
    nli = _real_nli_block()
    _write_zettel(SRC_ITER, "aaa", "web", _make_per_zettel("aaa", "web", nli=nli))
    _write_zettel(DST_ITER_A, "aaa", "web", _make_per_zettel("aaa", "web", nli=None))

    res = _run("--from", SRC_ITER, "--to", DST_ITER_A)
    assert res.returncode == 0, f"failed: {res.stderr or res.stdout}"

    # _overall and per-source both updated
    for sub in ("_overall", "web"):
        p = RUNS / DST_ITER_A / sub / "per_zettel" / "aaa.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["nli"] == nli


def test_overwrites_existing_fake_nli_in_destination():
    """Critical: when the destination has a FAKE stub block (from the 2026-05-29
    test-pollution pattern), the copy must replace it with the real block."""
    real = _real_nli_block(mean_ent=0.78)
    fake = {"mean_entailment": 0.05, "max_contradict": 0.85,
             "hard_fail_flagged": True, "per_claim": [
                 {"claim": "c", "entail_prob": 0.05, "contradict_prob": 0.85,
                  "neutral_prob": 0.10, "verdict": "contradicted"}],
             "n_claims": 1, "nli_model": "FAKE-minicheck",
             "nli_model_revision": "fake-revision"}
    _write_zettel(SRC_ITER, "aaa", "web", _make_per_zettel("aaa", "web", nli=real))
    _write_zettel(DST_ITER_A, "aaa", "web", _make_per_zettel("aaa", "web", nli=fake))

    res = _run("--from", SRC_ITER, "--to", DST_ITER_A)
    assert res.returncode == 0
    out = json.loads(
        (RUNS / DST_ITER_A / "_overall" / "per_zettel" / "aaa.json").read_text("utf-8")
    )
    assert out["nli"]["mean_entailment"] == 0.78
    assert out["nli"]["nli_model"] == "lytang/MiniCheck-DeBERTa-v3-Large"


def test_skips_destination_zettels_without_source_match():
    """Destination has zettels that aren't in source → orphan count, no crash."""
    _write_zettel(SRC_ITER, "aaa", "web", _make_per_zettel("aaa", "web", nli=_real_nli_block()))
    _write_zettel(DST_ITER_A, "aaa", "web", _make_per_zettel("aaa", "web"))
    _write_zettel(DST_ITER_A, "bbb", "youtube", _make_per_zettel("bbb", "youtube"))  # orphan

    res = _run("--from", SRC_ITER, "--to", DST_ITER_A)
    assert res.returncode == 0
    assert "orphans" in res.stdout
    # bbb gets no nli; aaa does
    a = json.loads((RUNS / DST_ITER_A / "_overall" / "per_zettel" / "aaa.json").read_text("utf-8"))
    b = json.loads((RUNS / DST_ITER_A / "_overall" / "per_zettel" / "bbb.json").read_text("utf-8"))
    assert "nli" in a
    assert "nli" not in b


def test_dry_run_does_not_write():
    nli = _real_nli_block()
    _write_zettel(SRC_ITER, "aaa", "web", _make_per_zettel("aaa", "web", nli=nli))
    _write_zettel(DST_ITER_A, "aaa", "web", _make_per_zettel("aaa", "web"))

    res = _run("--from", SRC_ITER, "--to", DST_ITER_A, "--dry-run")
    assert res.returncode == 0
    assert "[DRY-RUN]" in res.stdout
    d = json.loads((RUNS / DST_ITER_A / "_overall" / "per_zettel" / "aaa.json").read_text("utf-8"))
    assert "nli" not in d


def test_fails_loud_when_source_iter_missing():
    res = _run("--from", "iter-does-not-exist-xyz", "--to", DST_ITER_A)
    assert res.returncode != 0
    assert "not found" in (res.stderr + res.stdout)


def test_skips_destination_iter_with_missing_per_zettel_dir():
    _write_zettel(SRC_ITER, "aaa", "web", _make_per_zettel("aaa", "web", nli=_real_nli_block()))
    # DST_ITER_A intentionally not created — should be reported as SKIP

    res = _run("--from", SRC_ITER, "--to", DST_ITER_A)
    # Returns 0 because partial copy is OK semantics
    assert res.returncode == 0
    assert "SKIP" in res.stdout


def test_multiple_destinations_in_one_invocation():
    nli = _real_nli_block()
    _write_zettel(SRC_ITER, "aaa", "web", _make_per_zettel("aaa", "web", nli=nli))
    _write_zettel(DST_ITER_A, "aaa", "web", _make_per_zettel("aaa", "web"))
    _write_zettel(DST_ITER_B, "aaa", "web", _make_per_zettel("aaa", "web"))

    res = _run("--from", SRC_ITER, "--to", DST_ITER_A, DST_ITER_B)
    assert res.returncode == 0
    for dst in (DST_ITER_A, DST_ITER_B):
        d = json.loads((RUNS / dst / "_overall" / "per_zettel" / "aaa.json").read_text("utf-8"))
        assert d["nli"]["mean_entailment"] == 0.78


def test_refuses_to_copy_when_source_has_zero_nli():
    """If the source iter has no nli blocks (real NLI not yet run), the copy
    must abort rather than silently writing nothing."""
    _write_zettel(SRC_ITER, "aaa", "web", _make_per_zettel("aaa", "web", nli=None))
    _write_zettel(DST_ITER_A, "aaa", "web", _make_per_zettel("aaa", "web"))

    res = _run("--from", SRC_ITER, "--to", DST_ITER_A)
    assert res.returncode != 0
    assert "zero nli blocks" in (res.stderr + res.stdout)
