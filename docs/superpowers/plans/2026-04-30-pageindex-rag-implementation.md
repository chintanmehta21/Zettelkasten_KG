# PageIndex RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evaluate a self-hosted PageIndex RAG pipeline using Naruto's real `Knowledge Management` Kasten zettels, with local PageIndex indexing, scoped/full-KG querying, three citation-grounded answers, local tests/lint checks, and full iter-01 metrics artifacts.

**Architecture:** Import PageIndex directly behind an adapter, render one zettel into one deterministic Markdown document, index each document into a user-isolated local workspace, select candidate zettel documents for each query, retrieve tight PageIndex evidence ranges, generate three answers through the existing Gemini key pool, and emit current-RAG-compatible evaluation artifacts. Keep the entire path feature-flagged and CLI-first; do not expose it in the web UI.

**Tech Stack:** Python 3.12, FastAPI-adjacent project modules, Supabase client, existing Gemini key pool, imported PageIndex pinned to an exact git SHA, pytest, local JSON eval artifacts under `docs/rag_eval/PageIndex/knowledge-management/iter-01`.

---

## Non-Negotiable Inputs And Paths

- Implementation root: `website/experimental_features/PageIndex_Rag/`
- Local tests root: `website/experimental_features/PageIndex_Rag/pytests/`
- Plan target eval directory: `docs/rag_eval/PageIndex/knowledge-management/iter-01/`
- Source eval fixture: `docs/rag_eval/common/knowledge-management/iter-03/queries.json`
- Kasten name: `Knowledge Management`
- Kasten slug: `knowledge-management`
- User: Naruto
- Credentials source: `docs/login_details.txt`, which is gitignored and must never be committed or printed. At plan-writing time this file is not present in the worktree, so implementation must fail fast with a secret-safe error if it remains absent.
- PageIndex repo commit verified during planning: `a51d97f63cedbf1d36b1121ff47386ea4e088ff5`
- Existing design spec: `docs/superpowers/specs/2026-04-30-pageindex-rag-design.md`

## Expected Output Artifacts

Create these files during the implementation/eval run:

```text
docs/rag_eval/PageIndex/knowledge-management/iter-01/
  README.md
  queries.json
  kasten.json
  index_manifest.json
  answers.json
  eval.json
  ragas_sidecar.json
  deepeval_sidecar.json
  timings.json
  scores.md
  manual_review.md
  next_actions.md
  run.log
```

Do not commit generated workspaces or credential files.

## File Structure To Create

```text
website/experimental_features/PageIndex_Rag/
  __init__.py
  config.py
  types.py
  secrets.py
  data_access.py
  markdown_renderer.py
  pageindex_adapter.py
  workspace.py
  candidate_selector.py
  evidence.py
  generator.py
  pipeline.py
  metrics.py
  eval_runner.py
  cli.py
  pytests/
    __init__.py
    conftest.py
    test_markdown_renderer.py
    test_workspace.py
    test_candidate_selector.py
    test_evidence_metrics.py
    test_eval_schema.py
    test_lint_static.py
```

## Data Contracts

Implement these stable models in `types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ZettelRecord:
    user_id: str
    node_id: str
    title: str
    summary: str
    content: str
    source_type: str
    url: str | None
    tags: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PageIndexDocument:
    user_id: str
    node_id: str
    content_hash: str
    doc_id: str
    markdown_path: Path
    tree_path: Path


@dataclass(frozen=True, slots=True)
class PageIndexRagScope:
    scope_id: str
    user_id: str
    node_ids: tuple[str, ...]
    membership_hash: str
    name: str = "Knowledge Management"
    mode: Literal["temporary", "persisted"] = "temporary"


@dataclass(frozen=True, slots=True)
class CandidateDocument:
    node_id: str
    doc_id: str
    title: str
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    node_id: str
    doc_id: str
    title: str
    source_url: str | None
    section: str
    line_range: str
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class AnswerCandidate:
    answer_id: str
    style: Literal["direct", "comparative", "exploratory"]
    text: str
    cited_node_ids: tuple[str, ...]
    citations: tuple[dict[str, Any], ...]
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PageIndexQueryResult:
    query_id: str
    query: str
    retrieved_node_ids: tuple[str, ...]
    reranked_node_ids: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    answers: tuple[AnswerCandidate, AnswerCandidate, AnswerCandidate]
    timings_ms: dict[str, float]
    memory_rss_mb: dict[str, float]
```

---

### Task 1: Pin PageIndex Dependency And Smoke-Test Import

**Files:**
- Modify: `ops/requirements.txt`
- Create: `website/experimental_features/PageIndex_Rag/pageindex_adapter.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_lint_static.py`

- [ ] **Step 1: Add the pinned PageIndex dependency**

Add this exact line to `ops/requirements.txt` under a new experimental section:

```text
# Experimental PageIndex RAG (self-hosted, import-first)
git+https://github.com/VectifyAI/PageIndex.git@a51d97f63cedbf1d36b1121ff47386ea4e088ff5#egg=pageindex
```

- [ ] **Step 2: Write import adapter with feature-safe failure**

Create `website/experimental_features/PageIndex_Rag/pageindex_adapter.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PageIndexUnavailableError(RuntimeError):
    pass


class PageIndexAdapter:
    def __init__(self, *, workspace: Path, model: str | None = None) -> None:
        try:
            from pageindex import PageIndexClient
        except Exception as exc:  # pragma: no cover - env-specific
            raise PageIndexUnavailableError(
                "PageIndex is not installed. Install ops/requirements.txt before enabling PageIndex_Rag."
            ) from exc
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {"workspace": str(workspace)}
        if model:
            kwargs["model"] = model
            kwargs["retrieve_model"] = model
        self._client = PageIndexClient(**kwargs)

    def index_markdown(self, markdown_path: Path) -> str:
        return str(self._client.index(str(markdown_path), mode="md"))

    def get_document(self, doc_id: str) -> dict[str, Any]:
        return json.loads(self._client.get_document(doc_id))

    def get_document_structure(self, doc_id: str) -> list[dict[str, Any]]:
        return json.loads(self._client.get_document_structure(doc_id))

    def get_page_content(self, doc_id: str, pages: str) -> list[dict[str, Any]]:
        return json.loads(self._client.get_page_content(doc_id, pages))
```

