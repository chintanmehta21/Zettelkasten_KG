"""Test 03_run_nli.py: extends per-zettel JSONs with nli_* fields from MiniCheck-DeBERTa.

Uses a FAKE MiniCheck (deterministic canned predictions) to avoid 1.7GB download in CI/dev.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "docs" / "zettel_eval_v1" / "scripts" / "03_run_nli.py"
RUNS = REPO_ROOT / "docs" / "zettel_eval_v1" / "runs"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT)
    )


# NEVER write to a real iter_id — the script's --force-refresh permanently
# overwrites per_zettel JSONs in the live runs/ tree. The earlier version of
# these tests used "iter-003-nli" directly and polluted ~79 of 81 zettels with
# FakeMiniCheck stub values (ent=0.05, con=0.85), invalidating a real NLI run.
# Caught 2026-05-29. New tests use a sandbox iter_id and cleanup in fixture.

_TEST_ITER = "iter-test-fake-nli-sandbox"  # MUST NOT collide with any real iter


def _setup_sandbox_iter():
    """Copy a couple of iter-001 per_zettel JSONs into the sandbox iter so 03
    has structurally-valid input to augment. Returns the sandbox _overall dir."""
    src = RUNS / "iter-001-baseline" / "_overall" / "per_zettel"
    # iter-001-baseline is a generated run tree (gitignored) — absent in CI and
    # fresh clones. Skip (not fail) when its source fixtures aren't present; the
    # test runs for the operator who has done a real eval run.
    if not src.exists() or not any(src.glob("*.json")):
        pytest.skip(
            "runs/iter-001-baseline per_zettel fixtures absent "
            "(gitignored; produced by a real eval run)"
        )
    dst_overall = RUNS / _TEST_ITER / "_overall" / "per_zettel"
    dst_overall.mkdir(parents=True, exist_ok=True)
    dst_web = RUNS / _TEST_ITER / "web" / "per_zettel"
    dst_web.mkdir(parents=True, exist_ok=True)
    # Take just the first 2 — full corpus is unnecessary for test invariants
    for f in sorted(src.glob("*.json"))[:2]:
        content = f.read_text(encoding="utf-8", errors="replace")
        (dst_overall / f.name).write_text(content, encoding="utf-8")
        (dst_web / f.name).write_text(content, encoding="utf-8")
    return dst_overall


def _teardown_sandbox_iter():
    """Remove the sandbox iter tree — leaves no fake-NLI residue in runs/."""
    import shutil
    d = RUNS / _TEST_ITER
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def _set_judge_contradiction(sandbox_overall: Path, *, contradicted: bool) -> None:
    """Force the judge half of the LOOSE AND-gate on every sandbox per_zettel
    JSON. With ``contradicted=True`` we inject one ``summac_lite.contradicted_sentence``
    so the AND-gate can fire; with ``False`` we clear it so the gate must
    suppress an NLI-only flag. Mirrors into the per-source copy too so the
    script's in-place rewrite stays consistent."""
    for f in sandbox_overall.glob("*.json"):
        p = json.loads(f.read_text(encoding="utf-8"))
        summac = p.get("summac_lite")
        if not isinstance(summac, dict):
            summac = {}
            p["summac_lite"] = summac
        summac["contradicted_sentences"] = (
            ["A fabricated sentence the judge flagged."] if contradicted else []
        )
        f.write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # mirror into web/ per-source copy (same wz filename)
        web = RUNS / _TEST_ITER / "web" / "per_zettel" / f.name
        if web.exists():
            web.write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def test_extends_per_zettel_with_nli_fields():
    """After --fake-nli on the sandbox iter, per_zettel JSON gains nli fields."""
    try:
        dst_overall = _setup_sandbox_iter()
        res = _run("--iter", _TEST_ITER, "--fake-nli", "--fake-entail-prob", "0.85")
        assert res.returncode == 0, f"03 failed: {res.stderr or res.stdout}"

        extended = list(dst_overall.glob("*.json"))
        assert len(extended) >= 1
        for f in extended:
            p = json.loads(f.read_text(encoding="utf-8"))
            nli = p.get("nli") or {}
            assert "mean_entailment" in nli
            assert "max_contradict" in nli
            assert "per_claim" in nli
            assert isinstance(nli["per_claim"], list)
            assert 0.0 <= float(nli["mean_entailment"]) <= 1.0
    finally:
        _teardown_sandbox_iter()


def test_route_verdict_unit():
    """OR-with-review routing (route_verdict) — pure-function truth table.
    Adopted 2026-05-30, replacing the strict/LOOSE AND-gate."""
    m = _reload_module()
    assert m.route_verdict(True, 3) == ("hard_fail", "")       # both fire
    assert m.route_verdict(True, 0) == ("review", "nli_only")  # NLI only
    assert m.route_verdict(False, 5) == ("review", "judge_only")  # judge only
    assert m.route_verdict(False, 0) == ("clean", "")          # neither


