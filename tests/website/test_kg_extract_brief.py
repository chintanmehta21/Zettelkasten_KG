"""Guard against /api/graph drifting away from the shape the KG client expects.

The KG client has a defensive brief extractor (extractBriefFromSummary in
website/features/knowledge_graph/js/app.js). This test asserts the contract
holds: nodes ship a `summary` field that is either a plain string OR a
JSON-stringified object containing at least one of the keys the extractor
walks (brief_summary, summary, detailed_summary, closing_remarks).
"""
import json

from fastapi.testclient import TestClient

from website.app import create_app


_EXTRACTOR_KEYS = {"brief_summary", "briefSummary", "summary", "detailed_summary", "closing_remarks"}


def test_graph_summary_field_is_extractor_compatible():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/graph")
    assert resp.status_code == 200
    payload = resp.json()
    nodes = payload.get("nodes") or []
    if not nodes:
        # Empty graph in CI — contract trivially holds.
        return

    bad = []
    for n in nodes:
        s = n.get("summary")
        if s is None or s == "":
            continue  # extractor handles empty.
        if not isinstance(s, str):
            bad.append((n.get("id"), "non-string summary"))
            continue
        if s.lstrip().startswith("{"):
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError:
                bad.append((n.get("id"), "summary starts with { but is not valid JSON"))
                continue
            if not isinstance(parsed, dict):
                bad.append((n.get("id"), "JSON summary is not an object"))
                continue
            if not (set(parsed.keys()) & _EXTRACTOR_KEYS):
                bad.append((n.get("id"), f"JSON summary has none of the extractor keys ({sorted(_EXTRACTOR_KEYS)})"))

    assert not bad, f"Nodes with extractor-incompatible summary: {bad[:5]}"
