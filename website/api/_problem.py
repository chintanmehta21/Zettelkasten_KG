"""RFC 9457 (Problem Details for HTTP APIs) single-source-of-truth builder.

Both the sync ``_problem()`` JSONResponse helper in ``zettels_routes.py`` AND
the async background-worker ``_async_failure_error_payload(exc)`` helper
funnel through ``_problem_dict(...)`` so the two paths produce physically
identical bodies for the same exception. Frontend keys off the canonical
``code`` extension member (RFC 9457 §3.2) regardless of which path produced
the failure.

Lives in its own module to be importable from both ``website.api.*`` and
``website.core.operations_repo`` (the Phase-2 cancel() helper) without
circular-import risk.
"""

from __future__ import annotations

from typing import Any

# Canonical RFC 9457 normative members (§3.1) — extensions MUST NOT override
# these. Used to filter ``extra`` keys.
_CANONICAL_MEMBERS = frozenset({"type", "title", "status", "detail", "instance"})


def _problem_dict(
    *,
    status_code: int,
    title: str,
    detail: Any,
    type_slug: str,
    operation_id: str | None = None,
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem-detail dict.

    Preserves the existing sync ``_problem()`` output byte-for-byte so
    previously-deployed clients keep working:
      - ``type`` URL retains the ``errors/`` segment.
      - ``instance`` defaults to ``/api/zettels/add[/{op_id}]`` (matches the
        legacy sync route convention). Override with ``instance=`` arg.
      - ``operation_id`` is set as a top-level extension member when present
        (existing extension; frontend reads it).

    Adds the canonical ``code`` extension (== ``type_slug``) so async-finalized
    failures can be routed to the same class-specific UI as inline sync 4xxs.

    ``errors`` is the RFC 9457 §3.2 extension for multi-field validation
    failures (Spring / JSON:API community convention): each entry is a
    sub-problem dict the frontend renders as per-field error UI. Omitted for
    single-error problems.

    ``extra`` keys flow to the top level per §3.2 but cannot shadow the five
    canonical members; collisions are dropped silently (canonical wins).
    """
    body: dict[str, Any] = {
        "type": f"https://zettelkasten.in/problems/errors/{type_slug}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": (
            instance
            if instance is not None
            else (
                f"/api/zettels/add/{operation_id}"
                if operation_id
                else "/api/zettels/add"
            )
        ),
    }
    if operation_id:
        body["operation_id"] = operation_id
    # Canonical extension member used by the frontend for class-specific UI
    # dispatch. Identical key in sync 4xx bodies and async-finalized failures.
    body["code"] = type_slug
    if errors:
        body["errors"] = list(errors)
    if extra:
        for k, v in extra.items():
            if k in _CANONICAL_MEMBERS:
                continue  # canonical fields win; extension drop silently
            if k in body:
                continue  # don't overwrite operation_id / code / errors either
            body[k] = v
    return body