def test_route_hard_fail_when_both_fire():
    """NLI contradict >= 0.7 AND >=1 judge contradicted_sentence -> route='hard_fail'."""
    try:
        dst_overall = _setup_sandbox_iter()
        _set_judge_contradiction(dst_overall, contradicted=True)  # judge fires
        res = _run("--iter", _TEST_ITER, "--fake-nli", "--fake-entail-prob", "0.05",
                   "--fake-contradict-prob", "0.85", "--force-refresh")  # NLI fires
        assert res.returncode == 0, f"03 failed: {res.stderr}"
        f = next((RUNS / _TEST_ITER / "_overall" / "per_zettel").glob("*.json"))
        p = json.loads(f.read_text(encoding="utf-8"))
        assert p["nli"]["nli_threshold_flag"] is True
        assert p["nli"]["judge_contradicted_count"] >= 1
        assert p["nli"]["route"] == "hard_fail"
        assert p["nli"]["hard_fail_flagged"] is True  # back-compat == (route=hard_fail)
    finally:
        _teardown_sandbox_iter()


def test_nli_only_routes_to_review():
    """NLI fires (0.85) but judge flagged nothing -> route='review'/nli_only,
    NOT hard_fail. Under OR-with-review the NLI catch is NOT silently dropped
    (old AND-gate cleared it); it goes to the human queue instead."""
    try:
        dst_overall = _setup_sandbox_iter()
        _set_judge_contradiction(dst_overall, contradicted=False)  # judge clean
        res = _run("--iter", _TEST_ITER, "--fake-nli", "--fake-entail-prob", "0.05",
                   "--fake-contradict-prob", "0.85", "--force-refresh")  # NLI fires
        assert res.returncode == 0, f"03 failed: {res.stderr}"
        f = next((RUNS / _TEST_ITER / "_overall" / "per_zettel").glob("*.json"))
        p = json.loads(f.read_text(encoding="utf-8"))
        assert p["nli"]["nli_threshold_flag"] is True
        assert p["nli"]["judge_contradicted_count"] == 0
        assert p["nli"]["route"] == "review"
        assert p["nli"]["review_reason"] == "nli_only"
        assert p["nli"]["hard_fail_flagged"] is False
    finally:
        _teardown_sandbox_iter()


def test_judge_only_routes_to_review():
    """Judge flagged but NLI is BELOW threshold (0.05 < 0.7) -> route='review'/
    judge_only. THIS is the wz=1c0af8ec fix: the old AND-gate CLEARED a real
    hallucination here (NLI just under threshold); OR-with-review catches it."""
    try:
        dst_overall = _setup_sandbox_iter()
        _set_judge_contradiction(dst_overall, contradicted=True)  # judge fires
        res = _run("--iter", _TEST_ITER, "--fake-nli", "--fake-entail-prob", "0.95",
                   "--fake-contradict-prob", "0.05", "--force-refresh")  # NLI below T
        assert res.returncode == 0, f"03 failed: {res.stderr}"
        f = next((RUNS / _TEST_ITER / "_overall" / "per_zettel").glob("*.json"))
        p = json.loads(f.read_text(encoding="utf-8"))
        assert p["nli"]["nli_threshold_flag"] is False
        assert p["nli"]["judge_contradicted_count"] >= 1
        assert p["nli"]["route"] == "review"
        assert p["nli"]["review_reason"] == "judge_only"
        assert p["nli"]["hard_fail_flagged"] is False
    finally:
        _teardown_sandbox_iter()


def test_neither_routes_to_clean():
    """NLI below threshold AND judge clean -> route='clean'."""
    try:
        dst_overall = _setup_sandbox_iter()
        _set_judge_contradiction(dst_overall, contradicted=False)  # judge clean
        res = _run("--iter", _TEST_ITER, "--fake-nli", "--fake-entail-prob", "0.95",
                   "--fake-contradict-prob", "0.05", "--force-refresh")  # NLI below T
        assert res.returncode == 0, f"03 failed: {res.stderr}"
        f = next((RUNS / _TEST_ITER / "_overall" / "per_zettel").glob("*.json"))
        p = json.loads(f.read_text(encoding="utf-8"))
        assert p["nli"]["route"] == "clean"
        assert p["nli"]["hard_fail_flagged"] is False
    finally:
        _teardown_sandbox_iter()


# ---------------------------------------------------------------------------
# HF_TOKEN auto-loader from new_envs.txt — added 2026-05-29
# ---------------------------------------------------------------------------


