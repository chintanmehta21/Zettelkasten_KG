"""Hard CI gate for iter-03 (Task 4C.1).

Compares an iter-03 `answers.json` produced by the rag_eval_loop /
Phase-4D Claude-in-Chrome harness against the frozen iter-03
`baseline.json` thresholds.

Three gates, all hard (any failure -> non-zero exit):
1. end_to_end_gold_at_1   >= 0.65 (baseline.ci_gates.end_to_end_gold_at_1_min)
2. synthesizer_grounding  >= 0.85 (baseline.ci_gates.synthesizer_grounding_min)
3. infra_failures         <= 0    (baseline.ci_gates.infra_failures_max)

Soft signals (per_stage thresholds + 0.05) are printed as warnings but
do not fail the gate this iter — they harden in iter-04 per the plan
(see Phase 4C step 1 in the iter-03 plan).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# critic_verdict values that count as a successful refusal/partial answer
# for adversarial-negative queries (q9-style: gold list is empty).
_REFUSAL_VERDICTS = frozenset(
    {"unsupported", "partial", "retried_still_bad"}
)
_REFUSAL_PHRASE = "I can't find that in your Zettels."


# ---------- I/O -------------------------------------------------------------


def load_baseline(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_queries(path: Path) -> dict[str, dict]:
    """Load a queries.json (iter-02/iter-03 schema) keyed by qid."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    queries = raw.get("queries", raw if isinstance(raw, list) else [])
    return {q["qid"]: q for q in queries if "qid" in q}


# ---------- gold@1 ---------------------------------------------------------


def _expected_set(q: dict) -> set[str]:
    exp = q.get("expected_primary_citation")
    if exp is None:
        return set()
    if isinstance(exp, str):
        return {exp} if exp else set()
    return {x for x in exp if x}


def _is_adversarial_negative(q: dict) -> bool:
    """A query that EXPECTS a refusal (no gold zettel exists)."""
    if _expected_set(q):
        return False
    expected_verdict = q.get("expected_critic_verdict") or ""
    return "unsupported" in expected_verdict or "partial" in expected_verdict or not _expected_set(q)


def _top_citation_node_id(answer: dict) -> str | None:
    cits = answer.get("citations") or []
    if not cits:
        return None
    top = cits[0]
    if isinstance(top, dict):
        return top.get("node_id")
    return None


def _verdict(answer: dict) -> str | None:
    ps = answer.get("per_stage") or {}
    return ps.get("critic_verdict")


def _grounded_refusal(answer: dict) -> bool:
    if _verdict(answer) in _REFUSAL_VERDICTS:
        return True
    body = (answer.get("answer") or "").strip()
    return _REFUSAL_PHRASE in body


def compute_end_to_end_gold_at_1(
    answers: Iterable[dict], queries: dict[str, dict]
) -> float:
    """gold@1 across all queries.

    Definition:
    - Adversarial-negative query (no expected gold) PASSES iff the answer
      is a grounded refusal/partial (verdict in REFUSAL_VERDICTS or body
      contains the canonical refusal phrase) AND no top citation hijacks
      the response.
    - Otherwise PASSES iff the top-1 citation node_id is in the
      `expected_primary_citation` set.
    """
    answers = list(answers)
    if not answers:
        return 0.0
    passes = 0
    counted = 0
    for a in answers:
        qid = a.get("query_id")
        q = queries.get(qid)
        if q is None:
            # Unknown qid — count as failure rather than skip; the eval
            # set must match the queries set or the run is invalid.
            counted += 1
            continue
        counted += 1
        if _is_adversarial_negative(q):
            top = _top_citation_node_id(a)
            if top is None and _grounded_refusal(a):
                passes += 1
            elif top is None and _verdict(a) is None:
                # No citations and no verdict -> treat the answer body.
                if _grounded_refusal(a):
                    passes += 1
            continue
        top = _top_citation_node_id(a)
        if top is not None and top in _expected_set(q):
            passes += 1
    return passes / max(counted, 1)


# ---------- synthesizer grounding ------------------------------------------


def compute_synthesizer_grounding(answers: Iterable[dict]) -> float:
    """Mean of per_stage.synthesizer_grounding_pct, skipping None values.

    Returns 0.0 when no answer carries a numeric grounding score (i.e.,
    every record is an infra failure).
    """
    vals: list[float] = []
    for a in answers:
        ps = a.get("per_stage") or {}
        v = ps.get("synthesizer_grounding_pct")
        if v is None:
            continue
        vals.append(float(v))
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


# ---------- infra failures --------------------------------------------------


