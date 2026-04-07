"""Interactive live OAuth + import E2E for Nexus.

Use this when you want a real provider OAuth callback flow (not synthetic tokens),
then assert a successful import (`HTTP 200`) end-to-end.
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def _load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "supabase" / ".env", override=False)


def _require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _random_password(length: int = 22) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


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
            "user_metadata": {"full_name": "Nexus Live E2E"},
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    user_id = str((payload.get("user") or payload).get("id") or "").strip()
    if not user_id:
        raise RuntimeError("Failed to create Supabase auth user")
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
    client.table("nexus_ingested_artifacts").delete().eq("user_id", kg_user_id).execute()
    client.table("nexus_ingest_runs").delete().eq("user_id", kg_user_id).execute()
    client.table("nexus_provider_accounts").delete().eq("user_id", kg_user_id).execute()
    client.table("nexus_oauth_states").delete().eq("auth_user_sub", auth_user_sub).execute()
    client.table("kg_links").delete().eq("user_id", kg_user_id).execute()
    client.table("kg_nodes").delete().eq("user_id", kg_user_id).execute()
    client.table("kg_users").delete().eq("id", kg_user_id).execute()


def _oauth_env_ready(provider: str) -> bool:
    return all(
        (os.environ.get(name) or "").strip() and not _looks_placeholder(os.environ.get(name) or "")
        for name in PROVIDER_OAUTH_ENV[provider]
    )


def _looks_placeholder(value: str) -> bool:
    probe = value.strip().lower()
    if not probe:
        return True
    placeholder_tokens = (
        "nexus-smoke",
        "example",
        "replace",
        "your-",
        "your_",
        "changeme",
        "test-",
    )
    return any(token in probe for token in placeholder_tokens)


def _resolve_local_server_for_provider(provider: str) -> tuple[str, int]:
    redirect_env_name = PROVIDER_OAUTH_ENV[provider][2]
    redirect_uri = _require_env(redirect_env_name)
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _start_server(host: str, port: int) -> subprocess.Popen[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "website.app:create_app",
        "--factory",
        "--host",
        host,
        "--port",
        str(port),
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_health(base_url: str, timeout_seconds: int = 45) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=3.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("Server health check failed")


def _provider_connected(base_url: str, access_token: str, provider: str) -> bool:
    response = httpx.get(
        f"{base_url}/api/nexus/providers",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
    )
    response.raise_for_status()
    providers = response.json().get("providers") or []
    for row in providers:
        if str(row.get("provider")) == provider:
            return bool(row.get("connected"))
    return False


def _resolve_kg_user_id(auth_user_sub: str) -> str:
    from website.experimental_features.nexus.service.persist import get_supabase_scope

    scope = get_supabase_scope(auth_user_sub)
    if not scope:
        raise RuntimeError("Unable to resolve KG user id from Supabase scope")
    _repo, kg_user_id = scope
    return kg_user_id


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live Nexus OAuth + import E2E")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDER_OAUTH_ENV.keys()),
        default="github",
        help="Provider to test end-to-end",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Number of artifacts to import",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=420,
        help="How long to wait for OAuth callback completion",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("NEXUS_E2E_EMAIL", "").strip(),
        help="Existing Supabase email to use (otherwise creates temporary user)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("NEXUS_E2E_PASSWORD", "").strip(),
        help="Supabase password for --email",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Cleanup test user + imported data after run",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the OAuth URL in browser",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Use an already running app URL (example: http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--use-existing-server",
        action="store_true",
        help="Do not start uvicorn from this script; use --base-url or redirect URI host/port.",
    )
    parser.add_argument(
        "--remember-connection",
        action="store_true",
        help="Persist provider credentials after import (production behavior). Default is forget-after-import for testing.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _load_env()

    if not _oauth_env_ready(args.provider):
        missing = [
            key
            for key in PROVIDER_OAUTH_ENV[args.provider]
            if not (os.environ.get(key) or "").strip() or _looks_placeholder(os.environ.get(key) or "")
        ]
        raise RuntimeError(
            f"Provider '{args.provider}' OAuth env is incomplete. Missing: {', '.join(missing)}"
        )

    supabase_url = _require_env("SUPABASE_URL")
    supabase_anon_key = _require_env("SUPABASE_ANON_KEY")
    service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    _require_env("NEXUS_TOKEN_ENCRYPTION_KEY")

    parsed_base_url = (args.base_url or "").strip().rstrip("/")
    if parsed_base_url:
        base_url = parsed_base_url
        parsed = urlparse(base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    else:
        host, port = _resolve_local_server_for_provider(args.provider)
        base_url = f"http://{host}:{port}"

    server = None
    if not args.use_existing_server:
        server = _start_server(host, port)

    auth_user_sub = ""
    kg_user_id = ""
    created_user_id = ""

    try:
        _wait_for_health(base_url)

        if args.email and args.password:
            email = args.email
            password = args.password
        else:
            suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
            email = f"nexus-live-e2e-{suffix}@example.com"
            password = _random_password()
            created_user_id = _create_supabase_user(
                supabase_url,
                service_role_key,
                email=email,
                password=password,
            )

        auth_payload = _sign_in_password(
            supabase_url,
            supabase_anon_key,
            email=email,
            password=password,
        )
        access_token = str(auth_payload.get("access_token") or "").strip()
        auth_user_sub = str((auth_payload.get("user") or {}).get("id") or "").strip()
        if not access_token or not auth_user_sub:
            raise RuntimeError("Failed to sign in and obtain Supabase access token")

        home_response = httpx.get(f"{base_url}/home/nexus", timeout=20.0)
        home_response.raise_for_status()

        connect_response = httpx.post(
            f"{base_url}/api/nexus/connect/{args.provider}",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"redirect_path": "/home/nexus"},
            timeout=20.0,
        )
        connect_response.raise_for_status()
        redirect_url = str(connect_response.json().get("redirect_url") or "").strip()
        if not redirect_url.startswith("http"):
            raise RuntimeError("OAuth connect did not return a valid redirect_url")

        print("\nComplete OAuth in browser using this URL:\n")
        print(redirect_url)
        print("")
        if not args.no_browser:
            webbrowser.open(redirect_url, new=2)

        start_wait = time.time()
        while time.time() - start_wait < args.timeout_seconds:
            if _provider_connected(base_url, access_token, args.provider):
                break
            time.sleep(3)
        else:
            raise RuntimeError(
                f"Provider '{args.provider}' was not connected within {args.timeout_seconds}s"
            )

        import_response = httpx.post(
            f"{base_url}/api/nexus/import/{args.provider}",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "limit": max(1, args.limit),
                "force": True,
                "remember_connection": bool(args.remember_connection),
            },
            timeout=240.0,
        )
        if import_response.status_code != 200:
            raise RuntimeError(
                f"Import failed with status {import_response.status_code}: {import_response.text[:500]}"
            )
        import_payload = import_response.json()
        imported_count = int(import_payload.get("imported_count") or 0)
        skipped_count = int(import_payload.get("skipped_count") or 0)
        if imported_count + skipped_count < 1:
            raise RuntimeError("Import succeeded but no artifacts were imported or skipped")

        runs_response = httpx.get(
            f"{base_url}/api/nexus/runs?limit=10",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20.0,
        )
        runs_response.raise_for_status()
        runs = runs_response.json().get("runs") or []
        if not runs:
            raise RuntimeError("No ingest run records found after successful import")

        print("Nexus live OAuth E2E passed.")
        print(f"- provider: {args.provider}")
        print("- callback completion: OK")
        print("- import status: 200")
        print(f"- imported: {imported_count}")
        print(f"- skipped: {skipped_count}")
        print(f"- failed: {int(import_payload.get('failed_count') or 0)}")
        print(f"- runs found: {len(runs)}")
        print(f"- remember_connection: {bool(args.remember_connection)}")

        kg_user_id = _resolve_kg_user_id(auth_user_sub)
    finally:
        if args.cleanup and auth_user_sub:
            if not kg_user_id:
                try:
                    kg_user_id = _resolve_kg_user_id(auth_user_sub)
                except Exception:
                    kg_user_id = ""
            if kg_user_id:
                try:
                    _cleanup_kg_data(auth_user_sub, kg_user_id)
                except Exception as exc:  # noqa: BLE001
                    print(f"Cleanup warning (kg data): {exc}")
            if created_user_id:
                try:
                    _delete_supabase_user(supabase_url, service_role_key, created_user_id)
                except Exception as exc:  # noqa: BLE001
                    print(f"Cleanup warning (auth user): {exc}")

        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    main()