def _reload_module(*, scrub_hf_token: bool = True):
    """Reload 03_run_nli.py as a fresh module. The module-level
    ``_HF_TOKEN_LOADED = _load_hf_token_from_new_envs()`` runs during the
    re-import and WILL populate ``os.environ["HF_TOKEN"]`` from the real
    operator new_envs.txt. Tests that exercise the parser path must scrub
    that env-var post-import so the function's env-short-circuit doesn't
    swallow their test injection. Pass ``scrub_hf_token=False`` only when
    the test explicitly wants to verify the override-precedence behavior."""
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location("zettel_eval_v1_03_run_nli_reload", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    if scrub_hf_token:
        os.environ.pop("HF_TOKEN", None)
    return m


def _write_new_envs(tmp_path, content: str):
    p = tmp_path / "new_envs.txt"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def _clean_hf_env(monkeypatch):
    """Strip HF_TOKEN so the loader's env-short-circuit doesn't mask the parser
    path. Test sets it intentionally where needed."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    yield


def test_hf_token_loader_prefers_read_over_admin(tmp_path, _clean_hf_env):
    """When both HF_READ_TOKEN and HF_ADMIN_TOKEN are in new_envs.txt, the
    least-privilege HF_READ_TOKEN must win (model downloads only need read)."""
    import os
    nef = _write_new_envs(tmp_path, (
        "# fake new_envs\n"
        "HF_READ_TOKEN : hf_readread1234567890abcdef\n"
        "HF_ADMIN_TOKEN : hf_adminadmin1234567890ab\n"
    ))
    m = _reload_module()
    tok = m._load_hf_token_from_new_envs(candidates=[nef])
    assert tok == "hf_readread1234567890abcdef"
    assert os.environ["HF_TOKEN"] == "hf_readread1234567890abcdef"


def test_hf_token_loader_respects_explicit_env_override(tmp_path, monkeypatch):
    """If HF_TOKEN is already set in env (explicit operator override), the
    loader must NOT overwrite it from new_envs.txt — explicit wins."""
    import os
    monkeypatch.setenv("HF_TOKEN", "hf_explicitOverrideValue123")
    nef = _write_new_envs(tmp_path, "HF_READ_TOKEN : hf_fromFileDoNotUse\n")
    # scrub_hf_token=False so the override survives the reload
    m = _reload_module(scrub_hf_token=False)
    tok = m._load_hf_token_from_new_envs(candidates=[nef])
    assert tok == "hf_explicitOverrideValue123"
    assert os.environ["HF_TOKEN"] == "hf_explicitOverrideValue123"


def test_hf_token_loader_returns_none_when_missing(tmp_path, _clean_hf_env):
    """No HF_*_TOKEN line in any candidate file → returns None, no env-var
    mutation. Loader must not raise on a missing-file path either."""
    import os
    empty = _write_new_envs(tmp_path, "# nothing interesting here\nSOME_OTHER=value\n")
    missing = tmp_path / "does-not-exist.txt"
    m = _reload_module()
    tok = m._load_hf_token_from_new_envs(candidates=[missing, empty])
    assert tok is None
    assert "HF_TOKEN" not in os.environ


def test_hf_token_loader_handles_equals_separator(tmp_path, _clean_hf_env):
    """Some env files use ``KEY=VALUE`` (POSIX) instead of ``KEY : VALUE``;
    both must work since operators copy from different sources."""
    nef = _write_new_envs(tmp_path, "HF_READ_TOKEN=hf_equalsSeparator0987654321\n")
    m = _reload_module()
    assert m._load_hf_token_from_new_envs(candidates=[nef]) == "hf_equalsSeparator0987654321"


def test_hf_token_loader_ignores_comments_and_blanks(tmp_path, _clean_hf_env):
    """Lines starting with # and empty lines must not be parsed as keys."""
    nef = _write_new_envs(tmp_path, (
        "\n"
        "# === HuggingFace ===\n"
        "# HF_READ_TOKEN should be ignored when in a comment\n"
        "\n"
        "HF_READ_TOKEN : hf_realToken1234567890\n"
        "# trailing comment\n"
    ))
    m = _reload_module()
    assert m._load_hf_token_from_new_envs(candidates=[nef]) == "hf_realToken1234567890"


def test_hf_token_loader_strips_surrounding_quotes(tmp_path, _clean_hf_env):
    """If the operator quoted the value (common when copying from a JSON
    payload), strip the wrapping quotes only — not internal ones."""
    nef = _write_new_envs(tmp_path, 'HF_READ_TOKEN : "hf_quotedValue123"\n')
    m = _reload_module()
    assert m._load_hf_token_from_new_envs(candidates=[nef]) == "hf_quotedValue123"


# ---------------------------------------------------------------------------
# _extract_claims tier selection (atomic_facts cache vs regex) — added 2026-05-30
# This is the iter-003 false-positive root-cause fix: prefer clean cached
# atomic_facts (FActScore/RAGAS/FineSurE standard) over noisy regex split.
# ---------------------------------------------------------------------------


def test_extract_claims_prefers_atomic_facts_cache(tmp_path, monkeypatch):
    """Tier 1: when an atomic_facts cache entry exists for the zettel's
    (url, source_type, PROMPT_VERSION) key, _extract_claims returns those
    clean propositions tagged 'atomic_facts' — NOT the noisy regex split."""
    from website.features.summarization_engine.core.cache import FsContentCache
    from website.features.summarization_engine.evaluator.prompts import PROMPT_VERSION

    m = _reload_module()
    # Redirect module cache root to an isolated tmp dir — never touch real _cache.
    monkeypatch.setattr(m, "CACHE", tmp_path)

    url = "https://example.com/article"
    source_type = "web"
    FsContentCache(root=tmp_path, namespace="atomic_facts").put(
        (url, source_type, PROMPT_VERSION),
        {"facts": [
            {"claim": "Alpha is a clean atomic proposition.", "importance": 5},
            {"claim": "Beta is another grounded fact.", "importance": 4},
        ]},
    )
    meta_json = {"normalized_url": url, "source_type": source_type}
    # Deliberately noisy summary the regex path would shred into fragments:
    summary_json = {"detailed_summary": "## Header\n- 1.\nis."}
    claims, provenance = m._extract_claims({}, summary_json, meta_json)
    assert provenance == "atomic_facts"
    assert claims == [
        "Alpha is a clean atomic proposition.",
        "Beta is another grounded fact.",
    ]


def test_extract_claims_falls_back_to_regex_on_cache_miss(tmp_path, monkeypatch):
    """Tier 2: no atomic_facts cache entry -> regex sentence-split fallback,
    tagged 'regex_fallback'. Preserves legacy behavior for cache misses."""
    m = _reload_module()
    monkeypatch.setattr(m, "CACHE", tmp_path)  # empty cache dir
    meta_json = {"normalized_url": "https://no-cache.example", "source_type": "web"}
    summary_json = {"detailed_summary": "First sentence. Second sentence."}
    claims, provenance = m._extract_claims({}, summary_json, meta_json)
    assert provenance == "regex_fallback"
    assert claims == ["First sentence.", "Second sentence."]


def test_extract_claims_regex_when_no_meta(tmp_path, monkeypatch):
    """No meta_json -> cannot derive cache key -> regex fallback (no crash)."""
    m = _reload_module()
    monkeypatch.setattr(m, "CACHE", tmp_path)
    claims, provenance = m._extract_claims({}, {"detailed_summary": "Only one."}, None)
    assert provenance == "regex_fallback"
    assert claims == ["Only one."]


def test_hf_token_loader_first_existing_file_wins(tmp_path, _clean_hf_env):
    """Candidate list is searched in order — the first existing file's content
    wins; later candidates are not consulted. Documents the discovery contract."""
    first = _write_new_envs(tmp_path, "HF_READ_TOKEN : hf_fromFirst\n")
    second_dir = tmp_path / "subdir"; second_dir.mkdir()
    second = second_dir / "new_envs.txt"
    second.write_text("HF_READ_TOKEN : hf_fromSecond\n", encoding="utf-8")
    m = _reload_module()
    assert m._load_hf_token_from_new_envs(candidates=[first, second]) == "hf_fromFirst"


def test_sandbox_iter_id_is_not_a_real_iter():
    """Defense-in-depth: the sandbox iter_id must not collide with any iter_id
    in the run matrix. If you ever rename the sandbox, this fails first."""
    import yaml as _yaml
    judges_yaml = REPO_ROOT / "docs" / "zettel_eval_v1" / "_config" / "judges.yaml"
    if not judges_yaml.exists():
        import pytest
        pytest.skip("judges.yaml not present in checkout")
    matrix = _yaml.safe_load(judges_yaml.read_text(encoding="utf-8")).get("run_matrix", [])
    real_iter_ids = {row.get("iter_id") for row in matrix}
    assert _TEST_ITER not in real_iter_ids, (
        f"Sandbox iter_id {_TEST_ITER!r} collides with run matrix. "
        f"Rename it before running these tests against a live tree."
    )


# ---------------------------------------------------------------------------
# Binary-vs-3-class adapter — regression for the 2026-05-29 catch
# ---------------------------------------------------------------------------
# MiniCheck-DeBERTa-v3-Large is a BINARY factuality classifier
# (output shape = [not_supported, supported]). The original predict() assumed
# 3-class MNLI shape [contradict, neutral, entail] and threw IndexError on
# index 2 against the real model. The fix added shape-aware decoding; these
# tests pin both decode paths and the error path for unexpected shapes.

def _import_predictor():
    # The MiniCheckPredictor predict path needs torch (1.7GB, intentionally NOT
    # in CI deps). Every test_predict_* routes through here, so skip them all
    # when torch is absent (CI/dev); they run for anyone with torch installed.
    pytest.importorskip("torch")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "zettel_eval_v1_03_run_nli", SCRIPT
    )
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m.MiniCheckPredictor


