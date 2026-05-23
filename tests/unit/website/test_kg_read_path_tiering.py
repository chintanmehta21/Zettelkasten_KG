"""Phase B — KG read-path strength resolution + percentile tiering.

Covers the /api/graph render-strength logic (this unit owns ONLY the read
path; the upsert/migration side is covered by
tests/unit/supabase_v2/test_kg_two_level_strength.py):

  * KGRepository.list_workspace_edges SELECTs the Phase B columns
    (workspace_strength + connection_strength) and stays workspace-scoped,
    and deliberately does NOT select cross-workspace global_strength.
  * _resolve_edge_strength precedence: workspace_strength ->
    connection_strength -> legacy weight -> unscored sentinel; a NULL/missing
    score never becomes a false "strong" (was_scored=False).
  * _build_tier_classifier: percentile tiers from the workspace's scored-edge
    distribution; n < 20 -> fixed 0.7/0.4 fallback cutoffs.
  * Cross-workspace isolation (OWASP API1:2023 BOLA): workspace A's strength
    distribution can never influence workspace B's tiering — the classifier
    is built per-workspace and A's UUID/values never leak into B.

All Supabase access is mocked; no live DB.
"""
from __future__ import annotations

from uuid import UUID

from website.api.routes import (
    _UNSCORED_STRENGTH_SENTINEL,
    _build_tier_classifier,
    _percentile_threshold,
    _resolve_edge_strength,
)
from website.core.supabase_v2.repositories.kg_repository import KGRepository

WS_A = UUID("00000000-0000-0000-0000-00000000000a")
WS_B = UUID("00000000-0000-0000-0000-00000000000b")


# ---------------------------------------------------------------------------
# list_workspace_edges: SELECT shape + workspace scoping
# ---------------------------------------------------------------------------

class _Execute:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return type("Resp", (), {"data": self.data})()


class _Query:
    def __init__(self, calls):
        self.calls = calls

    def select(self, cols):
        self.calls.append(("select", cols))
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    def order(self, col, **kwargs):
        # B1 (Task 2.1): list_workspace_edges chains 3 .order() calls before
        # .limit(). The fake only records the call; ordering is enforced
        # contractually by `tests/unit/supabase_v2/test_kg_repository_ordering.py`.
        self.calls.append(("order", col, kwargs))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return _Execute([{"id": 1, "src_node_id": 2, "dst_node_id": 3}])


class _Schema:
    def __init__(self, calls):
        self.calls = calls

    def table(self, name):
        self.calls.append(("table", name))
        return _Query(self.calls)


class _Client:
    def __init__(self):
        self.calls = []

    def schema(self, name):
        self.calls.append(("schema", name))
        return _Schema(self.calls)

    def table(self, name):  # pragma: no cover - must always be schema-scoped
        raise AssertionError(f"unscoped table call: {name}")


def test_list_workspace_edges_selects_phase_b_strength_cols() -> None:
    client = _Client()
    repo = KGRepository(client)

    rows = repo.list_workspace_edges(WS_A)

    assert rows == [{"id": 1, "src_node_id": 2, "dst_node_id": 3}]
    select_call = next(c for c in client.calls if c[0] == "select")
    cols = select_call[1]
    # Phase B render driver + composite fallback are now selected.
    assert "workspace_strength" in cols
    assert "connection_strength" in cols
    # Legacy weight kept as last-resort fallback.
    assert "weight" in cols
    # Cross-workspace global_strength must NEVER reach the render surface.
    assert "global_strength" not in cols
    # Schema-scoped + workspace-scoped (never an unscoped table read).
    assert ("schema", "kg") in client.calls
    eq_call = next(c for c in client.calls if c[0] == "eq")
    assert eq_call == ("eq", "workspace_id", str(WS_A))


# ---------------------------------------------------------------------------
# _resolve_edge_strength: precedence + NULL-not-strong
# ---------------------------------------------------------------------------

def test_resolve_prefers_workspace_strength() -> None:
    s, scored = _resolve_edge_strength(
        {"workspace_strength": 0.9, "connection_strength": 0.2, "weight": 5}
    )
    assert s == 0.9
    assert scored is True


def test_resolve_falls_back_to_connection_strength_when_ws_null() -> None:
    s, scored = _resolve_edge_strength(
        {"workspace_strength": None, "connection_strength": 0.3, "weight": 9}
    )
    assert s == 0.3
    assert scored is True


def test_resolve_legacy_weight_normalised_and_marked_unscored() -> None:
    # weight is 1-10 scale -> normalised /10; still NOT a real score.
    s, scored = _resolve_edge_strength(
        {"workspace_strength": None, "connection_strength": None, "weight": 8}
    )
    assert s == 0.8
    assert scored is False


