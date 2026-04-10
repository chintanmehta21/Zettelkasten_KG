"""Tests for API route registration."""

from website.app import create_app


def test_v2_routes_are_registered():
    paths = {route.path for route in create_app().routes}
    assert "/api/v2/summarize" in paths
    assert "/api/v2/batch" in paths
    assert "/summarization-engine" in paths
