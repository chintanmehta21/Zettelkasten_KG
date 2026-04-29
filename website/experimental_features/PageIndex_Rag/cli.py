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
from .secrets import LoginDetailsMissingError, load_login_details
from .workspace import PageIndexWorkspace


async def run_eval() -> None:
    config = load_config()
    if not config.enabled or config.mode != "local":
        raise SystemExit("Set PAGEINDEX_RAG_ENABLED=true and PAGEINDEX_RAG_MODE=local.")
    try:
        login = load_login_details(config.login_details_path)
    except LoginDetailsMissingError as exc:
        raise SystemExit(str(exc)) from exc
    user_id = resolve_user_id_from_login(login)
    meta, queries = load_knowledge_management_fixture(config.queries_path)
    scope = scope_from_fixture(meta, user_id=user_id)
    zettels = fetch_zettels_for_scope(scope)
    adapter = PageIndexAdapter(workspace=config.workspace)
    workspace = PageIndexWorkspace(root=config.workspace, adapter=adapter)
    results = []
    index_manifest = []
    for query in queries:
        result = await answer_query(
            query_id=query["qid"],
            query=query["text"],
            zettels=zettels,
            workspace=workspace,
            adapter=adapter,
            candidate_limit=config.candidate_limit,
        )
        results.append(result)
    for zettel in zettels:
        doc = workspace.ensure_indexed(zettel)
        index_manifest.append(asdict(doc))
    config.eval_dir.mkdir(parents=True, exist_ok=True)
    (config.eval_dir / "queries.json").write_text(json.dumps({"_meta": meta, "queries": queries}, indent=2), encoding="utf-8")
    (config.eval_dir / "kasten.json").write_text(json.dumps({"scope": asdict(scope), "zettels": [asdict(z) for z in zettels]}, indent=2), encoding="utf-8")
    (config.eval_dir / "index_manifest.json").write_text(json.dumps(index_manifest, indent=2, default=str), encoding="utf-8")
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
