"""Surface-enum contract between mobile JS and the Add-Zettel route.

Production bug 2026-05-25: the mobile site (website/mobile/js/summarizer.js)
sent ``surface: 'mobile'`` while the route's ``AddZettelRequest`` and the
document-upload ``Form()`` parameter declared
``Literal["landing", "home", "zettels"]``. Every mobile capture (URL +
document) returned HTTP 422 ``literal_error`` in ~200 ms with NO
``core.operations`` row written — pre-``ops_accept`` Pydantic reject.

Confirmed in Caddy access log on 2026-05-25:
  07:09:46 GMT — zettel:mobile:1779692985978:tt3nux1zoer (4xx, 0.19 s)
  07:09:53 GMT — zettel:mobile:1779692993212:8171mk3szuy (4xx, 0.20 s)
  12:28:54 GMT — zettel:mobile:1779712133509:ytfda8gjlr (4xx, 0.20 s)

See ``docs/claude_audits/prajeet_grant_and_failure_audit_2026-05-25.md``
§4.a-bis for the full forensic trail.

This module pins three contract invariants:
  1. ``AddZettelRequest`` accepts ``surface='mobile'``.
  2. ``add_zettel_document`` Form param accepts ``surface='mobile'``.
  3. Every literal ``surface: '<value>'`` emitted from the in-tree JS files
     is a member of the route's Literal enum (drift guard).
"""
from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[3]


def _import_route_module():
    """Import lazily inside tests so a route-import side-effect can never
    silently re-tag a missed env var as a collection-time failure."""
    from website.api import zettels_routes as zr

    return zr


def _route_literal_values() -> tuple[str, ...]:
    """Read the JSON-body schema's surface Literal members at runtime.

    Pydantic v2 stores Literal members in the FieldInfo annotation; we
    inspect the model field rather than re-parsing the source to keep this
    test honest if the field moves.
    """
    zr = _import_route_module()
    annotation = zr.AddZettelRequest.model_fields["surface"].annotation
    args = typing.get_args(annotation)
    assert args, "surface field is not a Literal — schema shape changed"
    return tuple(args)


# ── 1. Backend schema accepts the value the mobile JS sends ────────────────


def test_add_zettel_request_accepts_surface_mobile() -> None:
    """Constructing AddZettelRequest with surface='mobile' must succeed.

    Pre-fix this raised ``pydantic.ValidationError`` (literal_error). After
    the fix the value is in the Literal and the model parses cleanly.
    """
    zr = _import_route_module()
    body = zr.AddZettelRequest(
        url="https://youtu.be/juHv_Vi4giU?si=",
        client_action_id="zettel:mobile:1779712133509:ytfda8gjlr",
        surface="mobile",
    )
    assert body.surface == "mobile"
    assert str(body.url) == "https://youtu.be/juHv_Vi4giU?si="


@pytest.mark.parametrize("surface", ["landing", "home", "zettels", "mobile"])
def test_add_zettel_request_accepts_every_documented_surface(surface: str) -> None:
    """All four documented frontend surfaces must parse — locks the enum to
    exactly the values emitted by the in-tree JS callers (landing, home,
    zettels, mobile). Add a new surface? Grow this list, grow the Literal,
    keep the JS in lockstep."""
    zr = _import_route_module()
    body = zr.AddZettelRequest(
        url="https://example.com",
        client_action_id="cai-test",
        surface=surface,
    )
    assert body.surface == surface


def test_add_zettel_request_rejects_unknown_surface() -> None:
    """The Literal must still reject typos — guard against widening to ``str``
    by accident."""
    from pydantic import ValidationError

    zr = _import_route_module()
    with pytest.raises(ValidationError) as exc_info:
        zr.AddZettelRequest(
            url="https://example.com",
            client_action_id="cai-test",
            surface="iphone",  # not in the contract — must reject
        )
    assert "literal_error" in str(exc_info.value).lower() or "should be" in str(
        exc_info.value
    ).lower()


# ── 2. Document-upload Form() route accepts surface='mobile' ───────────────


def test_document_upload_form_signature_accepts_surface_mobile() -> None:
    """The /api/zettels/add/document Form parameter must accept 'mobile'
    too — the mobile JS uses the same surface for both URL and document
    captures (mobile/js/summarizer.js:220,227).

    ``zettels_routes`` uses ``from __future__ import annotations`` so the
    raw ``__annotations__`` dict holds strings; resolve via
    ``typing.get_type_hints`` with ``include_extras=True`` to recover the
    real ``Annotated[Literal[...], Form()]``.
    """
    zr = _import_route_module()
    hints = typing.get_type_hints(zr.add_zettel_document, include_extras=True)
    sig = hints["surface"]  # Annotated[Literal[...], Form()]
    inner = typing.get_args(sig)[0]  # Literal[...]
    args = typing.get_args(inner)
    assert "mobile" in args, (
        f"add_zettel_document.surface Literal {args!r} is missing 'mobile' — "
        "mobile JS document upload will 422 pre-ops_accept"
    )


# ── 3. JS↔Backend drift guard ──────────────────────────────────────────────


_SURFACE_LITERAL_RE = re.compile(
    r"surface\s*:\s*['\"]([a-zA-Z_\-]+)['\"]",
)


def _scan_js_surface_literals() -> dict[Path, set[str]]:
    """Walk the in-tree JS callers of /api/zettels/add and collect every
    literal value passed as ``surface:``. Skips noise (minified bundles,
    vendor dirs) RELATIVE to each root so a worktree path like
    ``.claude/worktrees/...`` doesn't false-positive the dotfile filter.
    """
    roots = [
        _ROOT / "website" / "static" / "js",
        _ROOT / "website" / "mobile" / "js",
        _ROOT / "website" / "features",
    ]
    out: dict[Path, set[str]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.js"):
            rel_parts = path.relative_to(root).parts
            if any(p.startswith(".") or p == "node_modules" for p in rel_parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = set(_SURFACE_LITERAL_RE.findall(text))
            if hits:
                out[path] = hits
    return out


def test_every_js_surface_literal_is_in_backend_enum() -> None:
    """Drift guard: any `surface: '<value>'` literal emitted from the in-tree
    JS callers MUST be a member of ``AddZettelRequest.surface``'s Literal.

    Pre-fix this test FAILS — website/mobile/js/summarizer.js emits 'mobile'
    which is not in the Literal. Post-fix it PASSES. Keeps the JS↔backend
    contract from drifting again.
    """
    allowed = set(_route_literal_values())
    assert allowed >= {"landing", "home", "zettels"}, (
        f"Literal lost legacy values: {allowed!r}"
    )
    scanned = _scan_js_surface_literals()
    assert scanned, "No JS files matched the surface-literal scan — selector broken"
    violations: list[str] = []
    for path, values in scanned.items():
        rel = path.relative_to(_ROOT)
        bad = values - allowed
        if bad:
            violations.append(f"{rel} emits {sorted(bad)} (not in {sorted(allowed)})")
    assert not violations, (
        "JS↔backend surface enum drift:\n  " + "\n  ".join(violations)
    )