def _make_fake_predictor(softmax_output: list[float]):
    """Bypass __init__ (avoids the 1.7GB model load) and inject a mock model
    that produces the given softmax probabilities. Mirrors the real predict()
    plumbing so the shape-decode branch is exercised end-to-end."""
    torch = pytest.importorskip("torch")

    MiniCheckPredictor = _import_predictor()

    class _StubModel:
        def __call__(self, **_kw):
            class _Out: pass
            o = _Out()
            o.logits = torch.tensor([softmax_output]).log()  # softmax(log(p)) == p
            return o

        def to(self, _device): return self
        def eval(self): return self

    class _FakeBatch(dict):
        # transformers' BatchEncoding subclasses dict + adds .to(); mimic that
        # so `inp.to(device)` and `**inp` both work in the real predict() path.
        def to(self, _device): return self

    class _StubTok:
        def __call__(self, premise, claim, **kw):
            return _FakeBatch({"input_ids": torch.tensor([[1, 2, 3]])})

        def to(self, _device): return self

    p = MiniCheckPredictor.__new__(MiniCheckPredictor)
    p.tok = _StubTok()
    p.model = _StubModel()
    p.device = "cpu"
    p.torch = torch
    p.model_name = "stub"
    p.revision = "stub"
    return p


def test_predict_handles_binary_output_shape():
    """MiniCheck returns 2 probs [not_supported, supported]. Adapter must map
    to (contradict=not_supported, neutral=0, entail=supported) without crashing."""
    p = _make_fake_predictor([0.1, 0.9])  # 90% supported
    out = p.predict("claim", "premise")
    assert abs(out["entail_prob"] - 0.9) < 1e-5
    assert abs(out["contradict_prob"] - 0.1) < 1e-5
    assert out["neutral_prob"] == 0.0
    # verdict should pick entail since it dominates
    assert out["verdict"] == "entailed"


