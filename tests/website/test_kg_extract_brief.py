"""Guard against /api/graph drifting away from the shape the KG client expects.

The KG client has a defensive brief extractor (``extractBriefFromSummary`` in
``website/features/knowledge_graph/js/app.js``). This test asserts the contract
holds.

T4.15 / S3 (Phase 4): the server now normalises the AI-summary envelope at
the wire boundary via ``_normalize_summary_for_wire``, so ``summary`` ships
as a parsed dict with keys ``brief`` / ``detailed`` / ``closing``. The
extractor's fast-path keys off ``raw.brief`` (string).

Backward compat: the file-store graph (anonymous path) still ships raw
JSON-encoded strings for any rows that bypass the v2 assembler, and a small
fraction of legacy entries ship plain prose. The extractor handles ALL three
shapes — this test enforces the matching server-side contract.
"""
import json

from fastapi.testclient import TestClient

from website.app import create_app


_LEGACY_EXTRACTOR_KEYS = {
    "brief_summary",
    "briefSummary",
    "summary",
    "detailed_summary",
    "closing_remarks",
}
_NORMALIZED_KEYS = {"brief", "detailed", "closing"}


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
        # T4.15 / S3 path: server-normalised dict with brief/detailed/closing.
        if isinstance(s, dict):
            if not (set(s.keys()) & _NORMALIZED_KEYS):
                bad.append(
                    (n.get("id"), f"normalised summary has none of {sorted(_NORMALIZED_KEYS)}")
                )
            continue
        if not isinstance(s, str):
            bad.append((n.get("id"), "summary is neither a dict nor a string"))
            continue
        # Legacy / file-store path: raw JSON-encoded envelope.
        if s.lstrip().startswith("{"):
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError:
                bad.append((n.get("id"), "summary starts with { but is not valid JSON"))
                continue
            if not isinstance(parsed, dict):
                bad.append((n.get("id"), "JSON summary is not an object"))
                continue
            if not (set(parsed.keys()) & _LEGACY_EXTRACTOR_KEYS):
                bad.append(
                    (n.get("id"), f"JSON summary has none of {sorted(_LEGACY_EXTRACTOR_KEYS)}")
                )

    assert not bad, f"Nodes with extractor-incompatible summary: {bad[:5]}"
