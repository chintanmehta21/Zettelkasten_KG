"""Live smoke test for Nexus routes with Supabase-backed auth and storage.

This script:
1) Loads env from `.env` and `supabase/.env`
2) Starts the local FastAPI app
3) Creates a temporary Supabase auth user and signs in
4) Verifies `/home/nexus` and authenticated Nexus APIs
5) Exercises provider connect + import path
6) Cleans up temporary auth and KG data
"""

from __future__ import annotations

import os
import secrets
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_HOST = "127.0.0.1"
APP_PORT = int(os.environ.get("NEXUS_SMOKE_PORT", "8787"))
APP_BASE_URL = f"http://{APP_HOST}:{APP_PORT}"

PROVIDER_OAUTH_ENV: dict[str, tuple[str, str, str]] = {
    "github": (
        "NEXUS_GITHUB_CLIENT_ID",
        "NEXUS_GITHUB_CLIENT_SECRET",
        "NEXUS_GITHUB_REDIRECT_URI",
    ),
    "youtube": (
        "NEXUS_YOUTUBE_CLIENT_ID",
        "NEXUS_YOUTUBE_CLIENT_SECRET",
        "NEXUS_YOUTUBE_REDIRECT_URI",
    ),
    "reddit": (
        "NEXUS_REDDIT_CLIENT_ID",
        "NEXUS_REDDIT_CLIENT_SECRET",
        "NEXUS_REDDIT_REDIRECT_URI",
    ),
    "twitter": (
        "NEXUS_TWITTER_CLIENT_ID",
        "NEXUS_TWITTER_CLIENT_SECRET",
        "NEXUS_TWITTER_REDIRECT_URI",
    ),
}


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "supabase" / ".env", override=False)


