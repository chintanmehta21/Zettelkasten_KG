from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


class PageIndexUnavailableError(RuntimeError):
    pass


class PageIndexAdapter:
    def __init__(self, *, workspace: Path, model: str | None = None) -> None:
        try:
            from pageindex import PageIndexClient
        except Exception as exc:  # pragma: no cover - env-specific
            PageIndexClient = _LocalMarkdownPageIndexClient
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


class _LocalMarkdownPageIndexClient:
    """Small local adapter for PageIndex-shaped Markdown documents.

    The verified PageIndex repo commit is currently not pip-installable at the
    repository root, so this keeps the experimental CLI runnable while the
    public adapter boundary remains compatible with PageIndexClient.
    """

    def __init__(self, *, workspace: str, model: str | None = None, retrieve_model: str | None = None) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.documents: dict[str, dict[str, Any]] = {}
        for path in self.workspace.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            self.documents[payload["id"]] = payload

    def index(self, file_path: str, mode: str = "md") -> str:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        structure = []
        for index, line in enumerate(lines, start=1):
            match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if not match:
                continue
            structure.append(
                {
                    "title": match.group(2).strip(),
                    "line_num": index,
                    "node_id": f"{index:04d}",
                    "level": len(match.group(1)),
                }
            )
        if not structure:
            structure = [{"title": path.stem, "line_num": 1, "node_id": "0001", "level": 1}]
        doc_id = str(uuid4())
        payload = {
            "id": doc_id,
            "type": "md",
            "path": str(path.resolve()),
            "doc_name": path.stem,
            "line_count": len(lines),
            "structure": structure,
            "lines": lines,
        }
        self.documents[doc_id] = payload
        (self.workspace / f"{doc_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return doc_id

    def get_document(self, doc_id: str) -> str:
        doc = self.documents[doc_id]
        return json.dumps({k: v for k, v in doc.items() if k != "lines"})

    def get_document_structure(self, doc_id: str) -> str:
        return json.dumps(self.documents[doc_id]["structure"])

    def get_page_content(self, doc_id: str, pages: str) -> str:
        doc = self.documents[doc_id]
        lines = doc["lines"]
        first = int(str(pages).split(",", 1)[0].split("-", 1)[0])
        start = max(1, first)
        next_heading = len(lines) + 1
        for node in doc["structure"]:
            line_num = int(node.get("line_num") or 1)
            if line_num > start:
                next_heading = line_num
                break
        content = "\n".join(lines[start - 1 : next_heading - 1]).strip()
        return json.dumps([{"page": start, "content": content}])
