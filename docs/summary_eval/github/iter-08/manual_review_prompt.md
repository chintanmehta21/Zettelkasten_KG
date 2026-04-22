You are an INDEPENDENT rubric reviewer, blind to any prior evaluator's scoring. Do NOT read eval.json.

Stamp `eval_json_hash_at_review: "NOT_CONSULTED"` at the top of your manual_review.md.

RUBRIC:
version: rubric_github.v1
source_type: github
composite_max_points: 100
components:
- id: brief_summary
  max_points: 25
  criteria:
  - id: brief.user_facing_purpose
    description: Brief states what the repo does in user-facing terms.
    max_points: 6
    maps_to_metric:
    - g_eval.relevance
    - finesure.completeness
  - id: brief.architecture_high_level
    description: Brief identifies main components/architecture at a high level.
    max_points: 5
    maps_to_metric:
    - finesure.completeness
  - id: brief.languages_and_frameworks
    description: Primary languages and major frameworks are mentioned.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
    - qafact
  - id: brief.usage_pattern
    description: Describes documented usage/installation/workflow.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
  - id: brief.public_surface
    description: If exposed, REST routes, CLI entry, UI pages, or Pages URL are summarized.
    max_points: 4
    maps_to_metric:
    - finesure.completeness
  - id: brief.no_maturity_fabrication
    description: Maturity claims (experimental/production-ready) only if explicitly
      signaled.
    max_points: 2
    maps_to_metric:
    - finesure.faithfulness
    - summac
- id: detailed_summary
  max_points: 45
  criteria:
  - id: detailed.features_bullets
    description: Core features as bullets, each tied to explicit code or docs.
    max_points: 8
    maps_to_metric:
    - finesure.faithfulness
    - qafact
  - id: detailed.architecture_modules
    description: 'Architecture bullets: directories, key classes, interactions.'
    max_points: 8
    maps_to_metric:
    - finesure.completeness
  - id: detailed.interfaces_exact
    description: Public APIs / CLI commands / config options with exact names.
    max_points: 8
    maps_to_metric:
    - finesure.faithfulness
    - summac
  - id: detailed.operational
    description: Install steps, deps, env vars, build, deploy instructions captured.
    max_points: 6
    maps_to_metric:
    - finesure.completeness
  - id: detailed.limitations_docs
    description: Documented limitations, caveats, security notes preserved.
    max_points: 5
    maps_to_metric:
    - finesure.faithfulness
  - id: detailed.benchmarks_tests_examples
    description: If benchmarks/tests/examples exist, what they demonstrate is summarized.
    max_points: 5
    maps_to_metric:
    - finesure.completeness
  - id: detailed.bullets_focused
    description: Each bullet covers one coherent aspect.
    max_points: 5
    maps_to_metric:
    - g_eval.coherence
- id: tags
  max_points: 15
  criteria:
  - id: tags.count_7_to_10
    description: Exactly 7-10 tags.
    max_points: 2
    maps_to_metric:
    - finesure.conciseness
  - id: tags.domain_tag
    description: Main domain/application tag present.
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
  - id: tags.languages
    description: Primary language(s) tagged.
    max_points: 3
    maps_to_metric:
    - finesure.completeness
  - id: tags.technical_concepts
    description: Key technical concepts ('rest-api','cli-tool','ml-serving') present.
    max_points: 3
    maps_to_metric:
    - g_eval.relevance
  - id: tags.no_unsupported_claims
    description: No tags claim 'production-ready' without evidence.
    max_points: 4
    maps_to_metric:
    - finesure.faithfulness
    - summac
- id: label
  max_points: 15
  criteria:
  - id: label.owner_slash_repo
    description: Label is exactly 'owner/repo' matching the canonical GitHub path.
    max_points: 10
    maps_to_metric:
    - finesure.faithfulness
  - id: label.no_extra_descriptors
    description: No prepended/appended descriptors; qualifiers belong in summary or
      tags.
    max_points: 5
    maps_to_metric:
    - g_eval.conciseness
anti_patterns:
- id: production_ready_claim_no_evidence
  description: Summary claims 'production-ready' without README evidence.
  auto_cap: 60
- id: invented_public_interface
  description: Summary claims an API route / CLI command / export not present in repo.
  auto_cap: 60
- id: label_not_owner_repo
  description: Label doesn't match 'owner/repo' regex.
  auto_cap: 75
global_rules:
  editorialization_penalty:
    threshold_flags: 3


SUMMARY:
## URL 1: https://github.com/fastapi/fastapi