def test_predict_handles_3class_mnli_output_shape():
    """Legacy MNLI checkpoints (deberta-v3-large-snli-mnli) emit 3 probs
    [contradict, neutral, entail]. The shape-aware decode must keep working
    for those models so the harness can swap models without code changes."""
    p = _make_fake_predictor([0.05, 0.10, 0.85])  # entail dominant
    out = p.predict("claim", "premise")
    assert abs(out["entail_prob"] - 0.85) < 1e-5
    assert abs(out["neutral_prob"] - 0.10) < 1e-5
    assert abs(out["contradict_prob"] - 0.05) < 1e-5
    assert out["verdict"] == "entailed"


def test_predict_3class_contradict_dominant():
    """Sanity: 3-class with contradict dominant produces 'contradicted' verdict."""
    p = _make_fake_predictor([0.85, 0.10, 0.05])
    out = p.predict("claim", "premise")
    assert out["verdict"] == "contradicted"


def test_predict_unexpected_shape_raises():
    """5-class output (some random model) must fail loud rather than silently
    return garbage. Catches misconfigured model swaps at first call."""
    import pytest
    p = _make_fake_predictor([0.1, 0.1, 0.1, 0.1, 0.6])
    with pytest.raises(RuntimeError, match="unexpected output shape"):
        p.predict("claim", "premise")


# ---------------------------------------------------------------------------
# Batched predict — the 2026-05-29 perf refactor
# ---------------------------------------------------------------------------
# CPU NLI on 81 zettels was ~6.75 hr because predict() was called serially per
# claim (one model forward pass per claim, no batching). predict_batch() runs
# all claims for a zettel through a single padded forward pass, yielding ~10x
# speedup. These tests pin batch behavior + shape parity with predict().


def _make_batched_predictor(softmax_batch_output: list[list[float]]):
    """Mock that returns a 2-D batch of softmax rows. Each call to model(**inp)
    returns logits of shape [B, num_classes] which softmax to softmax_batch_output."""
    torch = pytest.importorskip("torch")
    MiniCheckPredictor = _import_predictor()

    class _FakeBatch(dict):
        def to(self, _device): return self

    class _StubModel:
        def __call__(self, **kw):
            class _Out: pass
            o = _Out()
            o.logits = torch.tensor(softmax_batch_output).log()
            return o

        def to(self, _device): return self
        def eval(self): return self

    class _StubTok:
        def __call__(self, premises, claims, **kw):
            # batch tokenizer call: lists of len B
            B = len(claims) if isinstance(claims, list) else 1
            return _FakeBatch({"input_ids": torch.zeros((B, 3), dtype=torch.long)})

    p = MiniCheckPredictor.__new__(MiniCheckPredictor)
    p.tok = _StubTok()
    p.model = _StubModel()
    p.device = "cpu"
    p.torch = torch
    p.model_name = "stub"
    p.revision = "stub"
    return p


