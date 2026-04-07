"""Supabase client singleton for knowledge graph operations."""

from __future__ import annotations

import atexit
import os
import logging
from functools import lru_cache
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions

logger = logging.getLogger(__name__)

# Load supabase-specific .env from supabase/.env (project root relative)
_SUPABASE_ENV = Path(__file__).resolve().parents[3] / "supabase" / ".env"
load_dotenv(_SUPABASE_ENV, override=False)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a lazily-initialized Supabase client.

    Credentials are loaded from ``supabase/.env``.  Uses the service-role
    key so the Python backend bypasses RLS and can manage data for any user.
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
            "Add them to supabase/.env — see that file for instructions."
        )

    timeout = _read_http_timeout()
    verify = _read_http_verify()
    proxy = (os.environ.get("SUPABASE_HTTP_PROXY") or "").strip() or None

    httpx_kwargs: dict[str, object] = {
        "timeout": timeout,
        "verify": verify,
    }
    if proxy:
        # httpx 0.27+ accepts a single proxy URL via ``proxy=``.
        httpx_kwargs["proxy"] = proxy

    shared_http_client = httpx.Client(**httpx_kwargs)
    atexit.register(shared_http_client.close)
    options = SyncClientOptions(httpx_client=shared_http_client)

    logger.info("Initializing Supabase client for %s", url)
    return create_client(url, key, options=options)


def get_supabase_env() -> dict[str, str]:
    """Return all three Supabase env vars as a dict (for MCP/tooling)."""
    return {
        "SUPABASE_URL": os.environ.get("SUPABASE_URL", ""),
        "SUPABASE_ANON_KEY": os.environ.get("SUPABASE_ANON_KEY", ""),
        "SUPABASE_SERVICE_ROLE_KEY": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    }


def is_supabase_configured() -> bool:
    """Check whether Supabase env vars are present (without initializing)."""
    return bool(
        os.environ.get("SUPABASE_URL")
        and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )


def _read_http_timeout() -> float:
    raw = (os.environ.get("SUPABASE_HTTP_TIMEOUT") or "").strip()
    if not raw:
        return 20.0
    try:
        value = float(raw)
    except ValueError:
        return 20.0
    return max(1.0, value)


def _read_http_verify() -> bool:
    raw = (os.environ.get("SUPABASE_HTTP_VERIFY") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True
