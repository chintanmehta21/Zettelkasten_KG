"""Feature-flag coverage for the Nexus UI and router exposure."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient


def _load_app_module():
    sys.modules.pop("website.app", None)
    return importlib.import_module("website.app")


class TestNexusFeatureFlag:
    def test_enabled_by_default_includes_nexus_routes_and_assets(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            app_module = _load_app_module()
            app = app_module.create_app()

        routes = {route.path for route in app.routes}
        assert "/home/nexus" in routes
        assert "/home/nexus/css" in routes
        assert "/home/nexus/js" in routes
        assert any(path.startswith("/api/nexus") for path in routes)

        client = TestClient(app)
        response = client.get("/home/nexus")
        assert response.status_code == 200

    def test_disabled_excludes_nexus_routes_and_assets(self) -> None:
        with patch.dict("os.environ", {"NEXUS_ENABLED": "false"}, clear=True):
            app_module = _load_app_module()
            app = app_module.create_app()

        routes = {route.path for route in app.routes}
        assert "/home/nexus" not in routes
        assert "/home/nexus/css" not in routes
        assert "/home/nexus/js" not in routes
        assert not any(path.startswith("/api/nexus") for path in routes)

        client = TestClient(app)
        response = client.get("/home/nexus")
        assert response.status_code == 404