def compute_infra_failures(answers: Iterable[dict]) -> int:
    """Count records that never reached the orchestrator.

    Heuristics (any one trips the counter):
    - explicit `infra_failure: true`
    - missing `per_stage` block (orchestrator never serialised the turn)
    """
    n = 0
    for a in answers:
        if a.get("infra_failure") is True:
            n += 1
            continue
        if "per_stage" not in a or a.get("per_stage") is None:
            n += 1
    return n


# ---------- top-level gate --------------------------------------------------


@dataclass
class GateResult:
    passed: bool
    exit_code: int
    gold_at_1: float
    synthesizer_grounding: float
    infra_failures: int
    failures: list[str] = field(default_factory=list)
    soft_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "exit_code": self.exit_code,
            "gold_at_1": self.gold_at_1,
            "synthesizer_grounding": self.synthesizer_grounding,
            "infra_failures": self.infra_failures,
            "failures": list(self.failures),
            "soft_warnings": list(self.soft_warnings),
        }


def enforce_gates(
    *,
    answers: list[dict],
    queries: dict[str, dict],
    baseline: dict,
) -> GateResult:
    gates = baseline.get("ci_gates", {})
    gold_min = float(gates.get("end_to_end_gold_at_1_min", 0.0))
    grounding_min = float(gates.get("synthesizer_grounding_min", 0.0))
    infra_max = int(gates.get("infra_failures_max", 0))

    gold = compute_end_to_end_gold_at_1(answers, queries)
    grounding = compute_synthesizer_grounding(answers)
    infra = compute_infra_failures(answers)

    failures: list[str] = []
    if gold < gold_min:
        failures.append(
            f"HARD GATE FAILED: end_to_end_gold_at_1 = {gold:.3f} < {gold_min:.3f}"
        )
    if grounding < grounding_min:
        failures.append(
            f"HARD GATE FAILED: synthesizer_grounding = {grounding:.3f} < {grounding_min:.3f}"
        )
    if infra > infra_max:
        failures.append(
            f"HARD GATE FAILED: infra_failures = {infra} > {infra_max}"
        )

    soft_warnings: list[str] = []
    per_stage_baseline = baseline.get("per_stage", {})
    for key, threshold in per_stage_baseline.items():
        if not isinstance(threshold, (int, float)):
            continue
        observed = _observe_per_stage(answers, key)
        if observed is None:
            continue
        target = float(threshold) + 0.05
        if observed < target:
            soft_warnings.append(
                f"soft signal: {key} = {observed:.3f} (target {target:.3f}) "
                "— within noise this iter, hardens in iter-04"
            )

    passed = not failures
    return GateResult(
        passed=passed,
        exit_code=0 if passed else 1,
        gold_at_1=gold,
        synthesizer_grounding=grounding,
        infra_failures=infra,
        failures=failures,
        soft_warnings=soft_warnings,
    )


def _observe_per_stage(answers: list[dict], key: str) -> float | None:
    """Map a baseline.per_stage key to an observed value."""
    if key == "retrieval_recall_at_10":
        vals = [
            (a.get("per_stage") or {}).get("retrieval_recall_at_10")
            for a in answers
        ]
        nums = [float(v) for v in vals if isinstance(v, (int, float))]
        return sum(nums) / len(nums) if nums else None
    if key == "synthesizer_grounding_pct":
        return compute_synthesizer_grounding(answers)
    if key == "retrieval_primary_citation_correct_pct":
        # Mirrors gold@1 for the answer-side partition; safe substitute.
        return None
    return None


# ---------- CLI helpers (used by rag_eval_loop._cli_dispatch) --------------


def run_gate_from_paths(
    *,
    answers_path: Path,
    queries_path: Path,
    baseline_path: Path,
    out_stream=sys.stdout,
    err_stream=sys.stderr,
) -> int:
    """Load + run the gate. Return process exit code (0 pass, 1 fail)."""
    answers_raw = json.loads(Path(answers_path).read_text(encoding="utf-8"))
    if isinstance(answers_raw, dict) and "answers" in answers_raw:
        answers = answers_raw["answers"]
    else:
        answers = answers_raw
    queries = load_queries(Path(queries_path))
    baseline = load_baseline(Path(baseline_path))
    result = enforce_gates(answers=answers, queries=queries, baseline=baseline)

    if result.passed:
        out_stream.write(
            f"OK gold_at_1={result.gold_at_1:.3f} grounding={result.synthesizer_grounding:.3f} "
            f"infra_failures={result.infra_failures}\n"
        )
    else:
        for f in result.failures:
            err_stream.write(f + "\n")
    for w in result.soft_warnings:
        out_stream.write(w + "\n")
    out_stream.write(json.dumps(result.to_dict(), indent=2) + "\n")
    return result.exit_code
