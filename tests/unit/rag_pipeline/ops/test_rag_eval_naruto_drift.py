import pytest
from ops.scripts.lib.rag_eval_naruto_drift import (
    check_naruto_drift,
    NarutoDriftError,
)


def test_within_tolerance_passes():
    check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                       current={"node_count": 105, "link_count": 220},
                       applied_mutation_count=0)


def test_node_drift_over_10_pct_blocks():
    with pytest.raises(NarutoDriftError, match="node"):
        check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                           current={"node_count": 115, "link_count": 220},
                           applied_mutation_count=0)


def test_drift_explained_by_applied_mutations_passes():
    # 10 applied mutations explain up to ~10 node/edge additions
    check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                       current={"node_count": 115, "link_count": 220},
                       applied_mutation_count=20)


def test_edge_drift_over_20_pct_blocks():
    with pytest.raises(NarutoDriftError, match="edge"):
        check_naruto_drift(baseline={"node_count": 100, "link_count": 200},
                           current={"node_count": 100, "link_count": 250},
                           applied_mutation_count=0)
