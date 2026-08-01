"""Import-time env stubs for tests that build the real FastAPI app.

Several unit-test modules call ``create_app()`` at import time, which runs
settings validation and would ``SystemExit(1)`` without credentials. They used
to each carry their own copy of this block::

    os.environ.setdefault("SUPABASE_V2_URL", "https://ci-stub.supabase.co")

That was a landmine, and on 2026-05-31 it detonated: ``setdefault`` runs at
MODULE level, pytest imports every module during collection, and ``setdefault``
(unlike ``monkeypatch``) is never reverted — so the stub was installed
process-wide for the entire session, including the live suite.
``supabase_v2/client.py::_v2_env`` reads ``SUPABASE_V2_*`` first and only falls
back to the canonical ``SUPABASE_*`` names, so the stub OUTRANKED the real
credentials; ``get_v2_client`` is ``lru_cache``d with no ``cache_clear``
anywhere in the repo, so a single poisoned client served every test. Result:
228 of 248 live-test failures, all ``[Errno -2] Name or service not known``
against the non-existent host ``ci-stub.supabase.co``.

The guard below is the fix: only stub when the process has no real Supabase
configuration at all. Under ``live-tests.yml`` (and any workflow that exports
real credentials) this becomes a no-op and the genuine values win.
"""
from __future__ import annotations

import os

# Any one of these being present means the process has real Supabase config
# and must not be stubbed.
_REAL_MARKERS = (
    "SUPABASE_URL",
    "SUPABASE_V2_URL",
    "SUPABASE_V2_DATABASE_URL",
)

_STUBS = {
    "GEMINI_API_KEY": "ci-stub",
    "SUPABASE_V2_URL": "https://ci-stub.supabase.co",
    "SUPABASE_V2_ANON_KEY": "ci-stub-anon",
    "SUPABASE_V2_SERVICE_ROLE_KEY": "ci-stub-service",
    "NEXUS_TOKEN_ENCRYPTION_KEY": "7TgtMgeR5dMTnXxW6ULICwhf66A1VpzwuNFuIBqmoe4=",
}


def is_really_configured() -> bool:
    """True when real Supabase credentials are present in the environment."""
    return any(os.environ.get(name) for name in _REAL_MARKERS)


def stub_app_env_if_unconfigured() -> None:
    """Install placeholder env vars so ``create_app()`` can construct.

    No-ops entirely when real credentials are present, so a live run can never
    be poisoned by a test stub. Safe to call repeatedly.
    """
    if is_really_configured():
        return
    for name, value in _STUBS.items():
        os.environ.setdefault(name, value)
