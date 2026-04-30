from __future__ import annotations

import json
from pathlib import Path

from .markdown_renderer import render_kasten_markdown, render_zettel_markdown
from .pageindex_adapter import PageIndexAdapter
from .types import PageIndexDocument, ZettelRecord


class PageIndexWorkspace:
    def __init__(self, *, root: Path, adapter: PageIndexAdapter) -> None:
        self.root = root
        self.adapter = adapter
        self.kasten_document: PageIndexDocument | None = None
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

    def ensure_kasten_indexed(self, scope_id: str, zettels: list[ZettelRecord]) -> PageIndexDocument:
        markdown, content_hash = render_kasten_markdown(scope_id, zettels)
        user_id = zettels[0].user_id if zettels else "unknown"
        node_dir = self.root / user_id / "__kasten__" / content_hash
        node_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = node_dir / "kasten.md"
        tree_path = node_dir / "tree.json"
        manifest_path = node_dir / "manifest.json"
        if manifest_path.exists() and tree_path.exists() and markdown_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.kasten_document = PageIndexDocument(
                user_id=user_id,
                node_id="__kasten__",
                content_hash=content_hash,
                doc_id=payload["doc_id"],
                markdown_path=markdown_path,
                tree_path=tree_path,
            )
            return self.kasten_document
        markdown_path.write_text(markdown, encoding="utf-8")
        doc_id = self.adapter.index_markdown(markdown_path)
        tree = self.adapter.get_document_structure(doc_id)
        tree_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "user_id": user_id,
                    "node_id": "__kasten__",
                    "scope_id": scope_id,
                    "content_hash": content_hash,
                    "doc_id": doc_id,
                    "markdown_path": str(markdown_path),
                    "tree_path": str(tree_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.kasten_document = PageIndexDocument(user_id, "__kasten__", content_hash, doc_id, markdown_path, tree_path)
        return self.kasten_document