def test_resolve_all_null_is_sentinel_not_false_strong() -> None:
    # The old None -> 1.0 bug: an unscored edge MUST NOT look strong.
    s, scored = _resolve_edge_strength(
        {"workspace_strength": None, "connection_strength": None, "weight": None}
    )
    assert s == _UNSCORED_STRENGTH_SENTINEL
    assert _UNSCORED_STRENGTH_SENTINEL < 1.0
    assert scored is False


def test_resolve_missing_keys_is_sentinel() -> None:
    s, scored = _resolve_edge_strength({})
    assert s == _UNSCORED_STRENGTH_SENTINEL
    assert scored is False


def test_resolve_garbage_value_skipped() -> None:
    s, scored = _resolve_edge_strength(
        {"workspace_strength": "n/a", "connection_strength": 0.6}
    )
    assert s == 0.6
    assert scored is True


# ---------------------------------------------------------------------------
# _percentile_threshold
# ---------------------------------------------------------------------------

def test_percentile_threshold_bounds_and_midpoint() -> None:
    vals = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert _percentile_threshold(vals, 0.0) == 0.1
    assert _percentile_threshold(vals, 1.0) == 0.5
    # Nearest-rank at 0.75 over 5 elements -> idx round(0.75*4)=3 -> 0.4
    assert _percentile_threshold(vals, 0.75) == 0.4


# ---------------------------------------------------------------------------
# _build_tier_classifier: percentile vs small-n fallback
# ---------------------------------------------------------------------------

def test_tier_classifier_percentile_when_enough_samples() -> None:
    # 20 scored edges spanning 0.05..1.0 -> percentile cutoffs, not fixed.
    scored = [i / 20 for i in range(1, 21)]  # 0.05 .. 1.0
    classify = _build_tier_classifier(scored)
    # Top of the distribution -> strong; very bottom -> weak.
    assert classify(1.0, True) == "strong"
    assert classify(0.05, True) == "weak"
    # Sentinel/unscored edge never strong even if numerically high.
    assert classify(0.99, False) == "weak"


def test_tier_classifier_small_n_uses_fixed_cutoffs() -> None:
    # < 20 scored edges -> fixed 0.7 / 0.4 cutoffs regardless of distribution.
    scored = [0.95, 0.92, 0.9]  # n=3, all high — would skew a percentile
    classify = _build_tier_classifier(scored)
    assert classify(0.71, True) == "strong"  # >= 0.7
    assert classify(0.69, True) == "medium"  # < 0.7 but >= 0.4
    assert classify(0.5, True) == "medium"
    assert classify(0.39, True) == "weak"  # < 0.4


def test_tier_classifier_empty_distribution_fixed_fallback() -> None:
    classify = _build_tier_classifier([])
    assert classify(0.8, True) == "strong"
    assert classify(0.45, True) == "medium"
    assert classify(0.1, True) == "weak"
    assert classify(0.99, False) == "weak"


def test_tier_classifier_degenerate_all_equal_no_inversion() -> None:
    # All-equal high distribution: medium_cut must not exceed strong_cut.
    scored = [0.8] * 25
    classify = _build_tier_classifier(scored)
    # Should not raise / invert; the common value lands strong-or-medium,
    # never producing an impossible (medium>strong) ordering.
    label = classify(0.8, True)
    assert label in {"strong", "medium"}


# ---------------------------------------------------------------------------
# Cross-workspace isolation (BOLA): A's distribution never tiers B
# ---------------------------------------------------------------------------

def test_cross_workspace_distribution_isolation() -> None:
    """Workspace A's strength distribution must never influence B's tiers.

    A has 25 uniformly-low edges (so A's 75th pctl is ~0.20). B has 25
    uniformly-high edges (B's 75th pctl is ~0.92). A classifier built from
    A's scored list must NOT tier B's 0.5 edge as 'strong' using A's low
    cutoff, and vice-versa — the classifiers are independent per workspace.
    """
    a_scored = [0.05 + i * 0.005 for i in range(25)]  # ~0.05..0.17, low
    b_scored = [0.80 + i * 0.005 for i in range(25)]  # ~0.80..0.92, high

    classify_a = _build_tier_classifier(a_scored)
    classify_b = _build_tier_classifier(b_scored)

    probe = 0.5
    # Under A's low distribution 0.5 is well above the 75th pctl -> strong.
    assert classify_a(probe, True) == "strong"
    # Under B's high distribution 0.5 is below B's 40th pctl -> weak.
    assert classify_b(probe, True) == "weak"
    # The two classifiers are distinct objects with no shared state:
    assert classify_a is not classify_b
    # Re-running A after building B is unchanged (no global leak/mutation).
    assert classify_a(probe, True) == "strong"

    # UUID-leak guard (OWASP API1 style): the classifiers are pure functions
    # of the strength lists only — neither workspace UUID nor B's values are
    # reachable from A's classifier closure.
    a_cell_contents = [c.cell_contents for c in (classify_a.__closure__ or ())]
    flat = repr(a_cell_contents)
    assert str(WS_B) not in flat
    assert "0.80" not in flat and "0.92" not in flat
