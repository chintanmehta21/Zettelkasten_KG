"""Full Nexus end-to-end loop test (real OAuth callback + real imports).

Flow:
1) Start local app on the redirect host/port configured for providers.
2) Create/sign in a real Supabase user (or use existing credentials).
3) For each provider: complete OAuth callback, import artifacts, verify runs.
4) Validate personal graph node growth from imported zettels.
5) Print a provider-by-provider report and exit non-zero on failures.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALL_PROVIDERS = ("github", "youtube", "reddit", "twitter")
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


@dataclass
class ProviderResult:
    provider: str
    status: str
    connected: bool = False
    import_status_code: int | None = None
    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    graph_delta: int = 0
    note: str = ""


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


def _provider_env_ready(provider: str) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for key in PROVIDER_OAUTH_ENV[provider]:
        value = (os.environ.get(key) or "").strip()
        if not value or _looks_placeholder(value):
            missing.append(key)
    return len(missing) == 0, missing


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


def _resolve_server_target(providers: list[str]) -> tuple[str, int]:
    host: str | None = None
    port: int | None = None
    for provider in providers:
        redirect_uri = _require_env(PROVIDER_OAUTH_ENV[provider][2])
        parsed = urlparse(redirect_uri)
        p_host = parsed.hostname or "127.0.0.1"
        p_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host is None:
            host = p_host
            port = p_port
            continue
        if p_host != host or p_port != port:
            raise RuntimeError(
                "Providers do not share the same local callback host/port. "
                f"Expected {host}:{port}, got {p_host}:{p_port} for {provider}."
            )
    if host is None or port is None:
        raise RuntimeError("No providers selected for E2E run")
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
            "user_metadata": {"full_name": "Nexus Full E2E"},
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
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()


def _provider_connected(base_url: str, access_token: str, provider: str) -> bool:
    response = httpx.get(
        f"{base_url}/api/nexus/providers",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
    )
    response.raise_for_status()
    for row in response.json().get("providers") or []:
        if str(row.get("provider")) == provider:
            return bool(row.get("connected"))
    return False


def _graph_node_count(base_url: str, access_token: str) -> int:
    response = httpx.get(
        f"{base_url}/api/graph?view=my&limit=10000&offset=0",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=45.0,
    )
    response.raise_for_status()
    payload = response.json()
    nodes = payload.get("nodes") or []
    return len(nodes)


def _resolve_kg_user_id(auth_user_sub: str) -> str:
    from website.experimental_features.nexus.service.persist import get_supabase_scope

    scope = get_supabase_scope(auth_user_sub)
    if not scope:
        raise RuntimeError("Unable to resolve KG scope for auth user")
    _repo, kg_user_id = scope
    return kg_user_id


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


def _run_provider_e2e(
    *,
    base_url: str,
    access_token: str,
    provider: str,
    limit: int,
    timeout_seconds: int,
    auto_open_browser: bool,
    remember_connection: bool,
) -> ProviderResult:
    result = ProviderResult(provider=provider, status="failed")

    before_count = _graph_node_count(base_url, access_token)
    connect = httpx.post(
        f"{base_url}/api/nexus/connect/{provider}",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"redirect_path": "/home/nexus"},
        timeout=20.0,
    )
    connect.raise_for_status()
    redirect_url = str(connect.json().get("redirect_url") or "").strip()
    if not redirect_url.startswith("http"):
        result.note = "connect endpoint did not return redirect_url"
        return result

    print(f"\n[{provider}] Complete OAuth in browser:")
    print(redirect_url)
    if auto_open_browser:
        webbrowser.open(redirect_url, new=2)

    started = time.time()
    while time.time() - started < timeout_seconds:
        if _provider_connected(base_url, access_token, provider):
            result.connected = True
            break
        time.sleep(3)

    if not result.connected:
        result.note = f"OAuth callback not completed within {timeout_seconds}s"
        return result

    import_response = httpx.post(
        f"{base_url}/api/nexus/import/{provider}",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "limit": max(1, limit),
            "force": True,
            "remember_connection": bool(remember_connection),
        },
        timeout=240.0,
    )
    result.import_status_code = import_response.status_code
    if import_response.status_code != 200:
        result.note = f"import failed with status {import_response.status_code}"
        return result

    payload = import_response.json()
    result.imported_count = int(payload.get("imported_count") or 0)
    result.skipped_count = int(payload.get("skipped_count") or 0)
    result.failed_count = int(payload.get("failed_count") or 0)

    runs_response = httpx.get(
        f"{base_url}/api/nexus/runs?limit=20",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
    )
    runs_response.raise_for_status()
    provider_runs = [
        run
        for run in (runs_response.json().get("runs") or [])
        if str(run.get("provider")) == provider
    ]
    if not provider_runs:
        result.note = "no ingest run recorded after import"
        return result

    after_count = _graph_node_count(base_url, access_token)
    result.graph_delta = after_count - before_count

    if result.imported_count + result.skipped_count < 1:
        result.note = "no artifacts imported/skipped"
        return result
    if result.imported_count > 0 and result.graph_delta < 0:
        result.note = "graph node count decreased unexpectedly"
        return result

    result.status = "passed"
    result.note = "ok"
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full Nexus E2E loop")
    parser.add_argument(
        "--providers",
        default="all",
        help="Comma-separated provider list or 'all' (github,youtube,reddit,twitter)",
    )
    parser.add_argument("--limit", type=int, default=2, help="Import limit per provider")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=600,
        help="OAuth callback timeout per provider",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("NEXUS_E2E_EMAIL", "").strip(),
        help="Existing Supabase auth email",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("NEXUS_E2E_PASSWORD", "").strip(),
        help="Supabase auth password for --email",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Cleanup test data/user after completion",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open OAuth links in browser",
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

    _require_env("SUPABASE_URL")
    _require_env("SUPABASE_ANON_KEY")
    _require_env("SUPABASE_SERVICE_ROLE_KEY")
    _require_env("NEXUS_TOKEN_ENCRYPTION_KEY")

    if args.providers.strip().lower() == "all":
        requested = list(ALL_PROVIDERS)
    else:
        requested = [item.strip().lower() for item in args.providers.split(",") if item.strip()]
        unknown = [provider for provider in requested if provider not in ALL_PROVIDERS]
        if unknown:
            raise RuntimeError(f"Unsupported providers: {', '.join(unknown)}")
        requested = list(dict.fromkeys(requested))

    runnable: list[str] = []
    skipped_env: dict[str, list[str]] = {}
    for provider in requested:
        ready, missing = _provider_env_ready(provider)
        if ready:
            runnable.append(provider)
        else:
            skipped_env[provider] = missing
    if not runnable:
        parts = [
            f"{provider}: {', '.join(missing)}"
            for provider, missing in skipped_env.items()
        ]
        raise RuntimeError(
            "No providers have complete OAuth env configuration. "
            f"Fix these env vars: {' | '.join(parts)}"
        )

    parsed_base_url = (args.base_url or "").strip().rstrip("/")
    if parsed_base_url:
        base_url = parsed_base_url
        parsed = urlparse(base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    else:
        host, port = _resolve_server_target(runnable)
        base_url = f"http://{host}:{port}"

    server = None
    if not args.use_existing_server:
        server = _start_server(host, port)
    created_user_id = ""
    auth_user_sub = ""
    kg_user_id = ""

    try:
        _wait_for_health(base_url)
        home = httpx.get(f"{base_url}/home/nexus", timeout=20.0)
        home.raise_for_status()

        supabase_url = _require_env("SUPABASE_URL")
        anon_key = _require_env("SUPABASE_ANON_KEY")
        service_role_key = _require_env("SUPABASE_SERVICE_ROLE_KEY")

        if args.email and args.password:
            email = args.email
            password = args.password
        else:
            suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
            email = f"nexus-full-e2e-{suffix}@example.com"
            password = _random_password()
            created_user_id = _create_supabase_user(
                supabase_url,
                service_role_key,
                email=email,
                password=password,
            )

        auth_payload = _sign_in_password(
            supabase_url,
            anon_key,
            email=email,
            password=password,
        )
        access_token = str(auth_payload.get("access_token") or "").strip()
        auth_user_sub = str((auth_payload.get("user") or {}).get("id") or "").strip()
        if not access_token or not auth_user_sub:
            raise RuntimeError("Failed to sign in to Supabase for E2E user")

        initial_nodes = _graph_node_count(base_url, access_token)

        results: list[ProviderResult] = []
        for provider in runnable:
            provider_result = _run_provider_e2e(
                base_url=base_url,
                access_token=access_token,
                provider=provider,
                limit=args.limit,
                timeout_seconds=args.timeout_seconds,
                auto_open_browser=not args.no_browser,
                remember_connection=bool(args.remember_connection),
            )
            results.append(provider_result)

        final_nodes = _graph_node_count(base_url, access_token)
        total_delta = final_nodes - initial_nodes

        print("\n=== Nexus Full E2E Summary ===")
        print(f"Base URL: {base_url}")
        print(f"Providers requested: {', '.join(requested)}")
        if skipped_env:
            for provider, missing in skipped_env.items():
                print(f"- {provider}: skipped (missing env: {', '.join(missing)})")

        failed = False
        for row in results:
            print(
                f"- {row.provider}: {row.status} | connected={row.connected} | "
                f"import_status={row.import_status_code} | imported={row.imported_count} | "
                f"skipped={row.skipped_count} | failed={row.failed_count} | "
                f"graph_delta={row.graph_delta} | note={row.note}"
            )
            if row.status != "passed":
                failed = True

        print(f"Personal graph delta (overall): {total_delta}")
        print(f"remember_connection mode: {bool(args.remember_connection)}")

        if failed:
            raise RuntimeError("One or more providers failed full E2E")

        print("Full Nexus E2E loop passed.")
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
                    _delete_supabase_user(
                        _require_env("SUPABASE_URL"),
                        _require_env("SUPABASE_SERVICE_ROLE_KEY"),
                        created_user_id,
                    )
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
