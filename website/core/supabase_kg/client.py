"""Supabase client singleton for knowledge graph operations."""

from __future__ import annotations

import os
import logging
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

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

    logger.info("Initializing Supabase client for %s", url)
    return create_client(url, key)


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
