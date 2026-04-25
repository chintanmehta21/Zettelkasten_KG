from unittest.mock import patch

from ops.scripts.rag_eval_loop import _cli_dispatch


def test_cli_dispatch_dry_run_returns_0():
    with patch("ops.scripts.rag_eval_loop._run_phase_a") as run_a:
        run_a.return_value = {"status": "dry_run"}
        rc = _cli_dispatch(["--source", "youtube", "--iter", "1", "--dry-run"])
    assert rc == 0