def test_predict_batch_returns_one_dict_per_claim():
    claims = ["c1", "c2", "c3"]
    rows = [[0.1, 0.9], [0.7, 0.3], [0.4, 0.6]]  # binary
    p = _make_batched_predictor(rows)
    out = p.predict_batch(claims, "premise", batch_size=16)
    assert len(out) == 3
    assert [o["claim"] for o in out] == claims
    assert abs(out[0]["entail_prob"] - 0.9) < 1e-5
    assert abs(out[1]["entail_prob"] - 0.3) < 1e-5
    assert out[0]["verdict"] == "entailed"
    assert out[1]["verdict"] == "contradicted"


def test_predict_batch_empty_input_returns_empty_list():
    """Edge: zettel with zero extractable claims must not crash the model call."""
    p = _make_batched_predictor([])
    assert p.predict_batch([], "premise") == []


def test_predict_batch_3class_mnli_path():
    claims = ["a", "b"]
    rows = [[0.05, 0.10, 0.85], [0.80, 0.10, 0.10]]
    p = _make_batched_predictor(rows)
    out = p.predict_batch(claims, "premise")
    assert out[0]["verdict"] == "entailed"
    assert out[1]["verdict"] == "contradicted"
    assert abs(out[0]["neutral_prob"] - 0.10) < 1e-5


def test_predict_batch_respects_batch_size_chunking():
    """4 claims at batch_size=2 → 2 forward passes; output order is preserved."""
    torch = pytest.importorskip("torch")
    MiniCheckPredictor = _import_predictor()

    class _FakeBatch(dict):
        def to(self, _device): return self

    calls = []

    class _StubModel:
        def __call__(self, **kw):
            calls.append(kw["input_ids"].shape[0])
            class _Out: pass
            o = _Out()
            # Return distinct probs per row so we can verify ordering
            B = kw["input_ids"].shape[0]
            o.logits = torch.tensor([[0.1, 0.9]] * B).log()
            return o

        def to(self, _device): return self
        def eval(self): return self

    class _StubTok:
        def __call__(self, premises, claims, **kw):
            B = len(claims)
            return _FakeBatch({"input_ids": torch.zeros((B, 3), dtype=torch.long)})

    p = MiniCheckPredictor.__new__(MiniCheckPredictor)
    p.tok = _StubTok()
    p.model = _StubModel()
    p.device = "cpu"
    p.torch = torch
    p.model_name = "stub"
    p.revision = "stub"

    out = p.predict_batch(["c1", "c2", "c3", "c4"], "premise", batch_size=2)
    assert len(out) == 4
    assert [o["claim"] for o in out] == ["c1", "c2", "c3", "c4"]
    # Verify chunking: 4 claims at batch_size=2 = 2 forward passes of size 2
    assert calls == [2, 2]


def test_decode_softmax_row_parity():
    """predict() and predict_batch() must produce IDENTICAL output for the
    same softmax row (no rounding/computation drift between paths)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    single = m._decode_softmax_row("c", [0.05, 0.10, 0.85], "stub")
    batched = m._decode_softmax_row("c", [0.05, 0.10, 0.85], "stub")
    assert single == batched


# ---------------------------------------------------------------------------
# Chunk-and-max-aggregate (Fix #3, 2026-05-29) — MiniCheck paper compliance
# ---------------------------------------------------------------------------
# Previously predict_batch did `tokenizer(premise, claim, max_length=2048)` once
# per claim — slow (~3hr/iter on CPU) AND silently truncated long premises past
# 2048 tokens. The refactor chunks the premise to ~400-token sentence-aggregated
# slices, scores every (chunk, claim) pair at max_length=512, and max-pools the
# chunk scores per claim. These tests pin the algorithm against the published
# MiniCheck inference (Tang et al., EMNLP 2024; arXiv 2404.10774).


class _CountingTok:
    """Tokenizer stub that uses whitespace-word-count as token estimate.
    Mirrors the encode(text, add_special_tokens=False) surface; deterministic
    so chunk boundaries land at predictable spots."""
    def encode(self, text, add_special_tokens=False):
        # ~1.3 tokens per whitespace-word — sufficient for boundary math
        n_words = len((text or "").split())
        return [0] * max(1, int(n_words * 1.3))


def test_chunk_premise_empty_returns_empty():
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert m._chunk_premise("", _CountingTok()) == []
    assert m._chunk_premise("   ", _CountingTok()) == []


def test_chunk_premise_short_premise_single_chunk():
    """A premise well under ~400 tokens must NOT be split — single chunk."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    text = "First short sentence. Second short sentence. Third short sentence."
    out = m._chunk_premise(text, _CountingTok(), chunk_token_target=400)
    assert len(out) == 1
    assert "First short sentence" in out[0]
    assert "Third short sentence" in out[0]


