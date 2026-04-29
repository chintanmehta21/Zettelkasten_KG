from __future__ import annotations

from pathlib import Path


class LoginDetailsMissingError(RuntimeError):
    pass


def _normalize_key(raw: str) -> str:
    return raw.strip().lower().lstrip("-* ").replace(" ", "_")


def load_login_details(path: Path) -> dict[str, str]:
    if not path.exists():
        raise LoginDetailsMissingError(
            f"Missing {path}. Create it locally with Naruto credentials. The file is gitignored and must not be committed."
        )
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        values[_normalize_key(key)] = value.strip()
    if not any(key in values for key in ("access_token", "render_user_id", "email", "kg_user_id")):
        if values:
            values["render_user_id"] = "naruto"
        else:
            raise ValueError("login_details.txt must include access_token, render_user_id, email, or kg_user_id for Naruto.")
    return values
