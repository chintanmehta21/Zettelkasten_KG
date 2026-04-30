# PageIndex Knowledge Management iter-01 Start Handoff

## Status

- Implementation path: `website/experimental_features/PageIndex_Rag`
- Eval path: `docs/rag_eval/PageIndex/knowledge-management/iter-01`
- Feature flag: `PAGEINDEX_RAG_ENABLED=true`
- Mode: `PAGEINDEX_RAG_MODE=local`
- Required local credential file: `docs/login_details.txt`
- Required source fixture: `docs/rag_eval/common/knowledge-management/iter-03/queries.json`

## Current Gates

- PageIndex local pytests: `20 passed`
- Broader RAG/API smoke tests: `6 passed`
- Required iter-01 artifacts: `13/13 present`
- Query count: `13`
- Answers per query: `3`
- Recall@5: `0.882`
- MRR: `0.885`
- NDCG@5: `0.928`
- p95 total latency: `17103.0 ms`

## Start Command

```powershell
$env:PAGEINDEX_RAG_ENABLED='true'
$env:PAGEINDEX_RAG_MODE='local'
$env:PAGEINDEX_RAG_WORKSPACE="$PWD\.cache\pageindex_rag"
python -m website.experimental_features.PageIndex_Rag.cli run-eval
```

## Verification Commands

```powershell
python -m pytest website/experimental_features/PageIndex_Rag/pytests -q
python -m pytest tests/test_rag_api_routes.py tests/unit/api/test_chat_concurrency.py -q
```

## Known Constraint

The verified upstream PageIndex commit `a51d97f63cedbf1d36b1121ff47386ea4e088ff5` is not pip-installable because it has no `setup.py` or `pyproject.toml` at the repository root. The runtime adapter keeps the PageIndexClient boundary and uses the local Markdown fallback until a packageable upstream or vendored boundary is approved.

## Next Iteration Target

Use `manual_review.md` and `next_actions.md` to choose the highest-error query for iter-02. Keep the web UI out of scope until PageIndex evaluation is replacement-grade.