def test_chunk_premise_long_premise_produces_multiple_chunks():
    """When sentence-token sum exceeds the target, emit multiple chunks."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    # Each sentence ~10 words → ~13 tokens. Target 30 tokens forces a chunk
    # every ~2-3 sentences. 12 sentences should yield 4-6 chunks.
    sent = "word " * 10 + "."
    text = " ".join([sent.strip()] * 12)
    out = m._chunk_premise(text, _CountingTok(), chunk_token_target=30)
    assert len(out) >= 4
    # Verify NO sentence is split across two chunks
    joined = " ".join(out)
    assert joined.count("word") == text.count("word")


def test_chunk_premise_does_not_split_mid_sentence():
    """Even if a single sentence exceeds chunk_token_target, it is emitted as
    its own chunk verbatim (the downstream tokenizer truncates it)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    huge_sent = ("longword " * 200).strip() + "."
    out = m._chunk_premise(huge_sent, _CountingTok(), chunk_token_target=50)
    # Single huge sentence → exactly one chunk, full content preserved
    assert len(out) == 1
    assert out[0].count("longword") == 200


def test_chunk_premise_short_sentences_pack_into_single_chunk():
    """Common-case correctness: 10 short sentences (each well under the
    chunk_token_target) must pack into a single chunk via greedy accumulation,
    NOT emit one chunk per sentence."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    text = ". ".join([f"sentence {i}" for i in range(10)]) + "."
    out = m._chunk_premise(text, _CountingTok(), chunk_token_target=400)
    assert len(out) == 1
    # All 10 sentences accounted for
    for i in range(10):
        assert f"sentence {i}" in out[0]


def test_chunk_premise_abbreviations_do_not_split_mid_sentence():
    """The pre-2026-05-29 naive regex split fired on abbreviations like
    'Dr.', 'U.S.', 'a.m.' — fragmenting evidence across spurious boundaries.
    The NLTK splitter must keep abbreviation-laden sentences intact. Falls
    back to the regex on environments without NLTK/punkt — in that case
    this test is skipped rather than failing the suite."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    # Probe NLTK availability before asserting; otherwise we're testing the
    # regex fallback which DOES over-split by design.
    try:
        from nltk.tokenize import sent_tokenize  # noqa: F401
        # Ensure punkt_tab is loadable (NLTK may need to download on first use)
        try:
            sent_tokenize("hi.")
        except LookupError:
            import nltk
            nltk.download("punkt_tab", quiet=True)
            sent_tokenize("hi.")
    except (ImportError, LookupError, Exception):
        import pytest
        pytest.skip("NLTK / punkt_tab not available — regex fallback in use")

    text = (
        "Dr. Smith met with Prof. Jones at 9 a.m. yesterday. "
        "They discussed U.S. policy on e.g. trade tariffs. "
        "He said the meeting was productive."
    )
    out = m._chunk_premise(text, _CountingTok(), chunk_token_target=400)
    # NLTK punkt should produce exactly 3 sentences → 1 chunk (all fit).
    # The naive regex would produce 7+ "sentences" (one per abbreviation period).
    assert len(out) == 1, f"expected 1 chunk, got {len(out)}: {out}"
    # Each abbreviation must remain attached to its sentence — not split off
    assert "Dr. Smith" in out[0]
    assert "Prof. Jones" in out[0]
    assert "9 a.m." in out[0]
    assert "U.S. policy" in out[0]


def test_chunk_premise_no_sentence_terminator_returns_whole_text():
    """If the premise has no `.` `!` `?` (rare; degenerate input), return it
    as a single chunk and let downstream truncation handle it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    text = "no terminator anywhere just running on and on"
    out = m._chunk_premise(text, _CountingTok())
    assert out == [text]


def test_chunk_premise_tokenizer_failure_falls_back_to_char_estimate():
    """If the injected tokenizer raises on .encode(), the helper must fall
    back to a char-based estimate rather than propagate the exception."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

    class _BrokenTok:
        def encode(self, *a, **kw):
            raise RuntimeError("tokenizer offline")

    text = "First sentence. Second sentence. Third sentence."
    # Should not raise; should produce >= 1 chunk
    out = m._chunk_premise(text, _BrokenTok())
    assert len(out) >= 1