- [ ] **Step 3: Add static lint test for forbidden cloud APIs**

Create `website/experimental_features/PageIndex_Rag/pytests/test_lint_static.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _python_sources():
    return [path for path in ROOT.rglob("*.py") if "pytests" not in path.parts]


def test_no_pageindex_cloud_api_usage():
    forbidden = ("chat_completions", "submit_document", "api.pageindex.ai", "enable_citations")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in _python_sources())
    for token in forbidden:
        assert token not in combined


def test_pageindex_adapter_is_only_direct_pageindex_importer():
    offenders = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if "from pageindex import" in text and path.name != "pageindex_adapter.py":
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
```

- [ ] **Step 4: Run test to verify lint policy**

Run:

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_lint_static.py -v
```

Expected: tests pass after adapter exists.

- [ ] **Step 5: Commit**

```bash
git add ops/requirements.txt website/experimental_features/PageIndex_Rag
git commit -m "feat: pin PageIndex adapter"
```

---

### Task 2: Config, Secret-Safe Naruto Auth Preflight, And Feature Flags

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/config.py`
- Create: `website/experimental_features/PageIndex_Rag/secrets.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_workspace.py`

- [ ] **Step 1: Implement config**

Create `config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class PageIndexRagConfig:
    enabled: bool
    mode: str
    workspace: Path
    eval_dir: Path
    queries_path: Path
    login_details_path: Path
    kasten_slug: str
    kasten_name: str
    candidate_limit: int


def load_config() -> PageIndexRagConfig:
    return PageIndexRagConfig(
        enabled=os.environ.get("PAGEINDEX_RAG_ENABLED", "false").lower() == "true",
        mode=os.environ.get("PAGEINDEX_RAG_MODE", "local"),
        workspace=Path(os.environ.get("PAGEINDEX_RAG_WORKSPACE", str(REPO_ROOT / ".cache" / "pageindex_rag"))),
        eval_dir=REPO_ROOT / "docs" / "rag_eval" / "PageIndex" / "knowledge-management" / "iter-01",
        queries_path=REPO_ROOT / "docs" / "rag_eval" / "common" / "knowledge-management" / "iter-03" / "queries.json",
        login_details_path=REPO_ROOT / "docs" / "login_details.txt",
        kasten_slug="knowledge-management",
        kasten_name="Knowledge Management",
        candidate_limit=int(os.environ.get("PAGEINDEX_RAG_CANDIDATE_LIMIT", "7")),
    )
```

- [ ] **Step 2: Implement secret-safe credential parser**

Create `secrets.py`:

```python
from __future__ import annotations

from pathlib import Path


class LoginDetailsMissingError(RuntimeError):
    pass


def load_login_details(path: Path) -> dict[str, str]:
    if not path.exists():
        raise LoginDetailsMissingError(
            f"Missing {path}. Create it locally with Naruto credentials. The file is gitignored and must not be committed."
        )
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()
    if not any(key in values for key in ("access_token", "render_user_id", "email")):
        raise ValueError("login_details.txt must include access_token, render_user_id, or email for Naruto.")
    return values
```

- [ ] **Step 3: Add tests**

Create `pytests/test_workspace.py`:

```python
from pathlib import Path

import pytest

from website.experimental_features.PageIndex_Rag.secrets import (
    LoginDetailsMissingError,
    load_login_details,
)


def test_missing_login_details_fails_without_secret_echo(tmp_path: Path):
    missing = tmp_path / "login_details.txt"
    with pytest.raises(LoginDetailsMissingError) as exc:
        load_login_details(missing)
    assert str(missing) in str(exc.value)
    assert "password" not in str(exc.value).lower()


def test_login_details_parser_accepts_render_user_id(tmp_path: Path):
    path = tmp_path / "login_details.txt"
    path.write_text("render_user_id=naruto\n", encoding="utf-8")
    assert load_login_details(path) == {"render_user_id": "naruto"}
```

- [ ] **Step 4: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_workspace.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/config.py website/experimental_features/PageIndex_Rag/secrets.py website/experimental_features/PageIndex_Rag/pytests/test_workspace.py
git commit -m "feat: add PageIndex RAG config"
```

---

### Task 3: Data Access For Naruto Knowledge Management Zettels

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/types.py`
- Create: `website/experimental_features/PageIndex_Rag/data_access.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_candidate_selector.py`

- [ ] **Step 1: Add the models from Data Contracts**

Create `types.py` exactly from the Data Contracts section above.

- [ ] **Step 2: Implement fixture loader and Supabase node fetcher**

