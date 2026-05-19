"""Deterministic, zero-dependency post-summary text-quality rule registry.

A rule is a PURE function ``str -> str``. Rules are registered under a key
``(source_type | None, field_kind)`` and run in the frozen RULE_ORDER. The
registry is conservative by construction:

* Unknown ``field_kind`` -> the value is returned BYTE-IDENTICAL (never lose
  data).
* Non-str input -> returned unchanged.
* A rule that raises -> swallowed (logged); the value is left unchanged so a
  buggy rule can never corrupt or drop a summary/title in production.
* Every rule MUST be idempotent: ``f(f(x)) == f(x)`` (enforced by
  test_registry_idempotency over a golden corpus).

Applied at the presentation/DTO layer only; the stored raw summary/title is
the source of truth and is never mutated by this module.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Callable

logger = logging.getLogger("website.post_summary_transformation.registry")

RuleFn = Callable[[str], str]

# Frozen global precedence. A field_kind not listed here still works (rules
# for it run in registration order) but listing it pins deterministic order
# across the codebase. Keep this list authoritative + reviewed.
RULE_ORDER: tuple[str, ...] = (
    "title",
    "format_value",
    "speakers_subsection_heading",
    "section_list",
)

# key = (source_type_lower | None, field_kind) -> ordered list[RuleFn]
_REGISTRY: "OrderedDict[tuple[str | None, str], list[RuleFn]]" = OrderedDict()


def register(*, source_type: str | None, field_kind: str):
    """Decorator/registrar. ``source_type=None`` => applies to ALL sources."""
    key = (source_type.lower() if isinstance(source_type, str) else None, field_kind)

    def _add(fn: RuleFn) -> RuleFn:
        _REGISTRY.setdefault(key, []).append(fn)
        return fn

    return _add


def _rules_for(source_type: str | None, field_kind: str) -> list[RuleFn]:
    st = source_type.lower() if isinstance(source_type, str) else None
    rules: list[RuleFn] = []
    rules.extend(_REGISTRY.get((None, field_kind), []))
    if st is not None:
        rules.extend(_REGISTRY.get((st, field_kind), []))
    return rules


def apply_text_quality(value: Any, *, source_type: str | None, field_kind: str) -> Any:
    """Run every rule registered for (source_type, field_kind) in order.
    Non-str or no-rule -> returned unchanged (byte-identical)."""
    if not isinstance(value, str):
        return value
    rules = _rules_for(source_type, field_kind)
    if not rules:
        return value
    out = value
    for fn in rules:
        try:
            res = fn(out)
            if isinstance(res, str):
                out = res
        except Exception:
            logger.exception(
                "post-summary rule failed (field_kind=%s, source=%s) — value left unchanged",
                field_kind, source_type,
            )
    return out


# Section-level rules operate on the list[section]; key field_kind is the
# fixed string "section_list". Each rule: list -> list, pure + idempotent.
SectionRuleFn = Callable[[list], list]
_SECTION_REGISTRY: "OrderedDict[str | None, list[SectionRuleFn]]" = OrderedDict()


def register_section(*, source_type: str | None):
    def _add(fn: "SectionRuleFn") -> "SectionRuleFn":
        st = source_type.lower() if isinstance(source_type, str) else None
        _SECTION_REGISTRY.setdefault(st, []).append(fn)
        return fn

    return _add


def apply_sections(sections: Any, *, source_type: str | None) -> Any:
    if not isinstance(sections, list):
        return sections
    st = source_type.lower() if isinstance(source_type, str) else None
    rules = list(_SECTION_REGISTRY.get(None, []))
    if st is not None:
        rules.extend(_SECTION_REGISTRY.get(st, []))
    if not rules:
        return sections
    out = sections
    for fn in rules:
        try:
            res = fn(out)
            if isinstance(res, list):
                out = res
        except Exception:
            logger.exception(
                "post-summary section rule failed (source=%s) — sections unchanged",
                source_type,
            )
    return out
