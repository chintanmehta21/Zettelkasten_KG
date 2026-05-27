"""Feedback feature — sole public entry point.

`register(app)` mounts the static directory and includes the router.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from website.features.feedback.api.routes import build_router


_FEATURE_ROOT = Path(__file__).resolve().parent
_STATIC_DIR = _FEATURE_ROOT / "ui" / "static"
_TEMPLATES_DIR = _FEATURE_ROOT / "ui" / "templates"


def register(app: FastAPI) -> FastAPI:
    """Wire the feedback feature into a FastAPI app.

    Call once during app construction:

        from website.features.feedback import register as register_feedback
        register_feedback(app)
    """
    app.include_router(build_router(), prefix="/api/feedback")
    app.mount(
        "/feedback-ui",
        _CombinedStatic(_STATIC_DIR, _TEMPLATES_DIR),
        name="feedback-ui",
    )
    return app


class _CombinedStatic(StaticFiles):
    """Serves /feedback-ui/templates/<x> from _TEMPLATES_DIR and everything else
    from _STATIC_DIR.
    """

    def __init__(self, static_dir: Path, templates_dir: Path) -> None:
        super().__init__(directory=str(static_dir), check_dir=True)
        self._templates_dir = templates_dir

    async def get_response(self, path, scope):
        if path.startswith("templates/"):
            sub = path[len("templates/"):]
            self.directory = str(self._templates_dir)
            try:
                return await super().get_response(sub, scope)
            finally:
                self.directory = str(_STATIC_DIR)
        return await super().get_response(path, scope)
