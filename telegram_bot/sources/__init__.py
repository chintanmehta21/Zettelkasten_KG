"""Dynamic source extractor registry.

Auto-discovers all SourceExtractor subclasses in this package at import time.
To add a new source: create a module in ``telegram_bot/sources/`` with a
class inheriting from :class:`SourceExtractor`. It will be registered
automatically — no manual wiring needed (R014).

Usage::

    from telegram_bot.sources import get_extractor, list_extractors
    extractor = get_extractor(SourceType.REDDIT, settings)
    content = await extractor.extract(url)
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

from telegram_bot.models.capture import SourceType
from telegram_bot.sources.base import SourceExtractor

if TYPE_CHECKING:
    from telegram_bot.config.settings import Settings

logger = logging.getLogger(__name__)

# Maps SourceType → extractor class (populated by _discover_extractors)
_REGISTRY: dict[SourceType, type[SourceExtractor]] = {}


def _discover_extractors() -> None:
    """Import all modules in this package to trigger registration.

    Any module that defines a concrete SourceExtractor subclass with a
    ``source_type`` attribute will be picked up automatically.
    """
    package = importlib.import_module(__package__)
    for _importer, module_name, _is_pkg in pkgutil.iter_modules(package.__path__):
        if module_name in ("base", "registry", "__init__"):
            continue
        try:
            mod = importlib.import_module(f"{__package__}.{module_name}")
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, SourceExtractor)
                    and attr is not SourceExtractor
                    and hasattr(attr, "source_type")
                    and attr.source_type is not None
                ):
                    _REGISTRY[attr.source_type] = attr
                    logger.debug(
                        "Registered extractor %s for %s", attr.__name__, attr.source_type
                    )
        except Exception as exc:
            logger.warning("Failed to import source module %s: %s", module_name, exc)


# Auto-discover on first import
_discover_extractors()


def get_extractor(source_type: SourceType, settings: Settings) -> SourceExtractor:
    """Return an instantiated extractor for *source_type*.

    Args:
        source_type: The content source to extract.
        settings: Application settings (used to inject credentials).

    Returns:
        A concrete :class:`SourceExtractor` instance.

    Raises:
        KeyError: If no extractor is registered for *source_type*.
    """
    if source_type not in _REGISTRY:
        raise KeyError(
            f"No extractor registered for {source_type}. "
            f"Available: {list(_REGISTRY.keys())}"
        )

    cls = _REGISTRY[source_type]

    # Inject credentials based on source type
    if source_type == SourceType.REDDIT:
        return cls(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            comment_depth=settings.reddit_comment_depth,
        )

    # Most extractors need no constructor args
    return cls()


def list_extractors() -> dict[SourceType, str]:
    """Return a mapping of registered source types to extractor class names."""
    return {st: cls.__name__ for st, cls in _REGISTRY.items()}