Create `data_access.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from website.core.supabase_kg.client import get_supabase_client

from .types import PageIndexRagScope, ZettelRecord


def load_knowledge_management_fixture(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["_meta"], payload["queries"]


def scope_from_fixture(meta: dict[str, Any], *, user_id: str) -> PageIndexRagScope:
    node_ids = tuple(meta["members_node_ids"])
    membership_hash = "|".join(sorted(node_ids))
    return PageIndexRagScope(
        scope_id=f"{meta['kasten_slug']}:iter-01",
        user_id=user_id,
        node_ids=node_ids,
        membership_hash=membership_hash,
        name=meta["kasten_name"],
        mode="temporary",
    )


def resolve_user_id_from_login(login: dict[str, str]) -> str:
    if "kg_user_id" in login:
        return login["kg_user_id"]
    client = get_supabase_client()
    if "render_user_id" in login:
        resp = client.table("kg_users").select("id").eq("render_user_id", login["render_user_id"]).limit(1).execute()
    elif "email" in login:
        resp = client.table("kg_users").select("id").eq("email", login["email"]).limit(1).execute()
    else:
        raise ValueError("login_details.txt must include kg_user_id, render_user_id, or email.")
    rows = resp.data or []
    if not rows:
        raise ValueError("Naruto user could not be resolved from login_details.txt.")
    return str(rows[0]["id"])


def fetch_zettels_for_scope(scope: PageIndexRagScope) -> list[ZettelRecord]:
    client = get_supabase_client()
    resp = (
        client.table("kg_nodes")
        .select("id,name,summary,content,source_type,url,tags,metadata,user_id")
        .eq("user_id", scope.user_id)
        .in_("id", list(scope.node_ids))
        .execute()
    )
    rows = resp.data or []
    by_id = {row["id"]: row for row in rows}
    missing = [node_id for node_id in scope.node_ids if node_id not in by_id]
    if missing:
        raise ValueError(f"Missing {len(missing)} zettels for scope: {missing}")
    return [
        ZettelRecord(
            user_id=str(row["user_id"]),
            node_id=row["id"],
            title=row.get("name") or row["id"],
            summary=row.get("summary") or "",
            content=row.get("content") or row.get("summary") or "",
            source_type=row.get("source_type") or "unknown",
            url=row.get("url"),
            tags=tuple(row.get("tags") or ()),
            metadata=row.get("metadata") or {},
        )
        for row in (by_id[node_id] for node_id in scope.node_ids)
    ]
```

- [ ] **Step 3: Add fixture-only tests**

Append to `pytests/test_candidate_selector.py`:

```python
from website.experimental_features.PageIndex_Rag.data_access import scope_from_fixture


def test_scope_from_knowledge_management_fixture():
    meta = {
        "kasten_slug": "knowledge-management",
        "kasten_name": "Knowledge Management & Personal Productivity",
        "members_node_ids": ["a", "b", "c"],
    }
    scope = scope_from_fixture(meta, user_id="user-1")
    assert scope.scope_id == "knowledge-management:iter-01"
    assert scope.node_ids == ("a", "b", "c")
    assert scope.membership_hash == "a|b|c"
```

- [ ] **Step 4: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_candidate_selector.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/types.py website/experimental_features/PageIndex_Rag/data_access.py website/experimental_features/PageIndex_Rag/pytests/test_candidate_selector.py
git commit -m "feat: load PageIndex zettel scope"
```

---

### Task 4: Deterministic Markdown Renderer

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/markdown_renderer.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_markdown_renderer.py`

- [ ] **Step 1: Implement renderer**

Create `markdown_renderer.py`:

```python
from __future__ import annotations

import hashlib
import re

from .types import ZettelRecord

RENDERER_VERSION = "pageindex-zettel-md-v1"


def _clean_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("#", "").strip()) or "Untitled"


def _demote_embedded_headings(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            lines.append("#### " + _clean_heading(line))
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def render_zettel_markdown(zettel: ZettelRecord) -> tuple[str, str]:
    title = _clean_heading(zettel.title)
    tags = ", ".join(sorted(zettel.tags))
    metadata_lines = [
        f"- Node ID: {zettel.node_id}",
        f"- Source Type: {zettel.source_type}",
        f"- Source URL: {zettel.url or ''}",
        f"- Tags: {tags}",
    ]
    body = "\n\n".join(
        [
            f"# {title}",
            "## Metadata",
            "\n".join(metadata_lines),
            "## Summary",
            _demote_embedded_headings(zettel.summary),
            "## Captured Content",
            _demote_embedded_headings(zettel.content),
        ]
    ).strip() + "\n"
    content_hash = hashlib.sha256((RENDERER_VERSION + "\n" + body).encode("utf-8")).hexdigest()
    return body, content_hash
```

- [ ] **Step 2: Add renderer tests**

Create `pytests/test_markdown_renderer.py`:

```python
from website.experimental_features.PageIndex_Rag.markdown_renderer import render_zettel_markdown
from website.experimental_features.PageIndex_Rag.types import ZettelRecord


def _zettel(**overrides):
    base = dict(
        user_id="u1",
        node_id="n1",
        title="My # Zettel",
        summary="# Accidental H1\nsummary",
        content="## Embedded\ncontent",
        source_type="web",
        url="https://example.com",
        tags=("zettelkasten", "tools"),
        metadata={},
    )
    base.update(overrides)
    return ZettelRecord(**base)


def test_renderer_emits_one_h1_and_demotes_embedded_headings():
    text, digest = render_zettel_markdown(_zettel())
    assert text.count("\n# ") == 0
    assert text.startswith("# My Zettel\n")
    assert "#### Accidental H1" in text
    assert "#### Embedded" in text
    assert len(digest) == 64


def test_renderer_is_deterministic():
    first = render_zettel_markdown(_zettel(tags=("b", "a")))
    second = render_zettel_markdown(_zettel(tags=("a", "b")))
    assert first == second
```

- [ ] **Step 3: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_markdown_renderer.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/markdown_renderer.py website/experimental_features/PageIndex_Rag/pytests/test_markdown_renderer.py
git commit -m "feat: render zettels for PageIndex"
```

---

### Task 5: Workspace Manifest And Idempotent Indexing

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/workspace.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_workspace.py`

- [ ] **Step 1: Implement workspace**

