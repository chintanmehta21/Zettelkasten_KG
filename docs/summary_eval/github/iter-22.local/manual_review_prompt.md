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
brief_summary: FastAPI is a Python framework for building high-performance REST and
  GraphQL APIs. It is built on Starlette for web functionality and Pydantic for data
  handling, using Python type hints to define API endpoints, parameters, and data
  models for automatic validation, serialization, and documentation. Users adopt it
  via `pip install "fastapi[standard]"`. Core public interfaces include `@app.get`,
  `@ap
tags:
- python
- api-framework
- async
- pydantic
- starlette
- openapi
- http-client
- testing
- api
- web-framework
detailed_summary:
- heading: Overview
  bullets:
  - FastAPI is a Python framework for building REST APIs, designed for high performance
    and rapid development.
  - It uses standard Python type hints to define API endpoints, parameters, and data
    models.
  sub_sections: {}
- heading: Architecture / Modules
  bullets:
  - Built on Starlette for core web functionality, including the ASGI interface, routing,
    WebSockets, and request/response handling.
  - Uses Pydantic for all data validation, serialization, and deserialization of request
    bodies, parameters, and response models.
  - Requires an ASGI server like Uvicorn for deployment.
  - API behavior is declared using Python type hints in function signatures, enabling
    runtime data validation, automatic serialization to JSON, editor autocompletion,
    and type checking.
  - 'Automatically generates OpenAPI 3 and JSON Schema, serving interactive API documentation
    UIs: Swagger UI at `/docs` and ReDoc at `/redoc`.'
  - Natively supports `async def` endpoints using Python's `asyncio`.
  - Includes a dependency injection system for managing dependencies like database
    sessions or authentication.
  - Provides helpers for security schemes, including OAuth2 with JWT tokens and HTTP
    Basic authentication.
  - Supports GraphQL APIs through integration with libraries like Strawberry.
  sub_sections: {}
- heading: Public API / Interfaces
  bullets:
  - API endpoints are defined using decorators applied to asynchronous or synchronous
    Python functions.
  - Path operations are declared using HTTP method decorators.
  sub_sections: {}
- heading: Operational guidance
  bullets:
  - Installation of FastAPI and common dependencies can be done using pip.
  - Deployment requires an ASGI server.
  sub_sections: {}
- heading: Tests / Benchmarks / Examples
  bullets:
  - Includes a `TestClient` based on `httpx` for testing applications, designed to
    work well with `pytest`.
  - TechEmpower benchmarks consistently place FastAPI among the fastest Python frameworks.
  - GraphQL APIs are supported through integration with libraries like Strawberry.
  sub_sections: {}
metadata:
  source_type: github
  url: https://github.com/fastapi/fastapi
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 2 extra doc(s) fetched
  total_tokens_used: 29319
  gemini_pro_tokens: 26124
  gemini_flash_tokens: 3195
  total_latency_ms: 91854
  cod_iterations_used: 2
  self_check_missing_count: 6
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: fastapi/fastapi
    architecture_overview: FastAPI is a Python framework for building REST and GraphQL
      APIs, leveraging Starlette for core web functionality and Pydantic for data
      validation and serialization. It uses standard Python type hints to declare
      API endpoints, parameters, and data models, which enables automatic data validation,
      serialization, editor support, and OpenAPI documentation. As an ASGI framework,
      it requires an ASGI server like Uvicorn for deployment.
    brief_summary: FastAPI is a Python framework for building high-performance REST
      and GraphQL APIs. It is built on Starlette for web functionality and Pydantic
      for data handling, using Python type hints to define API endpoints, parameters,
      and data models for automatic validation, serialization, and documentation.
      Users adopt it via `pip install "fastapi[standard]"`. Core public interfaces
      include `@app.get`, `@app.post`, `@app.put`, `@app.head`, and `@app.api_route`
      for defining routes.
    tags:
    - python
    - api-framework
    - async
    - pydantic
    - starlette
    - openapi
    - http-client
    - testing
    - api
    - web-framework
    benchmarks_tests_examples:
    - TechEmpower benchmarks consistently place FastAPI among the fastest Python frameworks,
      with performance claimed to be on par with NodeJS and Go.
    - Includes a `TestClient` based on `httpx` for testing applications, designed
      to work well with `pytest`.
    - Supports GraphQL APIs through integration with libraries like Strawberry.
    detailed_summary:
    - heading: Overview
      bullets:
      - FastAPI is a Python framework for building REST APIs, designed for high performance
        and rapid development.
      - It uses standard Python type hints to define API endpoints, parameters, and
        data models.
      sub_sections: {}
      module_or_feature: Overview
      main_stack:
      - Python
      - Starlette
      - Pydantic
      - Uvicorn
      public_interfaces: []
      usability_signals:
      - Production-ready
      - actively maintained
      - formal security policy
    - heading: Architecture / Modules
      bullets:
      - Built on Starlette for core web functionality, including the ASGI interface,
        routing, WebSockets, and request/response handling.
      - Uses Pydantic for all data validation, serialization, and deserialization
        of request bodies, parameters, and response models.
      - Requires an ASGI server like Uvicorn for deployment.
      - API behavior is declared using Python type hints in function signatures, enabling
        runtime data validation, automatic serialization to JSON, editor autocompletion,
        and type checking.
      - 'Automatically generates OpenAPI 3 and JSON Schema, serving interactive API
        documentation UIs: Swagger UI at `/docs` and ReDoc at `/redoc`.'
      - Natively supports `async def` endpoints using Python's `asyncio`.
      - Includes a dependency injection system for managing dependencies like database
        sessions or authentication.
      - Provides helpers for security schemes, including OAuth2 with JWT tokens and
        HTTP Basic authentication.
      - Supports GraphQL APIs through integration with libraries like Strawberry.
      sub_sections: {}
      module_or_feature: Starlette, Pydantic, Uvicorn, OpenAPI 3, JSON Schema, Swagger
        UI, ReDoc, asyncio, OAuth2, JWT, HTTP Basic authentication, Strawberry
      main_stack: []
      public_interfaces: []
      usability_signals: []
    - heading: Public API / Interfaces
      bullets:
      - API endpoints are defined using decorators applied to asynchronous or synchronous
        Python functions.
      - Path operations are declared using HTTP method decorators.
      sub_sections: {}
      module_or_feature: Public API / Interfaces
      main_stack: []
      public_interfaces:
      - '@app.get'
      - '@app.put'
      - '@app.api_route'
      - '@app.post'
      - '@app.head'
      usability_signals: []
    - heading: Operational guidance
      bullets:
      - Installation of FastAPI and common dependencies can be done using pip.
      - Deployment requires an ASGI server.
      sub_sections: {}
      module_or_feature: Operational guidance
      main_stack: []
      public_interfaces: []
      usability_signals:
      - pip install "fastapi[standard]"
      - pip install fastapi
      - pip install "fastapi[standard-no-fastapi-cloud-cli]"
    - heading: Tests / Benchmarks / Examples
      bullets:
      - Includes a `TestClient` based on `httpx` for testing applications, designed
        to work well with `pytest`.
      - TechEmpower benchmarks consistently place FastAPI among the fastest Python
        frameworks.
      - GraphQL APIs are supported through integration with libraries like Strawberry.
      sub_sections: {}
      module_or_feature: TestClient, httpx, pytest, TechEmpower benchmarks, Strawberry
      main_stack: []
      public_interfaces: []
      usability_signals: []
    _github_archetype:
      archetype: framework_api
      confidence: 0.692
      reasons:
      - framework_tokens=10
      - topics_framework
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
brief_summary: 'The library supports HTTP/1.1 and HTTP/2 (via the `httpx[http2]` extra)
  and can make requests directly to WSGI/ASGI applications using `WSGITransport` and
  `ASGITransport`. Its architecture is built upon the `httpcore` library, which manages
  the underlying transport. Core dependencies include `httpcore`, `h11` (for HTTP/1.1),
  `certifi`, `idna`, and `sniffio` (for async library detection). Optional '
tags:
- python
- api-framework
- async
- http-client
- testing
- asyncio
- http2
- cli
detailed_summary:
- heading: Overview
  bullets:
  - '`httpx` is a Python 3 HTTP client providing both synchronous and asynchronous
    APIs, intended as a successor to `requests`.'
  - It requires Python 3.9+ (support for 3.8 was dropped after v0.28.1).
  - The library supports HTTP/1.1 and HTTP/2 (via the `httpx[http2]` extra) and can
    make requests directly to WSGI/ASGI applications using `WSGITransport` and `ASGITransport`.
  sub_sections: {}
- heading: Architecture / Modules
  bullets:
  - Its architecture is built upon the `httpcore` library, which manages the underlying
    transport.
  - Core dependencies include `httpcore`, `h11` (for HTTP/1.1), `certifi`, `idna`,
    and `sniffio` (for async library detection).
  sub_sections:
    Optional Features:
    - '`[http2]`: `h2`'
    - '`[cli]`: `rich`, `click` for a command-line client'
    - '`[socks]`: `socksio` for SOCKS proxy support'
    - '`[brotli]`: `brotli` or `brotlicffi`'
    - '`[zstd]`: `zstandard` (added in v0.27.1)'
    Client Features:
    - connection pooling
    - sessions with cookie persistence
    - SSL verification
    - proxy support
    - automatic decompression (gzip, deflate, brotli, zstd)
    - strict default timeouts on all network operations
- heading: Public API / Interfaces
  bullets:
  - The API is designed for broad compatibility with `requests`, building on its usability.
  - The project is actively maintained (v0.28.1 released Dec 2024), fully type-annotated,
    and claims 100% test coverage.
  sub_sections: {}
- heading: Operational Guidance
  bullets:
  - Requires Python 3.9+ for operation.
  sub_sections: {}
- heading: Notable Issues and Behavior
  bullets:
  - 'Recent API evolution includes: `proxies` and `app` arguments removed after deprecation;
    simplified `proxy` argument added in v0.26.0; `cert` argument and string usage
    for `verify` deprecated in v0.28.0.'
  - Since v0.28.0, JSON request bodies use a more compact representation by default,
    which may affect test suites that rely on specific whitespace formatting.
  sub_sections:
    URL Parameter Merging:
    - 'Recent fixes (#3761, #3766) address bugs where query parameters from a `base_url`
      were incorrectly merged with or replaced by those in a request''s `params` argument,
      with behavior being refined for consistency with `requests`.'
    Redirects:
    - An open issue (#3783) requests an option to preserve the original HTTP method
      on 301/302 redirects. The current behavior follows browser convention by changing
      the method to `GET`, but some server applications expect the original method
      to be maintained.
    Performance/Resource Management:
    - Active work includes refactoring hot paths to avoid slower patterns like `contextlib.contextmanager`
      (#3778) and splitting large streamed request bodies into 64KB chunks to prevent
      memory spikes (#3752).
    Async Correctness:
    - Recent fixes ensure robust async operation, such as correcting the `__aiter__`
      implementation to prevent garbage collection warnings in `trio` (#3777) and
      ensuring all mounted transports are closed correctly during exceptions (#3769).
metadata:
  source_type: github
  url: https://github.com/encode/httpx
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 2 extra doc(s) fetched
  total_tokens_used: 22174
  gemini_pro_tokens: 18716
  gemini_flash_tokens: 3458
  total_latency_ms: 75034
  cod_iterations_used: 2
  self_check_missing_count: 3
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: encode/httpx
    architecture_overview: 'The library supports HTTP/1.1 and HTTP/2 (via the `httpx[http2]`
      extra) and can make requests directly to WSGI/ASGI applications using `WSGITransport`
      and `ASGITransport`. Its architecture is built upon the `httpcore` library,
      which manages the underlying transport. Core dependencies include `httpcore`,
      `h11` (for HTTP/1.1), `certifi`, `idna`, and `sniffio` (for async library detection).
      Optional features are enabled via extras: `[http2]`: `h2`, `[cli]`: `rich`,
      `click` for a command-line client'
    brief_summary: 'The library supports HTTP/1.1 and HTTP/2 (via the `httpx[http2]`
      extra) and can make requests directly to WSGI/ASGI applications using `WSGITransport`
      and `ASGITransport`. Its architecture is built upon the `httpcore` library,
      which manages the underlying transport. Core dependencies include `httpcore`,
      `h11` (for HTTP/1.1), `certifi`, `idna`, and `sniffio` (for async library detection).
      Optional features are enabled via extras: `[http2]`: `h2`, `[cli]`: `rich`,
      `click` for a command-line client'
    tags:
    - python
    - api-framework
    - async
    - http-client
    - testing
    - asyncio
    - http2
    - cli
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: Overview
      bullets:
      - '`httpx` is a Python 3 HTTP client providing both synchronous and asynchronous
        APIs, intended as a successor to `requests`.'
      - It requires Python 3.9+ (support for 3.8 was dropped after v0.28.1).
      - The library supports HTTP/1.1 and HTTP/2 (via the `httpx[http2]` extra) and
        can make requests directly to WSGI/ASGI applications using `WSGITransport`
        and `ASGITransport`.
      sub_sections: {}
      module_or_feature: Overview
      main_stack:
      - Python
      - Shell
      - asgi
      - click
      public_interfaces:
      - WSGITransport
      - ASGITransport
      usability_signals:
      - pip install httpx
      - pip install 'httpx[cli]'
      - pip install httpx[http2]
    - heading: Architecture / Modules
      bullets:
      - Its architecture is built upon the `httpcore` library, which manages the underlying
        transport.
      - Core dependencies include `httpcore`, `h11` (for HTTP/1.1), `certifi`, `idna`,
        and `sniffio` (for async library detection).
      sub_sections:
        Optional Features:
        - '`[http2]`: `h2`'
        - '`[cli]`: `rich`, `click` for a command-line client'
        - '`[socks]`: `socksio` for SOCKS proxy support'
        - '`[brotli]`: `brotli` or `brotlicffi`'
        - '`[zstd]`: `zstandard` (added in v0.27.1)'
        Client Features:
        - connection pooling
        - sessions with cookie persistence
        - SSL verification
        - proxy support
        - automatic decompression (gzip, deflate, brotli, zstd)
        - strict default timeouts on all network operations
      module_or_feature: Architecture / Modules
      main_stack: []
      public_interfaces: []
      usability_signals: []
    - heading: Public API / Interfaces
      bullets:
      - The API is designed for broad compatibility with `requests`, building on its
        usability.
      - The project is actively maintained (v0.28.1 released Dec 2024), fully type-annotated,
        and claims 100% test coverage.
      sub_sections: {}
      module_or_feature: Public API / Interfaces
      main_stack: []
      public_interfaces:
      - proxies
      - app
      - proxy
      - cert
      - verify
      usability_signals: []
    - heading: Operational Guidance
      bullets:
      - Requires Python 3.9+ for operation.
      sub_sections: {}
      module_or_feature: Operational Guidance
      main_stack: []
      public_interfaces: []
      usability_signals:
      - pip install httpx
      - pip install 'httpx[cli]'
      - pip install httpx[http2]
    - heading: Notable Issues and Behavior
      bullets:
      - 'Recent API evolution includes: `proxies` and `app` arguments removed after
        deprecation; simplified `proxy` argument added in v0.26.0; `cert` argument
        and string usage for `verify` deprecated in v0.28.0.'
      - Since v0.28.0, JSON request bodies use a more compact representation by default,
        which may affect test suites that rely on specific whitespace formatting.
      sub_sections:
        URL Parameter Merging:
        - 'Recent fixes (#3761, #3766) address bugs where query parameters from a
          `base_url` were incorrectly merged with or replaced by those in a request''s
          `params` argument, with behavior being refined for consistency with `requests`.'
        Redirects:
        - An open issue (#3783) requests an option to preserve the original HTTP method
          on 301/302 redirects. The current behavior follows browser convention by
          changing the method to `GET`, but some server applications expect the original
          method to be maintained.
        Performance/Resource Management:
        - Active work includes refactoring hot paths to avoid slower patterns like
          `contextlib.contextmanager` (#3778) and splitting large streamed request
          bodies into 64KB chunks to prevent memory spikes (#3752).
        Async Correctness:
        - Recent fixes ensure robust async operation, such as correcting the `__aiter__`
          implementation to prevent garbage collection warnings in `trio` (#3777)
          and ensuring all mounted transports are closed correctly during exceptions
          (#3769).
      module_or_feature: Notable Issues and Behavior
      main_stack: []
      public_interfaces: []
      usability_signals: []
    _github_archetype:
      archetype: cli_tool
      confidence: 0.529
      reasons:
      - cli_tokens=3
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
brief_summary: The `requests` library provides a high-level functional API (e.g.,
  `requests.get()`, `post()`) and a class-based `requests.Session` object for stateful
  operations like connection pooling and cookie persistence. Responses are encapsulated
  in a `Response` object, offering access to `status_code`, `headers`, and content
  via methods like `.text` and `.json()`. The library handles data encoding, authen
tags:
- python
- library
- http-client
- http
- client
- networking
- api-client
- web-development
detailed_summary:
- heading: Overview
  bullets:
  - A Python library for sending HTTP/1.1 requests, designed with a "for humans" philosophy
    to simplify common operations.
  - One of Python's most downloaded packages (~300M/week, used by >4M GitHub repositories).
  - Actively maintained, officially supporting Python 3.10+.
  sub_sections: {}
- heading: Architecture / Modules
  bullets:
  - Provides a high-level functional API.
  - Offers a class-based `requests.Session` object for stateful operations (connection
    pooling, Keep-Alive, cookie persistence).
  - Responses are encapsulated in a `Response` object with attributes like `status_code`,
    `headers`, and content access methods.
  - The codebase is 99.3% Python.
  sub_sections: {}
- heading: Features
  bullets: []
  sub_sections:
    Data Handling:
    - Automatic query string encoding, form-encoding for `PUT`/`POST`, multi-part
      file uploads, and content decompression.
    Authentication:
    - Built-in support for Basic and Digest authentication.
    - '`HTTPDigestAuth` was updated to support non-Latin credentials per RFC 7616
      (#7232).'
    Connection Management:
    - Connection pooling, browser-style TLS/SSL verification, SOCKS proxy support,
      and connection timeouts.
    Internationalization:
    - Supports International Domains and URLs.
    Advanced:
    - Streaming downloads (`stream=True`), chunked requests, and automatic `.netrc`
      file usage.
- heading: Operational Guidance
  bullets:
  - Installation is performed via pip.
  sub_sections: {}
- heading: Notable Issues & Caveats
  bullets: []
  sub_sections:
    Configuration:
    - The `REQUESTS_CA_BUNDLE` environment variable can silently override an explicit
      `session.verify=False`, forcing TLS verification (#7384).
    Concurrency:
    - Using a single `Session` object across forked processes is unsafe due to the
      shared underlying connection pool, which can lead to race conditions (#7297).
    Timeouts:
    - 'The `timeout` parameter is not a total request timeout; it applies separately
      to the connection attempt and the read time between bytes. The connect timeout
      also includes the time to send the request body (#7350, #7183).'
    State Management:
    - A bug was fixed where `PreparedRequest.copy()` shared its `hooks` dictionary
      with the original, leading to unintended side effects when modifying the copy.
    Content Handling:
    - When `stream=True`, automatic gzip decompression is disabled on the `Response.raw`
      object (#7181).
    - Documentation was improved to clarify that `ChunkedEncodingError` is often caused
      by transient network outages.
    - 'A bug was fixed where `data={''key'': None}` created a malformed chunked request
      because `Content-Length` was not set to 0 (#7217).'
    - A `Content-Length` bug with `io.StringIO` objects containing multi-byte characters
      was fixed; `tell()` was incorrectly returning character count instead of byte
      offset (#7201).
    URL & Proxy Handling:
    - A bug that collapsed leading slashes in URL paths (e.g., `//key`), breaking
      S3 presigned URLs, has been fixed (#7315).
    - '`no_proxy` environment variables were previously ignored on redirects (e.g.,
      302), but this is now resolved (#7194).'
    - A v2.32 regression that broke DMTF Redfish URLs by incorrectly encoding `%`
      to `%25` was fixed (#7188).
    Dependencies:
    - The library uses `chardet` for encoding detection if it is present in the environment,
      not only if installed via the `[use-chardet-on-py3]` extra, which can cause
      unexpected behavior (#7223).
    Development:
    - 'A major effort is underway to add inline type annotations (#7271, #7272).'
    - A project (`requests-docs-l10n`) has been launched to localize documentation.
    - Cloning the repository may require `git config --global fetch.fsck.badTimezone
      ignore` to work around a commit with a bad timestamp (#2690).
metadata:
  source_type: github
  url: https://github.com/psf/requests
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata and README fetched
  total_tokens_used: 16666
  gemini_pro_tokens: 12908
  gemini_flash_tokens: 3758
  total_latency_ms: 91616
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: psf/requests
    architecture_overview: The `requests` library provides a high-level functional
      API (e.g., `requests.get()`, `post()`) and a class-based `requests.Session`
      object for stateful operations like connection pooling and cookie persistence.
      Responses are encapsulated in a `Response` object, offering access to `status_code`,
      `headers`, and content via methods like `.text` and `.json()`. The library handles
      data encoding, authentication (Basic, Digest), connection management (TLS/SSL
      verification, SOCKS proxies, timeouts), int
    brief_summary: The `requests` library provides a high-level functional API (e.g.,
      `requests.get()`, `post()`) and a class-based `requests.Session` object for
      stateful operations like connection pooling and cookie persistence. Responses
      are encapsulated in a `Response` object, offering access to `status_code`, `headers`,
      and content via methods like `.text` and `.json()`. The library handles data
      encoding, authentication (Basic, Digest), connection management (TLS/SSL verification,
      SOCKS proxies, timeouts), int
    tags:
    - python
    - library
    - http-client
    - http
    - client
    - networking
    - api-client
    - web-development
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: Overview
      bullets:
      - A Python library for sending HTTP/1.1 requests, designed with a "for humans"
        philosophy to simplify common operations.
      - One of Python's most downloaded packages (~300M/week, used by >4M GitHub repositories).
      - Actively maintained, officially supporting Python 3.10+.
      sub_sections: {}
      module_or_feature: Overview
      main_stack:
      - Python
      public_interfaces: []
      usability_signals: []
    - heading: Architecture / Modules
      bullets:
      - Provides a high-level functional API.
      - Offers a class-based `requests.Session` object for stateful operations (connection
        pooling, Keep-Alive, cookie persistence).
      - Responses are encapsulated in a `Response` object with attributes like `status_code`,
        `headers`, and content access methods.
      - The codebase is 99.3% Python.
      sub_sections: {}
      module_or_feature: Core Library
      main_stack:
      - Python
      public_interfaces:
      - requests.get()
      - requests.post()
      - requests.Session
      - Response
      - status_code
      - headers
      - .text
      - .json()
      usability_signals: []
    - heading: Features
      bullets: []
      sub_sections:
        Data Handling:
        - Automatic query string encoding, form-encoding for `PUT`/`POST`, multi-part
          file uploads, and content decompression.
        Authentication:
        - Built-in support for Basic and Digest authentication.
        - '`HTTPDigestAuth` was updated to support non-Latin credentials per RFC 7616
          (#7232).'
        Connection Management:
        - Connection pooling, browser-style TLS/SSL verification, SOCKS proxy support,
          and connection timeouts.
        Internationalization:
        - Supports International Domains and URLs.
        Advanced:
        - Streaming downloads (`stream=True`), chunked requests, and automatic `.netrc`
          file usage.
      module_or_feature: Features
      main_stack: []
      public_interfaces:
      - stream=True
      - HTTPDigestAuth
      - timeout
      usability_signals: []
    - heading: Operational Guidance
      bullets:
      - Installation is performed via pip.
      sub_sections: {}
      module_or_feature: Operational Guidance
      main_stack: []
      public_interfaces: []
      usability_signals:
      - pip install requests
    - heading: Notable Issues & Caveats
      bullets: []
      sub_sections:
        Configuration:
        - The `REQUESTS_CA_BUNDLE` environment variable can silently override an explicit
          `session.verify=False`, forcing TLS verification (#7384).
        Concurrency:
        - Using a single `Session` object across forked processes is unsafe due to
          the shared underlying connection pool, which can lead to race conditions
          (#7297).
        Timeouts:
        - 'The `timeout` parameter is not a total request timeout; it applies separately
          to the connection attempt and the read time between bytes. The connect timeout
          also includes the time to send the request body (#7350, #7183).'
        State Management:
        - A bug was fixed where `PreparedRequest.copy()` shared its `hooks` dictionary
          with the original, leading to unintended side effects when modifying the
          copy.
        Content Handling:
        - When `stream=True`, automatic gzip decompression is disabled on the `Response.raw`
          object (#7181).
        - Documentation was improved to clarify that `ChunkedEncodingError` is often
          caused by transient network outages.
        - 'A bug was fixed where `data={''key'': None}` created a malformed chunked
          request because `Content-Length` was not set to 0 (#7217).'
        - A `Content-Length` bug with `io.StringIO` objects containing multi-byte
          characters was fixed; `tell()` was incorrectly returning character count
          instead of byte offset (#7201).
        URL & Proxy Handling:
        - A bug that collapsed leading slashes in URL paths (e.g., `//key`), breaking
          S3 presigned URLs, has been fixed (#7315).
        - '`no_proxy` environment variables were previously ignored on redirects (e.g.,
          302), but this is now resolved (#7194).'
        - A v2.32 regression that broke DMTF Redfish URLs by incorrectly encoding
          `%` to `%25` was fixed (#7188).
        Dependencies:
        - The library uses `chardet` for encoding detection if it is present in the
          environment, not only if installed via the `[use-chardet-on-py3]` extra,
          which can cause unexpected behavior (#7223).
        Development:
        - 'A major effort is underway to add inline type annotations (#7271, #7272).'
        - A project (`requests-docs-l10n`) has been launched to localize documentation.
        - Cloning the repository may require `git config --global fetch.fsck.badTimezone
          ignore` to work around a commit with a bad timestamp (#2690).
      module_or_feature: Notable Issues & Caveats
      main_stack:
      - chardet
      public_interfaces:
      - REQUESTS_CA_BUNDLE
      - session.verify=False
      usability_signals: []
    _github_archetype:
      archetype: cli_tool
      confidence: 0.6
      reasons:
      - cli_tokens=1
  is_schema_fallback: false

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


## URL 4: https://github.com/pydantic/pydantic

### SUMMARY
```yaml
mini_title: pydantic/pydantic
brief_summary: Pydantic V2 is a performance-focused rewrite with a hybrid implementation,
  approximately 83.1% Python and 16.6% Rust. Its performance-critical validation logic
  resides in Rust within the tightly coupled `pydantic-core` repository. The library
  requires Python 3.10+ and bundles the final Pydantic V1 version, accessible via
  `from pydantic import v1 as pydantic_v1`, to facilitate migration.
tags:
- python
- library
- pydantic
- openapi
- validation
- type-hints
- rust
- api-design
- data-modeling
- serialization
detailed_summary:
- heading: Overview
  bullets:
  - Pydantic is a widely used Python data validation and settings management library.
  - It uses standard type hints to define schemas for parsing, validating, and coercing
    input data into strongly-typed objects.
  - The library's primary functions are data validation and serialization through
    its core API, `pydantic.BaseModel`.
  - Users define data structures by inheriting from `BaseModel`, which Pydantic uses
    at runtime to validate and coerce input data (e.g., converting a JSON string '123'
    to an integer 123, or an ISO 8601 string to a `datetime` object).
  - Models can also generate JSON Schema definitions.
  - Because it uses standard type hints, Pydantic integrates with static analysis
    tools like IDEs and linters.
  - Functionality is extensible via optional dependencies for specific types.
  sub_sections: {}
- heading: Architecture / Modules
  bullets:
  - '**Hybrid Implementation:** Pydantic V2 is a performance-focused rewrite with
    a codebase of approximately 83.1% Python and 16.6% Rust.'
  - The performance-critical validation logic is implemented in Rust within a separate,
    tightly coupled repository named `pydantic-core`.
  - '**Version Support:** The library requires Python 3.10+ (support for 3.9 was dropped
    in commit `b36eaeb4e5eea176`).'
  - To ease migration from V1, Pydantic V2 bundles the final V1 version, accessible
    via `from pydantic import v1 as pydantic_v1`.
  sub_sections: {}
- heading: Maturity & Ecosystem
  bullets:
  - '**Active Development:** The project is actively maintained, evidenced by a high
    release frequency (e.g., v2.13.0 through v2.13.3) and the use of 13 distinct GitHub
    Actions workflows for continuous integration.'
  - '**Ecosystem:** The Pydantic organization also develops Pydantic Logfire, an observability
    platform that instruments Pydantic models to monitor validation events.'
  sub_sections: {}
- heading: Notable Issues & Caveats
  bullets:
  - '**Localization:** Validation error messages are hardcoded in English, with no
    built-in localization mechanism; this is a requested feature (#13113).'
  - '**Serialization Regressions:** JSON schema generation can be incorrect for certain
    types. A v2.12 regression caused the `Decimal` schema to generate a regex pattern
    that rejects scientific notation, a format Pydantic itself can produce (#13089).'
  - '**Complex Type Handling:** Support for advanced type hints has known gaps, including
    unresolved edge cases with generic recursive models (#13085).'
  - '**API Behavior:** The `model_copy(deep=True, update=...)` method unnecessarily
    deepcopies fields that are immediately replaced by the `update` dictionary, causing
    performance issues and potential crashes with objects that cannot be deep-copied
    (#13077, #13087).'
  - '**Dependency Management:** The tight coupling with `pydantic-core` has caused
    downstream packaging failures when git tags were missing from `pydantic-core`
    releases (#13071).'
  sub_sections: {}
metadata:
  source_type: github
  url: https://github.com/pydantic/pydantic
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 1 extra doc(s) fetched
  total_tokens_used: 18597
  gemini_pro_tokens: 15487
  gemini_flash_tokens: 3110
  total_latency_ms: 86874
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: pydantic/pydantic
    architecture_overview: Pydantic V2 is a performance-focused rewrite with a hybrid
      implementation, approximately 83.1% Python and 16.6% Rust. Its performance-critical
      validation logic resides in Rust within the tightly coupled `pydantic-core`
      repository. The library requires Python 3.10+ and bundles the final Pydantic
      V1 version, accessible via `from pydantic import v1 as pydantic_v1`, to facilitate
      migration.
    brief_summary: Pydantic V2 is a performance-focused rewrite with a hybrid implementation,
      approximately 83.1% Python and 16.6% Rust. Its performance-critical validation
      logic resides in Rust within the tightly coupled `pydantic-core` repository.
      The library requires Python 3.10+ and bundles the final Pydantic V1 version,
      accessible via `from pydantic import v1 as pydantic_v1`, to facilitate migration.
    tags:
    - python
    - library
    - pydantic
    - openapi
    - validation
    - type-hints
    - rust
    - api-design
    - data-modeling
    - serialization
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: Overview
      bullets:
      - Pydantic is a widely used Python data validation and settings management library.
      - It uses standard type hints to define schemas for parsing, validating, and
        coercing input data into strongly-typed objects.
      - The library's primary functions are data validation and serialization through
        its core API, `pydantic.BaseModel`.
      - Users define data structures by inheriting from `BaseModel`, which Pydantic
        uses at runtime to validate and coerce input data (e.g., converting a JSON
        string '123' to an integer 123, or an ISO 8601 string to a `datetime` object).
      - Models can also generate JSON Schema definitions.
      - Because it uses standard type hints, Pydantic integrates with static analysis
        tools like IDEs and linters.
      - Functionality is extensible via optional dependencies for specific types.
      sub_sections: {}
      module_or_feature: Overview
      main_stack:
      - Python
      - Rust
      - Makefile
      - fastapi
      public_interfaces:
      - '@users.noreply.github.com'
      - '@github.com'
      - '@haventax.com'
      - /summary
      - pydantic.BaseModel
      usability_signals:
      - pip install -U pydantic
    - heading: Architecture / Modules
      bullets:
      - '**Hybrid Implementation:** Pydantic V2 is a performance-focused rewrite with
        a codebase of approximately 83.1% Python and 16.6% Rust.'
      - The performance-critical validation logic is implemented in Rust within a
        separate, tightly coupled repository named `pydantic-core`.
      - '**Version Support:** The library requires Python 3.10+ (support for 3.9 was
        dropped in commit `b36eaeb4e5eea176`).'
      - To ease migration from V1, Pydantic V2 bundles the final V1 version, accessible
        via `from pydantic import v1 as pydantic_v1`.
      sub_sections: {}
      module_or_feature: Architecture / Modules
      main_stack: []
      public_interfaces: []
      usability_signals: []
    - heading: Maturity & Ecosystem
      bullets:
      - '**Active Development:** The project is actively maintained, evidenced by
        a high release frequency (e.g., v2.13.0 through v2.13.3) and the use of 13
        distinct GitHub Actions workflows for continuous integration.'
      - '**Ecosystem:** The Pydantic organization also develops Pydantic Logfire,
        an observability platform that instruments Pydantic models to monitor validation
        events.'
      sub_sections: {}
      module_or_feature: Maturity & Ecosystem
      main_stack: []
      public_interfaces: []
      usability_signals: []
    - heading: Notable Issues & Caveats
      bullets:
      - '**Localization:** Validation error messages are hardcoded in English, with
        no built-in localization mechanism; this is a requested feature (#13113).'
      - '**Serialization Regressions:** JSON schema generation can be incorrect for
        certain types. A v2.12 regression caused the `Decimal` schema to generate
        a regex pattern that rejects scientific notation, a format Pydantic itself
        can produce (#13089).'
      - '**Complex Type Handling:** Support for advanced type hints has known gaps,
        including unresolved edge cases with generic recursive models (#13085).'
      - '**API Behavior:** The `model_copy(deep=True, update=...)` method unnecessarily
        deepcopies fields that are immediately replaced by the `update` dictionary,
        causing performance issues and potential crashes with objects that cannot
        be deep-copied (#13077, #13087).'
      - '**Dependency Management:** The tight coupling with `pydantic-core` has caused
        downstream packaging failures when git tags were missing from `pydantic-core`
        releases (#13071).'
      sub_sections: {}
      module_or_feature: Notable Issues & Caveats
      main_stack: []
      public_interfaces: []
      usability_signals: []
    _github_archetype:
      archetype: cli_tool
      confidence: 0.6
      reasons:
      - cli_tokens=1
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Repository
pydantic/pydantic Data validation using Python type hints Language: Python Topics: hints, json-schema, parsing, pydantic, python, python310, python311, python312, python313, python39, validation

README
# Pydantic Validation [![CI](https://img.shields.io/github/actions/workflow/status/pydantic/pydantic/ci.yml?branch=main&logo=github&label=CI)](https://github.com/pydantic/pydantic/actions?query=event%3Apush+branch%3Amain+workflow%3ACI) [![Coverage](https://coverage-badge.samuelcolvin.workers.dev/pydantic/pydantic.svg)](https://coverage-badge.samuelcolvin.workers.dev/redirect/pydantic/pydantic) [![pypi](https://img.shields.io/pypi/v/pydantic.svg)](https://pypi.python.org/pypi/pydantic) [![CondaForge](https://img.shields.io/conda/v/conda-forge/pydantic.svg)](https://anaconda.org/conda-forge/pydantic) [![downloads](https://static.pepy.tech/badge/pydantic/month)](https://pepy.tech/project/pydantic) [![versions](https://img.shields.io/pypi/pyversions/pydantic.svg)](https://github.com/pydantic/pydantic) [![license](https://img.shields.io/github/license/pydantic/pydantic.svg)](https://github.com/pydantic/pydantic/blob/main/LICENSE) [![Pydantic v2](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json)](https://docs.pydantic.dev/latest/contributing/#badges) [![llms.txt](https://img.shields.io/badge/llms.txt-green)](https://docs.pydantic.dev/latest/llms.txt) Data validation using Python type hints. Fast and extensible, Pydantic plays nicely with your linters/IDE/brain. Define how data should be in pure, canonical Python 3.10+; validate it with Pydantic. ## Pydantic Logfire :fire: We've launched Pydantic Logfire to help you monitor your applications. [Learn more](https://pydantic.dev/logfire/?utm_source=pydantic_validation) ## Pydantic V1.10 vs. V2 Pydantic V2 is a ground-up rewrite that offers many new features, performance improvements, and some breaking changes compared to Pydantic V1. If you're using Pydantic V1 you may want to look at the [pydantic V1.10 Documentation](https://docs.pydantic.dev/) or, [`1.10.X-fixes` git branch](https://github.com/pydantic/pydantic/tree/1.10.X-fixes). Pydantic V2 also ships with the latest version of Pydantic V1 built in so that you can incrementally upgrade your code base and projects: `from pydantic import v1 as pydantic_v1`. ## Help See [documentation](https://docs.pydantic.dev/) for more details. ## Installation Install using `pip install -U pydantic` or `conda install pydantic -c conda-forge`. For more installation options to make Pydantic even faster, see the [Install](https://docs.pydantic.dev/install/) section in the documentation. ## A Simple Example ```python from datetime import datetime from typing import Optional from pydantic import BaseModel class User(BaseModel): id: int name: str = 'John Doe' signup_ts: Optional[datetime] = None friends: list[int] = [] external_data = {'id': '123', 'signup_ts': '2017-06-01 12:22', 'friends': [1, '2', b'3']} user = User(**external_data) print(user) #> User id=123 name='John Doe' signup_ts=datetime.datetime(2017, 6, 1, 12, 22) friends=[1, 2, 3] print(user.id) #> 123 ``` ## Contributing For guidance on setting up a development environment and how to make a contribution to Pydantic, see [Contributing to Pydantic](https://docs.pydantic.dev/contributing/). ## Reporting a Security Vulnerability See our [security policy](https://github.com/pydantic/pydantic/security/policy).

Docs
### docs/index.md # Pydantic Validation [![CI](https://img.shields.io/github/actions/workflow/status/pydantic/pydantic/ci.yml?branch=main&logo=github&label=CI)](https://github.com/pydantic/pydantic/actions?query=event%3Apush+branch%3Amain+workflow%3ACI) [![Coverage](https://coverage-badge.samuelcolvin.workers.dev/pydantic/pydantic.svg)](https://github.com/pydantic/pydantic/actions?query=event%3Apush+branch%3Amain+workflow%3ACI)<br> [![pypi](https://img.shields.io/pypi/v/pydantic.svg)](https://pypi.python.org/pypi/pydantic) [![CondaForge](https://img.shields.io/conda/v/conda-forge/pydantic.svg)](https://anaconda.org/conda-forge/pydantic) [![downloads](https://static.pepy.tech/badge/pydantic/month)](https://pepy.tech/project/pydantic)<br> [![license](https://img.shields.io/github/license/pydantic/pydantic.svg)](https://github.com/pydantic/pydantic/blob/main/LICENSE) [![llms.txt](https://img.shields.io/badge/llms.txt-green)](https://docs.pydantic.dev/latest/llms.txt) {{ version }}. Pydantic is the most widely used data validation library for Python. Fast and extensible, Pydantic plays nicely with your linters/IDE/brain. Define how data should be in pure, canonical Python 3.10+; validate it with Pydantic. !!! logfire "Monitor Pydantic with Pydantic Logfire :fire:" **[Pydantic Logfire](https://pydantic.dev/logfire)** is a production-grade observability platform for AI and general applications. See LLM interactions, agent behavior, API requests, and database queries in one unified trace. With SDKs for Python, JavaScript/TypeScript, and Rust, Logfire works with all OpenTelemetry-compatible languages. Logfire integrates with many popular Python libraries including FastAPI, OpenAI and Pydantic itself, so you can use Logfire to monitor Pydantic validations and understand why some inputs fail validation: ```python {title="Monitoring Pydantic with Logfire" test="skip"} from datetime import datetime import logfire from pydantic import BaseModel logfire.configure() logfire.instrument_pydantic() # (1)! class Delivery(BaseModel): timestamp: datetime dimensions: tuple[int, int] # this will record details of a successful validation to logfire m = Delivery(timestamp='2020-01-02T03:04:05Z', dimensions=['10', '20']) print(repr(m.timestamp)) #> datetime.datetime(2020, 1, 2, 3, 4, 5, tzinfo=TzInfo(UTC)) print(m.dimensions) #> (10, 20) Delivery(timestamp='2020-01-02T03:04:05Z', dimensions=['10']) # (2)! ``` 1. Set logfire record all both successful and failed validations, use `record='failure'` to only record failed validations, [learn more](https://logfire.pydantic.dev/docs/integrations/pydantic/). 2. This will raise a `ValidationError` since there are too few `dimensions`, details of the input data and validation errors will be recorded in Logfire. Would give you a view like this in the Logfire platform: [![Logfire Pydantic Integration](img/logfire-pydantic-integration.png)](https://logfire.pydantic.dev/docs/guides/web-ui/live/) This is just a toy example, but hopefully makes clear the potential value of instrumenting a more complex application. **[Learn more about Pydantic Logfire](https://logfire.pydantic.dev/docs/)** **Sign up for our newsletter, *The Pydantic Stack*, with updates & tutorials on Pydantic, Logfire, and Pydantic AI:** <form method="POST" action="https://eu.customerioforms.com/forms/submit_action?site_id=53d2086c3c4214eaecaa&form_id=14b22611745b458&success_url=https://docs.pydantic.dev/" class="md-typeset" style="display: flex; align-items: center; gap: 0.5rem; max-width: 100%;"> <input type="email" id="email_input" name="email" class="md-input md-input--stretch" style="flex: 1; background: var(--md-default-bg-color); color: var(--md-default-fg-color);" required placeholder="Email" data-1p-ignore data-lpignore=…

Languages
Python: 5971771, Rust: 1190943, Makefile: 9795, JavaScript: 6588, HTML: 2474, Shell: 2167

Issues
#13113: built-in error message localization via model_config (inheritable) ### Initial Checks - [x] I have searched Google & GitHub for similar requests and couldn't find anything - [x] I have read and followed [the docs](https://docs.pydantic.dev) and still think this feature is missing ### Description Pydantic validation error messages are always in English. For any non-English API this forces... #13112: Support `AliasPath` with an integer first segment to index top-level list inputs ### Initial Checks - [X] I have searched Google & GitHub for similar requests and couldn't find anything - [X] I have read and followed [the docs](https://docs.pydantic.dev) and still think this feature is missing ### Description `AliasPath` already supports integer indices after a string dict-key (e.g. `Alia... #13111: Bump cairosvg from 2.7.1 to 2.9.0 Bumps [cairosvg](https://github.com/Kozea/CairoSVG) from 2.7.1 to 2.9.0. <details> <summary>Release notes</summary> <p><em>Sourced from <a href="https://github.com/Kozea/CairoSVG/releases">cairosvg's releases</a>.</em></p> <blockquote> <h2>2.9.0</h2> <p><strong>WARNING:</strong> this is a security update.</p> <p>Using a lot of recursively nested use tags... #13110: Bump pytest from 8.3.5 to 9.0.3 Bumps [pytest](https://github.com/pytest-dev/pytest) from 8.3.5 to 9.0.3. <details> <summary>Release notes</summary> <p><em>Sourced from <a href="https://github.com/pytest-dev/pytest/releases">pytest's releases</a>.</em></p> <blockquote> <h2>9.0.3</h2> <h1>pytest 9.0.3 (2026-04-07)</h1> <h2>Bug fixes</h2> <ul> <li> <p><a href="https://redirect.github.com/py... #13105: Bump python-dotenv from 1.0.1 to 1.2.2 Bumps [python-dotenv](https://github.com/theskumar/python-dotenv) from 1.0.1 to 1.2.2. <details> <summary>Release notes</summary> <p><em>Sourced from <a href="https://github.com/theskumar/python-dotenv/releases">python-dotenv's releases</a>.</em></p> <blockquote> <h2>v1.2.2</h2> <h3>Added</h3> <ul> <li>Support for Python 3.14, including the free-thre... #13093: fix: consolidate WrapSerializer warnings into a single UserWarning ## Summary Fixes #12995 When a model has a field annotated with `WrapSerializer` **and** other fields with unexpected types during `model_dump()`, two separate `UserWarning`s were emitted instead of one consolidated warning. ### Root cause `SerializationCallable.__call__()` (the inner handler passed to user-supplied wrap f... #13091: Fix RootModel constructor typing in the mypy plugin ## Change Summary This PR fixes the `arg-type` false positive from #12978. With the default mypy plugin settings, `BaseModel` constructors keep accepting coercible inputs because the plugin synthesizes an untyped `__init__`. `RootModel` constructors were bypassing that path: `_RootModelMetaclass` still kept its dataclass-transform behavi... #13090: Fix `Decimal` serialization JSON schema pattern to accept scientific notation ## Change Summary The serialization-mode JSON schema regex for `Decimal` fields (introduced in #11987) rejects values that `pydantic-core` itself emits. `str(Decimal)` returns scientific notation for small/large magnitudes — `Decimal('0.0000001')` becomes `'1E-7'` — but the pattern `^(?!^[-+.]*$)[+-]?0*\d*\.?\d*... #13089: Decimal JSON schema pattern rejects pydantic's own scientific notation serialization output (v2.12 regression) ### Initial Checks - [x] I confirm that I'm using Pydantic V2 ### Description **`model_json_schema(mode="serialization")` pattern for `Decimal` breaks on scientific notation** The serialization schema for `Decimal` fields generates a regex that rejects values that `model_dump_jso... #13088: fix: include runtime extra fields in model_dump() output (#12937) ## Summary Fixes #12937. When `model_validate(..., extra='allow')` is called on a model whose class-level config is **not** `extra='allow'`, pydantic-core correctly stores the extra fields in `__pydantic_extra__`. However, the serializer is built from the class schema (which has `extra_fields_behavior='forbid'` or `'ignore'... #13087: Fix model_copy(deep=True, update=...) failing on non-deepcopyable fields ## Summary - `model_copy(deep=True, update={...})` no longer deepcopies fields that are going to be replaced by `update`. - Fixes a crash when such fields contain objects that cannot be deepcopied (native C extensions, file handles, GPU tensors, etc.). - Preserves shared references between fields by passing a single... #13085: Incomplete generic recursive models in Pydantic 2.13 From https://github.com/ome-zarr-models/ome-zarr-models-py/issues/417: ```python # module2.py from typing import Generic, TypeVar, Union from pydantic import BaseModel TBaseItem = Union["GroupSpec", "ArraySpec"] TItem = TypeVar('TItem', bound=TBaseItem) class ArraySpec(BaseModel): pass class GroupSpec(BaseModel, Generic[TItem]): members... #13083: fix: skip deep-copying fields in model_copy when replaced by update ## Summary When `model_copy(deep=True, update=...)` is called, the current implementation deepcopies the **entire** model first, then overwrites fields from `update`. This causes two problems: 1. **Wasteful performance**: fields that will be replaced are deep-copied for nothing 2. **Fails on non-copyable fields**: if a fi... #13077: `model_copy(deep=True, update=...)` unnecessarily deepcopies fields that will be replaced by `update` ### Initial Checks - [x] I have searched Google & GitHub for similar requests and couldn't find anything - [x] I have read and followed [the docs](https://docs.pydantic.dev) and still think this feature is missing ### Description When calling `model_copy(deep=True, update={...})`, the cur... #13075: Support Json Pointers (RFC 6901) in Serialization ### Initial Checks - [x] I have searched Google & GitHub for similar requests and couldn't find anything - [x] I have read and followed [the docs](https://docs.pydantic.dev) and still think this feature is missing ### Description [RFC 6901](https://datatracker.ietf.org/doc/html/rfc6901) specifies a syntax for the use of json pointers. For... #13073: Versioned intersphinx mappings disappearing intersphinx mappings for old pydantic versions have been disappearing, despite the html docs still being available - at some point between 2026-04-09T06:39:14Z and 2026-04-09T09:15:52Z, https://docs.pydantic.dev/2.9/objects.inv started returning a 404. the docs are still up at https://pydantic.dev/docs/validation/2.9/get-started/ - at some point... #13071: Pydantic 2.13.0: Missing tags for pydantic-core releases - unable to upgrade downstream package ### Initial Checks - [x] I confirm that I'm using Pydantic V2 ### Description Hi! 👋 I'm packaging this project for Arch Linux (together with @christian-heusel). With the release of pydantic 2.13.0 we noticed, that the [pydantic-core](https://github.com/pydantic/pydantic-core) repository is now... #13033: docs: add docstrings to undocumented _Pipeline methods in experimental/pipeline.py <!-- Thank you for your contribution! --> <!-- Unless your change is trivial, please create an issue to discuss the change before creating a PR --> ## Change Summary Add Google-style docstrings to 12 methods in `_Pipeline` (in `pydantic/experimental/pipeline.py`) that previously had no inline documentation:... #13027: Fix field info not being inherited from model parent when non-model parent has same attribute <!-- Thank you for your contribution! --> <!-- Unless your change is trivial, please create an issue to discuss the change before creating a PR --> ## Change Summary <!-- Please give a short summary of the changes. --> Skip the `getattr` value in `collect_model_fields` when it comes from a non-mo... #13024: `__pydantic_extra__` ignored if `extra = 'forbid'` at model level, overridden at runtime ### Initial Checks - [x] I confirm that I'm using Pydantic V2 ### Description After #12233 it is possible to pass `extra='allow'` at runtime to temporarily override `extra` setting. However, if this is done, the `__pydantic_extra__` type hint on the model (if present) is ignored. ### Example Code ```P...

Commits
fcb5da3087df51b5dca89e8120850e5a6bdcf960: Bump libc from 0.2.155 to 0.2.185 (#13109) 156dc0fa59edd90df311a84f13b6ce0911da6f2a: Make validation `Extra` immutable, like with serialization (#13081) 07724d08a90d01cdd6b38235eabd158cb63491bb: Fix Clippy 0.1.95 warnings (#13108) 749aa690f24b4867e4b21793bab68f37f0d28a25: Set version post v2.13 release (#13098) 5bc4d9cccc3d9a703a06319dd1a3452c6bd4a41d: Handle `AttributeError` subclasses with `from_attributes` (#13096) a6bf50b721c2dd1ed609c8bb402076e8ec0c43f3: Fix `ValidationInfo.field_name` missing with `model_validate_json()` (#13084) b7e81cfc9f3ebc7d42a0ee5c85bf28db181a38f7: Fix `ValidationInfo.data` missing with `model_validate_json()` (#13079) Co-authored-by: Victorien <65306057+Viicos@users.noreply.github.com> 71f0c4b8fc28d037ba034990b468b5dfa5a46de9: Bump pillow from 10.4.0 to 12.2.0 (#13080) Signed-off-by: dependabot[bot] <support@github.com> Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com> b36eaeb4e5eea176b5d638fce099c006564d02ad: Drop support for Python 3.9 (#13070) 895d8554ffdf65231287eb3193aed4b1e3ae9f72: Accept `None` in `MultiHostUrl.build()`'s `hosts` parameter (#13068) Co-authored-by: Arvind Saripalli <arvind@haventax.com>

Repository signals
Pages URL: none GitHub Actions workflows: 13 Recent releases: v2.13.3, v2.13.2, v2.13.1, v2.13.0, v2.13.0b3 Language composition: Python=83.1%, Rust=16.6%, Makefile=0.1%, JavaScript=0.1%, HTML=0.0% Root dirs: tests, docs_dir

Architecture overview
This repository implements Pydantic, a data validation library that uses Python type hints, primarily via its BaseModel. The `tests` directory validates the core logic, while `docs_dir` provides user documentation. Pydantic V2, a ground-up rewrite, also includes V1 for incremental upgrades.
```


## URL 5: https://github.com/tiangolo/typer

### SUMMARY
```yaml
mini_title: tiangolo/typer
brief_summary: Typer is a Python library for building Command Line Interface (CLI)
  applications, designed as the "FastAPI of CLIs". It leverages standard Python type
  hints for defining CLI arguments and options, building on top of the Click framework.
  This approach enhances developer experience with editor autocompletion and type
  checking, abstracting away Click's complexities while providing robust CLI generati
tags:
- python
- cli-tool
- pydantic
- typer
- cli
- command-line-interface
- type-hints
- click
- fastapi
- developer-tools
detailed_summary:
- heading: Overview
  bullets:
  - Typer is a Python library designed for building Command Line Interface (CLI) applications,
    sharing a design philosophy with FastAPI.
  - It emphasizes using standard Python type hints for defining CLI arguments and
    options, aiming to improve developer experience with editor autocompletion and
    type checks.
  - The library includes a `typer` command-line tool capable of running Python scripts
    as CLIs, even without explicit library usage.
  - The project is actively maintained, with recent releases like 0.24.2, and is licensed
    under the MIT license.
  - A security policy is in place, directing vulnerability reports to `security@tiangolo.com`.
  sub_sections: {}
- heading: Architecture / Modules
  bullets:
  - '`typer` is built as a layer on top of `Click`.'
  - Required dependencies include `Click`, `rich` (for formatted error output), and
    `shellingham` (for shell detection in completion installation).
  - The use of `rich` can be disabled by setting the environment variable `TYPER_USE_RICH`
    to `False` or `0`.
  - The `typer-slim` package was deprecated in version 0.22.0 and now installs the
    full package.
  - Recent development includes vendoring parts of Click to improve test coverage
    (#1690).
  sub_sections: {}
- heading: Public API / Interfaces
  bullets:
  - 'CLI parameters are defined as function parameters using type hints, e.g., `name:
    str`.'
  - Boolean parameters automatically generate corresponding `--option` and `--no-option`
    flags.
  - 'The library supports two main patterns: `typer.run(my_function)` for single-command
    applications.'
  - For multi-command applications with subcommands, users instantiate `app = typer.Typer()`
    and use the `@app.command()` decorator.
  - Command function signatures now support `*args` and `**kwargs` (#1654).
  sub_sections: {}
- heading: Operational Guidance
  bullets:
  - The library is installed using `pip install typer`.
  - The `typer` command-line tool can run Python scripts as CLIs.
  - Shell completion is automatically generated for Bash, Zsh, Fish, and PowerShell.
  - The use of `rich` for formatted output can be disabled by setting the `TYPER_USE_RICH`
    environment variable to `False` or `0`.
  - Vulnerability reports should be directed to `security@tiangolo.com`.
  sub_sections: {}
- heading: Notable Issues & Fixes
  bullets:
  - 'Fixed autocompletion for PowerShell command hints (#1685, closing #266).'
  - Fixed autocompletion for `click.Path` arguments within a `TyperGroup` (#1673).
  - 'A bug preventing `result_callback` from triggering in single-command applications
    was fixed (#1631, closing #445).'
  - 'Improved error handling for commands with multiple variadic arguments (e.g.,
    multiple `List[...]` parameters), which previously raised an opaque `TypeError`
    from Click (#1555, closing #260).'
  - Resolved an `AttributeError` when using `Annotated[..., typer.Option(None)]` (#1564).
  - Fixed an issue where enum option values were lost when a callback was present
    (#1554).
  sub_sections: {}
metadata:
  source_type: github
  url: https://github.com/tiangolo/typer
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 3 extra doc(s) fetched
  total_tokens_used: 21973
  gemini_pro_tokens: 18779
  gemini_flash_tokens: 3194
  total_latency_ms: 74042
  cod_iterations_used: 2
  self_check_missing_count: 6
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: tiangolo/typer
    architecture_overview: Typer is a Python library for building Command Line Interface
      (CLI) applications, designed as the "FastAPI of CLIs". It leverages standard
      Python type hints for defining CLI arguments and options, building on top of
      the Click framework. This approach enhances developer experience with editor
      autocompletion and type checking, abstracting away Click's complexities while
      providing robust CLI generation capabilities. It supports both single-command
      applications via typer.run() and multi-command appl
    brief_summary: Typer is a Python library for building Command Line Interface (CLI)
      applications, designed as the "FastAPI of CLIs". It leverages standard Python
      type hints for defining CLI arguments and options, building on top of the Click
      framework. This approach enhances developer experience with editor autocompletion
      and type checking, abstracting away Click's complexities while providing robust
      CLI generation capabilities. It supports both single-command applications via
      typer.run() and multi-command appl
    tags:
    - python
    - cli-tool
    - pydantic
    - typer
    - cli
    - command-line-interface
    - type-hints
    - click
    - fastapi
    - developer-tools
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: Overview
      bullets:
      - Typer is a Python library designed for building Command Line Interface (CLI)
        applications, sharing a design philosophy with FastAPI.
      - It emphasizes using standard Python type hints for defining CLI arguments
        and options, aiming to improve developer experience with editor autocompletion
        and type checks.
      - The library includes a `typer` command-line tool capable of running Python
        scripts as CLIs, even without explicit library usage.
      - The project is actively maintained, with recent releases like 0.24.2, and
        is licensed under the MIT license.
      - A security policy is in place, directing vulnerability reports to `security@tiangolo.com`.
      sub_sections: {}
      module_or_feature: Overview
      main_stack:
      - Python
      - Shell
      - Dockerfile
      - pydantic
      - click
      - rich
      - shellingham
      public_interfaces: []
      usability_signals:
      - '`pip install typer`'
      - Shell completion for Bash, Zsh, Fish, and PowerShell is automatically generated.
    - heading: Architecture / Modules
      bullets:
      - '`typer` is built as a layer on top of `Click`.'
      - Required dependencies include `Click`, `rich` (for formatted error output),
        and `shellingham` (for shell detection in completion installation).
      - The use of `rich` can be disabled by setting the environment variable `TYPER_USE_RICH`
        to `False` or `0`.
      - The `typer-slim` package was deprecated in version 0.22.0 and now installs
        the full package.
      - Recent development includes vendoring parts of Click to improve test coverage
        (#1690).
      sub_sections: {}
      module_or_feature: Architecture / Modules
      main_stack:
      - Click
      - rich
      - shellingham
      public_interfaces: []
      usability_signals: []
    - heading: Public API / Interfaces
      bullets:
      - 'CLI parameters are defined as function parameters using type hints, e.g.,
        `name: str`.'
      - Boolean parameters automatically generate corresponding `--option` and `--no-option`
        flags.
      - 'The library supports two main patterns: `typer.run(my_function)` for single-command
        applications.'
      - For multi-command applications with subcommands, users instantiate `app =
        typer.Typer()` and use the `@app.command()` decorator.
      - Command function signatures now support `*args` and `**kwargs` (#1654).
      sub_sections: {}
      module_or_feature: Public API / Interfaces
      main_stack: []
      public_interfaces:
      - '`@app.command()`'
      - '`typer.run()`'
      - '`typer.Typer()`'
      - '`name: str`'
      - '`--option`'
      - '`--no-option`'
      - '`*args`'
      - '`**kwargs`'
      usability_signals: []
    - heading: Operational Guidance
      bullets:
      - The library is installed using `pip install typer`.
      - The `typer` command-line tool can run Python scripts as CLIs.
      - Shell completion is automatically generated for Bash, Zsh, Fish, and PowerShell.
      - The use of `rich` for formatted output can be disabled by setting the `TYPER_USE_RICH`
        environment variable to `False` or `0`.
      - Vulnerability reports should be directed to `security@tiangolo.com`.
      sub_sections: {}
      module_or_feature: Operational Guidance
      main_stack: []
      public_interfaces: []
      usability_signals:
      - '`pip install typer`'
      - '`TYPER_USE_RICH=False`'
      - '`TYPER_USE_RICH=0`'
      - '`security@tiangolo.com`'
    - heading: Notable Issues & Fixes
      bullets:
      - 'Fixed autocompletion for PowerShell command hints (#1685, closing #266).'
      - Fixed autocompletion for `click.Path` arguments within a `TyperGroup` (#1673).
      - 'A bug preventing `result_callback` from triggering in single-command applications
        was fixed (#1631, closing #445).'
      - 'Improved error handling for commands with multiple variadic arguments (e.g.,
        multiple `List[...]` parameters), which previously raised an opaque `TypeError`
        from Click (#1555, closing #260).'
      - Resolved an `AttributeError` when using `Annotated[..., typer.Option(None)]`
        (#1564).
      - Fixed an issue where enum option values were lost when a callback was present
        (#1554).
      sub_sections: {}
      module_or_feature: Notable Issues & Fixes
      main_stack: []
      public_interfaces: []
      usability_signals: []
    _github_archetype:
      archetype: cli_tool
      confidence: 0.724
      reasons:
      - cli_tokens=6
      - topics_cli
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Repository
fastapi/typer Typer, build great CLIs. Easy to code. Based on Python type hints. Language: Python Topics: cli, click, python, python3, shell, terminal, typehints, typer

README
<p align="center"> <a href="https://typer.tiangolo.com"><img src="https://typer.tiangolo.com/img/logo-margin/logo-margin-vector.svg#only-light" alt="Typer"></a> </p> <p align="center"> <em>Typer, build great CLIs. Easy to code. Based on Python type hints.</em> </p> <p align="center"> <a href="https://github.com/fastapi/typer/actions?query=workflow%3ATest+event%3Apush+branch%3Amaster" target="_blank"> <img src="https://github.com/fastapi/typer/actions/workflows/test.yml/badge.svg?event=push&branch=master" alt="Test"> </a> <a href="https://github.com/fastapi/typer/actions?query=workflow%3APublish" target="_blank"> <img src="https://github.com/fastapi/typer/workflows/Publish/badge.svg" alt="Publish"> </a> <a href="https://coverage-badge.samuelcolvin.workers.dev/redirect/fastapi/typer" target="_blank"> <img src="https://coverage-badge.samuelcolvin.workers.dev/fastapi/typer.svg" alt="Coverage"> <a href="https://pypi.org/project/typer" target="_blank"> <img src="https://img.shields.io/pypi/v/typer?color=%2334D058&label=pypi%20package" alt="Package version"> </a> </p> --- **Documentation**: <a href="https://typer.tiangolo.com" target="_blank">https://typer.tiangolo.com</a> **Source Code**: <a href="https://github.com/fastapi/typer" target="_blank">https://github.com/fastapi/typer</a> --- Typer is a library for building <abbr title="command line interface, programs executed from a terminal">CLI</abbr> applications that users will **love using** and developers will **love creating**. Based on Python type hints. It's also a command line tool to run scripts, automatically converting them to CLI applications. The key features are: * **Intuitive to write**: Great editor support. <abbr title="also known as auto-complete, autocompletion, IntelliSense">Completion</abbr> everywhere. Less time debugging. Designed to be easy to use and learn. Less time reading docs. * **Easy to use**: It's easy to use for the final users. Automatic help, and automatic completion for all shells. * **Short**: Minimize code duplication. Multiple features from each parameter declaration. Fewer bugs. * **Start simple**: The simplest example adds only 2 lines of code to your app: **1 import, 1 function call**. * **Grow large**: Grow in complexity as much as you want, create arbitrarily complex trees of commands and groups of subcommands, with options and arguments. * **Run scripts**: Typer includes a `typer` command/program that you can use to run scripts, automatically converting them to CLIs, even if they don't use Typer internally. ## FastAPI of CLIs **Typer** is <a href="https://fastapi.tiangolo.com" class="external-link" target="_blank">FastAPI</a>'s little sibling, it's the FastAPI of CLIs. ## Installation Create and activate a <a href="https://typer.tiangolo.com/virtual-environments/" class="external-link" target="_blank">virtual environment</a> and then install **Typer**: <div class="termy"> ```console $ pip install typer ---> 100% Successfully installed typer rich shellingham ``` </div> ## Example ### The absolute minimum * Create a file `main.py` with: ```Python def main(name: str): print(f"Hello {name}") ``` This script doesn't even use Typer internally. But you can use the `typer` command to run it as a CLI application. ### Run it Run your application with the `typer` command: <div class="termy"> ```console // Run your application $ typer main.py run // You get a nice error, you are missing NAME Usage: typer [PATH_OR_MODULE] run [OPTIONS] NAME Try 'typer [PATH_OR_MODULE] run --help' for help. ╭─ Error ───────────────────────────────────────────╮ │ Missing argument 'NAME'. │ ╰───────────────────────────────────────────────────╯ // You get a --help for free $ typer main.py run --help Usage: typer [PATH_OR_MODULE] run [OPTIONS] NAME Run the provided Typer app. ╭─ Arguments ───────────────────────────────────────╮ │ * name TEXT [default: None] [required] | ╰───────────────────────────────────────────────────╯ ╭─ Options ─────────────────────────────────────────╮ │ --help Show this message and exit. │ ╰───────────────────────────────────────────────────╯ // Now pass the NAME argument $ typer main.py run Camila Hello Camila // It works! 🎉 ``` </div> This is the simplest use case, not even using Typer internally, but it can already be quite useful for simple scripts. **Note**: auto-completion works when you create a Python package and run it with `--install-completion` or when you use the `typer` command. ## Use Typer in your code Now let's start using Typer in your own code, update `main.py` with: ```Python import typer def main(name: str): print(f"Hello {name}") if __name__ == "__main__": typer.run(main) ``` Now you could run it with Python directly: <div class="termy"> ```console // Run your application $ python main.py // You get a nice error, you are missing NAME Usage: main.py [OPTIONS] NAME Try 'main.py --help' for help. ╭─ Error ───────────────────────────────────────────╮ │ Missing argument 'NAME'. │ ╰───────────────────────────────────────────────────╯ // You get a --help for free $ python main.py --help Usage: main.py [OPTIONS] NAME ╭─ Arguments ───────────────────────────────────────╮ │ * name TEXT [default: None] [required] | ╰───────────────────────────────────────────────────╯ ╭─ Options ─────────────────────────────────────────╮ │ --help Show this message and exit. │ ╰───────────────────────────────────────────────────╯ // Now pass the NAME argument $ python main.py Camila Hello Camila // It works! 🎉 ``` </div> **Note**: you can also call this same script with the `typer` command, but you don't need to. ## Example upgrade This was the simplest example possible. Now let's see one a bit more complex. ### An example with two subcommands Modify the file `main.py`. Create a `typer.Typer()` app, and create two subcommands with their parameters. ```Python hl_lines="3 6 11 20" import typer app = typer.Typer() @app.command() def hello(name: str): print(f"Hello {name}") @app.command() def goodbye(name: str, formal: bool = False): if formal: print(f"Goodbye Ms. {name}. Have a good day.") else: print(f"Bye {name}!") if __name__ == "__main__": app() ``` And that will: * Explicitly create a `typer.Typer` app. * The previous `typer.run` actually creates one implicitly for you. * Add two subcommands with `@app.command()`. * Execute the `app()` itself, as if it was a function (instead of `typer.run`). ### Run the upgraded example Check the new help: <div class="termy"> ```console $ python main.py --help Usage: main.py [OPTIONS] COMMAND [ARGS]... ╭─ Options ─────────────────────────────────────────╮ │ --install-completion Install completion │ │ for the current │ │ shell. │ │ --show-completion Show completion for │ │ the current shell, │ │ to copy it or │ │ customize the │ │ installation. │ │ --help Show this message │ │ and exit. │ ╰───────────────────────────────────────────────────╯ ╭─ Commands ────────────────────────────────────────╮ │ goodbye │ │ hello │ ╰───────────────────────────────────────────────────╯ // When you create a package you get ✨ auto-completion ✨ for free, installed with --install-completion // You have 2 subcommands (the 2 functions): goodbye and hello ``` </div> Now check the help for the `hello` command: <div class="termy"> ```console $ python main.py hello --help Usage: main.py hello [OPTIONS] NAME ╭─ Arguments ───────────────────────────────────────╮ │ * name TEXT [default: None] [required] │ ╰───────────────────────────────────────────────────╯ ╭─ Options ─────────────────────────────────────────╮ │ --help Show this message and exit. │ ╰───────────────────────────────────────────────────╯ ``` </div> And now check the help for the `goodbye` command: <div class="termy"> ```console $ python main.py goodbye --help Usage: main.py goodbye [OPTIONS] NAME ╭─ Arguments ───────────────────────────────────────╮ │ * name TEXT [default: None] [required] │ ╰───────────────────────────────────────────────────╯ ╭─ Options ─────────────────────────────────────────╮ │ --formal --no-formal [default: no-formal] │ │ --help Show this message │ │ and exit. │ ╰───────────────────────────────────────────────────╯ // Automatic --formal and --no-formal for the bool option 🎉 ``` </div> Now you can try out the new command line application: <div class="termy"> ```console // Use it with the hello command $ python main.py hello Camila Hello Camila // And with the goodbye command $ python main.py goodbye Camila Bye Camila! // And with --formal $ python main.py goodbye --formal Camila Goodbye Ms. Camila. Have a good day. ``` </div> **Note**: If your app only has one command, by default the command name is **omitted** in usage: `python main.py Camila`. However, when there are multiple commands, you must **explicitly include the command name**: `python main.py hello Camila`. See [One or Multiple Commands](https://typer.tiangolo.com/tutorial/commands/one-or-multiple/) for more details. ### Recap In summary, you declare **once** the types of parameters (*CLI arguments* and *CLI options*) as function parameters. You do that with standard modern Python types. You don't have to learn a new syntax, the methods or classes of a specific library, etc. Just standard **Python**. For example, for an `int`: ```Python total: int ``` or for a `bool` flag: ```Python force: bool ``` And similarly for **files**, **paths**, **enums** (choices), etc. And there are tools to create **groups of subcommands**, add metadata, extra **validation**, etc. **You get**: great editor support, including **completion** and **type checks** everywhere. **Your users get**: automatic **`--help`**, **auto-completion** in their terminal (Bash, Zsh, Fish, PowerShell) when they install your package or when using the `typer` command. For a more complete example including more features, see the <a href="https://typer.tiangolo.com/tutorial/">Tutorial - User Guide</a>. ## Dependencies **Typer** stands on the shoulders of giants. It has three required dependencies: * <a href="https://click.palletsprojects.com/" class="external-link" target="_blank">Click</a>: a popular tool for building CLIs in Python. Typer is based on it. * <a href="https://rich.readthedocs.io/en/stable/index.html" class="external-link" target="_blank"><code>rich</code></a>: to show nicely formatted errors automatically. * <a href="https://github.com/sarugaku/shellingham" class="external-link" target="_blank"><code>shellingham</code></a>: to automatically detect the current shell when installing completion. ### `typer-slim` There used to be a slimmed-down version of Typer called `typer-slim`, which didn't include the dependencies `rich` and `shellingham`, nor the `typer` command. However, since version 0.22.0, we have stopped supporting this, and `typer-slim` now simply installs (all of) Typer. If you want to disable Rich globally, you can set an environmental variable `TYPER_USE_RICH` to `False` or `0`. ## License This project is licensed under the terms of the MIT license.

Docs
### CONTRIBUTING.md Please read the [Development - Contributing](https://typer.tiangolo.com/contributing/) guidelines in the documentation site. ### SECURITY.md # Security Policy Security is very important for Typer and its community. 🔒 Learn more about it below. 👇 ## Versions The latest versions of Typer are supported. You are encouraged to [write tests](https://typer.tiangolo.com/tutorial/testing/) for your application and update your Typer version frequently after ensuring that your tests are passing. This way you will benefit from the latest features, bug fixes, and **security fixes**. ## Reporting a Vulnerability If you think you found a vulnerability, and even if you are not sure about it, please report it right away by sending an email to: security@tiangolo.com. Please try to be as explicit as possible, describing all the steps and example code to reproduce the security issue. I (the author, [@tiangolo](https://twitter.com/tiangolo)) will review it thoroughly and get back to you. ## Public Discussions Please restrain from publicly discussing a potential security vulnerability. 🙊 It's better to discuss privately and try to find a solution first, to limit the potential impact as much as possible. --- Thanks for your help! The Typer community and I thank you for that. 🙇 ### docs/index.md <style> .md-content .md-typeset h1 { display: none; } </style> <p align="center"> <a href="https://typer.tiangolo.com"><img src="https://typer.tiangolo.com/img/logo-margin/logo-margin-vector.svg#only-light" alt="Typer"></a> <!-- only-mkdocs --> <a href="https://typer.tiangolo.com"><img src="img/logo-margin/logo-margin-white-vector.svg#only-dark" alt="Typer"></a> <!-- /only-mkdocs --> </p> <p align="center"> <em>Typer, build great CLIs. Easy to code. Based on Python type hints.</em> </p> <p align="center"> <a href="https://github.com/fastapi/typer/actions?query=workflow%3ATest+event%3Apush+branch%3Amaster" target="_blank"> <img src="https://github.com/fastapi/typer/actions/workflows/test.yml/badge.svg?event=push&branch=master" alt="Test"> </a> <a href="https://github.com/fastapi/typer/actions?query=workflow%3APublish" target="_blank"> <img src="https://github.com/fastapi/typer/workflows/Publish/badge.svg" alt="Publish"> </a> <a href="https://coverage-badge.samuelcolvin.workers.dev/redirect/fastapi/typer" target="_blank"> <img src="https://coverage-badge.samuelcolvin.workers.dev/fastapi/typer.svg" alt="Coverage"> <a href="https://pypi.org/project/typer" target="_blank"> <img src="https://img.shields.io/pypi/v/typer?color=%2334D058&label=pypi%20package" alt="Package version"> </a> </p> --- **Documentation**: <a href="https://typer.tiangolo.com" target="_blank">https://typer.tiangolo.com</a> **Source Code**: <a href="https://github.com/fastapi/typer" target="_blank">https://github.com/fastapi/typer</a> --- Typer is a library for building <abbr title="command line interface, programs executed from a terminal">CLI</abbr> applications that users will **love using** and developers will **love creating**. Based on Python type hints. It's also a command line tool to run scripts, automatically converting them to CLI applications. The key features are: * **Intuitive to write**: Great editor support. <abbr title="also known as auto-complete, autocompletion, IntelliSense">Completion</abbr> everywhere. Less time debugging. Designed to be easy to use and learn. Less time reading docs. * **Easy to use**: It's easy to use for the final users. Automatic help, and automatic completion for all shells. * **Short**: Minimize code duplication. Multiple features from each parameter declaration. Fewer bugs. * **Start simple**: The simplest example adds only 2 lines of code to your app: **1 import, 1 function call**. * **Grow large**: Grow in complexity as much as you want, create arbitrarily complex trees of commands and groups of subcommands, with options and arguments. * **Run scripts**: Typer includes a `typer` command/program that you can use to run scripts, automatically converting them to CLIs, even if they don't use Typer internally. ## FastAPI of CLIs **Typer** is <a href="https://fastapi.tiangolo.com" class="external-link" target="_blank">FastAPI</a>'s little sibling, it's the FastAPI of CLIs. ## Installation Create and activate a <a href="https://typer.tiangolo.com/virtual-environments/" class="external-link" target="_blank">virtual environment</a> and then install **Typer**: <div class="termy"> ```console $ pip install typer ---> 100% Successfully installed typer rich shellingham ``` </div> ## Example ### The absolute minimum * Create a file `main.py` with: ```Python def main(name: str): print(f"Hello {name}") ``` This script doesn't even use Typer internally. But you can use the `typer` command to run it as a CLI application. ### Run it Run your application with the `typer` command: <div class="termy"> ```console // Run your application $ typer main.py run // You get a nice error, you are missing NAME Usage: typer [PATH_OR_MODULE] run [OPTIONS] NAME Try 'typer [PATH_OR_MODULE] run --help' for help. ╭─ Error ───────────────────────────────────────────╮ │ Missing argument 'NAME'. │ ╰───────────────────────────────────────────────────╯ // You get a --help for fre…

Languages
Python: 674018, Shell: 1278, Dockerfile: 895

Issues
#1714: ⬆ Bump python-dotenv from 1.2.1 to 1.2.2 Bumps [python-dotenv](https://github.com/theskumar/python-dotenv) from 1.2.1 to 1.2.2. <details> <summary>Release notes</summary> <p><em>Sourced from <a href="https://github.com/theskumar/python-dotenv/releases">python-dotenv's releases</a>.</em></p> <blockquote> <h2>v1.2.2</h2> <h3>Added</h3> <ul> <li>Support for Python 3.14, including the free-thr... #1705: 🔒️ Add zizmor and fix audit findings Changes applied: * Setup daily interval and 7 days cooldown period for Dependabot * Added `pre-commit` package ecosystem to Dependabot config * Ignored `dangerous-triggers` rule for `pull_request_target` and `workflow_run` (checked that they are used in a safe way) * Specified minimal permissions on workflow level, moved permissions to the job level * I... #1695: 🚸 Don't truncate code lines in traceback when formatted with Rich When tracebacks are formatted with Rich, code lines are currently truncated to 88 characters (or less if terminal width is less). This PR: * Makes it display full line if terminal width is large enough * Allows configuring it to wrap text instead of truncating it if terminal width is small --- **Small terminal width (before... #1690: Increase coverage Continue work from #1525, #1601 and #1680, vendoring Click. After the prep work from previous PRs, this PR contains a lot of work to finish the refactor: - Removing stuff we don't need in Typer - Writing unit tests for things we do need/document but aren't thoroughly tested in Typer's test suite - Adjusting the vendored code to adhere to Typer's code style - Adding `color... #1686: docs: fix environment variable wording ## Summary Fix wording in `docs/tutorial/exceptions.md` by changing `environmental variable` to `environment variable`. ## Related issue N/A ## Guideline alignment Single-file documentation-only change with no behavior change. ## Validation Not run; documentation-only change. #1685: fix: pwsh autocompletion not returning command hints Closes #266 ## What's the bug? `PowerShellComplete.get_completion_args()` was slicing `cwords[1:]` to skip the interpreter, but `$commandAst.ToString()` in the PowerShell template includes both the interpreter (`python`) and the prog name (`main.py`) as the first two tokens. This meant `main.py` was leaking into the args passed to Click'... #1683: Allow `click_type` and `parser` with Union type annotations Previously, any parameter annotated with a Union type (e.g. `int | str`) would unconditionally hit an assertion error. This change skips that assertion when the parameter has a custom `parser` or `click_type` specified. In those cases Typer delegates parsing entirely to the caller, making the type annotation irrelevant for type re... #1677: 📝 Add docstrings to testing module ## Summary `typer/testing.py` shipped with no docstrings on the module, the `CliRunner` class, or its `invoke` method. This PR adds all three. - **Module docstring** — brief description of the module's purpose with a link to the testing tutorial. - **`CliRunner` class docstring** — explains what it extends and why, with a short usage example that mirrors... #1673: 🐛 Fix shell completion for Path arguments when using TyperGroup Tab-completing a `click.Path` option doesn't work when the command is added via `TyperGroup.add_command()` — instead of showing files, the shell just echoes back whatever you typed and adds a space. Affects all four shells. The problem is that `complete()` in each shell class ignores `CompletionItem.type`. Click's `Path` retur... #1
```


## URL 6: https://github.com/pallets/flask

### SUMMARY
```yaml
mini_title: pallets/flask
brief_summary: Flask is a lightweight, unopinionated Python WSGI micro-framework that
  wraps Werkzeug and Jinja for web development. It avoids enforcing project structure,
  relying on an extension ecosystem. Users adopt it by instantiating the `Flask` class,
  defining routes with `@app.route()`, `@app.get`, or `@app.post` decorators, and
  running the development server via the `flask run` CLI command.
tags:
- python
- api-framework
- flask
- jinja
- pallets
- web-framework
- werkzeug
- wsgi
detailed_summary:
- heading: Overview
  bullets:
  - Flask is a popular, lightweight, unopinionated Python WSGI micro-framework from
    the Pallets organization, designed for simplicity and scalability.
  - Its unopinionated design avoids enforcing a specific project layout or third-party
    dependencies, leaving tool selection to the developer.
  - Functionality is extended through a large ecosystem of community extensions.
  - The project is mature and actively maintained, with recent releases including
    3.1.3, 3.1.2, 3.1.1, 3.1.0, and 3.0.3.
  - Its CI/CD pipeline uses 11 GitHub Actions workflows, with recent commits showing
    ongoing dependency updates, test refactoring, and build optimizations.
  - The Pallets organization accepts donations to support maintenance, and the project
    provides detailed contribution guidelines.
  sub_sections: {}
- heading: Architecture / Modules
  bullets:
  - 'Flask acts as a wrapper for two core libraries: Werkzeug, a WSGI utility library,
    and Jinja, a templating engine.'
  - Its unopinionated design means it does not enforce a specific project layout or
    require particular third-party dependencies.
  - The framework's functionality is designed to be extended through a broad ecosystem
    of community-contributed extensions.
  sub_sections: {}
- heading: Public API / Interfaces
  bullets:
  - A basic application is created by instantiating the `Flask` class.
  - The `@app.route()` decorator is used to map a URL to a view function.
  - Specific HTTP methods can be handled using decorators such as `@app.get` and `@app.post`.
  sub_sections: {}
- heading: Operational Guidance
  bullets:
  - A built-in CLI command, `flask run`, starts a development server.
  - The development server defaults to `http://127.0.0.1:5000/`.
  sub_sections: {}
- heading: Tests / Benchmarks / Examples
  bullets:
  - The repository includes `tests` and `examples` directories.
  - The `tests` directory is actively maintained, with recent commits showing test
    refactoring, such as removing Werkzeug host tests.
  sub_sections: {}
- heading: Notable Issues
  bullets:
  - '**#5918**: A planned refactoring aims to integrate `provide_automatic_options`
    into the standard routing and view dispatch system, eliminating its special-case
    handling per request. This change is dependent on Werkzeug 3.2 for its `DuplicateRuleError`
    exception.'
  - '**#5660**: A proposal suggests moving parts of the session handling code to a
    `sansio` implementation. The goal is to enable code reuse with the Quart framework,
    reducing code duplication and ensuring API consistency between the projects.'
  sub_sections: {}
metadata:
  source_type: github
  url: https://github.com/pallets/flask
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata and README fetched
  total_tokens_used: 8578
  gemini_pro_tokens: 5949
  gemini_flash_tokens: 2629
  total_latency_ms: 64937
  cod_iterations_used: 2
  self_check_missing_count: 3
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: pallets/flask
    architecture_overview: Flask is a lightweight, unopinionated Python WSGI micro-framework
      that acts as a wrapper for Werkzeug, a WSGI utility library, and Jinja, a templating
      engine. Its design emphasizes simplicity by not enforcing a specific project
      layout or third-party dependencies, allowing developers to choose their own
      tools. Functionality is extended through a broad ecosystem of community extensions,
      maintaining its core as a minimal foundation.
    brief_summary: Flask is a lightweight, unopinionated Python WSGI micro-framework
      that wraps Werkzeug and Jinja for web development. It avoids enforcing project
      structure, relying on an extension ecosystem. Users adopt it by instantiating
      the `Flask` class, defining routes with `@app.route()`, `@app.get`, or `@app.post`
      decorators, and running the development server via the `flask run` CLI command.
    tags:
    - python
    - api-framework
    - flask
    - jinja
    - pallets
    - web-framework
    - werkzeug
    - wsgi
    benchmarks_tests_examples:
    - The `tests` directory contains tests demonstrating framework functionality,
      with ongoing refactoring efforts (e.g., removing Werkzeug host tests).
    - The `examples` directory provides usage examples for the framework.
    detailed_summary:
    - heading: Overview
      bullets:
      - Flask is a popular, lightweight, unopinionated Python WSGI micro-framework
        from the Pallets organization, designed for simplicity and scalability.
      - Its unopinionated design avoids enforcing a specific project layout or third-party
        dependencies, leaving tool selection to the developer.
      - Functionality is extended through a large ecosystem of community extensions.
      - The project is mature and actively maintained, with recent releases including
        3.1.3, 3.1.2, 3.1.1, 3.1.0, and 3.0.3.
      - Its CI/CD pipeline uses 11 GitHub Actions workflows, with recent commits showing
        ongoing dependency updates, test refactoring, and build optimizations.
      - The Pallets organization accepts donations to support maintenance, and the
        project provides detailed contribution guidelines.
      sub_sections: {}
      module_or_feature: Web Framework
      main_stack:
      - Python
      - Werkzeug
      - Jinja
      public_interfaces: []
      usability_signals: []
    - heading: Architecture / Modules
      bullets:
      - 'Flask acts as a wrapper for two core libraries: Werkzeug, a WSGI utility
        library, and Jinja, a templating engine.'
      - Its unopinionated design means it does not enforce a specific project layout
        or require particular third-party dependencies.
      - The framework's functionality is designed to be extended through a broad ecosystem
        of community-contributed extensions.
      sub_sections: {}
      module_or_feature: Architecture / Modules
      main_stack:
      - Werkzeug
      - Jinja
      public_interfaces: []
      usability_signals: []
    - heading: Public API / Interfaces
      bullets:
      - A basic application is created by instantiating the `Flask` class.
      - The `@app.route()` decorator is used to map a URL to a view function.
      - Specific HTTP methods can be handled using decorators such as `@app.get` and
        `@app.post`.
      sub_sections: {}
      module_or_feature: Public API / Interfaces
      main_stack: []
      public_interfaces:
      - Flask
      - '@app.route'
      - '@app.get'
      - '@app.post'
      usability_signals: []
    - heading: Operational Guidance
      bullets:
      - A built-in CLI command, `flask run`, starts a development server.
      - The development server defaults to `http://127.0.0.1:5000/`.
      sub_sections: {}
      module_or_feature: Operational Guidance
      main_stack: []
      public_interfaces: []
      usability_signals:
      - flask run
    - heading: Tests / Benchmarks / Examples
      bullets:
      - The repository includes `tests` and `examples` directories.
      - The `tests` directory is actively maintained, with recent commits showing
        test refactoring, such as removing Werkzeug host tests.
      sub_sections: {}
      module_or_feature: Tests / Benchmarks / Examples
      main_stack: []
      public_interfaces: []
      usability_signals: []
    - heading: Notable Issues
      bullets:
      - '**#5918**: A planned refactoring aims to integrate `provide_automatic_options`
        into the standard routing and view dispatch system, eliminating its special-case
        handling per request. This change is dependent on Werkzeug 3.2 for its `DuplicateRuleError`
        exception.'
      - '**#5660**: A proposal suggests moving parts of the session handling code
        to a `sansio` implementation. The goal is to enable code reuse with the Quart
        framework, reducing code duplication and ensuring API consistency between
        the projects.'
      sub_sections: {}
      module_or_feature: Notable Issues
      main_stack: []
      public_interfaces: []
      usability_signals: []
    _github_archetype:
      archetype: framework_api
      confidence: 0.667
      reasons:
      - framework_tokens=3
      - topics_framework
  is_schema_fallback: false

```

### ATOMIC FACTS
```yaml
[]

```

### SOURCE
```
Repository
pallets/flask The Python micro framework for building web applications. Language: Python Topics: flask, jinja, pallets, python, web-framework, werkzeug, wsgi

README
<div align="center"><img src="https://raw.githubusercontent.com/pallets/flask/refs/heads/stable/docs/_static/flask-name.svg" alt="" height="150"></div> # Flask Flask is a lightweight [WSGI] web application framework. It is designed to make getting started quick and easy, with the ability to scale up to complex applications. It began as a simple wrapper around [Werkzeug] and [Jinja], and has become one of the most popular Python web application frameworks. Flask offers suggestions, but doesn't enforce any dependencies or project layout. It is up to the developer to choose the tools and libraries they want to use. There are many extensions provided by the community that make adding new functionality easy. [WSGI]: https://wsgi.readthedocs.io/ [Werkzeug]: https://werkzeug.palletsprojects.com/ [Jinja]: https://jinja.palletsprojects.com/ ## A Simple Example ```python # save this as app.py from flask import Flask app = Flask(__name__) @app.route("/") def hello(): return "Hello, World!" ``` ``` $ flask run * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit) ``` ## Donate The Pallets organization develops and supports Flask and the libraries it uses. In order to grow the community of contributors and users, and allow the maintainers to devote more time to the projects, [please donate today]. [please donate today]: https://palletsprojects.com/donate ## Contributing See our [detailed contributing documentation][contrib] for many ways to contribute, including reporting issues, requesting features, asking or answering questions, and making PRs. [contrib]: https://palletsprojects.com/contributing/

Languages
Python: 566541, HTML: 405, Shell: 193, CSS: 18

Issues
#5918: automatic options as separate route Implement `provide_automatic_options` as a regular part of the routing and view dispatch, rather than as a special check on every request. Can be updated to do `except DuplicateRuleError` instead of `Exception` once Werkzeug 3.2 is out. Relies on the duplicate check to not add the internal route multiple times, for example if `@app.get` and `@app.post` r... #5665: Workflow <!-- Before opening a PR, open a ticket describing the issue or feature the PR will address. An issue is not required for fixing typos in documentation, or other simple non-code changes. Replace this comment with a description of the change. Describe how it addresses the linked ticket. --> <!-- Link to relevant issues or previous PRs, one per line. Use "fixes" to automatically clo... #5660: Move parts of the session code to sansio This will allow it to be used in Quart, thereby reducing duplication, and ensuring the APIs match. <!-- Before opening a PR, open a ticket describing the issue or feature the PR will address. An issue is not required for fixing typos in documentation, or other simple non-code changes. Replace this comment with a description of the change. Describe h...

Commits
2ac89889f4cc330eabd50f295dcef02828522c69: Merge branch 'stable' 689362089edd09b6d68f7cfe99075e1345e0fede: fix typo 258d68b6ff5e2244386540f48b48bab90d6ab827: Merge branch 'stable' a31e6b73469cb2bf7eb8f70b5ff21f710fd2e23c: remove werkzeug host tests e4e4bf6543ac1f132afddb1ffd0bf02bea4c93f7: Merge branch 'stable' b21425d6df207fec0c47e9563faa10a2819984ca: reduce venv size 83dbcb222a65a87741c9d96bb183f34528149269: update dev dependencies 7ef2946fb5151b745df30201b8c27790cac53875: remove unicode host test (#5962) 91c6b3fecf36b1f04554e57cc4060ccb737a445d: remove unicode host test 4cae5d8e411b1e69949d8fae669afeacbd3e5908: Merge branch 'stable'

Repository signals
Pages URL: none GitHub Actions workflows: 11 Recent releases: 3.1.3, 3.1.2, 3.1.1, 3.1.0, 3.0.3 Language composition: Python=99.9%, HTML=0.1%, Shell=0.0%, CSS=0.0% Root dirs: tests, examples, docs_dir

Architecture overview
Flask is a lightweight WSGI web application framework, initially a wrapper around Werkzeug and Jinja, that doesn't enforce project layout. The repository includes `examples` to demonstrate its usage, `tests` for quality assurance, and `docs_dir` for comprehensive documentation.
```


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 54de66574abdcf18e516039d83e31400d428acaf4e10d3bd67622b1704475ff8