def _make_chunked_predictor(per_chunk_softmax: dict[str, list[list[float]]]):
    """Mock predictor where the model returns different softmax outputs
    depending on which premise chunk was tokenized. ``per_chunk_softmax``
    maps a substring marker → batched softmax rows. The tok stub records
    which chunk it last saw via a closure cell."""
    torch = pytest.importorskip("torch")
    MiniCheckPredictor = _import_predictor()

    class _FakeBatch(dict):
        def to(self, _device): return self

    last_premise = {"text": ""}

    class _StubTok:
        def encode(self, text, add_special_tokens=False):
            # Cheap token estimate so _chunk_premise works
            return [0] * max(1, len((text or "").split()))

        def __call__(self, premises, claims, **kw):
            B = len(claims) if isinstance(claims, list) else 1
            # premises is a list of identical strings = the current chunk
            last_premise["text"] = premises[0] if isinstance(premises, list) else premises
            return _FakeBatch({"input_ids": torch.zeros((B, 3), dtype=torch.long)})

    class _StubModel:
        def __call__(self, **kw):
            class _Out: pass
            o = _Out()
            cur = last_premise["text"]
            # Pick the softmax rows for whichever chunk-marker matches
            rows = None
            for marker, batched in per_chunk_softmax.items():
                if marker in cur:
                    rows = batched
                    break
            B = kw["input_ids"].shape[0]
            if rows is None:
                # Default: neutral-ish row broadcast to the batch size
                rows = [[0.5, 0.5]] * B
            elif len(rows) < B:
                # Broadcast the last row to fill — mirrors how a real model
                # would produce one prob row per batch item.
                rows = rows + [rows[-1]] * (B - len(rows))
            o.logits = torch.tensor(rows).log()
            return o

        def to(self, _device): return self
        def eval(self): return self

    p = MiniCheckPredictor.__new__(MiniCheckPredictor)
    p.tok = _StubTok()
    p.model = _StubModel()
    p.device = "cpu"
    p.torch = torch
    p.model_name = "stub"
    p.revision = "stub"
    return p


def test_predict_batch_max_aggregates_across_chunks():
    """Core algorithmic test: the supporting evidence for a claim may live in
    ANY chunk of the premise. predict_batch must pick the max entail_prob
    chunk per claim (not a chunk-1-only or last-chunk-only bias)."""
    # Premise: 6 sentences, force 2 chunks via small chunk_token_target.
    # We can't control that target through predict_batch's call, so build a
    # premise where the natural ~400-token boundary lands between sentence 3
    # and sentence 4. Easier: rely on chunk_token_target=400 default and use
    # a premise with ~800 tokens via long sentences.
    premise = ("nothing relevant here " * 60 + ". " +
                "this chunk has supporting evidence " * 60 + ".")
    p = _make_chunked_predictor({
        # Chunk 1 marker "nothing relevant" — low entail
        "nothing relevant": [[0.8, 0.2]],
        # Chunk 2 marker "supporting evidence" — high entail
        "supporting evidence": [[0.1, 0.9]],
    })
    out = p.predict_batch(["one claim"], premise, batch_size=1)
    assert len(out) == 1
    assert out[0]["entail_prob"] == 0.9  # max over chunks
    assert out[0]["n_chunks"] >= 2
    assert out[0]["best_chunk_idx"] == 1  # the supporting chunk


def test_predict_batch_single_chunk_short_premise_backward_compat():
    """Short premise → single chunk → behavior must match the pre-refactor
    contract (no best_chunk_idx surprise, entail_prob from the only chunk)."""
    p = _make_chunked_predictor({
        "anything": [[0.2, 0.8]],
    })
    out = p.predict_batch(["c1", "c2"], "anything premise text", batch_size=8)
    assert len(out) == 2
    assert abs(out[0]["entail_prob"] - 0.8) < 1e-5
    assert out[0]["n_chunks"] == 1
    assert out[0]["best_chunk_idx"] == 0


def test_predict_batch_empty_premise_does_not_crash():
    """Defensive: empty premise still produces one result-dict per claim
    (using the degenerate empty-string chunk fallback)."""
    p = _make_chunked_predictor({})  # falls through to default [[0.5, 0.5]]
    out = p.predict_batch(["c1"], "", batch_size=1)
    assert len(out) == 1
    assert "entail_prob" in out[0]


def test_fake_predictor_implements_batch_surface():
    """FakeMiniCheck must expose predict_batch so _augment_one's call site
    works uniformly (real and stub paths). Output must mirror per-call predict."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("zev1_03", SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    fake = m.FakeMiniCheck(entail_prob=0.9, contradict_prob=0.05)
    assert hasattr(fake, "predict_batch")
    out = fake.predict_batch(["c1", "c2"], "premise", batch_size=4)
    assert len(out) == 2
    assert all(o["entail_prob"] == 0.9 for o in out)


if __name__ == "__main__":
    test_extends_per_zettel_with_nli_fields()
    print("PASS test_extends_per_zettel_with_nli_fields")
    test_hard_fail_gate_recorded()
    print("PASS test_hard_fail_gate_recorded")
    test_predict_handles_binary_output_shape()
    print("PASS test_predict_handles_binary_output_shape")
    test_predict_handles_3class_mnli_output_shape()
    print("PASS test_predict_handles_3class_mnli_output_shape")
    test_predict_3class_contradict_dominant()
    print("PASS test_predict_3class_contradict_dominant")
    test_predict_unexpected_shape_raises()
    print("PASS test_predict_unexpected_shape_raises")
    print("ALL 6 TESTS PASS")
