"""Per-request operation correlation id, propagated via a ContextVar.

Set once at the Add-Zettel runner boundary so deep ingest / dense-verify /
persist log lines can be tied back to a single operation without threading an
id through every function signature. ContextVar (PEP 567) is copy-on-task-spawn
safe, so the id survives ``asyncio.shield`` / ``asyncio.to_thread`` hops inside
the background worker.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_OPERATION_ID: ContextVar[str] = ContextVar("_operation_id", default="-")


def get_operation_id() -> str:
    """Return the current operation id, or ``"-"`` when unset."""
    return _OPERATION_ID.get()


@contextmanager
def operation_context(operation_id: str) -> Iterator[None]:
    """Bind ``operation_id`` for the duration of the with-block."""
    token = _OPERATION_ID.set(operation_id or "-")
    try:
        yield
    finally:
        _OPERATION_ID.reset(token)
