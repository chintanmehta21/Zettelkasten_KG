"""Auto-discovery registry for source summarizers."""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from website.features.summarization_engine.core.errors import RoutingError
from website.features.summarization_engine.core.models import SourceType

if TYPE_CHECKING:
    from website.features.summarization_engine.summarization.base import BaseSummarizer

_REGISTRY: dict[SourceType, type["BaseSummarizer"]] = {}


def register_summarizer(cls: type["BaseSummarizer"]) -> None:
    """Register a summarizer class."""
    if hasattr(cls, "source_type"):
        _REGISTRY[cls.source_type] = cls


def get_summarizer(source_type: SourceType | str) -> type["BaseSummarizer"]:
    """Return the summarizer class for a source type."""
    try:
        normalized = SourceType(source_type) if isinstance(source_type, str) else source_type
    except ValueError as exc:
        raise RoutingError(f"No summarizer registered for source_type={source_type!r}", url="") from exc
    if normalized not in _REGISTRY:
        raise RoutingError(f"No summarizer registered for source_type={source_type!r}", url="")
    return _REGISTRY[normalized]


def list_summarizers() -> dict[SourceType, type["BaseSummarizer"]]:
    """Return a copy of registered summarizers."""
    return dict(_REGISTRY)


def _auto_discover() -> None:
    from website.features.summarization_engine.summarization.base import BaseSummarizer

    package_name = __name__
    package_path = __path__  # type: ignore[name-defined]
    for _, modname, ispkg in pkgutil.iter_modules(package_path):
        if not ispkg or modname == "common":
            continue
        try:
            mod = importlib.import_module(f"{package_name}.{modname}.summarizer")
        except ModuleNotFoundError:
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseSummarizer)
                and obj is not BaseSummarizer
                and hasattr(obj, "source_type")
            ):
                register_summarizer(obj)


_auto_discover()