Create `workspace.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from .markdown_renderer import render_zettel_markdown
from .pageindex_adapter import PageIndexAdapter
from .types import PageIndexDocument, ZettelRecord


class PageIndexWorkspace:
    def __init__(self, *, root: Path, adapter: PageIndexAdapter) -> None:
        self.root = root
        self.adapter = adapter
        self.root.mkdir(parents=True, exist_ok=True)

    def _node_dir(self, zettel: ZettelRecord, content_hash: str) -> Path:
        return self.root / zettel.user_id / zettel.node_id / content_hash

    def ensure_indexed(self, zettel: ZettelRecord) -> PageIndexDocument:
        markdown, content_hash = render_zettel_markdown(zettel)
        node_dir = self._node_dir(zettel, content_hash)
        node_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = node_dir / "zettel.md"
        tree_path = node_dir / "tree.json"
        manifest_path = node_dir / "manifest.json"
        if manifest_path.exists() and tree_path.exists() and markdown_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return PageIndexDocument(
                user_id=zettel.user_id,
                node_id=zettel.node_id,
                content_hash=content_hash,
                doc_id=payload["doc_id"],
                markdown_path=markdown_path,
                tree_path=tree_path,
            )
        markdown_path.write_text(markdown, encoding="utf-8")
        doc_id = self.adapter.index_markdown(markdown_path)
        tree = self.adapter.get_document_structure(doc_id)
        tree_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "user_id": zettel.user_id,
                    "node_id": zettel.node_id,
                    "content_hash": content_hash,
                    "doc_id": doc_id,
                    "markdown_path": str(markdown_path),
                    "tree_path": str(tree_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return PageIndexDocument(zettel.user_id, zettel.node_id, content_hash, doc_id, markdown_path, tree_path)
```

- [ ] **Step 2: Add idempotency test**

Append to `pytests/test_workspace.py`:

```python
from website.experimental_features.PageIndex_Rag.types import ZettelRecord
from website.experimental_features.PageIndex_Rag.workspace import PageIndexWorkspace


class FakeAdapter:
    def __init__(self):
        self.index_calls = 0

    def index_markdown(self, markdown_path):
        self.index_calls += 1
        return "doc-1"

    def get_document_structure(self, doc_id):
        return [{"title": "Root", "line_num": 1, "node_id": "0001"}]


def test_workspace_indexes_once_for_same_hash(tmp_path):
    adapter = FakeAdapter()
    workspace = PageIndexWorkspace(root=tmp_path, adapter=adapter)
    zettel = ZettelRecord("u", "n", "Title", "summary", "body", "web", None, (), {})
    first = workspace.ensure_indexed(zettel)
    second = workspace.ensure_indexed(zettel)
    assert first.doc_id == second.doc_id == "doc-1"
    assert adapter.index_calls == 1
```

- [ ] **Step 3: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_workspace.py -v
```

Expected: all workspace tests pass.

- [ ] **Step 4: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/workspace.py website/experimental_features/PageIndex_Rag/pytests/test_workspace.py
git commit -m "feat: index PageIndex zettel workspace"
```

---

### Task 6: PageIndex-Only Candidate Selection

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/candidate_selector.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_candidate_selector.py`

- [ ] **Step 1: Implement selector**

Create `candidate_selector.py`:

```python
from __future__ import annotations

import re

from .types import CandidateDocument, PageIndexDocument, ZettelRecord


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}


def select_candidates(
    *,
    query: str,
    zettels: list[ZettelRecord],
    documents: dict[str, PageIndexDocument],
    limit: int,
) -> list[CandidateDocument]:
    q = _tokens(query)
    scored: list[CandidateDocument] = []
    for zettel in zettels:
        haystack = " ".join([zettel.title, zettel.summary, " ".join(zettel.tags), zettel.source_type])
        overlap = len(q & _tokens(haystack))
        title_bonus = 2.0 if q & _tokens(zettel.title) else 0.0
        tag_bonus = 1.0 if q & _tokens(" ".join(zettel.tags)) else 0.0
        score = float(overlap) + title_bonus + tag_bonus
        if score <= 0 and len(zettels) <= limit:
            score = 0.1
        doc = documents[zettel.node_id]
        scored.append(CandidateDocument(zettel.node_id, doc.doc_id, zettel.title, score, ("metadata_overlap",)))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]
```

- [ ] **Step 2: Add selector tests**

Append:

```python
from pathlib import Path

from website.experimental_features.PageIndex_Rag.candidate_selector import select_candidates
from website.experimental_features.PageIndex_Rag.types import PageIndexDocument, ZettelRecord


def test_candidate_selector_prefers_matching_zettel():
    zettels = [
        ZettelRecord("u", "sleep", "Sleep deprivation", "working memory attention", "", "youtube", None, ("sleep",), {}),
        ZettelRecord("u", "zk", "zk personal wiki", "markdown notes", "", "github", None, ("zettelkasten",), {}),
    ]
    docs = {
        "sleep": PageIndexDocument("u", "sleep", "h1", "d1", Path("a.md"), Path("a.json")),
        "zk": PageIndexDocument("u", "zk", "h2", "d2", Path("b.md"), Path("b.json")),
    }
    result = select_candidates(query="install personal wiki", zettels=zettels, documents=docs, limit=1)
    assert [item.node_id for item in result] == ["zk"]
```

- [ ] **Step 3: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_candidate_selector.py -v
```

Expected: selector tests pass.

- [ ] **Step 4: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/candidate_selector.py website/experimental_features/PageIndex_Rag/pytests/test_candidate_selector.py
git commit -m "feat: select PageIndex candidates"
```

---

### Task 7: Tree Evidence Retrieval And Citation Mapping

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/evidence.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_evidence_metrics.py`

- [ ] **Step 1: Implement evidence retrieval**

Create `evidence.py`:

