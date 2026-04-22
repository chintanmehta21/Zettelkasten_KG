# Phase 0 smoke test - 2026-04-22

## Exit criteria

- [ ] pytest green (all units pass)
- [x] links.txt section-headered parse
- [x] all rubric YAMLs validate
- [ ] POST /api/v2/summarize returns valid YouTube SummaryResult
- [x] docs/summary_eval/_cache/ directories auto-create on first cache put
- [ ] evaluator PROMPT_VERSION = evaluator.v1 stamped in eval.json metadata

## Results

### Check 1: all unit tests green

Command:

```bash
python -m pytest tests/unit/ website/features/summarization_engine/tests/unit/ -q
```

Outcome:

```text
ERROR tests/unit/summarization_engine/core/test_cache.py
import file mismatch:
imported module 'test_cache' has this __file__ attribute:
  tests/unit/rag/retrieval/test_cache.py
which is not the same as the test file we want to collect:
  tests/unit/summarization_engine/core/test_cache.py
```

Status: failed during collection because duplicate `test_cache.py` module names collided via bytecode/module import state.

### Check 2: links.txt section-headered parse

Command:

```bash
python ops/scripts/eval_loop.py --source youtube --list-urls
```

Outcome:

```json
[
  "https://www.youtube.com/watch?v=hhjhU5MXZOo",
  "https://www.youtube.com/watch?v=HBTYVVUBAGs",
  "https://www.youtube.com/watch?v=Brm71uCWr-I",
  "https://www.youtube.com/watch?v=Ctwc8t5CsQs",
  "https://www.youtube.com/watch?v=CtrhU7GOjOg"
]
```

Status: passed.

### Check 3: rubric YAMLs validate

Command:

```bash
python - <<'PY'
from pathlib import Path
from website.features.summarization_engine.evaluator.rubric_loader import load_rubric
for path in Path("docs/summary_eval/_config").glob("rubric_*.yaml"):
    load_rubric(path)
print("OK")
PY
```

Outcome:

```text
OK
```

Status: passed.

### Check 4: start server and hit /api/v2/summarize

Command:

```bash
python run.py
POST http://127.0.0.1:10000/api/v2/summarize
```

Outcome:

```text
website.main: Starting Zettelkasten website on 0.0.0.0:10000
POST /api/v2/summarize -> {"detail":"Gemini API key not configured"}
```

Status: endpoint reachable, summarization blocked by missing Gemini API key in the local environment.

### Cache directories

Observed directories:

```text
docs/summary_eval/_cache
docs/summary_eval/_cache/ingests
```

Status: present.

### Evaluator prompt version stamp

Status: not yet verified in an `eval.json` artifact during this smoke pass.
