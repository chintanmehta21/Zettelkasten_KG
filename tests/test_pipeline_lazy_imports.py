"""Verify website.core.pipeline does NOT eagerly import heavy modules."""
from __future__ import annotations

import sys


HEAVY_MODULES = [
    "telegram_bot.pipeline.summarizer",
    "telegram_bot.sources",
    "telegram_bot.sources.registry",
    "google.genai",
    "trafilatura",
    "yt_dlp",
    "praw",
]


def test_pipeline_module_does_not_import_heavy_deps():
    """Importing website.core.pipeline must not pull in heavy modules."""
    for mod_name in HEAVY_MODULES + ["website.core.pipeline"]:
        sys.modules.pop(mod_name, None)
        for key in list(sys.modules.keys()):
            if key.startswith(mod_name + "."):
                sys.modules.pop(key, None)

    import website.core.pipeline  # noqa: F401

    leaked = [module_name for module_name in HEAVY_MODULES if module_name in sys.modules]
    assert leaked == [], (
        f"website.core.pipeline eagerly imported: {leaked}. "
        f"Move these imports inside summarize_url()."
    )


def test_summarize_url_is_still_callable_after_lazy_refactor():
    """The lazy refactor must not break the public symbol."""
    import website.core.pipeline

    assert hasattr(website.core.pipeline, "summarize_url")
    assert callable(website.core.pipeline.summarize_url)
