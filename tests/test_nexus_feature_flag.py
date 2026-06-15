"""Feature-flag coverage for the Nexus UI and router exposure."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.routing import Mount


def _load_app_module():
    sys.modules.pop("website.app", None)
    return importlib.import_module("website.app")


class TestNexusFeatureFlag:
    def test_enabled_by_default_includes_nexus_routes_and_assets(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            app_module = _load_app_module()
            app = app_module.create_app()

        # FastAPI 0.137 made app.routes a tree (an internal detail); assert via
        # public, forward-compatible surfaces — OpenAPI schema for API routes,
        # top-level Mounts for static dirs, a live request for the page.
        client = TestClient(app)
        assert client.get("/home/nexus").status_code == 200
        api_paths = app.openapi()["paths"]
        assert any(p.startswith("/api/nexus") for p in api_paths)
        mount_paths = {r.path for r in app.routes if isinstance(r, Mount)}
        assert "/home/nexus/css" in mount_paths
        assert "/home/nexus/js" in mount_paths

    def test_disabled_excludes_nexus_routes_and_assets(self) -> None:
        with patch.dict("os.environ", {"NEXUS_ENABLED": "false"}, clear=True):
            app_module = _load_app_module()
            app = app_module.create_app()

        # Disabled → page 404, no nexus API routes in the schema, no nexus
        # static Mounts (see the enabled case for why we use these surfaces).
        client = TestClient(app)
        assert client.get("/home/nexus").status_code == 404
        api_paths = app.openapi()["paths"]
        assert not any(p.startswith("/api/nexus") for p in api_paths)
        mount_paths = {r.path for r in app.routes if isinstance(r, Mount)}
        assert "/home/nexus/css" not in mount_paths
        assert "/home/nexus/js" not in mount_paths