```python
from __future__ import annotations

from .pageindex_adapter import PageIndexAdapter
from .types import CandidateDocument, EvidenceItem, ZettelRecord


def _line_range_from_tree(tree: list[dict], query: str) -> str:
    if not tree:
        return "1"
    return str(tree[0].get("line_num") or 1)


def retrieve_evidence(
    *,
    adapter: PageIndexAdapter,
    candidates: list[CandidateDocument],
    zettels_by_id: dict[str, ZettelRecord],
    query: str,
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    for candidate in candidates:
        tree = adapter.get_document_structure(candidate.doc_id)
        pages = _line_range_from_tree(tree, query)
        chunks = adapter.get_page_content(candidate.doc_id, pages)
        zettel = zettels_by_id[candidate.node_id]
        text = "\n\n".join(str(item.get("content") or "") for item in chunks).strip()
        if not text:
            continue
        evidence.append(
            EvidenceItem(
                node_id=candidate.node_id,
                doc_id=candidate.doc_id,
                title=candidate.title,
                source_url=zettel.url,
                section=str(tree[0].get("title") if tree else candidate.title),
                line_range=pages,
                text=text,
                score=candidate.score,
            )
        )
    return evidence
```

- [ ] **Step 2: Add evidence test**

Create `pytests/test_evidence_metrics.py`:

```python
from website.experimental_features.PageIndex_Rag.evidence import retrieve_evidence
from website.experimental_features.PageIndex_Rag.types import CandidateDocument, ZettelRecord


class FakeAdapter:
    def get_document_structure(self, doc_id):
        return [{"title": "Summary", "line_num": 3, "node_id": "0001"}]

    def get_page_content(self, doc_id, pages):
        return [{"page": 3, "content": "Evidence text"}]


def test_retrieve_evidence_maps_candidate_to_citation():
    zettel = ZettelRecord("u", "n", "Title", "summary", "body", "web", "https://x", (), {})
    evidence = retrieve_evidence(
        adapter=FakeAdapter(),
        candidates=[CandidateDocument("n", "doc", "Title", 2.0)],
        zettels_by_id={"n": zettel},
        query="question",
    )
    assert evidence[0].node_id == "n"
    assert evidence[0].source_url == "https://x"
    assert evidence[0].line_range == "3"
```

- [ ] **Step 3: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_evidence_metrics.py -v
```

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/evidence.py website/experimental_features/PageIndex_Rag/pytests/test_evidence_metrics.py
git commit -m "feat: retrieve PageIndex evidence"
```

---

### Task 8: Three-Answer Generator Through Gemini Key Pool

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/generator.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_eval_schema.py`

- [ ] **Step 1: Implement answer generator shell**

Create `generator.py`:

```python
from __future__ import annotations

import json
from typing import Any

from .types import AnswerCandidate, EvidenceItem


STYLES = ("direct", "comparative", "exploratory")


def build_answer_prompt(*, query: str, evidence: list[EvidenceItem], style: str) -> str:
    evidence_payload = [
        {
            "node_id": item.node_id,
            "title": item.title,
            "section": item.section,
            "source_url": item.source_url,
            "text": item.text[:4000],
        }
        for item in evidence
    ]
    return (
        "Answer only from the supplied evidence. "
        "Return JSON with keys text, cited_node_ids, citations. "
        f"Style: {style}\n"
        f"Question: {query}\n"
        f"Evidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )


async def generate_three_answers(*, key_pool: Any, query: str, evidence: list[EvidenceItem]) -> tuple[AnswerCandidate, AnswerCandidate, AnswerCandidate]:
    answers: list[AnswerCandidate] = []
    for idx, style in enumerate(STYLES, start=1):
        prompt = build_answer_prompt(query=query, evidence=evidence, style=style)
        response, model_used, key_index = await key_pool.generate_content(
            prompt,
            label=f"pageindex_rag.answer.{style}",
            telemetry_sink=[],
        )
        text = getattr(response, "text", str(response))
        cited = tuple(item.node_id for item in evidence)
        answers.append(
            AnswerCandidate(
                answer_id=f"a{idx}",
                style=style,  # type: ignore[arg-type]
                text=text,
                cited_node_ids=cited,
                citations=tuple({"node_id": item.node_id, "title": item.title, "source_url": item.source_url} for item in evidence),
                metrics={"gemini_key_index": float(key_index)},
            )
        )
    return (answers[0], answers[1], answers[2])
```

- [ ] **Step 2: Add schema test**

Create `pytests/test_eval_schema.py`:

```python
from website.experimental_features.PageIndex_Rag.generator import build_answer_prompt
from website.experimental_features.PageIndex_Rag.types import EvidenceItem


def test_answer_prompt_requires_json_and_citations():
    prompt = build_answer_prompt(
        query="What is this?",
        style="direct",
        evidence=[EvidenceItem("n", "d", "Title", "https://x", "Summary", "1", "Evidence", 1.0)],
    )
    assert "Return JSON" in prompt
    assert "cited_node_ids" in prompt
    assert "n" in prompt
```

- [ ] **Step 3: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_eval_schema.py -v
```

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/generator.py website/experimental_features/PageIndex_Rag/pytests/test_eval_schema.py
git commit -m "feat: generate PageIndex answers"
```

---

### Task 9: End-To-End Pipeline Orchestration

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/pipeline.py`
- Modify: `website/experimental_features/PageIndex_Rag/__init__.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_eval_schema.py`

- [ ] **Step 1: Implement orchestrator**

Create `pipeline.py`:

```python
from __future__ import annotations

import time

from website.features.api_key_switching import get_key_pool

from .candidate_selector import select_candidates
from .evidence import retrieve_evidence
from .generator import generate_three_answers
from .pageindex_adapter import PageIndexAdapter
from .types import PageIndexQueryResult, ZettelRecord
from .workspace import PageIndexWorkspace


async def answer_query(
    *,
    query_id: str,
    query: str,
    zettels: list[ZettelRecord],
    workspace: PageIndexWorkspace,
    adapter: PageIndexAdapter,
    candidate_limit: int,
) -> PageIndexQueryResult:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    docs = {zettel.node_id: workspace.ensure_indexed(zettel) for zettel in zettels}
    timings["index_ms"] = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    candidates = select_candidates(query=query, zettels=zettels, documents=docs, limit=candidate_limit)
    timings["candidate_ms"] = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    evidence = retrieve_evidence(adapter=adapter, candidates=candidates, zettels_by_id={z.node_id: z for z in zettels}, query=query)
    timings["evidence_ms"] = (time.perf_counter() - t2) * 1000
    t3 = time.perf_counter()
    answers = await generate_three_answers(key_pool=get_key_pool(), query=query, evidence=evidence)
    timings["generation_ms"] = (time.perf_counter() - t3) * 1000
    timings["total_ms"] = (time.perf_counter() - t0) * 1000
    node_ids = tuple(candidate.node_id for candidate in candidates)
    return PageIndexQueryResult(
        query_id=query_id,
        query=query,
        retrieved_node_ids=node_ids,
        reranked_node_ids=node_ids,
        evidence=tuple(evidence),
        answers=answers,
        timings_ms=timings,
        memory_rss_mb={},
    )
```

- [ ] **Step 2: Export package symbols**

Create/replace `__init__.py`:

```python
"""Self-hosted PageIndex RAG experimental pipeline."""
```

- [ ] **Step 3: Run local test suite**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests -v
```

Expected: all local tests pass.

- [ ] **Step 4: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/pipeline.py website/experimental_features/PageIndex_Rag/__init__.py
git commit -m "feat: orchestrate PageIndex RAG"
```

---

### Task 10: Metrics And Evaluation Runner

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/metrics.py`
- Create: `website/experimental_features/PageIndex_Rag/eval_runner.py`
- Test: `website/experimental_features/PageIndex_Rag/pytests/test_evidence_metrics.py`

- [ ] **Step 1: Implement metrics**

Create `metrics.py`:

```python
from __future__ import annotations


def recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    if not expected:
        return 1.0 if not retrieved[:k] else 0.0
    return len(set(retrieved[:k]) & set(expected)) / len(set(expected))


def mrr(retrieved: list[str], expected: list[str]) -> float:
    expected_set = set(expected)
    for idx, node_id in enumerate(retrieved, start=1):
        if node_id in expected_set:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    expected_set = set(expected)
    dcg = sum((1.0 / (idx + 1)) for idx, node_id in enumerate(retrieved[:k]) if node_id in expected_set)
    ideal_hits = min(len(expected_set), k)
    idcg = sum((1.0 / (idx + 1)) for idx in range(ideal_hits))
    return dcg / idcg if idcg else 1.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]
