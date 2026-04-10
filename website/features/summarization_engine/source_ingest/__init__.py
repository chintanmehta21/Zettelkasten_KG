"""Auto-discovery registry for source ingestors."""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from website.features.summarization_engine.core.errors import RoutingError
from website.features.summarization_engine.core.models import SourceType

if TYPE_CHECKING:
    from website.features.summarization_engine.source_ingest.base import BaseIngestor

_REGISTRY: dict[SourceType, type["BaseIngestor"]] = {}


def register_ingestor(cls: type["BaseIngestor"]) -> None:
    """Register an ingestor class."""
    if hasattr(cls, "source_type"):
        _REGISTRY[cls.source_type] = cls


def get_ingestor(source_type: SourceType | str) -> type["BaseIngestor"]:
    """Return the ingestor class for a source type."""
    try:
        normalized = SourceType(source_type) if isinstance(source_type, str) else source_type
    except ValueError as exc:
        raise RoutingError(f"No ingestor registered for source_type={source_type!r}", url="") from exc
    if normalized not in _REGISTRY:
        raise RoutingError(f"No ingestor registered for source_type={source_type!r}", url="")
    return _REGISTRY[normalized]


def list_ingestors() -> dict[SourceType, type["BaseIngestor"]]:
    """Return a copy of registered ingestors."""
    return dict(_REGISTRY)


def _auto_discover() -> None:
    from website.features.summarization_engine.source_ingest.base import BaseIngestor

    package_name = __name__
    package_path = __path__  # type: ignore[name-defined]
    for _, modname, ispkg in pkgutil.iter_modules(package_path):
        if not ispkg:
            continue
        try:
            mod = importlib.import_module(f"{package_name}.{modname}.ingest")
        except ModuleNotFoundError:
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseIngestor)
                and obj is not BaseIngestor
                and hasattr(obj, "source_type")
            ):
                register_ingestor(obj)


_auto_discover()
