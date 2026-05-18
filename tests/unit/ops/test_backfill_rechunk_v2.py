"""Unit coverage for ops/scripts/backfill_rechunk_v2.py (no live DB / LLM).

A hand-rolled fake PostgREST client models the chained
``.schema().table().select().eq().is_().gt().order().limit().execute()`` +
``.delete().eq().execute()`` + ``.upsert(...).execute()`` surface so the
backfill runs fully offline. ``build_canonical_chunks`` is monkeypatched (no
live Gemini / chunker).

Covered (per task spec):
- re-chunk REPLACES old chunks idempotently (delete old + insert new);
- --dry-run performs ZERO writes AND ZERO embed/build calls;
- profile fencing: a workspace-B zettel is never read or written when scoped
  to profile A (UUID-leak assertion on the workspace filter);
- unbounded run (no --profile/--workspace) is refused (exit 2);
- a build_canonical_chunks failure (-> []) SKIPS the zettel and does NOT
  delete its existing chunks (never replace good chunks with nothing);
- shared core: the script imports persist.build_canonical_chunks (no
  duplicated chunk/embed logic).
"""
from __future__ import annotations

from uuid import UUID, uuid4

from ops.scripts import backfill_rechunk_v2 as bf

_PROFILE = str(UUID("00000000-0000-0000-0000-0000000000a1"))
_WS_A = str(UUID("00000000-0000-0000-0000-00000000000a"))
_WS_B = str(UUID("00000000-0000-0000-0000-00000000000b"))


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, schema, table):
        self._c = client
        self._schema = schema
        self._table = table
        self._op = "select"
        self._payload = None
        self._eq = {}
        self._gt = {}

    def select(self, *_c, **_k):
        self._op = "select"
        return self

    def delete(self):
        self._op = "delete"
        return self

    def upsert(self, payload, **_k):
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def is_(self, *_a, **_k):
        return self

    def gt(self, col, val):
        self._gt[col] = val
        return self

    def gte(self, col, val):
        # D5: ContentRepository.upsert_chunks now appends a stale-chunk
        # prune ``DELETE ... .gte("chunk_idx", N)`` after the upsert.
        self._gt[("gte", col)] = val
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def range(self, *_a, **_k):
        return self

    def execute(self):
        self._c.calls.append(
            {
                "schema": self._schema,
                "table": self._table,
                "op": self._op,
                "eq": dict(self._eq),
                "gt": dict(self._gt),
                "payload": self._payload,
            }
        )
        if self._op == "select" and self._table == "workspaces":
            return _Resp(self._c.workspaces_for(self._eq.get("owner_profile_id")))
        if self._op == "select" and self._table == "workspace_zettels":
            return _Resp(
                self._c.zettels_for(self._eq.get("workspace_id"), self._gt.get("id"))
            )
        if self._op == "delete" and self._table == "canonical_chunks":
            # D5 (old->new): ContentRepository.upsert_chunks now appends a
            # BOUNDED stale-chunk prune (DELETE ... .gte("chunk_idx", N))
            # after the upsert. That is distinct from the backfill's OWN
            # full chunk-replace delete (no chunk_idx bound). Record the
            # full delete into ``deleted`` (the test contract) and the
            # bounded prune separately so the prune does not pollute the
            # "the backfill replaced the chunk set" assertion.
            if ("gte", "chunk_idx") in self._gt:
                self._c.pruned.append(self._eq.get("canonical_zettel_id"))
            else:
                self._c.deleted.append(self._eq.get("canonical_zettel_id"))
            return _Resp([])
        if self._op == "upsert" and self._table == "canonical_chunks":
            ids = [str(uuid4()) for _ in self._payload]
            self._c.inserted.append(
                {"cz": self._eq, "n": len(self._payload), "ids": ids}
            )
            return _Resp([{"id": i} for i in ids])
        if self._op == "upsert" and self._table == "workspace_chunk_membership":
            self._c.membership.append(self._payload)
            return _Resp([])
        return _Resp([])


class _Schema:
    def __init__(self, client, schema):
        self._c = client
        self._schema = schema

    def table(self, name):
        return _Query(self._c, self._schema, name)


class _FakeSB:
    def __init__(self, *, zettels_a, zettels_b):
        self.calls = []
        self.deleted = []
        self.pruned = []  # D5 bounded stale-chunk prune (gte chunk_idx)
        self.inserted = []
        self.membership = []
        self._za = zettels_a
        self._zb = zettels_b

    def schema(self, name):
        return _Schema(self, name)

    def workspaces_for(self, owner):
        # Profile A owns WS_A only. Never returns WS_B for profile A.
        if owner == _PROFILE:
            return [{"id": _WS_A}]
        return []

    def zettels_for(self, ws, after):
        rows = self._za if ws == _WS_A else (self._zb if ws == _WS_B else [])
        if after is not None:
            rows = [r for r in rows if str(r["id"]) > after]
        return rows