def _start_server(env: dict[str, str]) -> subprocess.Popen[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "website.app:create_app",
        "--factory",
        "--host",
        APP_HOST,
        "--port",
        str(APP_PORT),
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_health(timeout_seconds: int = 45) -> None:
    deadline = time.time() + timeout_seconds
    last_error = "unknown"
    while time.time() < deadline:
        try:
            response = httpx.get(f"{APP_BASE_URL}/api/health", timeout=3.0)
            if response.status_code == 200:
                return
            last_error = f"status={response.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"Server failed health check: {last_error}")


def _provider_env_ready(provider: str) -> bool:
    names = PROVIDER_OAUTH_ENV[provider]
    return all((os.environ.get(name) or "").strip() for name in names)


def _create_supabase_user(
    supabase_url: str,
    service_role_key: str,
    *,
    email: str,
    password: str,
) -> str:
    response = httpx.post(
        f"{supabase_url}/auth/v1/admin/users",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": "Nexus Smoke"},
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    user_id = str((payload.get("user") or payload).get("id") or "").strip()
    if not user_id:
        raise RuntimeError("Failed to read created Supabase user id.")
    return user_id


def _delete_supabase_user(supabase_url: str, service_role_key: str, user_id: str) -> None:
    response = httpx.delete(
        f"{supabase_url}/auth/v1/admin/users/{user_id}",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        },
        timeout=20.0,
    )
    if response.status_code not in (200, 204, 404):
        response.raise_for_status()


def _sign_in_password(
    supabase_url: str,
    anon_key: str,
    *,
    email: str,
    password: str,
) -> dict[str, Any]:
    response = httpx.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={
            "apikey": anon_key,
            "Content-Type": "application/json",
        },
        json={"email": email, "password": password},
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()


def _cleanup_kg_data(auth_user_sub: str, kg_user_id: str) -> None:
    from website.core.supabase_kg import get_supabase_client

    client = get_supabase_client()
    # Keep cleanup order explicit to avoid FK conflicts.
    client.table("nexus_ingested_artifacts").delete().eq("user_id", kg_user_id).execute()
    client.table("nexus_ingest_runs").delete().eq("user_id", kg_user_id).execute()
    client.table("nexus_provider_accounts").delete().eq("user_id", kg_user_id).execute()
    client.table("nexus_oauth_states").delete().eq("auth_user_sub", auth_user_sub).execute()
    client.table("kg_links").delete().eq("user_id", kg_user_id).execute()
    client.table("kg_nodes").delete().eq("user_id", kg_user_id).execute()
    client.table("kg_users").delete().eq("id", kg_user_id).execute()


def _run() -> None:
    _load_env()
    supabase_url = _require_env("SUPABASE_URL")
    anon_key = _require_env("SUPABASE_ANON_KEY")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    _require_env("NEXUS_TOKEN_ENCRYPTION_KEY")

    env = os.environ.copy()
    server = _start_server(env)

    auth_user_sub = ""
    kg_user_id = ""
    created_user_id = ""

    try:
        _wait_for_health()

        suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
        email = f"nexus-smoke-{suffix}@example.com"
        password = _random_password()
        created_user_id = _create_supabase_user(
            supabase_url,
            service_role_key,
            email=email,
            password=password,
        )

        token_payload = _sign_in_password(
            supabase_url,
            anon_key,
            email=email,
            password=password,
        )
        access_token = str(token_payload.get("access_token") or "").strip()
        auth_user_sub = str((token_payload.get("user") or {}).get("id") or "").strip()
        if not access_token or not auth_user_sub:
            raise RuntimeError("Failed to obtain Supabase access token for smoke user.")

        headers = {"Authorization": f"Bearer {access_token}"}

        home_response = httpx.get(f"{APP_BASE_URL}/home/nexus", timeout=20.0)
        if home_response.status_code != 200:
            raise RuntimeError(f"/home/nexus failed with status {home_response.status_code}")

        providers_response = httpx.get(
            f"{APP_BASE_URL}/api/nexus/providers",
            headers=headers,
            timeout=20.0,
        )
        providers_response.raise_for_status()
        providers_payload = providers_response.json()
        providers = providers_payload.get("providers") or []
        if not providers:
            raise RuntimeError("Nexus providers endpoint returned no providers.")

        connect_passed: list[str] = []
        connect_skipped: list[str] = []
        for provider in ("github", "youtube", "reddit", "twitter"):
            if not _provider_env_ready(provider):
                connect_skipped.append(provider)
                continue
            response = httpx.post(
                f"{APP_BASE_URL}/api/nexus/connect/{provider}",
                headers=headers,
                json={"redirect_path": "/home/nexus"},
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            redirect_url = str(payload.get("redirect_url") or "").strip()
            if not redirect_url.startswith("http"):
                raise RuntimeError(f"Connect did not return redirect_url for {provider}")
            connect_passed.append(provider)

        if not connect_passed:
            raise RuntimeError("No provider connect flow could be validated from current env.")

        from website.experimental_features.nexus.service.bulk_import import upsert_provider_account
        from website.experimental_features.nexus.service.persist import get_supabase_scope
        from website.experimental_features.nexus.source_ingest.common.models import (
            NexusProvider,
            StoredProviderAccount,
        )

        scope = get_supabase_scope(auth_user_sub)
        if not scope:
            raise RuntimeError("Failed to resolve Supabase KG scope for smoke user.")
        _repo, kg_user_id = scope

        import_provider = "github" if "github" in connect_passed else connect_passed[0]
        account = StoredProviderAccount(
            user_id=UUID(kg_user_id),
            provider=NexusProvider(import_provider),
            account_id="smoke-account",
            account_username="smoke-user",
            access_token="smoke-invalid-token",
            refresh_token=None,
            token_type="Bearer",
            scopes=["smoke:test"],
            metadata={"source": "nexus_smoke_test"},
        )
        upsert_provider_account(account)

        import_response = httpx.post(
            f"{APP_BASE_URL}/api/nexus/import/{import_provider}",
            headers=headers,
            json={"limit": 1, "force": True},
            timeout=60.0,
        )
        if import_response.status_code not in (200, 500):
            raise RuntimeError(
                f"Import endpoint returned unexpected status {import_response.status_code}"
            )

        runs_response = httpx.get(
            f"{APP_BASE_URL}/api/nexus/runs?limit=5",
            headers=headers,
            timeout=20.0,
        )
        runs_response.raise_for_status()
        runs_payload = runs_response.json()
        runs = runs_payload.get("runs") or []
        if not runs:
            raise RuntimeError("Import smoke did not produce any ingest run records.")

        disconnect_response = httpx.post(
            f"{APP_BASE_URL}/api/nexus/disconnect/{import_provider}",
            headers=headers,
            timeout=20.0,
        )
        disconnect_response.raise_for_status()

        print("Nexus smoke test passed.")
        print(f"- /home/nexus: OK")
        print(f"- providers listed: {len(providers)}")
        print(f"- connect validated: {', '.join(connect_passed)}")
        if connect_skipped:
            print(f"- connect skipped (missing env): {', '.join(connect_skipped)}")
        print(f"- import endpoint status: {import_response.status_code}")
        print(f"- ingest runs observed: {len(runs)}")
    finally:
        if auth_user_sub and kg_user_id:
            try:
                _cleanup_kg_data(auth_user_sub, kg_user_id)
            except Exception as exc:  # noqa: BLE001
                print(f"Cleanup warning (KG data): {exc}")
        if created_user_id:
            try:
                _delete_supabase_user(supabase_url, service_role_key, created_user_id)
            except Exception as exc:  # noqa: BLE001
                print(f"Cleanup warning (auth user): {exc}")

        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    _run()
