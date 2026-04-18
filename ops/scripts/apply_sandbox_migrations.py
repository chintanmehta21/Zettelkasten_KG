"""Apply rag_chatbot migrations 003/004/005 via Supabase Management API.

One-shot script. Reads creds from supabase/.env and posts each SQL file to the
project's /v1/projects/{ref}/database/query endpoint.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "supabase" / ".env")

TOKEN = os.environ["SUPABASE_ACCESS_TOKEN"]
URL = os.environ["SUPABASE_URL"]
PROJECT_REF = URL.split("//", 1)[1].split(".", 1)[0]

MIGRATIONS = [
    ROOT / "supabase" / "website" / "rag_chatbot" / "002_chunks_table.sql",
    ROOT / "supabase" / "website" / "rag_chatbot" / "005_rag_rpcs.sql",
]


def apply(path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    print(f"\n=== Applying {path.name} ({len(sql)} chars) ===")
    resp = httpx.post(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        json={"query": sql},
        timeout=60.0,
    )
    print(f"HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    print(body)
    if resp.status_code >= 400:
        sys.exit(f"FAILED: {path.name}")


def main() -> None:
    print(f"Project ref: {PROJECT_REF}")
    for mig in MIGRATIONS:
        if not mig.exists():
            sys.exit(f"Missing migration: {mig}")
        apply(mig)
    print("\nAll migrations applied.")


if __name__ == "__main__":
    main()