### SUMMARY
```yaml
mini_title: fastapi/fastapi
brief_summary: FastAPI is an ASGI framework built upon Starlette for web handling
  (WebSockets, CORS, sessions). At a high level, FastAPI is an ASGI framework built
  upon Starlette for web handling (WebSockets, CORS, sessions). The main stack includes
  Starlette, Pydantic, Uvicorn, ASGI. Documented public surfaces include OpenAPI 3,
  JSON Schema, Swagger UI, ReDoc. The documented workflow emphasizes Used in producti
tags:
- api-framework
- async
- pydantic
- starlette
- openapi
- python
- web-framework
- api
- asgi
- type-hints
detailed_summary:
- heading: Architecture
  bullets:
  - FastAPI is an ASGI framework built upon Starlette for web handling (WebSockets,
    CORS, sessions) and Pydantic for data handling.
  sub_sections:
    Core Mechanism:
    - Uses Python type hints in function signatures to define API endpoints.
    - Enables Pydantic to perform automatic data validation, serialization (Python
      to JSON), and deserialization (network data to Python).
    Serving:
    - Natively supports `async def` endpoints.
    - Typically served by an ASGI server like Uvicorn.
- heading: APIs & Features
  bullets: []
  sub_sections:
    API Definition:
    - Path/query parameters, headers, cookies, form fields, and file uploads are declared
      as type-hinted function arguments.
    - Complex JSON bodies are defined using Pydantic `BaseModel` classes.
    Automatic Documentation:
    - Generates OpenAPI 3 and JSON Schema from code.
    - Serves interactive Swagger UI (`/docs`) and ReDoc (`/redoc`) interfaces.
    Dependency Injection:
    - A system (`Depends`) is provided for managing resources, authentication, and
      logic reuse.
    Security:
    - Includes utilities for security schemes like OAuth2 with JWT and HTTP Basic
      authentication.
    GraphQL:
    - Supports GraphQL integration, with documentation recommending libraries like
      Strawberry.
    Installation:
    - The `fastapi[standard]` package includes `uvicorn`, `httpx` (for `TestClient`),
      `python-multipart` (for form parsing), and `email-validator`.
- heading: Maturity
  bullets:
  - Actively maintained with frequent releases and a mature CI process using 31 GitHub
    Actions workflows.
  - Security policy supports the latest version and requires private vulnerability
    disclosure.
  sub_sections:
    Adoption:
    - Used in production by companies including Microsoft, Uber, and Netflix.
    Performance:
    - A core design goal, with project claims of performance on par with NodeJS and
      Go.
    - TechEmpower benchmarks position FastAPI (on Uvicorn) as one of the fastest Python
      frameworks, a result attributed to its Starlette and Pydantic foundations.
    - Internal team tests claim it enables 200-300% faster development and results
      in 40% fewer bugs.
    Recent Updates:
    - A recent significant dependency update was Starlette to v1.0.0 (#15397).
- heading: Ecosystem
  bullets: []
  sub_sections:
    Typer:
    - A sibling project from the same creator that applies FastAPI's design principles
      (type hints, automatic help) to build command-line interfaces (CLIs).
    FastAPI Cloud:
    - A commercial service from the FastAPI team for deploying applications.
- heading: Notable Issues & Discussions
  bullets: []
  sub_sections:
    Typing Complexity:
    - 'Recurring issues involve the correct resolution of complex type annotations,
      particularly with `Annotated` and string forward references (`from __future__
      import annotations`), leading to bugs in dependency injection and schema generation
      (#15364, #15307, #15234).'
    Feature Evolution:
    - 'A long-standing request exists for class-based views (CBVs) (#15392, #2625).'
    - Authentication for static file serving was recently added (#15295) to address
      a limitation where static files bypassed the dependency injection system (#858).
    Concurrency & Performance:
    - Issues have been identified with the dependency injection system's concurrency,
      including potential deadlocks requiring fixes to resource limiters (#15388).
    - A memory usage regression was recently identified and fixed (#15336).
    Schema & Routing:
    - Bugs persist in OpenAPI schema generation, such as duplicate `operationId` for
      routes with multiple HTTP methods (#15398) and incorrect metadata propagation
      for Server-Sent Events (SSE) through `APIRouter` (#15401).
metadata:
  source_type: github
  url: https://github.com/fastapi/fastapi
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 2 extra doc(s) fetched
  total_tokens_used: 28153
  gemini_pro_tokens: 25221
  gemini_flash_tokens: 2932
  total_latency_ms: 86615
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: fastapi/fastapi
    architecture_overview: FastAPI is an ASGI framework built upon Starlette for web
      handling (WebSockets, CORS, sessions) and Pydantic for data handling. It leverages
      Python type hints in function signatures to define API endpoints, enabling Pydantic
      to perform automatic data validation, serialization (Python to JSON), and deserialization
      (network data to Python). The framework natively supports `async def` endpoints
      and is typically served by an ASGI server like Uvicorn.
    brief_summary: FastAPI is an ASGI framework built upon Starlette for web handling
      (WebSockets, CORS, sessions). At a high level, FastAPI is an ASGI framework
      built upon Starlette for web handling (WebSockets, CORS, sessions). The main
      stack includes Starlette, Pydantic, Uvicorn, ASGI. Documented public surfaces
      include OpenAPI 3, JSON Schema, Swagger UI, ReDoc. The documented workflow emphasizes
      Used in production by Microsoft, Uber, Netflix.
    tags:
    - api-framework
    - async
    - pydantic
    - starlette
    - openapi
    - python
    - web-framework
    - api
    - asgi
    - type-hints
    benchmarks_tests_examples:
    - TechEmpower benchmarks position FastAPI (on Uvicorn) as one of the fastest Python
      frameworks.
    - Internal team tests claim it enables 200-300% faster development and results
      in 40% fewer bugs.
    detailed_summary:
    - heading: Architecture
      bullets:
      - FastAPI is an ASGI framework built upon Starlette for web handling (WebSockets,
        CORS, sessions) and Pydantic for data handling.
      sub_sections:
        Core Mechanism:
        - Uses Python type hints in function signatures to define API endpoints.
        - Enables Pydantic to perform automatic data validation, serialization (Python
          to JSON), and deserialization (network data to Python).
        Serving:
        - Natively supports `async def` endpoints.
        - Typically served by an ASGI server like Uvicorn.
      module_or_feature: Architecture
      main_stack:
      - Starlette
      - Pydantic
      - Uvicorn
      - ASGI
      public_interfaces: []
      usability_signals: []
    - heading: APIs & Features
      bullets: []
      sub_sections:
        API Definition:
        - Path/query parameters, headers, cookies, form fields, and file uploads are
          declared as type-hinted function arguments.
        - Complex JSON bodies are defined using Pydantic `BaseModel` classes.
        Automatic Documentation:
        - Generates OpenAPI 3 and JSON Schema from code.
        - Serves interactive Swagger UI (`/docs`) and ReDoc (`/redoc`) interfaces.
        Dependency Injection:
        - A system (`Depends`) is provided for managing resources, authentication,
          and logic reuse.
        Security:
        - Includes utilities for security schemes like OAuth2 with JWT and HTTP Basic
          authentication.
        GraphQL:
        - Supports GraphQL integration, with documentation recommending libraries
          like Strawberry.
        Installation:
        - The `fastapi[standard]` package includes `uvicorn`, `httpx` (for `TestClient`),
          `python-multipart` (for form parsing), and `email-validator`.
      module_or_feature: APIs & Features
      main_stack: []
      public_interfaces:
      - OpenAPI 3
      - JSON Schema
      - Swagger UI
      - ReDoc
      - GraphQL
      usability_signals: []
    - heading: Maturity
      bullets:
      - Actively maintained with frequent releases and a mature CI process using 31
        GitHub Actions workflows.
      - Security policy supports the latest version and requires private vulnerability
        disclosure.
      sub_sections:
        Adoption:
        - Used in production by companies including Microsoft, Uber, and Netflix.
        Performance:
        - A core design goal, with project claims of performance on par with NodeJS
          and Go.
        - TechEmpower benchmarks position FastAPI (on Uvicorn) as one of the fastest
          Python frameworks, a result attributed to its Starlette and Pydantic foundations.
        - Internal team tests claim it enables 200-300% faster development and results
          in 40% fewer bugs.
        Recent Updates:
        - A recent significant dependency update was Starlette to v1.0.0 (#15397).
      module_or_feature: Maturity
      main_stack: []
      public_interfaces: []
      usability_signals:
      - Used in production by Microsoft, Uber, Netflix
      - Claims 200-300% faster development
      - Claims 40% fewer bugs
    - heading: Ecosystem
      bullets: []
      sub_sections:
        Typer:
        - A sibling project from the same creator that applies FastAPI's design principles
          (type hints, automatic help) to build command-line interfaces (CLIs).
        FastAPI Cloud:
        - A commercial service from the FastAPI team for deploying applications.
      module_or_feature: Ecosystem
      main_stack: []
      public_interfaces: []
      usability_signals: []
    - heading: Notable Issues & Discussions
      bullets: []
      sub_sections:
        Typing Complexity:
        - 'Recurring issues involve the correct resolution of complex type annotations,
          particularly with `Annotated` and string forward references (`from __future__
          import annotations`), leading to bugs in dependency injection and schema
          generation (#15364, #15307, #15234).'
        Feature Evolution:
        - 'A long-standing request exists for class-based views (CBVs) (#15392, #2625).'
        - Authentication for static file serving was recently added (#15295) to address
          a limitation where static files bypassed the dependency injection system
          (#858).
        Concurrency & Performance:
        - Issues have been identified with the dependency injection system's concurrency,
          including potential deadlocks requiring fixes to resource limiters (#15388).
        - A memory usage regression was recently identified and fixed (#15336).
        Schema & Routing:
        - Bugs persist in OpenAPI schema generation, such as duplicate `operationId`
          for routes with multiple HTTP methods (#15398) and incorrect metadata propagation
          for Server-Sent Events (SSE) through `APIRouter` (#15401).
      module_or_feature: Notable Issues & Discussions
      main_stack: []
      public_interfaces: []
      usability_signals: []
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Repository
fastapi/fastapi FastAPI framework, high performance, easy to learn, fast to code, ready for production Language: Python Topics: api, async, asyncio, fastapi, framework, json, json-schema, openapi, openapi3, pydantic, python, python-types, python3, redoc, rest, starlette, swagger, swagger-ui, uvicorn, web

README
<p align="center"> <a href="https://fastapi.tiangolo.com"><img src="https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png" alt="FastAPI"></a> </p> <p align="center"> <em>FastAPI framework, high performance, easy to learn, fast to code, ready for production</em> </p> <p align="center"> <a href="https://github.com/fastapi/fastapi/actions?query=workflow%3ATest+event%3Apush+branch%3Amaster"> <img src="https://github.com/fastapi/fastapi/actions/workflows/test.yml/badge.svg?event=push&branch=master" alt="Test"> </a> <a href="https://coverage-badge.samuelcolvin.workers.dev/redirect/fastapi/fastapi"> <img src="https://coverage-badge.samuelcolvin.workers.dev/fastapi/fastapi.svg" alt="Coverage"> </a> <a href="https://pypi.org/project/fastapi"> <img src="https://img.shields.io/pypi/v/fastapi?color=%2334D058&label=pypi%20package" alt="Package version"> </a> <a href="https://pypi.org/project/fastapi"> <img src="https://img.shields.io/pypi/pyversions/fastapi.svg?color=%2334D058" alt="Supported Python versions"> </a> </p> --- **Documentation**: [https://fastapi.tiangolo.com](https://fastapi.tiangolo.com) **Source Code**: [https://github.com/fastapi/fastapi](https://github.com/fastapi/fastapi) --- FastAPI is a modern, fast (high-performance), web framework for building APIs with Python based on standard Python type hints. The key features are: * **Fast**: Very high performance, on par with **NodeJS** and **Go** (thanks to Starlette and Pydantic). [One of the fastest Python frameworks available](#performance). * **Fast to code**: Increase the speed to develop features by about 200% to 300%. * * **Fewer bugs**: Reduce about 40% of human (developer) induced errors. * * **Intuitive**: Great editor support. <dfn title="also known as auto-complete, autocompletion, IntelliSense">Completion</dfn> everywhere. Less time debugging. * **Easy**: Designed to be easy to use and learn. Less time reading docs. * **Short**: Minimize code duplication. Multiple features from each parameter declaration. Fewer bugs. * **Robust**: Get production-ready code. With automatic interactive documentation. * **Standards-based**: Based on (and fully compatible with) the open standards for APIs: [OpenAPI](https://github.com/OAI/OpenAPI-Specification) (previously known as Swagger) and [JSON Schema](https://json-schema.org/). <small>* estimation based on tests conducted by an internal development team, building production applications.</small> ## Sponsors <!-- sponsors --> ### Keystone Sponsor <a href="https://fastapicloud.com" target="_blank" title="FastAPI Cloud. By the same team behind FastAPI. You code. We Cloud."><img src="https://fastapi.tiangolo.com/img/sponsors/fastapicloud.png"></a> ### Gold and Silver Sponsors <a href="https://blockbee.io?ref=fastapi" target="_blank" title="BlockBee Cryptocurrency Payment Gateway"><img src="https://fastapi.tiangolo.com/img/sponsors/blockbee.png"></a> <a href="https://github.com/scalar/scalar/?utm_source=fastapi&utm_medium=website&utm_campaign=main-badge" target="_blank" title="Scalar: Beautiful Open-Source API References from Swagger/OpenAPI files"><img src="https://fastapi.tiangolo.com/img/sponsors/scalar.svg"></a> <a href="https://www.propelauth.com/?utm_source=fastapi&utm_campaign=1223&utm_medium=mainbadge" target="_blank" title="Auth, user management and more for your B2B product"><img src="https://fastapi.tiangolo.com/img/sponsors/propelauth.png"></a> <a href="https://liblab.com?utm_source=fastapi" target="_blank" title="liblab - Generate SDKs from FastAPI"><img src="https://fastapi.tiangolo.com/img/sponsors/liblab.png"></a> <a href="https://docs.render.com/deploy-fastapi?utm_source=deploydoc&utm_medium=referral&utm_campaign=fastapi" target="_blank" title="Deploy & scale any full-stack web app on Render. Focus on building apps, not infra."><img src="https://fastapi.tiangolo.com/img/sponsors/render.svg"></a> <a href="https://www.coderabbit.ai/?utm_source=fastapi&utm_medium=badge&utm_campaign=fastapi" target="_blank" title="Cut Code Review Time & Bugs in Half with CodeRabbit"><img src="https://fastapi.tiangolo.com/img/sponsors/coderabbit.png"></a> <a href="https://subtotal.com/?utm_source=fastapi&utm_medium=sponsorship&utm_campaign=open-source" target="_blank" title="The Gold Standard in Retail Account Linking"><img src="https://fastapi.tiangolo.com/img/sponsors/subtotal.svg"></a> <a href="https://docs.railway.com/guides/fastapi?utm_medium=integration&utm_source=docs&utm_campaign=fastapi" target="_blank" title="Deploy enterprise applications at startup speed"><img src="https://fastapi.tiangolo.com/img/sponsors/railway.png"></a> <a href="https://serpapi.com/?utm_source=fastapi_website" target="_blank" title="SerpApi: Web Search API"><img src="https://fastapi.tiangolo.com/img/sponsors/serpapi.png"></a> <a href="https://www.greptile.com/?utm_source=fastapi&utm_medium=sponsorship&utm_campaign=fastapi_sponsor_page" target="_blank" title="Greptile: The AI Code Reviewer"><img src="https://fastapi.tiangolo.com/img/sponsors/greptile.png"></a> <a href="https://databento.com/?utm_source=fastapi&utm_medium=sponsor&utm_content=display" target="_blank" title="Pay as you go for market data"><img src="https://fastapi.tiangolo.com/img/sponsors/databento.svg"></a> <a href="https://www.svix.com/" target="_blank" title="Svix - Webhooks as a service"><img src="https://fastapi.tiangolo.com/img/sponsors/svix.svg"></a> <a href="https://www.stainlessapi.com/?utm_source=fastapi&utm_medium=referral" target="_blank" title="Stainless | Generate best-in-class SDKs"><img src="https://fastapi.tiangolo.com/img/sponsors/stainless.png"></a> <a href="https://www.permit.io/blog/implement-authorization-in-fastapi?utm_source=github&utm_medium=referral&utm_campaign=fastapi" target="_blank" title="Fine-Grained Authorization for FastAPI"><img src="https://fastapi.tiangolo.com/img/sponsors/permit.png"></a> <a href="https://www.interviewpal.com/?utm_source=fastapi&utm_medium=open-source&utm_campaign=dev-hiring" target="_blank" title="InterviewPal - AI Interview Coach for Engineers and Devs"><img src="https://fastapi.tiangolo.com/img/sponsors/interviewpal.png"></a> <a href="https://dribia.com/en/" target="_blank" title="Dribia - Data Science within your reach"><img src="https://fastapi.tiangolo.com/img/sponsors/dribia.png"></a> <!-- /sponsors --> [Other sponsors](https://fastapi.tiangolo.com/fastapi-people/#sponsors) ## Opinions "_[...] I'm using **FastAPI** a ton these days. [...] I'm actually planning to use it for all of my team's **ML services at Microsoft**. Some of them are getting integrated into the core **Windows** product and some **Office** products._" <div style="text-align: right; margin-right: 10%;">Kabir Khan - <strong>Microsoft</strong> <a href="https://github.com/fastapi/fastapi/pull/26"><small>(ref)</small></a></div> --- "_We adopted the **FastAPI** library to spawn a **REST** server that can be queried to obtain **predictions**. [for Ludwig]_" <div style="text-align: right; margin-right: 10%;">Piero Molino, Yaroslav Dudin, and Sai Sumanth Miryala - <strong>Uber</strong> <a href="https://eng.uber.com/ludwig-v0-2/"><small>(ref)</small></a></div> --- "_**Netflix** is pleased to announce the open-source release of our **crisis management** orchestration framework: **Dispatch**! [built with **FastAPI**]_" <div style="text-align: right; margin-right: 10%;">Kevin Glisson, Marc Vilanova, Forest Monsen - <strong>Netflix</strong> <a href="https://netflixtechblog.com/introducing-dispatch-da4b8a2a8072"><small>(ref)</small></a></div> --- "_I’m over the moon excited about **FastAPI**. It’s so fun!_" <div style="text-align: right; margin-right: 10%;">Brian Okken - <strong>[Python Bytes](https://pythonbytes.fm/episodes/show/123/time-to-right-the-py-wrongs?time_in_sec=855) podcast host</strong> <a href="https://x.com/brianokken/status/1112220079972728832"><small>(ref)</small></a></div> --- "_Honestly, what you've built looks super solid and polished. In many ways, it's what I wanted **Hug** to be - it's really inspiring to see someone build that._" <div style="text-align: right; margin-right: 10%;">Timothy Crosley - <strong>[Hug](https://github.com/hugapi/hug) creator</strong> <a href="https://news.ycombinator.com/item?id=19455465"><small>(ref)</small></a></div> --- "_If you're looking to learn one **modern framework** for building REST APIs, check out **FastAPI** [...] It's fast, easy to use and easy to learn [...]_" "_We've switched over to **FastAPI** for our **APIs** [...] I think you'll like it [...]_" <div style="text-align: right; margin-right: 10%;">Ines Montani - Matthew Honnibal - <strong>[Explosion AI](https://explosion.ai) founders - [spaCy](https://spacy.io) creators</strong> <a href="https://x.com/_inesmontani/status/1144173225322143744"><small>(ref)</small></a> - <a href="https://x.com/honnibal/status/1144031421859655680"><small>(ref)</small></a></div> --- "_If anyone is looking to build a production Python API, I would highly recommend **FastAPI**. It is **beautifully designed**, **simple to use** and **highly scalable**, it has become a **key component** in our API first development strategy and is driving many automations and services such as our Virtual TAC Engineer._" <div style="text-align: right; margin-right: 10%;">Deon Pillsbury - <strong>Cisco</strong> <a href="https://www.linkedin.com/posts/deonpillsbury_cisco-cx-python-activity-6963242628536487936-trAp/"><small>(ref)</small></a></div> --- ## FastAPI mini documentary There's a [FastAPI mini documentary](https://www.youtube.com/watch?v=mpR8ngthqiE) released at the end of 2025, you can watch it online: <a href="https://www.youtube.com/watch?v=mpR8ngthqiE"><img src="https://fastapi.tiangolo.com/img/fastapi-documentary.jpg" alt="FastAPI Mini Documentary"></a> ## **Typer**, the FastAPI of CLIs <a href="https://typer.tiangolo.com"><img src="https://typer.tiangolo.com/img/logo-margin/logo-margin-vector.svg" style="width: 20%;"></a> If you are building a <abbr title="Command Line Interface">CLI</abbr> app to be used in the terminal instead of a web API, check out [**Typer**](https://typer.tiangolo.com/). **Typer** is FastAPI's little sibling. And it's intended to be the **FastAPI of CLIs**. ⌨️ 🚀 ## Requirements FastAPI stands on the shoulders of giants: * [Starlette](https://www.starlette.dev/) for the web parts. * [Pydantic](https://docs.pydantic.dev/) for the data parts. ## Installation Create and activate a [virtual environment](https://fastapi.tiangolo.com/virtual-environments/) and then install FastAPI: <div class="termy"> ```console $ pip install "fastapi[standard]" ---> 100% ``` </div> **Note**: Make sure you put `"fastapi[standard]"` in quotes to ensure it works in all terminals. ## Example ### Create it Create a file `main.py` with: ```Python from fastapi import FastAPI app = FastAPI() @app.get("/") def read_root(): return {"Hello": "World"} @app.get("/items/{item_id}") def read_item(item_id: int, q: str | None = None): return {"item_id": item_id, "q": q} ``` <details markdown="1"> <summary>Or use <code>async def</code>...</summary> If your code uses `async` / `await`, use `async def`: ```Python hl_lines="7 12" from fastapi import FastAPI app = FastAPI() @app.get("/") async def read_root(): return {"Hello": "World"} @app.get("/items/{item_id}") async def read_item(item_id: int, q: str | None = None): return {"item_id": item_id, "q": q} ``` **Note**: If you don't know, check the _"In a hurry?"_ section about [`async` and `await` in the docs](https://fastapi.tiangolo.com/async/#in-a-hurry). </details> ### Run it Run the server with: <div class="termy"> ```console $ fastapi dev ╭────────── FastAPI CLI - Development mode ───────────╮ │ │ │ Serving at: http://127.0.0.1:8000 │ │ │ │ API docs: http://127.0.0.1:8000/docs │ │ │ │ Running in development mode, for production use: │ │ │ │ fastapi run │ │ │ ╰─────────────────────────────────────────────────────╯ INFO: Will watch for changes in these directories: ['/home/user/code/awesomeapp'] INFO: Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit) INFO: Started reloader process [2248755] using WatchFiles INFO: Started server process [2248757] INFO: Waiting for application startup. INFO: Application startup complete. ``` </div> <details markdown="1"> <summary>About the command <code>fastapi dev</code>...</summary> The command `fastapi dev` reads your `main.py` file automatically, detects the **FastAPI** app in it, and starts a server using [Uvicorn](https://www.uvicorn.dev). By default, `fastapi dev` will start with auto-reload enabled for local development. You can read more about it in the [FastAPI CLI docs](https://fastapi.tiangolo.com/fastapi-cli/). </details> ### Check it Open your browser at [http://127.0.0.1:8000/items/5?q=somequery](http://127.0.0.1:8000/items/5?q=somequery). You will see the JSON response as: ```JSON {"item_id": 5, "q": "somequery"} ``` You already created an API that: * Receives HTTP requests in the _paths_ `/` and `/items/{item_id}`. * Both _paths_ take `GET` <em>operations</em> (also known as HTTP _methods_). * The _path_ `/items/{item_id}` has a _path parameter_ `item_id` that should be an `int`. * The _path_ `/items/{item_id}` has an optional `str` _query parameter_ `q`. ### Interactive API docs Now go to [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). You will see the automatic interactive API documentation (provided by [Swagger UI](https://github.com/swagger-api/swagger-ui)): ![Swagger UI](https://fastapi.tiangolo.com/img/index/index-01-swagger-ui-simple.png) ### Alternative API docs And now, go to [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc). You will see the alternative automatic documentation (provided by [ReDoc](https://github.com/Rebilly/ReDoc)): ![ReDoc](https://fastapi.tiangolo.com/img/index/index-02-redoc-simple.png) ## Example upgrade Now modify the file `main.py` to receive a body from a `PUT` request. Declare the body using standard Python types, thanks to Pydantic. ```Python hl_lines="2 7-10 23-25" from fastapi import FastAPI from pydantic import BaseModel app = FastAPI() class Item(BaseModel): name: str price: float is_offer: bool | None = None @app.get("/") def read_root(): return {"Hello": "World"} @app.get("/items/{item_id}") def read_item(item_id: int, q: str | None = None): return {"item_id": item_id, "q": q} @app.put("/items/{item_id}") def update_item(item_id: int, item: Item): return {"item_name": item.name, "item_id": item_id} ``` The `fastapi dev` server should reload automatically. ### Interactive API docs upgrade Now go to [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). * The interactive API documentation will be automatically updated, including the new body: ![Swagger UI](https://fastapi.tiangolo.com/img/index/index-03-swagger-02.png) * Click on the button "Try it out", it allows you to fill the parameters and directly interact with the API: ![Swagger UI interaction](https://fastapi.tiangolo.com/img/index/index-04-swagger-03.png) * Then click on the "Execute" button, the user interface will communicate with your API, send the parameters, get the results and show them on the screen: ![Swagger UI interaction](https://fastapi.tiangolo.com/img/index/index-05-swagger-04.png) ### Alternative API docs upgrade And now, go to [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc). * The alternative documentation will also reflect the new query parameter and body: ![ReDoc](https://fastapi.tiangolo.com/img/index/index-06-redoc-02.png) ### Recap In summary, you declare **once** the types of parameters, body, etc. as function parameters. You do that with standard modern Python types. You don't have to learn a new syntax, the methods or classes of a specific library, etc. Just standard **Python**. For example, for an `int`: ```Python item_id: int ``` or for a more complex `Item` model: ```Python item: Item ``` ...and with that single declaration you get: * Editor support, including: * Completion. * Type checks. * Validation of data: * Automatic and clear errors when the data is invalid. * Validation even for deeply nested JSON objects. * <dfn title="also known as: serialization, parsing, marshalling">Conversion</dfn> of input data: coming from the network to Python data and types. Reading from: * JSON. * Path parameters. * Query parameters. * Cookies. * Headers. * Forms. * Files. * <dfn title="also known as: serialization, parsing, marshalling">Conversion</dfn> of output data: converting from Python data and types to network data (as JSON): * Convert Python types (`str`, `int`, `float`, `bool`, `list`, etc). * `datetime` objects. * `UUID` objects. * Database models. * ...and many more. * Automatic interactive API documentation, including 2 alternative user interfaces: * Swagger UI. * ReDoc. --- Coming back to the previous code example, **FastAPI** will: * Validate that there is an `item_id` in the path for `GET` and `PUT` requests. * Validate that the `item_id` is of type `int` for `GET` and `PUT` requests. * If it is not, the client will see a useful, clear error. * Check if there is an optional query parameter named `q` (as in `http://127.0.0.1:8000/items/foo?q=somequery`) for `GET` requests. * As the `q` parameter is declared with `= None`, it is optional. * Without the `None` it would be required (as is the body in the case with `PUT`). * For `PUT` requests to `/items/{item_id}`, read the body as JSON: * Check that it has a required attribute `name` that should be a `str`. * Check that it has a required attribute `price` that has to be a `float`. * Check that it has an optional attribute `is_offer`, that should be a `bool`, if present. * All this would also work for deeply nested JSON objects. * Convert from and to JSON automatically. * Document everything with OpenAPI, that can be used by: * Interactive documentation systems. * Automatic client code generation systems, for many languages. * Provide 2 interactive documentation web interfaces directly. --- We just scratched the surface, but you already get the idea of how it all works. Try changing the line with: ```Python return {"item_name": item.name, "item_id": item_id} ``` ...from: ```Python ... "item_name": item.name ... ``` ...to: ```Python ... "item_price": item.price ... ``` ...and see how your editor will auto-complete the attributes and know their types: ![editor support](https://fastapi.tiangolo.com/img/vscode-completion.png) For a more complete example including more features, see the <a href="https://fastapi.tiangolo.com/tutorial/">Tutorial - User Guide</a>. **Spoiler alert**: the tutorial - user guide includes: * Declaration of **parameters** from other different places as: **headers**, **cookies**, **form fields** and **files**. * How to set **validation constraints** as `maximum_length` or `regex`. * A very powerful and easy to use **<dfn title="also known as components, resources, providers, services, injectables">Dependency Injection</dfn>** system. * Security and authentication, including support for **OAuth2** with **JWT tokens** and **HTTP Basic** auth. * More advanced (but equally easy) techniques for declaring **deeply nested JSON models** (thanks to Pydantic). * **GraphQL** integration with [Strawberry](https://strawberry.rocks) and other libraries. * Many extra features (thanks to Starlette) as: * **WebSockets** * extremely easy tests based on HTTPX and `pytest` * **CORS** * **Cookie Sessions** * ...and more. ### Deploy your app (optional) You can optionally deploy your FastAPI app to [FastAPI Cloud](https://fastapicloud.com), go and join the waiting list if you haven't. 🚀 If you already have a **FastAPI Cloud** account (we invited you from the wait
```


## URL 2: https://github.com/encode/httpx

### SUMMARY
```yaml
mini_title: encode/httpx
brief_summary: Built on a layered architecture, using `httpcore` as its low-level
  transport library. At a high level, httpx employs a layered architecture, utilizing
  `httpcore` as its foundational low-level transport library. It. The main stack includes
  Python 3.9+, httpcore, h11, certifi. Documented public surfaces include httpx.WSGITransport,
  httpx.ASGITransport. The documented workflow emphasizes installation
