"""Tests for API route registration."""

from website.app import create_app


def test_v2_routes_are_registered():
    # app.routes is a tree on FastAPI 0.137 (an internal detail); the OpenAPI
    # schema is the public, tree-aware way to assert routes are registered.
    paths = set(create_app().openapi()["paths"])
    assert "/api/v2/summarize" in paths
    assert "/api/v2/batch" in paths
    assert "/summarization-engine" in paths
