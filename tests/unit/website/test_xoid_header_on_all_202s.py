"""Regression guard for PR #89 commit C's X-Operation-Id contract.

Every ``return JSONResponse(..., status_code=202, headers={...})`` site in
``website/api/zettels_routes.py`` MUST include ``X-Operation-Id`` in its
headers dict. Verified live on 2026-05-25 that 5 of 5 such sites previously
missed the header (Location was present, X-Operation-Id was not). This is a
static contract test, cheap to run, deterministic — guards against the bug
re-introducing during future refactors.

If you add a 6th ``status_code=202`` JSONResponse to zettels_routes.py and
this test fails, the fix is to add ``"X-Operation-Id": <op_id>`` to its
headers dict — not to weaken the assertion."""
from __future__ import annotations

from pathlib import Path

ROUTE_FILE = (
    Path(__file__).resolve().parents[3] / "website" / "api" / "zettels_routes.py"
)


def test_every_status_code_202_response_carries_xoid_header() -> None:
    src = ROUTE_FILE.read_text(encoding="utf-8")
    # Split at each "status_code=202" — chunks[0] is the prologue, chunks[1..N]
    # are the tails after each occurrence. The next ~400 chars of each tail must
    # contain "X-Operation-Id" (it's typically the first key in the headers
    # dict, but we allow it anywhere within the JSONResponse return).
    chunks = src.split("status_code=202")
    n_sites = len(chunks) - 1
    assert n_sites >= 5, (
        f"expected >=5 status_code=202 JSONResponse sites in "
        f"website/api/zettels_routes.py, found {n_sites}. Has the file "
        f"been refactored?"
    )
    missing: list[int] = []
    for i, tail in enumerate(chunks[1:], start=1):
        # Look at the JSONResponse construction following each 202. The
        # headers dict normally completes within ~300 chars; give it 500 for
        # safety against future additions like SSE/proxy headers.
        window = tail[:500]
        if "X-Operation-Id" not in window:
            missing.append(i)
    assert not missing, (
        f"status_code=202 JSONResponse site(s) missing X-Operation-Id header: "
        f"{missing} of {n_sites}. Per PR #89 commit C the contract is "
        f"'every 202 carries X-Operation-Id' — add it to the headers dict."
    )