tags:
- python
- api-framework
- async
- cli-tool
- http-client
- asyncio
- trio
- http2
- api-compatibility
- type-annotations
detailed_summary:
- heading: Architecture and Transport
  bullets:
  - Built on a layered architecture, using `httpcore` as its low-level transport library.
  - Core dependencies include `h11` for HTTP/1.1, `certifi` for SSL certificates,
    `idna` for internationalized domains, and `sniffio` for detecting the async environment
    (asyncio/trio).
  - Features an integrated transport system that allows mounting transports to handle
    specific URL prefixes.
  - Enables direct requests to WSGI/ASGI applications via `httpx.WSGITransport` and
    `httpx.ASGITransport`.
  sub_sections:
    CLI:
    - Requires `rich`, `click`
    HTTP/2:
    - Requires `h2`
    Proxies:
    - Requires `socksio`
    Decompression:
    - Requires `brotli`/`brotlicffi` (for brotli)
    - Requires `zstandard` (for zstd, added in v0.27.1)
- heading: API Maturity and Breaking Changes
  bullets:
  - The API is actively maintained and has undergone recent simplification.
  - The default serialization for JSON request bodies was changed to a more compact
    representation (v0.28.0), which may impact tests relying on specific whitespace
    formatting.
  sub_sections:
    Configuration Simplification (v0.26.0-v0.28.0):
    - The `proxies` argument was deprecated and removed, replaced by a singular `proxy`
      argument or `mounts=` for complex routing.
    - The `app=` shortcut for WSGI/ASGI apps was removed in favor of the explicit
      `transport=` argument.
    - String-based `verify` and the `cert` argument for SSL configuration were deprecated
      in v0.28.0.
