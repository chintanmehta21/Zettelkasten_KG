"""Unit tests for the GitHub archetype classifier and README signal extractor."""
from __future__ import annotations

from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
    classify_archetype,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    extract_signals,
)


_FASTAPI_README = """Repository
fastapi/fastapi
FastAPI framework, high performance, easy to learn
Language: Python
Topics: python, api, web-framework, async, openapi

README
# FastAPI

FastAPI is a modern, fast (high-performance), web framework for building APIs
with Python based on standard Python type hints.

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
```

Install with `pip install "fastapi[standard]"`. Then run `fastapi dev main.py`.
Interactive docs at /docs and /redoc (Swagger UI and ReDoc) are generated
automatically from the OpenAPI schema. Built on Starlette (ASGI) and Pydantic.

Docs
See https://fastapi.tiangolo.com for full documentation.
"""


_TYPER_README = """Repository
tiangolo/typer
Typer, build great CLIs. Easy to code. Based on Python type hints.
Language: Python
Topics: python, cli, command-line, typer, click

README
# Typer

Typer is a library for building **CLI applications** that users will love using
and developers will love creating. Based on Python type hints.

```python
import typer

app = typer.Typer()

@app.command()
def hello(name: str):
    typer.echo(f"Hello {name}")

if __name__ == "__main__":
    app()
```

Install with `pip install typer`. Run `your_script.py --help` to see the
auto-generated CLI help. Typer uses Click under the hood.
"""


_REQUESTS_README = """Repository
psf/requests
Python HTTP for Humans.
Language: Python
Topics: python, http, requests

README
# Requests

Requests is a simple, yet elegant, HTTP library.

```python
>>> import requests
>>> r = requests.get('https://httpbin.org/user-agent')
>>> r.status_code
200
```

Install with `pip install requests`.
"""


def test_classify_framework_api_on_fastapi_like_readme():
    verdict = classify_archetype(
        raw_text=_FASTAPI_README,
        metadata={"language": "Python", "topics": ["python", "api", "web-framework", "async"]},
    )
    assert verdict.archetype == RepoArchetype.FRAMEWORK_API
    assert verdict.confidence > 0.3


def test_classify_cli_tool_on_typer_like_readme():
    verdict = classify_archetype(
        raw_text=_TYPER_README,
        metadata={"language": "Python", "topics": ["python", "cli", "command-line"]},
    )
    assert verdict.archetype == RepoArchetype.CLI_TOOL
    assert verdict.confidence > 0.3


def test_classify_library_thin_on_requests_like_readme():
    verdict = classify_archetype(
        raw_text=_REQUESTS_README,
        metadata={"language": "Python", "topics": ["python", "http", "requests"]},
    )
    # Requests has a thin README with imports and no framework/CLI signals
    assert verdict.archetype in {RepoArchetype.LIBRARY_THIN, RepoArchetype.UNKNOWN}


def test_classify_unknown_on_empty_input():
    verdict = classify_archetype(raw_text="", metadata={})
    assert verdict.archetype == RepoArchetype.UNKNOWN
    assert verdict.confidence == 0.0


def test_extract_signals_captures_endpoints_decorators_and_install():
    signals = extract_signals(
        raw_text=_FASTAPI_README,
        metadata={"language": "Python"},
    )
    assert any(cmd.startswith("pip install") for cmd in signals.install_cmds)
    assert any("/docs" == e or "/redoc" == e for e in signals.endpoints)
    assert any(d.startswith("@app.") for d in signals.decorators)
    assert "Python" in signals.stack or "python" in signals.stack
    assert signals.first_code_block


def test_extract_signals_captures_cli_flags():
    signals = extract_signals(
        raw_text=_TYPER_README,
        metadata={"language": "Python"},
    )
    assert any(flag == "--help" for flag in signals.cli_flags)
    assert any("typer" in cmd for cmd in signals.install_cmds)


def test_extract_signals_never_raises_on_empty_input():
    signals = extract_signals(raw_text="", metadata={})
    assert signals.install_cmds == ()
    assert signals.endpoints == ()
    assert signals.first_code_block == ""


def test_any_public_surface_ranks_decorators_before_inline_code():
    signals = extract_signals(
        raw_text=_FASTAPI_README,
        metadata={"language": "Python"},
    )
    surfaces = signals.any_public_surface()
    # Endpoints and decorators should appear before generic inline tokens
    assert surfaces
    assert any(s.startswith(("@", "/")) for s in surfaces[:3])