def _row(*, wz_id: str, cz_id: str, ws_url: str) -> dict:
    return {
        "id": wz_id,
        "canonical_zettel_id": cz_id,
        "ai_summary": "stored summary",
        "user_tags": ["anime"],
        "canonical": {
            "id": cz_id,
            "normalized_url": ws_url,
            "title": "Naruto",
            "source_type": "web",
            "body_md": "A long stored body about Naruto becoming Hokage.",
            "source_metadata": {"metadata": {"author": "Kishimoto"}},
        },
    }


def test_unbounded_run_refused(monkeypatch):
    sb = _FakeSB(zettels_a=[], zettels_b=[])
    rc = bf._run(bf._parse_args([]), sb)
    assert rc == 2
    assert sb.calls == []  # refused before any query


def test_dry_run_zero_writes_zero_build(monkeypatch):
    """--dry-run must not delete, insert, re-link, or call the chunk+embed
    core."""
    build_calls = {"n": 0}

    async def _spy_build(*, payload, detailed_summary):
        build_calls["n"] += 1
        return []

    monkeypatch.setattr(
        "website.core.persist.build_canonical_chunks", _spy_build
    )
    cz = str(uuid4())
    sb = _FakeSB(
        zettels_a=[_row(wz_id=str(uuid4()), cz_id=cz, ws_url="https://a/1")],
        zettels_b=[],
    )
    rc = bf._run(bf._parse_args(["--profile", _PROFILE, "--dry-run"]), sb)
    assert rc == 0
    assert build_calls["n"] == 0
    assert sb.deleted == [] and sb.inserted == [] and sb.membership == []


def test_rechunk_replaces_old_chunks_idempotently(monkeypatch):
    """Live run deletes the old canonical chunks then inserts the freshly
    segmented set and re-links membership — for the in-scope workspace only."""
    from website.core.supabase_v2.models import CanonicalChunkCreate

    async def _fake_build(*, payload, detailed_summary):
        assert payload["raw_text"]  # body_md fed as raw_text
        return [
            CanonicalChunkCreate(
                chunk_idx=i,
                content=f"chunk {i}",
                content_hash=b"\x00" * 32,
                chunk_type="semantic",
                token_count=5,
                embedding=[0.0] * 768,
            )
            for i in range(3)
        ]

    monkeypatch.setattr(
        "website.core.persist.build_canonical_chunks", _fake_build
    )
    cz = str(uuid4())
    wz = str(uuid4())
    sb = _FakeSB(
        zettels_a=[_row(wz_id=wz, cz_id=cz, ws_url="https://a/1")],
        zettels_b=[_row(wz_id=str(uuid4()), cz_id=str(uuid4()), ws_url="https://b/1")],
    )
    rc = bf._run(bf._parse_args(["--profile", _PROFILE]), sb)
    assert rc == 0
    # Deleted the in-scope zettel's old chunks then inserted 3 new ones.
    assert sb.deleted == [cz]
    assert len(sb.inserted) == 1 and sb.inserted[0]["n"] == 3
    # Membership re-linked for the in-scope workspace zettel.
    assert sb.membership and all(
        m[0]["workspace_zettel_id"] == wz for m in sb.membership
    )
    # PROFILE FENCING: WS_B's url/zettel must never appear in any call.
    serialized = repr(sb.calls)
    assert _WS_B not in serialized
    assert "https://b/1" not in serialized


def test_embed_failure_skips_zettel_no_delete(monkeypatch):
    """build_canonical_chunks -> [] (empty source / batch-embed failure)
    must SKIP: do NOT delete the existing good chunks to replace with
    nothing. Retried next run (idempotent)."""

    async def _fail_build(*, payload, detailed_summary):
        return []

    monkeypatch.setattr(
        "website.core.persist.build_canonical_chunks", _fail_build
    )
    cz = str(uuid4())
    sb = _FakeSB(
        zettels_a=[_row(wz_id=str(uuid4()), cz_id=cz, ws_url="https://a/1")],
        zettels_b=[],
    )
    rc = bf._run(bf._parse_args(["--profile", _PROFILE]), sb)
    assert rc == 1  # one failed/skipped
    assert sb.deleted == []  # NEVER deleted the existing chunks
    assert sb.inserted == [] and sb.membership == []


def test_shared_core_is_persist_build_canonical_chunks():
    """No duplicated chunk/embed logic — the script must call the SAME
    persist.build_canonical_chunks the inline path uses."""
    import inspect

    src = inspect.getsource(bf._rechunk_one)
    assert "from website.core.persist import build_canonical_chunks" in src
    assert "build_canonical_chunks(" in src
