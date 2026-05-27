"""Resolve the user's full name + country for the Slack message.

Reuses helpers from web_monitor (cross-feature import under website/features/
is allowed). Falls back gracefully when claims or headers are missing.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    full_name: str
    email: str | None
    country_label: str       # e.g. "India — IN" or "India — IN (approx.)"
    is_anonymous: bool


def _format_country(code: str | None, *, approx: bool) -> str:
    if not code or code == "??":
        return "Unknown"
    code_upper = code.upper()
    # Reuse web_monitor's format_country verbatim — returns "India (IN)" style.
    # Operator preference (2026-05-27): keep parens format, not em-dash.
    try:
        from website.features.web_monitor._country import format_country
        label = format_country(code_upper)
    except Exception:
        label = code_upper
    if approx:
        label += " (approx.)"
    return label


def _name_from_claims(claims: dict) -> str | None:
    if not claims:
        return None
    meta = claims.get("user_metadata") or {}
    for key in ("full_name", "name", "display_name"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Fall back to the email local part if name absent.
    email = claims.get("email")
    if isinstance(email, str) and "@" in email:
        return email.split("@", 1)[0]
    return None


def resolve_identity(
    *,
    claims: dict | None,
    anon_name: str | None,
    headers: dict,
    profile_country_code: str | None,
) -> Identity:
    """Top-level resolver.

    Args:
        claims: decoded Supabase JWT claims dict, or None when anonymous.
        anon_name: user-typed name on the anonymous form; ignored when authed.
        headers: request headers (lowercased keys expected); used for cf-ipcountry.
        profile_country_code: 2-letter code from core.profiles when present,
                              else None.
    """
    is_anonymous = claims is None
    if is_anonymous:
        name = (anon_name or "").strip() or "Anonymous"
        email = None
    else:
        name = _name_from_claims(claims) or "Unknown"
        email = (claims.get("email") or None) if isinstance(claims, dict) else None

    if profile_country_code:
        country_label = _format_country(profile_country_code, approx=False)
    else:
        ip_country = (headers.get("cf-ipcountry") or "").upper()
        country_label = _format_country(ip_country or None, approx=True)

    return Identity(
        full_name=name,
        email=email,
        country_label=country_label,
        is_anonymous=is_anonymous,
    )
