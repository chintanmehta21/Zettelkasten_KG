"""Deterministic README signal extraction.

Parses the ingested README body for high-value facts that the LLM should never
be allowed to invent or omit: exact public surfaces (endpoints, CLI flags,
decorators), install commands, quickstart snippets, and language/stack.

These signals are fed into prompts as a must-preserve slot AND used by the
graceful-fallback brief builder when structured extraction fails.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_CODE_FENCE = re.compile(r"```(?:\w+)?\s*(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_ENDPOINT_PATH = re.compile(r"(?<![\w/])(/[A-Za-z0-9_\-./{}:]+)")
_DECORATOR = re.compile(r"@[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+")
_CLI_FLAG = re.compile(r"(?<!\w)(--[A-Za-z][\w-]*)")
_PIP_INSTALL = re.compile(r"(pip install [^\n`]+?)(?=[\n`]|\s{2,}|$)", re.IGNORECASE)
_POETRY_INSTALL = re.compile(r"(poetry (?:add|install)[^\n`]*?)(?=[\n`]|\s{2,}|$)", re.IGNORECASE)
_NPM_INSTALL = re.compile(r"((?:npm|yarn|pnpm) (?:add|install)[^\n`]*?)(?=[\n`]|\s{2,}|$)", re.IGNORECASE)
_CARGO_INSTALL = re.compile(r"(cargo (?:install|add)[^\n`]*?)(?=[\n`]|\s{2,}|$)", re.IGNORECASE)
_GO_INSTALL = re.compile(r"(go (?:install|get)[^\n`]*?)(?=[\n`]|\s{2,}|$)", re.IGNORECASE)

_GENERIC_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "your", "our",
    "using", "use", "uses", "used",
}


@dataclass(frozen=True)
class ReadmeSignals:
    install_cmds: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()
    cli_flags: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    inline_code: tuple[str, ...] = ()
    first_code_block: str = ""
    stack: tuple[str, ...] = ()
    purpose_sentence: str = ""

    def any_public_surface(self) -> tuple[str, ...]:
        """Ranked best-effort list of exact public surface names.

        Decorators, endpoints, and CLI flags are high-signal: they're the
        user-facing entry points README code examples document. Inline
        code tokens (backtick spans) are too noisy for must-preserve —
        they leak internal helpers (`provide_automatic_options`) and
        exception names (`DuplicateRuleError`) that the LLM then echoes
        as "documented public surfaces", triggering
        invented_public_interface anti-patterns. Use
        `any_public_surface_with_inline()` when inline tokens are wanted.
        """
        out: list[str] = []
        for bucket in (self.decorators, self.endpoints, self.cli_flags):
            for item in bucket:
                if item and item not in out:
                    out.append(item)
        return tuple(out[:8])

    def any_public_surface_with_inline(self) -> tuple[str, ...]:
        """Include inline-code tokens; use only for best-effort fallback prose."""
        out: list[str] = list(self.any_public_surface())
        for item in self.inline_code:
            if item and item not in out:
                out.append(item)
        return tuple(out[:10])


def extract_signals(
    *,
    raw_text: str,
    metadata: dict | None = None,
) -> ReadmeSignals:
    """Extract deterministic README signals. Never calls an LLM, never raises."""
    text = raw_text or ""
    meta = metadata or {}

    # Endpoints: only keep plausible URL paths, drop file paths (no dots in final segment)
    endpoints: list[str] = []
    for path in _ENDPOINT_PATH.findall(text):
        if path.startswith("//") or path.endswith("/"):
            continue
        # skip filesystem-like paths — keep root-level routes
        if path.count("/") <= 3 and not re.search(r"\.[a-z]{1,5}$", path):
            if path not in endpoints:
                endpoints.append(path)
    endpoints = [p for p in endpoints if len(p) <= 40][:8]

    decorators = _unique_preserve(_DECORATOR.findall(text))[:8]
    cli_flags = _unique_preserve(_CLI_FLAG.findall(text))[:10]

    inline: list[str] = []
    for token in _INLINE_CODE.findall(text):
        tok = token.strip()
        if not tok or len(tok) > 40 or len(tok) < 2:
            continue
        if tok.lower() in _GENERIC_WORDS:
            continue
        if tok not in inline:
            inline.append(tok)
    inline = inline[:12]

    install_cmds: list[str] = []
    for pattern in (_PIP_INSTALL, _POETRY_INSTALL, _NPM_INSTALL, _CARGO_INSTALL, _GO_INSTALL):
        for m in pattern.findall(text):
            cmd = m.strip().strip("`")
            if cmd and cmd not in install_cmds:
                install_cmds.append(cmd)
    install_cmds = install_cmds[:4]

    first_code_block = ""
    cb = _CODE_FENCE.search(text)
    if cb:
        first_code_block = cb.group(1).strip()[:400]

    stack = _derive_stack(text, meta)

    return ReadmeSignals(
        install_cmds=tuple(install_cmds),
        endpoints=tuple(endpoints),
        cli_flags=tuple(cli_flags),
        decorators=tuple(decorators),
        inline_code=tuple(inline),
        first_code_block=first_code_block,
        stack=tuple(stack),
        purpose_sentence=_derive_purpose(text, meta),
    )


def _unique_preserve(items) -> list[str]:
    seen: list[str] = []
    for it in items:
        val = str(it).strip()
        if val and val not in seen:
            seen.append(val)
    return seen


def _derive_stack(text: str, meta: dict) -> list[str]:
    stack: list[str] = []
    lang = meta.get("language")
    if isinstance(lang, str) and lang.strip():
        stack.append(lang.strip())
    langs = meta.get("languages")
    if isinstance(langs, (list, tuple)):
        for entry in langs[:3]:
            if isinstance(entry, (list, tuple)) and entry:
                name = str(entry[0]).strip()
                if name and name not in stack:
                    stack.append(name)
            elif isinstance(entry, str) and entry.strip() and entry not in stack:
                stack.append(entry.strip())
    lowered = text.lower()
    for kw in (
        "starlette", "pydantic", "asgi", "uvicorn", "click", "typer", "argparse",
        "httpx", "numpy", "pytorch", "tensorflow", "django", "flask", "fastapi",
        "sqlalchemy", "react", "node.js", "tokio",
    ):
        if kw in lowered and kw not in [s.lower() for s in stack]:
            stack.append(kw)
    return stack[:6]


def _derive_purpose(text: str, meta: dict) -> str:
    """First non-title sentence that states what the repo does."""
    desc = meta.get("description")
    if isinstance(desc, str) and 20 <= len(desc) <= 260:
        return desc.strip().rstrip(".") + "."
    # README body: skip heading lines, grab the first plain prose sentence
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "-", "*", ">", "|", "`", "!", "[")):
            continue
        if len(s) < 30 or len(s) > 400:
            continue
        # Stop at first period
        m = re.search(r"^(.{30,320}?[\.!?])\s", s + " ")
        if m:
            return m.group(1).strip()
        return s[:280]
    return ""
