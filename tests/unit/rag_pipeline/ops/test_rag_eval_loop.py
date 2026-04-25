from unittest.mock import patch

from ops.scripts.rag_eval_loop import _cli_dispatch, _resolve_seed_node_ids


def test_cli_dispatch_dry_run_returns_0():
    with patch("ops.scripts.rag_eval_loop._run_phase_a") as run_a:
        run_a.return_value = {"status": "dry_run"}
        rc = _cli_dispatch(["--source", "youtube", "--iter", "1", "--dry-run"])
    assert rc == 0


def test_resolve_seed_node_ids_iter01_youtube():
    ids = _resolve_seed_node_ids("youtube", 1)
    assert len(ids) == 5
    assert "yt-andrej-karpathy-s-llm-in" in ids
    assert "yt-effective-public-speakin" not in ids


def test_resolve_seed_node_ids_iter04_adds_probe():
    ids = _resolve_seed_node_ids("youtube", 4)
    assert len(ids) == 6
    assert "yt-effective-public-speakin" in ids


def test_resolve_seed_node_ids_iter05_adds_heldout():
    ids = _resolve_seed_node_ids("youtube", 5)
    assert len(ids) == 7
    assert "yt-zero-day-market-covert-exploits" in ids