- heading: Notable Issues and Behavior
  bullets:
  - Recent development has focused on aligning URL and query parameter handling with
    `requests`.
  - 'Fixes (#3760, #3761, #3766) address bugs in merging `base_url` and `params` arguments.'
  - 'A fix in #3764 changed behavior to percent-encode the pipe character (`|`) in
    URL paths, conforming to RFC 3986 but diverging from previous `requests`-like
    behavior.'
  - An open issue (#3783) highlights that `httpx` follows the common browser pattern
    of changing the HTTP method to `GET` on 301/302 redirects. A feature has been
    requested to provide an option to preserve the original method, which is often
    desired for API clients.
  - Fixes (#3769) have improved shutdown reliability, ensuring all mounted transports
    are closed even if the primary transport raises an exception.
  - Performance is also a focus, with optimizations like refactoring exception mapping
    to avoid `contextlib.contextmanager` overhead in hot paths (#3778).
  sub_sections: {}
metadata:
  source_type: github
  url: https://github.com/encode/httpx
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 2 extra doc(s) fetched
  total_tokens_used: 25391
  gemini_pro_tokens: 19171
  gemini_flash_tokens: 6220
  total_latency_ms: 80802
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: encode/httpx
    architecture_overview: httpx employs a layered architecture, utilizing `httpcore`
      as its foundational low-level transport library. It integrates core dependencies
      like `h11` for HTTP/1.1, `certifi` for SSL, `idna` for internationalized domains,
      and `sniffio` for async environment detection (asyncio/trio). A key architectural
      feature is its flexible transport system, enabling the mounting of custom transports
      to handle specific URL prefixes, including direct communication with WSGI/ASGI
      applications.
    brief_summary: Built on a layered architecture, using `httpcore` as its low-level
      transport library. At a high level, httpx employs a layered architecture, utilizing
      `httpcore` as its foundational low-level transport library. It. The main stack
      includes Python 3.9+, httpcore, h11, certifi. Documented public surfaces include
      httpx.WSGITransport, httpx.ASGITransport. The documented workflow emphasizes
      installation, configuration, and developer usage guidance.
    tags:
    - python
    - api-framework
    - async
    - cli-tool
    - http-client
    - asyncio
    - trio
    - http2
    - api-compatibility
    - type-annotations
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: Architecture and Transport
      bullets:
      - Built on a layered architecture, using `httpcore` as its low-level transport
        library.
      - Core dependencies include `h11` for HTTP/1.1, `certifi` for SSL certificates,
        `idna` for internationalized domains, and `sniffio` for detecting the async
        environment (asyncio/trio).
      - Features an integrated transport system that allows mounting transports to
        handle specific URL prefixes.
      - Enables direct requests to WSGI/ASGI applications via `httpx.WSGITransport`
        and `httpx.ASGITransport`.
      sub_sections:
        CLI:
        - Requires `rich`, `click`
        HTTP/2:
        - Requires `h2`
        Proxies:
        - Requires `socksio`
        Decompression:
        - Requires `brotli`/`brotlicffi` (for brotli)
        - Requires `zstandard` (for zstd, added in v0.27.1)
      module_or_feature: Architecture and Transport
      main_stack:
      - Python 3.9+
      - httpcore
      - h11
      - certifi
      - idna
      - sniffio
      public_interfaces:
      - httpx.WSGITransport
      - httpx.ASGITransport
      usability_signals: []
    - heading: API Maturity and Breaking Changes
      bullets:
      - The API is actively maintained and has undergone recent simplification.
      - The default serialization for JSON request bodies was changed to a more compact
        representation (v0.28.0), which may impact tests relying on specific whitespace
        formatting.
      sub_sections:
        Configuration Simplification (v0.26.0-v0.28.0):
        - The `proxies` argument was deprecated and removed, replaced by a singular
          `proxy` argument or `mounts=` for complex routing.
        - The `app=` shortcut for WSGI/ASGI apps was removed in favor of the explicit
          `transport=` argument.
        - String-based `verify` and the `cert` argument for SSL configuration were
          deprecated in v0.28.0.
      module_or_feature: API Maturity and Breaking Changes
      main_stack: []
      public_interfaces: []
      usability_signals: []
    - heading: Notable Issues and Behavior
      bullets:
      - Recent development has focused on aligning URL and query parameter handling
        with `requests`.
      - 'Fixes (#3760, #3761, #3766) address bugs in merging `base_url` and `params`
        arguments.'
      - 'A fix in #3764 changed behavior to percent-encode the pipe character (`|`)
        in URL paths, conforming to RFC 3986 but diverging from previous `requests`-like
        behavior.'
      - An open issue (#3783) highlights that `httpx` follows the common browser pattern
        of changing the HTTP method to `GET` on 301/302 redirects. A feature has been
        requested to provide an option to preserve the original method, which is often
        desired for API clients.
      - Fixes (#3769) have improved shutdown reliability, ensuring all mounted transports
        are closed even if the primary transport raises an exception.
      - Performance is also a focus, with optimizations like refactoring exception
        mapping to avoid `contextlib.contextmanager` overhead in hot paths (#3778).
      sub_sections: {}
      module_or_feature: Notable Issues and Behavior
      main_stack: []
      public_interfaces: []
      usability_signals: []
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Repository
encode/httpx A next generation HTTP client for Python. 🦋 Language: Python Topics: asyncio, http, python, trio

README
<p align="center"> <a href="https://www.python-httpx.org/"><img width="350" height="208" src="https://raw.githubusercontent.com/encode/httpx/master/docs/img/butterfly.png" alt='HTTPX'></a> </p> <p align="center"><strong>HTTPX</strong> <em>- A next-generation HTTP client for Python.</em></p> <p align="center"> <a href="https://github.com/encode/httpx/actions"> <img src="https://github.com/encode/httpx/workflows/Test%20Suite/badge.svg" alt="Test Suite"> </a> <a href="https://pypi.org/project/httpx/"> <img src="https://badge.fury.io/py/httpx.svg" alt="Package version"> </a> </p> HTTPX is a fully featured HTTP client library for Python 3. It includes **an integrated command line client**, has support for both **HTTP/1.1 and HTTP/2**, and provides both **sync and async APIs**. --- Install HTTPX using pip: ```shell $ pip install httpx ``` Now, let's get started: ```pycon >>> import httpx >>> r = httpx.get('https://www.example.org/') >>> r <Response [200 OK]> >>> r.status_code 200 >>> r.headers['content-type'] 'text/html; charset=UTF-8' >>> r.text '<!doctype html>\n<html>\n<head>\n<title>Example Domain</title>...' ``` Or, using the command-line client. ```shell $ pip install 'httpx[cli]' # The command line client is an optional dependency. ``` Which now allows us to use HTTPX directly from the command-line... <p align="center"> <img width="700" src="docs/img/httpx-help.png" alt='httpx --help'> </p> Sending a request... <p align="center"> <img width="700" src="docs/img/httpx-request.png" alt='httpx http://httpbin.org/json'> </p> ## Features HTTPX builds on the well-established usability of `requests`, and gives you: * A broadly [requests-compatible API](https://www.python-httpx.org/compatibility/). * An integrated command-line client. * HTTP/1.1 [and HTTP/2 support](https://www.python-httpx.org/http2/). * Standard synchronous interface, but with [async support if you need it](https://www.python-httpx.org/async/). * Ability to make requests directly to [WSGI applications](https://www.python-httpx.org/advanced/transports/#wsgi-transport) or [ASGI applications](https://www.python-httpx.org/advanced/transports/#asgi-transport). * Strict timeouts everywhere. * Fully type annotated. * 100% test coverage. Plus all the standard features of `requests`... * International Domains and URLs * Keep-Alive & Connection Pooling * Sessions with Cookie Persistence * Browser-style SSL Verification * Basic/Digest Authentication * Elegant Key/Value Cookies * Automatic Decompression * Automatic Content Decoding * Unicode Response Bodies * Multipart File Uploads * HTTP(S) Proxy Support * Connection Timeouts * Streaming Downloads * .netrc Support * Chunked Requests ## Installation Install with pip: ```shell $ pip install httpx ``` Or, to include the optional HTTP/2 support, use: ```shell $ pip install httpx[http2] ``` HTTPX requires Python 3.9+. ## Documentation Project documentation is available at [https://www.python-httpx.org/](https://www.python-httpx.org/). For a run-through of all the basics, head over to the [QuickStart](https://www.python-httpx.org/quickstart/). For more advanced topics, see the [Advanced Usage](https://www.python-httpx.org/advanced/) section, the [async support](https://www.python-httpx.org/async/) section, or the [HTTP/2](https://www.python-httpx.org/http2/) section. The [Developer Interface](https://www.python-httpx.org/api/) provides a comprehensive API reference. To find out about tools that integrate with HTTPX, see [Third Party Packages](https://www.python-httpx.org/third_party_packages/). ## Contribute If you want to contribute with HTTPX check out the [Contributing Guide](https://www.python-httpx.org/contributing/) to learn how to start. ## Dependencies The HTTPX project relies on these excellent libraries: * `httpcore` - The underlying transport implementation for `httpx`. * `h11` - HTTP/1.1 support. * `certifi` - SSL certificates. * `idna` - Internationalized domain name support. * `sniffio` - Async library autodetection. As well as these optional installs: * `h2` - HTTP/2 support. *(Optional, with `httpx[http2]`)* * `socksio` - SOCKS proxy support. *(Optional, with `httpx[socks]`)* * `rich` - Rich terminal support. *(Optional, with `httpx[cli]`)* * `click` - Command line client support. *(Optional, with `httpx[cli]`)* * `brotli` or `brotlicffi` - Decoding for "brotli" compressed responses. *(Optional, with `httpx[brotli]`)* * `zstandard` - Decoding for "zstd" compressed responses. *(Optional, with `httpx[zstd]`)* A huge amount of credit is due to `requests` for the API layout that much of this work follows, as well as to `urllib3` for plenty of design inspiration around the lower-level networking details. --- <p align="center"><i>HTTPX is <a href="https://github.com/encode/httpx/blob/master/LICENSE.md">BSD licensed</a> code.<br/>Designed & crafted with care.</i><br/>&mdash; 🦋 &mdash;</p>

Docs
### CHANGELOG.md # Changelog All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). ## [UNRELEASED] ### Removed * Drop support for Python 3.8 ### Added * Expose `FunctionAuth` from the public API. (#3699) ## 0.28.1 (6th December, 2024) * Fix SSL case where `verify=False` together with client side certificates. ## 0.28.0 (28th November, 2024) Be aware that the default *JSON request bodies now use a more compact representation*. This is generally considered a prefered style, tho may require updates to test suites. The 0.28 release includes a limited set of deprecations... **Deprecations**: We are working towards a simplified SSL configuration API. *For users of the standard `verify=True` or `verify=False` cases, or `verify=<ssl_context>` case this should require no changes. The following cases have been deprecated...* * The `verify` argument as a string argument is now deprecated and will raise warnings. * The `cert` argument is now deprecated and will raise warnings. Our revised [SSL documentation](docs/advanced/ssl.md) covers how to implement the same behaviour with a more constrained API. **The following changes are also included**: * The deprecated `proxies` argument has now been removed. * The deprecated `app` argument has now been removed. * JSON request bodies use a compact representation. (#3363) * Review URL percent escape sets, based on WHATWG spec. (#3371, #3373) * Ensure `certifi` and `httpcore` are only imported if required. (#3377) * Treat `socks5h` as a valid proxy scheme. (#3178) * Cleanup `Request()` method signature in line with `client.request()` and `httpx.request()`. (#3378) * Bugfix: When passing `params={}`, always strictly update rather than merge with an existing querystring. (#3364) ## 0.27.2 (27th August, 2024) ### Fixed * Reintroduced supposedly-private `URLTypes` shortcut. (#2673) ## 0.27.1 (27th August, 2024) ### Added * Support for `zstd` content decoding using the python `zstandard` package is added. Installable using `httpx[zstd]`. (#3139) ### Fixed * Improved error messaging for `InvalidURL` exceptions. (#3250) * Fix `app` type signature in `ASGITransport`. (#3109) ## 0.27.0 (21st February, 2024) ### Deprecated * The `app=...` shortcut has been deprecated. Use the explicit style of `transport=httpx.WSGITransport()` or `transport=httpx.ASGITransport()` instead. ### Fixed * Respect the `http1` argument while configuring proxy transports. (#3023) * Fix RFC 2069 mode digest authentication. (#3045) ## 0.26.0 (20th December, 2023) ### Added * The `proxy` argument was added. You should use the `proxy` argument instead of the deprecated `proxies`, or use `mounts=` for more complex configurations. (#2879) ### Deprecated * The `proxies` argument is now deprecated. It will still continue to work, but it will be removed in the future. (#2879) ### Fixed * Fix cases of double escaping of URL path components. Allow / as a safe character in the query portion. (#2990) * Handle `NO_PROXY` envvar cases when a fully qualified URL is supplied as the value. (#2741) * Allow URLs where username or password contains unescaped '@'. (#2986) * Ensure ASGI `raw_path` does not include URL query component. (#2999) * Ensure `Response.iter_text()` cannot yield empty strings. (#2998) ## 0.25.2 (24th November, 2023) ### Added * Add missing type hints to few `__init__()` methods. (#2938) ## 0.25.1 (3rd November, 2023) ### Added * Add support for Python 3.12. (#2854) * Add support for httpcore 1.0 (#2885) ### Fixed * Raise `ValueError` on `Response.encoding` being set after `Response.text` has been accessed. (#2852) ## 0.25.0 (11th September, 2023) ### Removed * Drop support for Python 3.7. (#2813) ### Added * Support HTTPS proxies. (#2845) * Change the type of `Extensions` from `Mapping[Str, Any]` to `MutableMapping[Str, Any]`. (#2803) * Add `socket_options` argument to `httpx.HTTPTransport` and `http… ### docs/index.md <p align="center" style="margin: 0 0 10px"> <img width="350" height="208" src="https://raw.githubusercontent.com/encode/httpx/master/docs/img/butterfly.png" alt='HTTPX'> </p> <h1 align="center" style="font-size: 3rem; margin: -15px 0"> HTTPX </h1> --- <div align="center"> <p> <a href="https://github.com/encode/httpx/actions"> <img src="https://github.com/encode/httpx/workflows/Test%20Suite/badge.svg" alt="Test Suite"> </a> <a href="https://pypi.org/project/httpx/"> <img src="https://badge.fury.io/py/httpx.svg" alt="Package version"> </a> </p> <em>A next-generation HTTP client for Python.</em> </div> HTTPX is a fully featured HTTP client for Python 3, which provides sync and async APIs, and support for both HTTP/1.1 and HTTP/2. --- Install HTTPX using pip: ```shell $ pip install httpx ``` Now, let's get started: ```pycon >>> import httpx >>> r = httpx.get('https://www.example.org/') >>> r <Response [200 OK]> >>> r.status_code 200 >>> r.headers['content-type'] 'text/html; charset=UTF-8' >>> r.text '<!doctype html>\n<html>\n<head>\n<title>Example Domain</title>...' ``` Or, using the command-line client. ```shell # The command line client is an optional dependency. $ pip install 'httpx[cli]' ``` Which now allows us to use HTTPX directly from the command-line... ![httpx --help](img/httpx-help.png) Sending a request... ![httpx http://httpbin.org/json](img/httpx-request.png) ## Features HTTPX builds on the well-established usability of `requests`, and gives you: * A broadly [requests-compatible API](compatibility.md). * Standard synchronous interface, but with [async support if you need it](async.md). * HTTP/1.1 [and HTTP/2 support](http2.md). * Ability to make requests directly to [WSGI applications](advanced/transports.md#wsgi-transport) or [ASGI applications](advanced/transports.md#asgi-transport). * Strict timeouts everywhere. * Fully type annotated. * 100% test coverage. Plus all the standard features of `requests`... * International Domains and URLs * Keep-Alive & Connection Pooling * Sessions with Cookie Persistence * Browser-style SSL Verification * Basic/Digest Authentication * Elegant Key/Value Cookies * Automatic Decompression * Automatic Content Decoding * Unicode Response Bodies * Multipart File Uploads * HTTP(S) Proxy Support * Connection Timeouts * Streaming Downloads * .netrc Support * Chunked Requests ## Documentation For a run-through of all the basics, head over to the [QuickStart](quickstart.md). For more advanced topics, see the **Advanced** section, the [async support](async.md) section, or the [HTTP/2](http2.md) section. The [Developer Interface](api.md) provides a comprehensive API reference. To find out about tools that integrate with HTTPX, see [Third Party Packages](third_party_packages.md). ## Dependencies The HTTPX project relies on these excellent libraries: * `httpcore` - The underlying transport implementation for `httpx`. * `h11` - HTTP/1.1 support. * `certifi` - SSL certificates. * `idna` - Internationalized domain name support. * `sniffio` - Async library autodetection. As well as these optional installs: * `h2` - HTTP/2 support. *(Optional, with `httpx[http2]`)* * `socksio` - SOCKS proxy support. *(Optional, with `httpx[socks]`)* * `rich` - Rich terminal support. *(Optional, with `httpx[cli]`)* * `click` - Command line client support. *(Optional, with `httpx[cli]`)* * `brotli` or `brotlicffi` - Decoding for "brotli" compressed responses. *(Optional, with `httpx[brotli]`)* * `zstandard` - Decoding for "zstd" compressed responses. *(Optional, with `httpx[zstd]`)* A huge amount of credit is due to `requests` for the API layout that much of this work follows, as well as to `urllib3` for plenty of design inspiration around the lower-level networking details. ## Installation Install with pip: ```shell $ pip install httpx ``` Or, to include the optional HTTP/2 support, use: ```shell $ pip install httpx[http2] ``` To include the optional brotli and zstanda…

Languages
Python: 570031, Shell: 2821

Issues
#3785: Bump cryptography from 45.0.7 to 46.0.6 Bumps [cryptography](https://github.com/pyca/cryptography) from 45.0.7 to 46.0.6. <details> <summary>Changelog</summary> <p><em>Sourced from <a href="https://github.com/pyca/cryptography/blob/main/CHANGELOG.rst">cryptography's changelog</a>.</em></p> <blockquote> <p>46.0.6 - 2026-03-25</p> <pre><code> * **SECURITY ISSUE**: Fixed a bug where name cons... #3783: Add option to keep the same method for 301/302 redirects # Summary RFC hasn't been clear enough about the expected behavior for 301 and 302 response. While it's (unfortunately) common for browsers to switch the original http method to GET when following redirects, some server applications expects the "legacy" behavior which keeps the same method over redirects. Add new option to clients to... #3778: Refactor `map_httpcore_exceptions` to not be a context manager # Summary `contextlib.contextmanager`s are much slower than `try:except:` (where the no-except path is free in new Pythons), and here they occur in very hot paths. Sibling of encode/httpcore#1044. This benchmarks to be slightly faster than the original, like in the `httpcore` sibling PR: ``` $ hyperfine --warmup=3 'git checkout... #3777: Add real async iterator for ByteStreams # Summary Previously, `__aiter__` was implemented as a generator function, and as such could get garbage collected when not completely exhausted in a way that has (recent versions of) `trio` complaining: ``` $ uv pip list | grep io [... snip ...] Package Version anyio 4.12.1 trio 0.31.0 [... snip ...] $ uv run pytest tests/ -k test_write_timeout[trio... #3776: Quiesce warnings from `grep` in sync-version # Summary `(?:...)` non-capturing groups are a PCRE thing, not a grep ERE thing. As we can see in e.g. GitHub Actions runs, `sync-version` as of current main throws six (count 'em!) warnings when run. (Looks like [this warning was added into GNU tools some 4 years ago.](https://github.com/coreutils/gnulib/commit/88d3598a277061b855c778103c1f5a114... #3775: Do not hang forever if test server fails to start # Summary I was wondering why the test suite just hung forever, and finally with `pytest tests/ -vvvx --log-cli-level=DEBUG -s` I found that: ``` [Errno 48] error while attempting to bind on address ('127.0.0.1', 8000): [errno 48] address already in use ``` – yep, I was working on something else on port 8000 – and so, `server.running` never... #3774: docs: fix two broken examples in transports.md Found two broken examples in `docs/advanced/transports.md` that would confuse anyone trying to run them. The first is in the "Custom transports" section. It references `httpx.Mounts()` as a class, which doesn't exist - the correct way to use mounts is passing a dict to `Client(mounts=...)`. The example also had a missing comma between dict ent... #3771: Fix `unquote` IndexError on empty string input `unquote('')` in `_utils.py` raises `IndexError` because it accesses `value[0]` without checking string length first. This can occur when parsing digest auth `WWW-Authenticate` headers containing parameters with empty unquoted values (e.g. `realm=` instead of `realm=""`). #3770: Add missing `| None` to auth parameter in convenience methods The `options()`, `head()`, `post()`, `put()`, `patch()`, and `delete()` methods on both `Client` and `AsyncClient` are missing `| None` in their `auth` parameter type annotation. This is inconsistent with `get()`, `request()`, `send()`, and `stream()` which all accept `auth: AuthTypes | UseClientDefault | None`. Passing `auth=No... #3769: Ensure mounted transports are closed even if main transport raises When closing a client with proxy mounts, if the main transport's `close()`/`__exit__()` raises an exception, the mounted proxy transports would never be cleaned up. This wraps transport cleanup in `try/finally` to ensure all transports are properly closed. Affects `Client.close()`, `Client.__exit__()`, `AsyncClient.aclose()... #3768: Enable ruff UP (pyupgrade) rule and fix all 56 violations ## Summary Enables the ruff `UP` (pyupgrade) rule set and fixes all 56 existing violations across 17 files. ## Changes | Rule | Description | Count | |------|-------------|-------| | UP006 | Use builtin `tuple`/`dict`/`list` instead of `typing.Tuple`/`Dict`/`List` | 29 | | UP012 | Remove unnecessary `.encode('utf-8')` calls | 10 | |... #3767: Include header name in encoding error message ## Summary - When a header value contains non-ASCII characters that can't be encoded, the `UnicodeEncodeError` now includes the header name - Before: `'ascii' codec can't encode characters in position 0-27: ordinal not in range(128)` - After: `'ascii' codec can't encode characters in position 0-27: ordinal not in range(128) (header: 'auth')` Fi... #3766: Fix base_url query parameters corrupted during URL merging ## Summary - Fix `_enforce_trailing_slash()` appending `/` after query string in `raw_path`, corrupting `?data=1` into `?data=1/` - Fix `_merge_url()` concatenating paths without separating query string from path component - Both methods now split `raw_path` at `?` before path manipulation, then rejoin with query intact Fixes #3614... #3764: Percent-encode pipe character in URL paths Fixes #3565. The `|` character wasn't being percent-encoded in path segments, even though it's not a valid `pchar` per RFC 3986. Some servers reject or redirect URLs that contain an unencoded pipe — which is what the original reporter ran into (getting a 301 redirect when switching from `requests` to `httpx`). This removes `|` (U+007C) from the `P... #3761: Merge params with existing URL query parameters instead of replacing ## Summary - Fixes #3621: When a URL already contains query parameters (e.g. `https://example.com/path?page=1&s=list`) and the `params` argument is also provided, the existing query parameters were silently dropped and replaced by only the new `params`. This was inconsistent with the `requests` library and surprised users... #3760: Fix: Prevent query parameter corruption in base_url ## Summary Fixes #3614 When a `base_url` contains query parameters, the trailing slash enforcement was corrupting the query parameter values by appending the slash to the query string instead of just the path. ## Problem ```python client = httpx.Client(base_url="https://api.com/get?data=1") print(client.base_url.query) # Before: b'data=1/... #3758: Fix: Improve error message for invalid data parameter with AsyncClient ## Summary Fixes #3471 When `AsyncClient` receives invalid `data` like `data=[{"a": "b"}]` (a list of dicts), it was raising a confusing error: ``` RuntimeError: Attempted to send a sync request with an AsyncClient instance. ``` This error is misleading because the user IS using an async client correctly - the actual pr... #3757: Fix MockTransport not setting elapsed property ## Summary Fixes MockTransport to automatically set `response.elapsed` to `timedelta(0)` for both sync and async requests, eliminating boilerplate and matching real transpo
```


## URL 3: https://github.com/psf/requests

### SUMMARY
```yaml
mini_title: psf/requests
brief_summary: '* **ID:** 20240726101532 * **Tags:** #python, #http, #library, #api-client
  `psf/requests` is a high-level, user-friendly HTTP/1.1 client library for Python.
  It is one of the most downloaded Python packages, with ~300 million weekly downloads
  and usage in over 4,000,000 GitHub repositories. The library officially supports
  Python 3.10+. ### Architecture and API'
tags:
- _schema_fallback_
- github
- ai
- research
- knowledge
- capture
- summary
detailed_summary:
- heading: schema_fallback
  bullets:
  - structured extractor fell back; see metadata.is_schema_fallback
  - '* **ID:** 20240726101532 * **Tags:** #python, #http, #library, #api-client `psf/requests`
    is a high-level, user-friendly HTTP/1.1 client library for Python. It is one of
    the most downloaded Python packages, with ~300 million weekly downloads and usage
    in over 4,000,000 GitHub repositories. The library officially supports Python
    3.10+. ### Architecture and API'
  sub_sections: {}
metadata:
  source_type: github
  url: https://github.com/psf/requests
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata and README fetched
  total_tokens_used: 19011
  gemini_pro_tokens: 12644
  gemini_flash_tokens: 6367
  total_latency_ms: 79231
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload: null
  is_schema_fallback: true

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Repository
psf/requests A simple, yet elegant, HTTP library. Language: Python Topics: client, cookies, forhumans, http, humans, python, python-requests, requests

README
# Requests [![Version](https://img.shields.io/pypi/v/requests.svg?maxAge=86400)](https://pypi.org/project/requests/) [![Supported Versions](https://img.shields.io/pypi/pyversions/requests.svg)](https://pypi.org/project/requests) [![Downloads](https://static.pepy.tech/badge/requests/month)](https://pepy.tech/project/requests) [![Contributors](https://img.shields.io/github/contributors/psf/requests.svg)](https://github.com/psf/requests/graphs/contributors) [![Documentation](https://readthedocs.org/projects/requests/badge/?version=latest)](https://requests.readthedocs.io) **Requests** is a simple, yet elegant, HTTP library. ```python >>> import requests >>> r = requests.get('https://httpbin.org/basic-auth/user/pass', auth=('user', 'pass')) >>> r.status_code 200 >>> r.headers['content-type'] 'application/json; charset=utf8' >>> r.encoding 'utf-8' >>> r.text '{"authenticated": true, ...' >>> r.json() {'authenticated': True, ...} ``` Requests allows you to send HTTP/1.1 requests extremely easily. There’s no need to manually add query strings to your URLs, or to form-encode your `PUT` & `POST` data — but nowadays, just use the `json` method! Requests is one of the most downloaded Python packages today, pulling in around `300M downloads / week` — according to GitHub, Requests is currently [depended upon](https://github.com/psf/requests/network/dependents?package_id=UGFja2FnZS01NzA4OTExNg%3D%3D) by `4,000,000+` repositories. ## Installing Requests and Supported Versions Requests is available on PyPI: ```console $ python -m pip install requests ``` Requests officially supports Python 3.10+. ## Supported Features & Best–Practices Requests is ready for the demands of building robust and reliable HTTP–speaking applications, for the needs of today. - Keep-Alive & Connection Pooling - International Domains and URLs - Sessions with Cookie Persistence - Browser-style TLS/SSL Verification - Basic & Digest Authentication - Familiar `dict`–like Cookies - Automatic Content Decompression and Decoding - Multi-part File Uploads - SOCKS Proxy Support - Connection Timeouts - Streaming Downloads - Automatic honoring of `.netrc` - Chunked HTTP Requests ## Cloning the repository When cloning the Requests repository, you may need to add the `-c fetch.fsck.badTimezone=ignore` flag to avoid an error about a bad commit timestamp (see [this issue](https://github.com/psf/requests/issues/2690) for more background): ```shell git clone -c fetch.fsck.badTimezone=ignore https://github.com/psf/requests.git ``` You can also apply this setting to your global Git config: ```shell git config --global fetch.fsck.badTimezone ignore ``` --- [![Kenneth Reitz](https://raw.githubusercontent.com/psf/requests/main/ext/kr.png)](https://kennethreitz.org) [![Python Software Foundation](https://raw.githubusercontent.com/psf/requests/main/ext/psf.png)](https://www.python.org/psf)

Languages
Python: 358123, Makefile: 2527

Issues
#7384: Don't let REQUESTS_CA_BUNDLE override an explicit session.verify=False ## Problem When a session is configured with `verify=False` and the `REQUESTS_CA_BUNDLE` (or `CURL_CA_BUNDLE`) environment variable is set, the environment variable silently wins and TLS verification still happens: ```python import os os.environ["REQUESTS_CA_BUNDLE"] = "/etc/ssl/certs/ca-certificates.crt" s = requests.S... #7357: Localization of The Requests Documentation ## Announcement Hello Requests Community, I am the author of the @localizethedocs organization. And I’m glad to announce that the 🎉 **requests-docs-l10n** 🎉 project is published now: - 🚀 **Preview:** [requests-docs-l10n](https://projects.localizethedocs.org/requests-docs-l10n) - 🌐 **Crowdin:** [requests-docs-l10n](https://localizethedocs.crowdin.c... #7350: [Docs] Clarify behavior of timeout parameter in requests.get ## Description The current documentation for the `timeout` parameter in `requests.get()` does not clearly explain that it applies to both connection and read timeouts unless specified otherwise. This can be confusing for users who expect it to behave as a total request timeout. ## Suggested Improvement Add clarification in the do... #7341: Documentation for ChunkedEncodingError is either incorrect or very misleading As per https://github.com/psf/requests/issues/4771 the docs need improving, since this is caused by transient network outages. That github bug is the best explanation of this situation currently. The easiest fix would be to just add to the documentation on https://docs.python-requests.org/en/latest/_modules/reque... #7315: Preserve leading slashes in request path_url ## Summary Fixes issue #6711 where S3 presigned URLs with keys starting with '/' were incorrectly modified, breaking URL signatures. URLs like `https://bucket.s3.amazonaws.com//key_name` now correctly preserve `//key_name` in the path. ## Changes - Remove URL manipulation that collapsed leading slashes in `request_url()` method - Add test to ver... #7297: docs: warn about using Session across forked processes Context: psf/requests#4323 notes that creating a Session before forking can lead to unsafe behavior because connection pools may be shared between processes. This PR adds a short warning to the "Session Objects" section of the advanced usage docs to help users avoid this pitfall. What changed - Add a warning admonition about fork()/mul... #7289: Docs: add complete error handling example to quickstart This PR adds a complete, copy-paste-ready example to the Quickstart guide demonstrating how to handle errors when making HTTP requests. ### What’s included Example using requests.get Proper use of response.raise_for_status() Basic exception handling with HTTPError and generic exceptions ### Why this is useful The current documentation... #7272: Add inline types to Requests # Add inline type annotations > [!IMPORTANT] > We want feedback from people who actively maintain projects that depend on Requests or use it heavily. Please share your experience testing this against your code **in the linked issue**. > >Comments that are clearly AI-generated will be hidden or removed. This is a library written "for Humans". The conversation is... #7271: RFC: Adding inline type annotations to Requests > [!TIP] > Want to skip the background? Jump to [How to test](#how-to-test) or [What feedback we need](#what-feedback-were-looking-for). ## Motivation Requests has notably been without inline type annotations since type hints entered the Python ecosystem. We've had aspirations of bringing Requests up to par with community standards for a few... #7232: feat: add RFC 7616 support for non-Latin credentials in HTTPDigestAuth ## Summary Implement [RFC 7616](https://www.rfc-editor.org/rfc/rfc7616) extensions to fix `HTTPDigestAuth` failing with non-Latin-1 usernames (e.g., Cyrillic, Czech diacritics). ## Problem ```python import requests from requests.auth import HTTPDigestAuth # This fails — 'ř' cannot be encoded as latin-1 auth = HTTPDigest... #7223: Chardet is used, when it is available, not when `[use-chardet-on-py3]`-extra is installed First: IMHO this is related to but not a duplicate of #5871 #7222 #7219 `requests` tries to use `chardet` when it can be imported. However, IMHO it should only use it, if `requests` was installed with the `[use-chardet-on-py3]`-extra. As reported in #7219, `requests` shows a warning, when the version... #7217: Fix #6122: Empty body with None values sends malformed chunked request When `data={'foo': None}`, the body encodes to an empty string but `Content-Length` was not set because `0` is falsy in the `if length:` check. This caused the adapter to fall back to `Transfer-Encoding: chunked`, sending a terminating chunk (`0\r\n\r\n`) that servers misinterpreted as a second, malformed request. ## Fi... #7213: Fix PreparedRequest.copy() sharing hooks reference with original `PreparedRequest.copy()` currently assigns `p.hooks = self.hooks` which means the copy shares the same hooks dictionary and callback lists with the original request. Modifying hooks on the copy (e.g., registering a new response hook) will unintentionally affect the original as well. This is inconsistent with how the method ha... #7201: Fix incorrect Content-Length for StringIO with multi-byte characters ## Summary Fixes #6917. `super_len()` uses `seek`/`tell` to measure the length of file-like objects such as `StringIO` and `BytesIO`. However, `StringIO.tell()` returns the **character position**, not the byte offset. For strings containing multi-byte UTF-8 characters (e.g. emoji), this produces an incorrect `Content-Leng... #7194: Fix: Strip proxies when redirect URL matches no_proxy This fixes issue #3296 where the no_proxy environment variable was ignored on 302 redirects. The root cause was in resolve_proxies() - when should_bypass_proxies() returned True, the function only avoided adding new environment proxies, but did not remove existing proxies that were passed in from the original request. Changes: - Modifie... #7188: DMTF Redfish fails with 2.32 request module The DMTF redfish is failing with the latest Request module the issue is not seen with requests-2.31.0. The issue is in file requests/sessions.py, self.prepare_request(req) function where by encoding "%" url converts to "%25" while preparing request url. Debug - > /usr/local/lib/python3.12/site-packages/requests/sessions.py(564)request() -> method... #7184: Remove quotes on qop and algorithm values for Digest auth This fixes https://github.com/psf/requests/issues/5745 ## Motivation The [RFC7616](https://datatracker.ietf.org/doc/html/rfc7616) states the following for the Authorization header: "For historical reasons, a sender MUST NOT generate the quoted string syntax for the following parameters: algorithm, qop, and nc." The examples provided... #7183: docs: Clarify connect timeout also includes time for sending request body Adding to the docs that connect timeout includes the time for sending the request body, so people don't set this timeout too low for larger POST requests. #7181: docs: clarify gzip decompression behavior when using stream=True When using stream=True, Requests does not automatically decompress gzip-encoded responses when accessing Response.raw. This behavior is intentional but not clearly documented and has caused repeated confusion. This PR adds a note in the advanced documentation explaining the behavior and shows how to enable decompression manua... #7151: Fix: Correct Content-Length for StringIO with multi-byte characters ## Summary Fixes a regression where `Content-Length` is incorrectly calculated for `io.StringIO` objects containing multi-byte characters (like emojis). ## The Issue When `io.StringIO` is passed as `data`, [super_len](cci:1://file:///c:/Users/Harish/OneDrive/Desktop/webdev/sample%20project/requests_repo/src/requests/utils....

Commits
79f4df84cf77a2fee873809821dfbd786de05b97: Bump pypa/gh-action-pypi-publish from 1.13.0 to 1.14.0 (#7378) Bumps [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish) from 1.13.0 to 1.14.0. - [Release notes](https://g... b294b08fe3b08df9f646f64d1250f96193dab066: Consider urllib3 version has 3 numbers at most (#7375) (#7376) 5f3ff9b9e4d3d44960467e7877e06e9efa22f20b: Fix typos discovered by codespell (#7371) 514c1623fefff760bfa15a693aa38e474aba8560: Update README and remove extraneous images (#7366) d2f6bdecc835475c3cfbb83565ea879d7b2712ca: Clarify decode_unicode behaviour in iter_{content,lines} docstrings (#7365) a044b020dea43230585126901684a0f30ec635a8: Move DigestAuth hash algorithms to use usedforsecurity=False (#7310) 16df2a09173b17a82d607c31a6826b7c5dd0fc57: Move pytest pin to support 9.x series (#7364) fe2063be0cfbc08150ef468ae57a708c2514a321: Don't hide navigation on mobile webpage (#7360) 4b0b1a3e9f2fc21b9dcd8b906f2ff02645aa697e: Update pre-commit versions (#7348) * Update pre-commit versions * Add dependabot entry for pre-commit * Update pre-commit and ruff hooks 185f587a78e2d2df31ae8af8c95d97a012213df7: Cleanup docs and add i18n wrappers (#7354)

Repository signals
Pages URL: none GitHub Actions workflows: 10 Recent releases: v2.33.1, v2.33.0, v2.32.5, v2.32.4, v2.32.3 Language composition: Python=99.3%, Makefile=0.7% Root dirs: tests, docs_dir

Architecture overview
The Requests repository provides a simple HTTP library, accessible via `import requests`. Its `tests` directory ensures the library's functionality, while `docs_dir` contains its documentation.
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): ceabaea142f3bfbffd594bc913b6f43988f9c5a12a4b7d0b3fb40ee899d49107
