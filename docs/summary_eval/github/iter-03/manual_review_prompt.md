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
brief_summary: Primary goal is to build high-performance, RESTful APIs in Python.
  At a high level, FastAPI is an ASGI web framework built on Starlette for core web
  functionality and. The main stack includes Python, Starlette, Pydantic, ASGI. Documented
  public surfaces include RESTful APIs, ASGI, OpenAPI, Swagger UI. The documented
  workflow emphasizes Operates as an ASGI framework, running on servers like Uvicorn
tags:
- python
- api-framework
- async
- pydantic
- starlette
- openapi
- cli-tool
- web-framework
- api
- asgi
detailed_summary:
- heading: Purpose
  bullets:
  - Primary goal is to build high-performance, RESTful APIs in Python.
  - Leverages standard Python type hints for API declaration, data validation, and
    documentation.
  - Claims performance on par with NodeJS and Go.
  - Claims to increase development speed by 200-300% and reduce human-induced bugs
    by ~40% (based on internal team tests).
  sub_sections: {}
- heading: Architecture
  bullets:
  - Built upon Starlette for core web and ASGI functionality (e.g., WebSockets, CORS).
  - Uses Pydantic for data validation, serialization, and settings management.
  - Operates as an ASGI framework, running on servers like Uvicorn.
  - Natively supports Python's `async`/`await` syntax.
  - API endpoints, parameters, and request/response bodies are defined using type-annotated
    parameters in standard Python functions.
  sub_sections: {}
- heading: APIs & Features
  bullets:
  - Automatically validates incoming data against Pydantic models.
  - Serializes outgoing Python objects (including `datetime`, `UUID`) to JSON.
  - Generates OpenAPI 3 and JSON Schema from code.
  - Serves interactive Swagger UI (`/docs`) and ReDoc (`/redoc`) interfaces by default.
  - Enables strong editor support with autocompletion and type checking due to type
    hints.
  - Provides a dependency injection system for managing resources, authentication,
    and logic reuse.
  - Includes helpers for security schemes like OAuth2 (with JWT) and HTTP Basic.
  - The `standard` installation includes `uvicorn`, `httpx`, `jinja2`, `python-multipart`,
    and `email-validator`.
  - Offers a `TestClient` (based on HTTPX) for testing.
  - Integrates with GraphQL via Strawberry.
  - Has a sibling project, Typer, for building CLIs with similar design principles.
  sub_sections:
    Data Handling:
    - Automatically validates incoming data against Pydantic models
    - Serializes outgoing Python objects (including datetime, UUID) to JSON
    Automatic Documentation:
    - Generates OpenAPI 3 and JSON Schema from code
    - Serves interactive Swagger UI (/docs) and ReDoc (/redoc) interfaces by default
    Editor Support:
    - Enables strong editor support with autocompletion and type checking
    Dependency Injection:
    - System for managing resources, authentication, and logic reuse
    Security:
    - Includes helpers for security schemes like OAuth2 (with JWT) and HTTP Basic
    Ecosystem:
    - Standard installation includes uvicorn, httpx, jinja2, python-multipart, email-validator
    - Offers a TestClient (based on HTTPX) for testing
    - Integrates with GraphQL via Strawberry
    - Sibling project Typer applies same design principles to building CLIs
- heading: Maturity & Project Health
  bullets:
  - Actively maintained and used in production by major companies like Microsoft,
    Uber, and Netflix.
  - Primarily sponsored by FastAPI Cloud, a commercial service from the same team.
  - Utilizes 31 GitHub Actions workflows for testing and maintenance, indicating robust
    CI/CD.
  - Recently upgraded its core dependency Starlette from v0.52.1 to v1.0.0.
  - Security policy covers only the latest version.
  - Vulnerabilities are reported privately to `security@tiangolo.com`.
  sub_sections:
    Status:
    - Actively maintained
    - Used in production by Microsoft, Uber, and Netflix
    Sponsorship:
    - Primarily sponsored by FastAPI Cloud
    CI/CD:
    - Utilizes 31 GitHub Actions workflows for testing and maintenance
    Dependencies:
    - Recently upgraded Starlette from v0.52.1 to v1.0.0
    Security Policy:
    - Covers only the latest version
    - Vulnerabilities reported privately to security@tiangolo.com
