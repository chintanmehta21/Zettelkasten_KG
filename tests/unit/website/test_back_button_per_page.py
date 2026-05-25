"""Asserts the per-page back-button rule from design spec §9: /home hides
the back-button (it's the dashboard entry, no "back" semantics); every
other shared-header page renders it."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


@pytest.mark.parametrize("path", [
    "/home/zettels",
    "/home/kastens",
    "/home/rag",
    "/home/nexus",
    "/profile",
    "/pricing",
])
def test_back_button_present_on_non_home_pages(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "data-zk-back" in resp.text


def test_back_button_absent_on_home(client):
    resp = client.get("/home")
    assert resp.status_code == 200
    assert "data-zk-back" not in resp.text