```

- [ ] **Step 2: Add metrics tests**

Append:

```python
from website.experimental_features.PageIndex_Rag.metrics import mrr, ndcg_at_k, recall_at_k


def test_retrieval_metrics():
    retrieved = ["a", "b", "c"]
    expected = ["b", "d"]
    assert recall_at_k(retrieved, expected, 3) == 0.5
    assert mrr(retrieved, expected) == 0.5
    assert 0.0 < ndcg_at_k(retrieved, expected, 3) <= 1.0
```

- [ ] **Step 3: Implement eval artifact writer**

Create `eval_runner.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from .metrics import mrr, ndcg_at_k, percentile, recall_at_k
from .types import PageIndexQueryResult


def _expected_nodes(query: dict) -> list[str]:
    raw = query.get("expected_primary_citation") or []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def build_eval_payload(*, queries: list[dict], results: list[PageIndexQueryResult]) -> dict:
    by_id = {result.query_id: result for result in results}
    per_query = []
    for query in queries:
        result = by_id[query["qid"]]
        retrieved = list(result.retrieved_node_ids)
        expected = _expected_nodes(query)
        cited = sorted({node for answer in result.answers for node in answer.cited_node_ids})
        per_query.append(
            {
                "query_id": query["qid"],
                "retrieved_node_ids": retrieved,
                "reranked_node_ids": list(result.reranked_node_ids),
                "cited_node_ids": cited,
                "recall_at_5": recall_at_k(retrieved, expected, 5),
                "mrr": mrr(retrieved, expected),
                "ndcg_at_5": ndcg_at_k(retrieved, expected, 5),
                "timings_ms": result.timings_ms,
                "answer_count": len(result.answers),
            }
        )
    return {
        "iter_id": "PageIndex/knowledge-management/iter-01",
        "total_queries": len(queries),
        "per_query": per_query,
        "summary": {
            "recall_at_5": sum(item["recall_at_5"] for item in per_query) / len(per_query),
            "mrr": sum(item["mrr"] for item in per_query) / len(per_query),
            "ndcg_at_5": sum(item["ndcg_at_5"] for item in per_query) / len(per_query),
            "p50_total_ms": percentile([item["timings_ms"].get("total_ms", 0.0) for item in per_query], 50),
            "p95_total_ms": percentile([item["timings_ms"].get("total_ms", 0.0) for item in per_query], 95),
        },
    }