- heading: Notable Issues & Developments
  bullets:
  - 'Type hint resolution, especially for complex and forward-referenced annotations,
    is a recurring maintenance area (e.g., #15364, #15307, #15234).'
  - 'Recent feature enhancements include `AuthStaticFiles` for authenticated static
    files (#15295, #858) and automatic `HEAD` request support for `GET` routes (#15356).'
  - A proposal for class-based view (CBV) utilities is currently under discussion
    (#15392).
  - Performance and concurrency fixes addressed deadlocks in dependency injection
    teardown (#15388) and a memory usage regression in the `Dependant` object (#15336).
  - An error handling fix addressed incorrect HTTP 400 reporting for client disconnects
    during body parsing (#15315).
  sub_sections:
    Type Hint Resolution:
    - 'Recurring maintenance area involves correctly resolving complex and forward-referenced
      type annotations (ForwardRef, Annotated), as seen in issues #15364, #15307,
      and #15234.'
    Feature Enhancements:
    - 'Added AuthStaticFiles to serve authenticated static files, closing a long-standing
      request (#15295, #858).'
    - GET routes now automatically support HEAD requests, inheriting Starlette's behavior
      (#15356).
    - A proposal for class-based view (CBV) utilities is under discussion (#15392).
    Performance & Concurrency:
    - Recent fixes addressed deadlocks in the dependency injection teardown process
      (#15388).
    - Addressed a memory usage regression in the Dependant object (#15336).
    Error Handling:
    - Fixed an issue where client disconnects during body parsing were incorrectly
      reported as HTTP 400 errors (#15315).
metadata:
  source_type: github
  url: https://github.com/fastapi/fastapi
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 2 extra doc(s) fetched
  total_tokens_used: 28776
  gemini_pro_tokens: 25210
  gemini_flash_tokens: 3566
  total_latency_ms: 84214
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: fastapi/fastapi
    architecture_overview: FastAPI is an ASGI web framework built on Starlette for
      core web functionality and Pydantic for data validation and serialization. It
      leverages standard Python type hints to define API endpoints, parameters, and
      request/response bodies, enabling automatic documentation generation and strong
      editor support. It runs on ASGI servers like Uvicorn and natively supports asynchronous
      operations.
    brief_summary: Primary goal is to build high-performance, RESTful APIs in Python.
      At a high level, FastAPI is an ASGI web framework built on Starlette for core
      web functionality and. The main stack includes Python, Starlette, Pydantic,
      ASGI. Documented public surfaces include RESTful APIs, ASGI, OpenAPI, Swagger
      UI. The documented workflow emphasizes Operates as an ASGI framework, running
      on servers like Uvicorn.
    tags:
    - python
    - api-framework
    - async
    - pydantic
    - starlette
    - openapi
    - cli-tool
    - web-framework
    - api
    - asgi
    benchmarks_tests_examples:
    - Internal team tests (claims 200-300% development speed increase, ~40% bug reduction)
    - TestClient (based on HTTPX) for testing
    detailed_summary:
    - heading: Purpose
      bullets:
      - Primary goal is to build high-performance, RESTful APIs in Python.
      - Leverages standard Python type hints for API declaration, data validation,
        and documentation.
      - Claims performance on par with NodeJS and Go.
      - Claims to increase development speed by 200-300% and reduce human-induced
        bugs by ~40% (based on internal team tests).
      sub_sections: {}
      module_or_feature: Core Functionality
      main_stack:
      - Python
      public_interfaces:
      - RESTful APIs
      usability_signals:
      - High Performance
      - Developer Velocity
    - heading: Architecture
      bullets:
      - Built upon Starlette for core web and ASGI functionality (e.g., WebSockets,
        CORS).
      - Uses Pydantic for data validation, serialization, and settings management.
      - Operates as an ASGI framework, running on servers like Uvicorn.
      - Natively supports Python's `async`/`await` syntax.
      - API endpoints, parameters, and request/response bodies are defined using type-annotated
        parameters in standard Python functions.
      sub_sections: {}
      module_or_feature: Framework Structure
      main_stack:
      - Starlette
      - Pydantic
      - ASGI
      - Uvicorn
      public_interfaces:
      - ASGI
      usability_signals:
      - Type-annotated API definition
      - Asynchronous support
    - heading: APIs & Features
      bullets:
      - Automatically validates incoming data against Pydantic models.
      - Serializes outgoing Python objects (including `datetime`, `UUID`) to JSON.
      - Generates OpenAPI 3 and JSON Schema from code.
      - Serves interactive Swagger UI (`/docs`) and ReDoc (`/redoc`) interfaces by
        default.
      - Enables strong editor support with autocompletion and type checking due to
        type hints.
      - Provides a dependency injection system for managing resources, authentication,
        and logic reuse.
      - Includes helpers for security schemes like OAuth2 (with JWT) and HTTP Basic.
      - The `standard` installation includes `uvicorn`, `httpx`, `jinja2`, `python-multipart`,
        and `email-validator`.
      - Offers a `TestClient` (based on HTTPX) for testing.
      - Integrates with GraphQL via Strawberry.
      - Has a sibling project, Typer, for building CLIs with similar design principles.
      sub_sections:
        Data Handling:
        - Automatically validates incoming data against Pydantic models
        - Serializes outgoing Python objects (including datetime, UUID) to JSON
        Automatic Documentation:
        - Generates OpenAPI 3 and JSON Schema from code
        - Serves interactive Swagger UI (/docs) and ReDoc (/redoc) interfaces by default
        Editor Support:
        - Enables strong editor support with autocompletion and type checking
        Dependency Injection:
        - System for managing resources, authentication, and logic reuse
        Security:
        - Includes helpers for security schemes like OAuth2 (with JWT) and HTTP Basic
        Ecosystem:
        - Standard installation includes uvicorn, httpx, jinja2, python-multipart,
          email-validator
        - Offers a TestClient (based on HTTPX) for testing
        - Integrates with GraphQL via Strawberry
        - Sibling project Typer applies same design principles to building CLIs
      module_or_feature: API Development Toolkit
      main_stack:
      - Pydantic
      - OpenAPI 3
      - JSON Schema
      - OAuth2
      - JWT
      - HTTPX
      - Strawberry
      - Typer
      public_interfaces:
      - RESTful APIs
      - OpenAPI
      - Swagger UI
      - ReDoc
      - GraphQL (via Strawberry)
      usability_signals:
      - Automatic validation
      - Automatic serialization
      - Interactive documentation
      - Autocompletion
      - Type checking
      - Resource management
      - Security helpers
      - Testing client
    - heading: Maturity & Project Health
      bullets:
      - Actively maintained and used in production by major companies like Microsoft,
        Uber, and Netflix.
      - Primarily sponsored by FastAPI Cloud, a commercial service from the same team.
      - Utilizes 31 GitHub Actions workflows for testing and maintenance, indicating
        robust CI/CD.
      - Recently upgraded its core dependency Starlette from v0.52.1 to v1.0.0.
      - Security policy covers only the latest version.
      - Vulnerabilities are reported privately to `security@tiangolo.com`.
      sub_sections:
        Status:
        - Actively maintained
        - Used in production by Microsoft, Uber, and Netflix
        Sponsorship:
        - Primarily sponsored by FastAPI Cloud
        CI/CD:
        - Utilizes 31 GitHub Actions workflows for testing and maintenance
        Dependencies:
        - Recently upgraded Starlette from v0.52.1 to v1.0.0
        Security Policy:
        - Covers only the latest version
        - Vulnerabilities reported privately to security@tiangolo.com
      module_or_feature: Project Lifecycle
      main_stack:
      - GitHub Actions
      public_interfaces: []
      usability_signals:
      - Actively maintained
      - Production usage
      - Commercial sponsorship
      - Robust CI/CD
      - Security policy
    - heading: Notable Issues & Developments
      bullets:
      - 'Type hint resolution, especially for complex and forward-referenced annotations,
        is a recurring maintenance area (e.g., #15364, #15307, #15234).'
      - 'Recent feature enhancements include `AuthStaticFiles` for authenticated static
        files (#15295, #858) and automatic `HEAD` request support for `GET` routes
        (#15356).'
      - A proposal for class-based view (CBV) utilities is currently under discussion
        (#15392).
      - Performance and concurrency fixes addressed deadlocks in dependency injection
        teardown (#15388) and a memory usage regression in the `Dependant` object
        (#15336).
      - An error handling fix addressed incorrect HTTP 400 reporting for client disconnects
        during body parsing (#15315).
      sub_sections:
        Type Hint Resolution:
        - 'Recurring maintenance area involves correctly resolving complex and forward-referenced
          type annotations (ForwardRef, Annotated), as seen in issues #15364, #15307,
          and #15234.'
        Feature Enhancements:
        - 'Added AuthStaticFiles to serve authenticated static files, closing a long-standing
          request (#15295, #858).'
        - GET routes now automatically support HEAD requests, inheriting Starlette's
          behavior (#15356).
        - A proposal for class-based view (CBV) utilities is under discussion (#15392).
        Performance & Concurrency:
        - Recent fixes addressed deadlocks in the dependency injection teardown process
          (#15388).
        - Addressed a memory usage regression in the Dependant object (#15336).
        Error Handling:
        - Fixed an issue where client disconnects during body parsing were incorrectly
          reported as HTTP 400 errors (#15315).
      module_or_feature: Recent Updates & Challenges
      main_stack: []
      public_interfaces: []
      usability_signals:
      - Active development
      - Continuous improvement
      - Bug fixes
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


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): d4ab46c4d2edcae263572fe8fd30ff4d3141ab9533d91152f59ec8b8f5d2e9c2