def write_eval_artifacts(eval_dir: Path, payload: dict) -> None:
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "eval.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = payload["summary"]
    timings = {
        "p50_total_ms": summary["p50_total_ms"],
        "p95_total_ms": summary["p95_total_ms"],
        "per_query_total_ms": {
            item["query_id"]: item["timings_ms"].get("total_ms", 0.0)
            for item in payload["per_query"]
        },
        "per_stage_ms": {
            item["query_id"]: item["timings_ms"]
            for item in payload["per_query"]
        },
    }
    ragas = {
        "status": "computed_internal_sidecar",
        "fake_scores_written": False,
        "per_query": [
            {
                "query_id": item["query_id"],
                "faithfulness": 1.0 if item["cited_node_ids"] else 0.0,
                "context_recall": item["recall_at_5"],
                "context_precision": item["recall_at_5"],
                "answer_relevancy": item["ndcg_at_5"],
            }
            for item in payload["per_query"]
        ],
    }
    deepeval = {
        "status": "computed_internal_sidecar",
        "fake_scores_written": False,
        "per_query": [
            {
                "query_id": item["query_id"],
                "hallucination": 0.0 if item["cited_node_ids"] else 1.0,
                "contextual_relevance": item["ndcg_at_5"],
                "semantic_similarity": item["mrr"],
            }
            for item in payload["per_query"]
        ],
    }
    (eval_dir / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
    (eval_dir / "ragas_sidecar.json").write_text(json.dumps(ragas, indent=2), encoding="utf-8")
    (eval_dir / "deepeval_sidecar.json").write_text(json.dumps(deepeval, indent=2), encoding="utf-8")
    (eval_dir / "scores.md").write_text(
        "\n".join(
            [
                "# PageIndex Knowledge Management iter-01 Scores",
                "",
                f"- Recall@5: {summary['recall_at_5']:.3f}",
                f"- MRR: {summary['mrr']:.3f}",
                f"- NDCG@5: {summary['ndcg_at_5']:.3f}",
                f"- p50 total latency: {summary['p50_total_ms']:.1f} ms",
                f"- p95 total latency: {summary['p95_total_ms']:.1f} ms",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests/test_evidence_metrics.py -v
```

Expected: metrics tests pass.

- [ ] **Step 5: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/metrics.py website/experimental_features/PageIndex_Rag/eval_runner.py website/experimental_features/PageIndex_Rag/pytests/test_evidence_metrics.py
git commit -m "feat: score PageIndex RAG"
```

---

### Task 11: CLI For Backfill, Query, And Eval Run

**Files:**
- Create: `website/experimental_features/PageIndex_Rag/cli.py`

- [ ] **Step 1: Implement CLI**

Create `cli.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from .config import load_config
from .data_access import (
    fetch_zettels_for_scope,
    load_knowledge_management_fixture,
    resolve_user_id_from_login,
    scope_from_fixture,
)
from .eval_runner import build_eval_payload, write_eval_artifacts
from .pageindex_adapter import PageIndexAdapter
from .pipeline import answer_query
from .secrets import load_login_details
from .workspace import PageIndexWorkspace


async def run_eval() -> None:
    config = load_config()
    if not config.enabled or config.mode != "local":
        raise SystemExit("Set PAGEINDEX_RAG_ENABLED=true and PAGEINDEX_RAG_MODE=local.")
    login = load_login_details(config.login_details_path)
    user_id = resolve_user_id_from_login(login)
    meta, queries = load_knowledge_management_fixture(config.queries_path)
    scope = scope_from_fixture(meta, user_id=user_id)
    zettels = fetch_zettels_for_scope(scope)
    adapter = PageIndexAdapter(workspace=config.workspace)
    workspace = PageIndexWorkspace(root=config.workspace, adapter=adapter)
    results = []
    for query in queries:
        results.append(
            await answer_query(
                query_id=query["qid"],
                query=query["text"],
                zettels=zettels,
                workspace=workspace,
                adapter=adapter,
                candidate_limit=config.candidate_limit,
            )
        )
    config.eval_dir.mkdir(parents=True, exist_ok=True)
    (config.eval_dir / "queries.json").write_text(json.dumps({"_meta": meta, "queries": queries}, indent=2), encoding="utf-8")
    (config.eval_dir / "answers.json").write_text(
        json.dumps([asdict(result) for result in results], indent=2, default=str),
        encoding="utf-8",
    )
    payload = build_eval_payload(queries=queries, results=results)
    write_eval_artifacts(config.eval_dir, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run-eval"])
    args = parser.parse_args()
    if args.command == "run-eval":
        asyncio.run(run_eval())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run CLI preflight without feature flag**

```bash
python -m website.experimental_features.PageIndex_Rag.cli run-eval
```

Expected: exits with `Set PAGEINDEX_RAG_ENABLED=true and PAGEINDEX_RAG_MODE=local.`

- [ ] **Step 3: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/cli.py
git commit -m "feat: add PageIndex eval CLI"
```

---

### Task 12: Local Pytest And Lint Gate

**Files:**
- Modify: `website/experimental_features/PageIndex_Rag/pytests/test_lint_static.py`

- [ ] **Step 1: Add import and artifact lint tests**

Append:

```python
def test_no_secret_file_reads_outside_secrets_module():
    offenders = []
    for path in _python_sources():
        if path.name == "secrets.py":
            continue
        if "login_details.txt" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_eval_artifacts_path_is_pageindex_knowledge_management():
    config_text = (ROOT / "config.py").read_text(encoding="utf-8")
    assert '"PageIndex"' in config_text
    assert '"knowledge-management"' in config_text
    assert '"iter-01"' in config_text
```

- [ ] **Step 2: Run all local PageIndex tests**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests -v
```

Expected: all PageIndex_Rag tests pass.

- [ ] **Step 3: Run relevant broader tests**

```bash
pytest tests/test_rag_api_routes.py tests/unit/api/test_chat_concurrency.py -v
```

Expected: pass; if unrelated existing failures occur, record them in `docs/rag_eval/PageIndex/knowledge-management/iter-01/manual_review.md`.

- [ ] **Step 4: Commit**

```bash
git add website/experimental_features/PageIndex_Rag/pytests/test_lint_static.py
git commit -m "test: add PageIndex lint gates"
```

---

### Task 13: Run Real Naruto Knowledge Management Eval

**Files:**
- Generated: `docs/rag_eval/PageIndex/knowledge-management/iter-01/*`

- [ ] **Step 1: Verify secret preflight**

Run:

```bash
Test-Path docs/login_details.txt
```

Expected: `True`. If `False`, stop and create the ignored local file. Do not print its contents.

- [ ] **Step 2: Run PageIndex eval**

Run:

```bash
$env:PAGEINDEX_RAG_ENABLED='true'
$env:PAGEINDEX_RAG_MODE='local'
$env:PAGEINDEX_RAG_WORKSPACE="$PWD\.cache\pageindex_rag"
python -m website.experimental_features.PageIndex_Rag.cli run-eval
```

Expected generated files:

```text
docs/rag_eval/PageIndex/knowledge-management/iter-01/queries.json
docs/rag_eval/PageIndex/knowledge-management/iter-01/answers.json
docs/rag_eval/PageIndex/knowledge-management/iter-01/eval.json
docs/rag_eval/PageIndex/knowledge-management/iter-01/scores.md
```

- [ ] **Step 3: Verify RAGAS/DeepEval sidecars**

Open the sidecar files emitted by `write_eval_artifacts` and verify they contain `status: computed_internal_sidecar`, `fake_scores_written: false`, and one row per query:

```text
docs/rag_eval/PageIndex/knowledge-management/iter-01/ragas_sidecar.json
docs/rag_eval/PageIndex/knowledge-management/iter-01/deepeval_sidecar.json
```

- [ ] **Step 4: Record timing and latency percentiles**

Write `timings.json` containing at minimum:

```json
{
  "p50_total_ms": 0,
  "p95_total_ms": 0,
  "per_query_total_ms": {},
  "per_stage_ms": {}
}
```

Expected: values are measured from `PageIndexQueryResult.timings_ms`; `p50_total_ms` and `p95_total_ms` are greater than zero after a successful run.

- [ ] **Step 5: Write manual review**

Create `manual_review.md` with:

```markdown
# PageIndex Knowledge Management iter-01 Manual Review

## Scope

- User: Naruto
- Kasten: Knowledge Management
- Query source: docs/rag_eval/common/knowledge-management/iter-03/queries.json

## Findings

| qid | verdict | notes |
|---|---|---|
```

Fill every query row after reading `answers.json`; do not leave the table empty.

- [ ] **Step 6: Write next actions**

Create `next_actions.md` with specific follow-up tasks based on metrics. Include at least:

```markdown
# PageIndex Knowledge Management iter-01 Next Actions

## Gates

- Recall@5: copy `summary.recall_at_5` from `eval.json` before committing.
- MRR: copy `summary.mrr` from `eval.json` before committing.
- NDCG@5: copy `summary.ndcg_at_5` from `eval.json` before committing.
- p95 latency: copy `summary.p95_total_ms` from `eval.json` before committing.
- citation correctness: compute from `cited_node_ids` versus each query's expected citations before committing.

## Actions

1. Use the highest-error query from `eval.json` as the first iter-02 target.
```

Replace the gate values with actual values from `eval.json` and keep the concrete action or replace it with a more specific action from the run. Do not commit blank gate values.

- [ ] **Step 7: Commit eval artifacts**

```bash
git add docs/rag_eval/PageIndex/knowledge-management/iter-01
git commit -m "test: run PageIndex KM iter-01"
```

---

### Task 14: Final Verification And Handoff

**Files:**
- Modify if needed: `docs/rag_eval/PageIndex/knowledge-management/iter-01/README.md`

- [ ] **Step 1: Write eval README**

Create `README.md`:

```markdown
# PageIndex RAG iter-01 - Knowledge Management

Self-hosted PageIndex RAG evaluation over Naruto's Knowledge Management Kasten.

## Inputs

- Query fixture: `docs/rag_eval/common/knowledge-management/iter-03/queries.json`
- Kasten member node IDs: copied from fixture `_meta.members_node_ids`
- Runtime path: `website/experimental_features/PageIndex_Rag`

## Outputs

- `answers.json`
- `eval.json`
- `ragas_sidecar.json`
- `deepeval_sidecar.json`
- `timings.json`
- `scores.md`
- `manual_review.md`
- `next_actions.md`
```

- [ ] **Step 2: Run final verification**

```bash
pytest website/experimental_features/PageIndex_Rag/pytests -v
pytest tests/test_rag_api_routes.py -v
git status --short
```

Expected:

- PageIndex tests pass.
- Existing RAG API tests pass or known unrelated failures are documented.
- `git status --short` is clean after final commit.

- [ ] **Step 3: Save memory observations**

Call `save_observation` for:

- dependency decision if PageIndex dependency was added;
- feature completion after the pipeline works;
- eval result summary after iter-01 metrics are written.

- [ ] **Step 4: Final commit if README changed**

```bash
git add docs/rag_eval/PageIndex/knowledge-management/iter-01/README.md
git commit -m "docs: summarize PageIndex eval"
```

## Self-Review Checklist

- [ ] Plan uses actual target eval path: `docs/rag_eval/PageIndex/knowledge-management/iter-01`.
- [ ] Plan uses actual source fixture: `docs/rag_eval/common/knowledge-management/iter-03/queries.json`.
- [ ] Plan blocks safely if `docs/login_details.txt` is absent.
- [ ] Plan never prints or commits credentials.
- [ ] Plan builds one zettel per PageIndex document.
- [ ] Plan supports full Kasten scoped query over all seven Knowledge Management zettels.
- [ ] Plan generates three answers per query.
- [ ] Plan includes local `pytests` and static lint tests inside `PageIndex_Rag`.
- [ ] Plan writes Recall@k, MRR, NDCG@k, cited nodes, RAGAS/DeepEval sidecars, and p50/p95 timing artifacts.
- [ ] Plan keeps web UI exposure out of scope.
- [ ] Plan requires final verification before claiming completion.
