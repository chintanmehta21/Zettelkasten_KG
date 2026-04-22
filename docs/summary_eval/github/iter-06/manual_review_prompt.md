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
brief_summary: 'FastAPI is a composite framework orchestrating Starlette and Pydantic.
  At a high level, FastAPI is a composite framework that orchestrates two primary
  libraries: Starlette (core web and. The main stack includes Python, Starlette, Pydantic,
  ASGI. Documented public surfaces include OpenAPI 3, JSON Schema, Swagger UI, ReDoc.
  The documented workflow emphasizes A `fastapi` CLI uses Uvicorn to run a dev'
tags:
- python
- api-framework
- async
- pydantic
- starlette
- openapi
- cli-tool
- api
- framework
detailed_summary:
- heading: Purpose & Architecture
  bullets:
  - FastAPI is a composite framework orchestrating Starlette and Pydantic.
  - Starlette provides core web and ASGI functionality, including routing, requests,
    responses, and WebSockets.
  - Pydantic handles all data validation, serialization, and deserialization, driven
    by Python type hints.
  - Design philosophy is to be "Short" by minimizing code duplication.
  - 'A single type-hinted parameter declaration is used to derive multiple features:
    data validation, serialization, and API documentation.'
  - FastAPI integrates these components, using type hints and Pydantic models to automatically
    generate API schemas (OpenAPI 3, JSON Schema).
  sub_sections:
    Starlette:
    - Provides all core web and ASGI (Asynchronous Server Gateway Interface) functionality.
    - Includes routing, requests, responses, and WebSockets.
    Pydantic:
    - Handles all data validation, serialization, and deserialization.
    - Driven by Python type hints.
    Design Philosophy:
    - Designed to be "Short" by minimizing code duplication.
    - 'A single type-hinted parameter declaration is used to derive multiple features:
      data validation, serialization, and API documentation.'
- heading: APIs & Features
  bullets:
  - API endpoints are standard Python functions (`def` or `async def`).
  - Path/query parameters, headers, cookies, and request bodies are declared as type-hinted
    function arguments.
  - The use of standard type hints enables editor autocompletion ("IntelliSense")
    for request bodies and parameters, reducing debugging time.
  - Automatically validates incoming data against types and serializes outgoing Python
    objects (including `datetime`, `UUID`, database models) to JSON.
  - Pydantic raises detailed validation errors on failure.
  - 'Automatically generates and serves interactive API documentation: Swagger UI
    (at `/docs`) and ReDoc (at `/redoc`).'
  - A Dependency Injection system manages dependencies like database sessions or authentication,
    handling resolution and resource cleanup (teardown).
  - Includes helpers and dependency injection patterns for security schemes like OAuth2
    (with JWT) and HTTP Basic auth.
  - A `fastapi` CLI uses Uvicorn to run a development server with auto-reloading.
  - The `fastapi[standard]` installation includes `starlette`, `pydantic`, `uvicorn`,
    `httpx` (for `TestClient`), and `python-multipart`.
  - Optional high-performance JSON encoders like `orjson` and `ujson` are supported.
  sub_sections:
    Declaration:
    - API endpoints are standard Python functions (`def` or `async def`).
    - Path/query parameters, headers, cookies, and request bodies are declared as
      type-hinted function arguments.
    Developer Experience:
    - The use of standard type hints enables editor autocompletion ("IntelliSense")
      for request bodies and parameters, reducing debugging time.
    Data Handling:
    - Automatically validates incoming data against types and serializes outgoing
      Python objects (including `datetime`, `UUID`, database models) to JSON.
    - Pydantic raises detailed validation errors on failure.
    Documentation:
    - 'Automatically generates and serves interactive API documentation: Swagger UI
      (at `/docs`) and ReDoc (at `/redoc`).'
    Dependency Injection:
    - A system for managing dependencies like database sessions or authentication.
      It handles dependency resolution and resource cleanup (teardown).
    Security:
    - Includes helpers and dependency injection patterns for security schemes like
      OAuth2 (with JWT) and HTTP Basic auth.
    Tooling:
    - A `fastapi` CLI uses Uvicorn to run a development server with auto-reloading.
    - The `fastapi[standard]` installation includes `starlette`, `pydantic`, `uvicorn`,
      `httpx` (for `TestClient`), and `python-multipart`.
    - Optional high-performance JSON encoders like `orjson` and `ujson` are supported.
- heading: Maturity & Ecosystem
  bullets:
  - Used in production by companies including Microsoft, Uber, and Netflix, according
    to project testimonials.
  - The project is primarily sponsored by FastAPI Cloud, a commercial deployment platform
    from the same team.
  - The creator also developed Typer, a library for building CLI applications with
    a similar design philosophy ("the FastAPI of CLIs").
  - Actively maintained with a mature CI process (31 GitHub Actions workflows).
  - The security policy covers the latest version and requires private vulnerability
    disclosure.
  - Project's README claims performance is on par with NodeJS and Go, citing TechEmpower
    benchmarks where FastAPI/Uvicorn ranks among the fastest Python frameworks.
  - Claims a 200-300% increase in development speed and a 40% reduction in human-induced
    errors, based on internal team tests.
  sub_sections:
    Adoption:
    - Used in production by companies including Microsoft, Uber, and Netflix, according
      to project testimonials.
    Sponsorship:
    - The project is primarily sponsored by FastAPI Cloud, a commercial deployment
      platform from the same team.
    Sibling Projects:
    - The creator also developed Typer, a library for building CLI applications with
      a similar design philosophy ("the FastAPI of CLIs").
    Maintenance:
    - Actively maintained with a mature CI process (31 GitHub Actions workflows).
    - The security policy covers the latest version and requires private vulnerability
      disclosure.
    Performance Claims:
    - The project's README claims performance is on par with NodeJS and Go, citing
      TechEmpower benchmarks where FastAPI/Uvicorn ranks among the fastest Python
      frameworks.
    - It also claims a 200-300% increase in development speed and a 40% reduction
      in human-induced errors, based on internal team tests.
- heading: Notable Issues & Development Trends
  bullets:
  - A primary development focus is keeping pace with Python's evolving typing system.
  - 'Recent issues and fixes address complexities with `Annotated`, `ForwardRef`,
    and postponed annotations (`from __future__ import annotations`) (e.g., #15364,
    #15307).'
  - Ongoing work targets the DI system's performance and stability, with recent issues
    addressing deadlocks in dependency teardown (#15388) and memory regressions in
    the `Dependant` object (#15336).
  - Bugs are being fixed for OpenAPI schema generation with multi-method routes (#15398)
    and type propagation for Server-Sent Event (SSE) streams across routers (#15401).
  - 'Long-standing feature requests are being implemented, such as adding authentication
    to static file serving (#15295, closing #858), with active discussions on features
    like class-based views (#15392).'
  sub_sections:
    Advanced Typing:
    - A primary development focus is keeping pace with Python's evolving typing system.
    - 'Recent issues and fixes address complexities with `Annotated`, `ForwardRef`,
      and postponed annotations (`from __future__ import annotations`) (e.g., #15364,
      #15307).'
    Dependency Injection Robustness:
    - Ongoing work targets the DI system's performance and stability, with recent
      issues addressing deadlocks in dependency teardown (#15388) and memory regressions
      in the `Dependant` object (#15336).
    Schema & Routing Edge Cases:
    - Bugs are being fixed for OpenAPI schema generation with multi-method routes
      (#15398) and type propagation for Server-Sent Event (SSE) streams across routers
      (#15401).
    Feature Development:
    - 'Long-standing feature requests are being implemented, such as adding authentication
      to static file serving (#15295, closing #858), with active discussions on features
      like class-based views (#15392).'
metadata:
  source_type: github
  url: https://github.com/fastapi/fastapi
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 2 extra doc(s) fetched
  total_tokens_used: 34878
  gemini_pro_tokens: 25998
  gemini_flash_tokens: 8880
  total_latency_ms: 80257
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: fastapi/fastapi
    architecture_overview: 'FastAPI is a composite framework that orchestrates two
      primary libraries: Starlette (core web and ASGI functionality) and Pydantic
      (data validation, serialization). Its design philosophy minimizes code duplication
      by using a single type-hinted parameter declaration for multiple features. FastAPI
      integrates these components, using type hints and Pydantic models to automatically
      generate API schemas (OpenAPI 3, JSON Schema).'
    brief_summary: 'FastAPI is a composite framework orchestrating Starlette and Pydantic.
      At a high level, FastAPI is a composite framework that orchestrates two primary
      libraries: Starlette (core web and. The main stack includes Python, Starlette,
      Pydantic, ASGI. Documented public surfaces include OpenAPI 3, JSON Schema, Swagger
      UI, ReDoc. The documented workflow emphasizes A `fastapi` CLI uses Uvicorn to
      run a development server with auto-reloading.'
    tags:
    - python
    - api-framework
    - async
    - pydantic
    - starlette
    - openapi
    - cli-tool
    - api
    - framework
    benchmarks_tests_examples:
    - TechEmpower benchmarks
    - TestClient (via httpx)
    detailed_summary:
    - heading: Purpose & Architecture
      bullets:
      - FastAPI is a composite framework orchestrating Starlette and Pydantic.
      - Starlette provides core web and ASGI functionality, including routing, requests,
        responses, and WebSockets.
      - Pydantic handles all data validation, serialization, and deserialization,
        driven by Python type hints.
      - Design philosophy is to be "Short" by minimizing code duplication.
      - 'A single type-hinted parameter declaration is used to derive multiple features:
        data validation, serialization, and API documentation.'
      - FastAPI integrates these components, using type hints and Pydantic models
        to automatically generate API schemas (OpenAPI 3, JSON Schema).
      sub_sections:
        Starlette:
        - Provides all core web and ASGI (Asynchronous Server Gateway Interface) functionality.
        - Includes routing, requests, responses, and WebSockets.
        Pydantic:
        - Handles all data validation, serialization, and deserialization.
        - Driven by Python type hints.
        Design Philosophy:
        - Designed to be "Short" by minimizing code duplication.
        - 'A single type-hinted parameter declaration is used to derive multiple features:
          data validation, serialization, and API documentation.'
      module_or_feature: Core Framework Design
      main_stack:
      - Python
      - Starlette
      - Pydantic
      - ASGI
      public_interfaces:
      - OpenAPI 3
      - JSON Schema
      usability_signals:
      - Minimizes code duplication
      - Leverages standard Python type hints
    - heading: APIs & Features
      bullets:
      - API endpoints are standard Python functions (`def` or `async def`).
      - Path/query parameters, headers, cookies, and request bodies are declared as
        type-hinted function arguments.
      - The use of standard type hints enables editor autocompletion ("IntelliSense")
        for request bodies and parameters, reducing debugging time.
      - Automatically validates incoming data against types and serializes outgoing
        Python objects (including `datetime`, `UUID`, database models) to JSON.
      - Pydantic raises detailed validation errors on failure.
      - 'Automatically generates and serves interactive API documentation: Swagger
        UI (at `/docs`) and ReDoc (at `/redoc`).'
      - A Dependency Injection system manages dependencies like database sessions
        or authentication, handling resolution and resource cleanup (teardown).
      - Includes helpers and dependency injection patterns for security schemes like
        OAuth2 (with JWT) and HTTP Basic auth.
      - A `fastapi` CLI uses Uvicorn to run a development server with auto-reloading.
      - The `fastapi[standard]` installation includes `starlette`, `pydantic`, `uvicorn`,
        `httpx` (for `TestClient`), and `python-multipart`.
      - Optional high-performance JSON encoders like `orjson` and `ujson` are supported.
      sub_sections:
        Declaration:
        - API endpoints are standard Python functions (`def` or `async def`).
        - Path/query parameters, headers, cookies, and request bodies are declared
          as type-hinted function arguments.
        Developer Experience:
        - The use of standard type hints enables editor autocompletion ("IntelliSense")
          for request bodies and parameters, reducing debugging time.
        Data Handling:
        - Automatically validates incoming data against types and serializes outgoing
          Python objects (including `datetime`, `UUID`, database models) to JSON.
        - Pydantic raises detailed validation errors on failure.
        Documentation:
        - 'Automatically generates and serves interactive API documentation: Swagger
          UI (at `/docs`) and ReDoc (at `/redoc`).'
        Dependency Injection:
        - A system for managing dependencies like database sessions or authentication.
          It handles dependency resolution and resource cleanup (teardown).
        Security:
        - Includes helpers and dependency injection patterns for security schemes
          like OAuth2 (with JWT) and HTTP Basic auth.
        Tooling:
        - A `fastapi` CLI uses Uvicorn to run a development server with auto-reloading.
        - The `fastapi[standard]` installation includes `starlette`, `pydantic`, `uvicorn`,
          `httpx` (for `TestClient`), and `python-multipart`.
        - Optional high-performance JSON encoders like `orjson` and `ujson` are supported.
      module_or_feature: API Declaration & Tooling
      main_stack:
      - Python
      - ASGI
      - Pydantic
      - Starlette
      public_interfaces:
      - Swagger UI
      - ReDoc
      - OAuth2
      - HTTP Basic Auth
      usability_signals:
      - Editor autocompletion
      - Automatic data validation
      - Automatic documentation generation
      - Dependency Injection
    - heading: Maturity & Ecosystem
      bullets:
      - Used in production by companies including Microsoft, Uber, and Netflix, according
        to project testimonials.
      - The project is primarily sponsored by FastAPI Cloud, a commercial deployment
        platform from the same team.
      - The creator also developed Typer, a library for building CLI applications
        with a similar design philosophy ("the FastAPI of CLIs").
      - Actively maintained with a mature CI process (31 GitHub Actions workflows).
      - The security policy covers the latest version and requires private vulnerability
        disclosure.
      - Project's README claims performance is on par with NodeJS and Go, citing TechEmpower
        benchmarks where FastAPI/Uvicorn ranks among the fastest Python frameworks.
      - Claims a 200-300% increase in development speed and a 40% reduction in human-induced
        errors, based on internal team tests.
      sub_sections:
        Adoption:
        - Used in production by companies including Microsoft, Uber, and Netflix,
          according to project testimonials.
        Sponsorship:
        - The project is primarily sponsored by FastAPI Cloud, a commercial deployment
          platform from the same team.
        Sibling Projects:
        - The creator also developed Typer, a library for building CLI applications
          with a similar design philosophy ("the FastAPI of CLIs").
        Maintenance:
        - Actively maintained with a mature CI process (31 GitHub Actions workflows).
        - The security policy covers the latest version and requires private vulnerability
          disclosure.
        Performance Claims:
        - The project's README claims performance is on par with NodeJS and Go, citing
          TechEmpower benchmarks where FastAPI/Uvicorn ranks among the fastest Python
          frameworks.
        - It also claims a 200-300% increase in development speed and a 40% reduction
          in human-induced errors, based on internal team tests.
      module_or_feature: Project Status & Adoption
      main_stack:
      - Python
      public_interfaces: []
      usability_signals:
      - Industry adoption
      - Active maintenance
      - Performance claims
      - Developer productivity claims
    - heading: Notable Issues & Development Trends
      bullets:
      - A primary development focus is keeping pace with Python's evolving typing
        system.
      - 'Recent issues and fixes address complexities with `Annotated`, `ForwardRef`,
        and postponed annotations (`from __future__ import annotations`) (e.g., #15364,
        #15307).'
      - Ongoing work targets the DI system's performance and stability, with recent
        issues addressing deadlocks in dependency teardown (#15388) and memory regressions
        in the `Dependant` object (#15336).
      - Bugs are being fixed for OpenAPI schema generation with multi-method routes
        (#15398) and type propagation for Server-Sent Event (SSE) streams across routers
        (#15401).
      - 'Long-standing feature requests are being implemented, such as adding authentication
        to static file serving (#15295, closing #858), with active discussions on
        features like class-based views (#15392).'
      sub_sections:
        Advanced Typing:
        - A primary development focus is keeping pace with Python's evolving typing
          system.
        - 'Recent issues and fixes address complexities with `Annotated`, `ForwardRef`,
          and postponed annotations (`from __future__ import annotations`) (e.g.,
          #15364, #15307).'
        Dependency Injection Robustness:
        - Ongoing work targets the DI system's performance and stability, with recent
          issues addressing deadlocks in dependency teardown (#15388) and memory regressions
          in the `Dependant` object (#15336).
        Schema & Routing Edge Cases:
        - Bugs are being fixed for OpenAPI schema generation with multi-method routes
          (#15398) and type propagation for Server-Sent Event (SSE) streams across
          routers (#15401).
        Feature Development:
        - 'Long-standing feature requests are being implemented, such as adding authentication
          to static file serving (#15295, closing #858), with active discussions on
          features like class-based views (#15392).'
      module_or_feature: Current Development Focus
      main_stack:
      - Python Typing
      - Dependency Injection
      - OpenAPI
      public_interfaces: []
      usability_signals:
      - Active bug fixing
      - Feature development
      - Adaptation to Python evolution
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
brief_summary: Architecture built upon the `httpcore` library for transport layer
  management. At a high level, httpx provides a modern, async-capable alternative
  to requests. Its architecture leverages the httpcore library. The main stack includes
  httpcore, h11 (for HTTP/1.1), certifi, idna. Documented public surfaces include
  WSGITransport, ASGITransport. The documented workflow emphasizes Actively maintained.
tags:
- python
- api-framework
- async
- cli-tool
- http-client
- asyncio
- trio
- http-1-1
- http-2
- requests-compatible
detailed_summary:
- heading: Repository Purpose & Architecture
  bullets:
  - Offers a modern, async-capable alternative to `requests`.
  - Architecture built upon the `httpcore` library for transport layer management.
  - Supports direct requests to WSGI or ASGI applications via `WSGITransport` and
    `ASGITransport`.
  sub_sections: {}
- heading: API & Maturity
  bullets:
  - Actively maintained (v0.28.1).
  - BSD licensed.
  - Claims 100% test coverage.
  - Fully type-annotated.
  - Requires Python 3.9+ (Python 3.7 support dropped in v0.25.0).
  sub_sections:
    API Simplification and Refinement:
    - 'WSGI/ASGI Shortcut: `app` argument deprecated in v0.27.0, removed in v0.28.0;
      favors explicit transport instances.'
    - 'Proxy Config: `proxies` argument deprecated in v0.26.0, removed in v0.28.0;
      replaced by `proxy` or `mounts`.'
    - 'SSL Config: `cert` argument and string for `verify` deprecated in v0.28.0.'
    - 'Request Body: v0.28.0 introduced more compact JSON request bodies by default
      (potentially breaking change).'
- heading: Notable Issues & Behavior
  bullets:
  - Recent development focused on correcting specific request and error handling behaviors.
  sub_sections:
    Query Parameters:
    - 'Fixed bugs where `params` would overwrite, not merge with, existing URL query
      parameters (#3761, #3614).'
    URL Encoding:
    - Pipe character (`|`) now percent-encoded in URL paths (RFC 3986 conformance)
      (#3764).
    Redirects:
    - Feature requested (#3783) to optionally preserve original HTTP method on 301/302
      redirects, diverging from common browser behavior of changing method to `GET`.
    Error Handling:
    - Improved misleading error messages for invalid `data` arguments (#3758).
    - Fixed resource cleanup to ensure mounted transports are closed if main transport
      fails during initialization (#3769).
metadata:
  source_type: github
  url: https://github.com/encode/httpx
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 2 extra doc(s) fetched
  total_tokens_used: 24631
  gemini_pro_tokens: 18692
  gemini_flash_tokens: 5939
  total_latency_ms: 80808
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: encode/httpx
    architecture_overview: httpx provides a modern, async-capable alternative to requests.
      Its architecture leverages the httpcore library for transport management. Core
      dependencies include httpcore, h11 (HTTP/1.1), certifi, idna, and sniffio. Optional
      dependencies add features like HTTP/2 (h2), SOCKS proxies (socksio), decompression
      (brotli/zstandard), and a CLI (rich/click). It can make requests directly to
      WSGI or ASGI applications using WSGITransport and ASGITransport.
    brief_summary: Architecture built upon the `httpcore` library for transport layer
      management. At a high level, httpx provides a modern, async-capable alternative
      to requests. Its architecture leverages the httpcore library. The main stack
      includes httpcore, h11 (for HTTP/1.1), certifi, idna. Documented public surfaces
      include WSGITransport, ASGITransport. The documented workflow emphasizes Actively
      maintained.
    tags:
    - python
    - api-framework
    - async
    - cli-tool
    - http-client
    - asyncio
    - trio
    - http-1-1
    - http-2
    - requests-compatible
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: Repository Purpose & Architecture
      bullets:
      - Offers a modern, async-capable alternative to `requests`.
      - Architecture built upon the `httpcore` library for transport layer management.
      - Supports direct requests to WSGI or ASGI applications via `WSGITransport`
        and `ASGITransport`.
      sub_sections: {}
      module_or_feature: Core Architecture & Dependencies
      main_stack:
      - httpcore
      - h11 (for HTTP/1.1)
      - certifi
      - idna
      - sniffio
      - h2 (optional, for HTTP/2)
      - socksio (optional, for SOCKS proxies)
      - brotli/brotlicffi (optional, for decompression)
      - zstandard (optional, for decompression)
      - rich/click (optional, for CLI)
      public_interfaces:
      - WSGITransport
      - ASGITransport
      usability_signals: []
    - heading: API & Maturity
      bullets:
      - Actively maintained (v0.28.1).
      - BSD licensed.
      - Claims 100% test coverage.
      - Fully type-annotated.
      - Requires Python 3.9+ (Python 3.7 support dropped in v0.25.0).
      sub_sections:
        API Simplification and Refinement:
        - 'WSGI/ASGI Shortcut: `app` argument deprecated in v0.27.0, removed in v0.28.0;
          favors explicit transport instances.'
        - 'Proxy Config: `proxies` argument deprecated in v0.26.0, removed in v0.28.0;
          replaced by `proxy` or `mounts`.'
        - 'SSL Config: `cert` argument and string for `verify` deprecated in v0.28.0.'
        - 'Request Body: v0.28.0 introduced more compact JSON request bodies by default
          (potentially breaking change).'
      module_or_feature: API Stability & Evolution
      main_stack: []
      public_interfaces: []
      usability_signals:
      - Actively maintained
      - BSD licensed
      - 100% test coverage (claimed)
      - Fully type-annotated
      - Ongoing API simplification and refinement
    - heading: Notable Issues & Behavior
      bullets:
      - Recent development focused on correcting specific request and error handling
        behaviors.
      sub_sections:
        Query Parameters:
        - 'Fixed bugs where `params` would overwrite, not merge with, existing URL
          query parameters (#3761, #3614).'
        URL Encoding:
        - Pipe character (`|`) now percent-encoded in URL paths (RFC 3986 conformance)
          (#3764).
        Redirects:
        - Feature requested (#3783) to optionally preserve original HTTP method on
          301/302 redirects, diverging from common browser behavior of changing method
          to `GET`.
        Error Handling:
        - Improved misleading error messages for invalid `data` arguments (#3758).
        - Fixed resource cleanup to ensure mounted transports are closed if main transport
          fails during initialization (#3769).
      module_or_feature: Behavioral Fixes & Enhancements
      main_stack: []
      public_interfaces: []
      usability_signals:
      - Ongoing bug fixes and behavioral corrections
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
brief_summary: '* **ID:** psf/requests * **Tags:** #python, #http, #library, #client
  **psf/requests** is a high-level HTTP/1.1 client library for Python, officially
  supporting versions 3.10+. Guided by the philosophy "HTTP for Humans," it is one
  of Python''s most downloaded packages (~300M/week) and a dependency for over 4,000,000
  GitHub repositories. ### Architecture and API'
tags:
- _schema_fallback_
- github
- knowledge
- capture
- research
- notes
- summary
detailed_summary:
- heading: schema_fallback
  bullets:
  - structured extractor fell back; see metadata.is_schema_fallback
  - '* **ID:** psf/requests * **Tags:** #python, #http, #library, #client **psf/requests**
    is a high-level HTTP/1.1 client library for Python, officially supporting versions
    3.10+. Guided by the philosophy "HTTP for Humans," it is one of Python''s most
    downloaded packages (~300M/week) and a dependency for over 4,000,000 GitHub repositories.
    ### Architecture and API'
  sub_sections: {}
metadata:
  source_type: github
  url: https://github.com/psf/requests
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata and README fetched
  total_tokens_used: 19539
  gemini_pro_tokens: 12802
  gemini_flash_tokens: 6737
  total_latency_ms: 86772
  cod_iterations_used: 2
  self_check_missing_count: 4
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


## URL 4: https://github.com/pydantic/pydantic

### SUMMARY
```yaml
mini_title: pydantic/pydantic
brief_summary: 'Primary API involves inheriting from `pydantic.BaseModel` and defining
  fields with Python type annotations. At a high level, Pydantic V2 was a ground-up
  rewrite for performance and extensibility, introducing breaking changes from. The
  main stack includes Python, Rust, GitHub Actions, OpenTelemetry. Documented public
  surfaces include pydantic.BaseModel, pydantic.v1, model_copy, model_validate. The '
tags:
- python
- api-framework
- pydantic
- openapi
- validation
- parsing
- type-hints
- rust
- data-validation
- data-parsing
detailed_summary:
- heading: API and Architecture
  bullets:
  - Primary API involves inheriting from `pydantic.BaseModel` and defining fields
    with Python type annotations.
  - Models can generate JSON Schemas to describe their data structure.
  - Performs automatic, unambiguous type coercion (e.g., string '123' to int 123,
    string '2017-06-01 12:22' to a `datetime` object).
  - Pydantic V2 was a ground-up rewrite for performance and extensibility, introducing
    breaking changes from V1.
  - V2 bundles the latest V1 version for backward compatibility, accessible via `from
    pydantic import v1 as pydantic_v1`.
  - A `1.10.X-fixes` git branch is maintained for V1 patches.
  - Installable via `pip` or `conda`.
  - Requires Python 3.10 or newer; support for Python 3.9 has been dropped.
  - Codebase is primarily Python (83.1%) with a significant Rust component (16.6%)
    for performance-critical logic, understood to be within `pydantic-core`.
  sub_sections:
    V2 Changes:
    - Ground-up rewrite for performance and extensibility.
    - Introduced breaking changes from V1.
    - Bundles V1 for backward compatibility (`from pydantic import v1`).
    Installation & Requirements:
    - Installable via `pip` or `conda`.
    - Requires Python 3.10+ (dropped 3.9 support).
    Codebase Composition:
    - 83.1% Python, 16.6% Rust (for `pydantic-core`).
- heading: Maturity and Ecosystem
  bullets:
  - Actively maintained with a high frequency of releases (e.g., v2.13.0 through v2.13.3).
  - Uses 13 distinct GitHub Actions workflows, indicating a mature CI/CD process.
  - Maintains a formal security policy for reporting vulnerabilities.
  - Promotes Pydantic Logfire, a multi-language (Python, JS/TS, Rust) observability
    platform compatible with OpenTelemetry.
  - Logfire can monitor Pydantic validations via `logfire.instrument_pydantic()`.
  sub_sections:
    Observability:
    - Pydantic Logfire offers multi-language observability.
    - Compatible with OpenTelemetry.
    - Integrates with Pydantic validations.
- heading: Notable Issues and Constraints
  bullets:
  - Validation error messages are in English only; a feature request for localization
    is open (#13113).
  - A regression in v2.12 caused the JSON schema for `Decimal` fields to reject scientific
    notation, a format Pydantic can produce (#13089).
  - Open issues regarding "incomplete generic recursive models," suggesting edge cases
    in handling advanced generic types (#13085).
  - '`model_copy(deep=True, update=...)` deepcopies the entire model *before* applying
    updates, causing performance overhead and crashes if the model contains non-deepcopyable
    fields (#13077, #13087).'
  - Runtime configuration overrides, such as `model_validate(..., extra='allow')`,
    can unexpectedly ignore class-level configuration hints like `__pydantic_extra__`
    (#13024).
  - Downstream packagers have been blocked by missing Git tags for `pydantic-core`
    releases (#13071).
  sub_sections:
    Localization:
    - 'Validation error messages are English-only; feature request #13113 open.'
    Serialization:
    - 'v2.12 regression: `Decimal` JSON schema rejects scientific notation (#13089).'
    Complex Types:
    - Issues with 'incomplete generic recursive models' (#13085).
    API Behavior:
    - '`model_copy(deep=True, update=...)` deepcopies before updates, causing overhead/crashes
      (#13077, #13087).'
    - Runtime config overrides can ignore class-level hints (e.g., `model_validate(...,
      extra='allow')` ignoring `__pydantic_extra__`) (#13024).
    Release Management:
    - Missing Git tags for `pydantic-core` releases blocking downstream packagers
      (#13071).
metadata:
  source_type: github
  url: https://github.com/pydantic/pydantic
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 1 extra doc(s) fetched
  total_tokens_used: 18450
  gemini_pro_tokens: 15538
  gemini_flash_tokens: 2912
  total_latency_ms: 76217
  cod_iterations_used: 2
  self_check_missing_count: 5
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: pydantic/pydantic
    architecture_overview: Pydantic V2 was a ground-up rewrite for performance and
      extensibility, introducing breaking changes from V1. For backward compatibility,
      V2 bundles the latest V1 version. The codebase is primarily Python (83.1%) with
      a significant Rust component (16.6%) for performance-critical logic, understood
      to be within its `pydantic-core` dependency. This architecture enables high-performance
      data validation and parsing using standard Python type hints.
    brief_summary: Primary API involves inheriting from `pydantic.BaseModel` and defining
      fields with Python type annotations. At a high level, Pydantic V2 was a ground-up
      rewrite for performance and extensibility, introducing breaking changes from.
      The main stack includes Python, Rust, GitHub Actions, OpenTelemetry. Documented
      public surfaces include pydantic.BaseModel, pydantic.v1, model_copy, model_validate.
      The documented workflow emphasizes Installable via `pip` or `conda`.
    tags:
    - python
    - api-framework
    - pydantic
    - openapi
    - validation
    - parsing
    - type-hints
    - rust
    - data-validation
    - data-parsing
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: API and Architecture
      bullets:
      - Primary API involves inheriting from `pydantic.BaseModel` and defining fields
        with Python type annotations.
      - Models can generate JSON Schemas to describe their data structure.
      - Performs automatic, unambiguous type coercion (e.g., string '123' to int 123,
        string '2017-06-01 12:22' to a `datetime` object).
      - Pydantic V2 was a ground-up rewrite for performance and extensibility, introducing
        breaking changes from V1.
      - V2 bundles the latest V1 version for backward compatibility, accessible via
        `from pydantic import v1 as pydantic_v1`.
      - A `1.10.X-fixes` git branch is maintained for V1 patches.
      - Installable via `pip` or `conda`.
      - Requires Python 3.10 or newer; support for Python 3.9 has been dropped.
      - Codebase is primarily Python (83.1%) with a significant Rust component (16.6%)
        for performance-critical logic, understood to be within `pydantic-core`.
      sub_sections:
        V2 Changes:
        - Ground-up rewrite for performance and extensibility.
        - Introduced breaking changes from V1.
        - Bundles V1 for backward compatibility (`from pydantic import v1`).
        Installation & Requirements:
        - Installable via `pip` or `conda`.
        - Requires Python 3.10+ (dropped 3.9 support).
        Codebase Composition:
        - 83.1% Python, 16.6% Rust (for `pydantic-core`).
      module_or_feature: Core Data Validation
      main_stack:
      - Python
      - Rust
      public_interfaces:
      - pydantic.BaseModel
      - pydantic.v1
      - model_copy
      - model_validate
      usability_signals:
      - Strong IDE integration
      - Static analysis tool compatibility
      - Automatic type coercion
    - heading: Maturity and Ecosystem
      bullets:
      - Actively maintained with a high frequency of releases (e.g., v2.13.0 through
        v2.13.3).
      - Uses 13 distinct GitHub Actions workflows, indicating a mature CI/CD process.
      - Maintains a formal security policy for reporting vulnerabilities.
      - Promotes Pydantic Logfire, a multi-language (Python, JS/TS, Rust) observability
        platform compatible with OpenTelemetry.
      - Logfire can monitor Pydantic validations via `logfire.instrument_pydantic()`.
      sub_sections:
        Observability:
        - Pydantic Logfire offers multi-language observability.
        - Compatible with OpenTelemetry.
        - Integrates with Pydantic validations.
      module_or_feature: Project Health & Community
      main_stack:
      - Python
      - GitHub Actions
      - OpenTelemetry
      public_interfaces:
      - logfire.instrument_pydantic()
      usability_signals:
      - Active development
      - Mature CI/CD
      - Formal security policy
      - Ecosystem integration (Logfire)
    - heading: Notable Issues and Constraints
      bullets:
      - Validation error messages are in English only; a feature request for localization
        is open (#13113).
      - A regression in v2.12 caused the JSON schema for `Decimal` fields to reject
        scientific notation, a format Pydantic can produce (#13089).
      - Open issues regarding "incomplete generic recursive models," suggesting edge
        cases in handling advanced generic types (#13085).
      - '`model_copy(deep=True, update=...)` deepcopies the entire model *before*
        applying updates, causing performance overhead and crashes if the model contains
        non-deepcopyable fields (#13077, #13087).'
      - Runtime configuration overrides, such as `model_validate(..., extra='allow')`,
        can unexpectedly ignore class-level configuration hints like `__pydantic_extra__`
        (#13024).
      - Downstream packagers have been blocked by missing Git tags for `pydantic-core`
        releases (#13071).
      sub_sections:
        Localization:
        - 'Validation error messages are English-only; feature request #13113 open.'
        Serialization:
        - 'v2.12 regression: `Decimal` JSON schema rejects scientific notation (#13089).'
        Complex Types:
        - Issues with 'incomplete generic recursive models' (#13085).
        API Behavior:
        - '`model_copy(deep=True, update=...)` deepcopies before updates, causing
          overhead/crashes (#13077, #13087).'
        - Runtime config overrides can ignore class-level hints (e.g., `model_validate(...,
          extra='allow')` ignoring `__pydantic_extra__`) (#13024).
        Release Management:
        - Missing Git tags for `pydantic-core` releases blocking downstream packagers
          (#13071).
      module_or_feature: Known Limitations & Bugs
      main_stack:
      - Python
      - Rust
      public_interfaces:
      - model_copy
      - model_validate
      usability_signals:
      - Open feature requests
      - Identified regressions
      - Performance concerns in specific API usage
      - Configuration override inconsistencies
      - Release process issues for dependencies
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
mini_title: fastapi/typer
brief_summary: A Python library for building command-line interface (CLI) applications.
  At a high level, typer is a Python library for building command-line interface (CLI)
  applications, positioned as a. The main stack includes Python, Click, rich, shellingham.
  Documented public surfaces include typer.run(), @app.command(), typer CLI tool,
  Python type hints. The documented workflow emphasizes The `typer-slim` pa
tags:
- python
- api-framework
- cli-tool
- cli
- type-hints
- click
- fastapi
- command-line-tool
- developer-tool
detailed_summary:
- heading: Purpose
  bullets:
  - A Python library for building command-line interface (CLI) applications.
  - Positioned as a sibling project to FastAPI.
  - Utilizes Python type hints to define CLI arguments and options, aiming to reduce
    boilerplate code.
  - Includes a `typer` command-line tool to execute Python scripts as CLIs without
    explicit library usage.
  sub_sections: {}
- heading: Architecture & Dependencies
  bullets:
  - '`typer` is built as a layer on top of `Click`.'
  - Required dependencies include `Click` (underlying CLI framework), `rich` (formatted
    error messages/tracebacks), and `shellingham` (detects user's shell for completion).
  - '`rich` can be disabled by setting `TYPER_USE_RICH` environment variable to `False`
    or `0`.'
  - The `typer-slim` package, which previously omitted `rich` and `shellingham`, was
    deprecated in version 0.22.0 and now installs the full `typer` package.
  sub_sections: {}
- heading: API & Functionality
  bullets:
  - API leverages type hints for strong editor support (autocompletion, type checks),
    which can reduce debugging time.
  sub_sections:
    Core API:
    - CLI commands are defined as standard Python functions.
    - Function parameters and their type hints are automatically converted to CLI
      arguments and options (e.g., a `bool` parameter becomes `--flag`/`--no-flag`).
    Application Structure:
    - Single-command CLIs are created with minimal code, typically an import and a
      `typer.run(my_function)` call.
    - Multi-command CLIs with subcommands use an instance of the `typer.Typer` class
      with the `@app.command()` decorator.
    Features:
    - '**Automatic Help:** Generates `--help` text from function signatures and docstrings.'
    - '**Shell Completion:** Provides tab completion for Bash, Zsh, Fish, and PowerShell,
      enabled by the user via an `--install-completion` flag.'
    - '**Script Runner:** The `typer` executable can run a script''s main function
      as a CLI (e.g., `typer main.py run`).'
- heading: Maturity & Project Status
  bullets:
  - '**License:** MIT.'
  - '**CI/CD:** Employs 16 GitHub Actions workflows for testing and publishing.'
  - '**Maintenance:** Actively maintained, with recent releases including version
    `0.24.2`.'
  - '**Security:** Vulnerabilities are reported privately to `security@tiangolo.com`.
    The policy advises using the latest versions for security fixes.'
  sub_sections: {}
- heading: Notable Issues & Developments
  bullets: []
  sub_sections:
    Refactoring:
    - Recent work includes vendoring parts of its core dependency, Click, to increase
      test coverage and internal control.
    Features:
    - Support for `*args` and `**kwargs` in command function signatures was added
      (#1654).
    Bug Fixes:
    - Shell completion logic was fixed for PowerShell command hints (#1685) and for
      `click.Path` arguments in a `TyperGroup` (#1673).
    - 'An optimization that skipped `result_callback` execution in single-command
      apps was fixed (#1631, #445).'
    - Type annotation edge cases were addressed for `Union` (#1683) and `Annotated`
      with `typer.Option(None)` (#1564).
    Error Handling:
    - Defining a command with multiple variadic arguments (e.g., multiple `List[...]`
      parameters) now raises a clear `UsageError` instead of an opaque `TypeError`
      from Click (#1555).
metadata:
  source_type: github
  url: https://github.com/tiangolo/typer
  author: null
  date: null
  extraction_confidence: high
  confidence_reason: repo metadata, README, and 3 extra doc(s) fetched
  total_tokens_used: 22522
  gemini_pro_tokens: 19577
  gemini_flash_tokens: 2945
  total_latency_ms: 73817
  cod_iterations_used: 2
  self_check_missing_count: 3
  patch_applied: true
  engine_version: 2.0.0
  structured_payload:
    mini_title: fastapi/typer
    architecture_overview: typer is a Python library for building command-line interface
      (CLI) applications, positioned as a layer built on top of Click. It leverages
      Python type hints for defining CLI arguments and options, reducing boilerplate.
      Key dependencies include Click for the underlying framework, rich for formatted
      error messages, and shellingham for shell detection and completion installation.
    brief_summary: A Python library for building command-line interface (CLI) applications.
      At a high level, typer is a Python library for building command-line interface
      (CLI) applications, positioned as a. The main stack includes Python, Click,
      rich, shellingham. Documented public surfaces include typer.run(), @app.command(),
      typer CLI tool, Python type hints. The documented workflow emphasizes The `typer-slim`
      package, which previously omitted `rich` and `shellingham`, was deprecated in.
    tags:
    - python
    - api-framework
    - cli-tool
    - cli
    - type-hints
    - click
    - fastapi
    - command-line-tool
    - developer-tool
    benchmarks_tests_examples: null
    detailed_summary:
    - heading: Purpose
      bullets:
      - A Python library for building command-line interface (CLI) applications.
      - Positioned as a sibling project to FastAPI.
      - Utilizes Python type hints to define CLI arguments and options, aiming to
        reduce boilerplate code.
      - Includes a `typer` command-line tool to execute Python scripts as CLIs without
        explicit library usage.
      sub_sections: {}
      module_or_feature: Core Library
      main_stack:
      - Python
      - Click
      public_interfaces:
      - typer.run()
      - '@app.command()'
      - typer CLI tool
      usability_signals:
      - Type Hinting for CLI
      - Reduced boilerplate
      - Strong editor support
    - heading: Architecture & Dependencies
      bullets:
      - '`typer` is built as a layer on top of `Click`.'
      - Required dependencies include `Click` (underlying CLI framework), `rich` (formatted
        error messages/tracebacks), and `shellingham` (detects user's shell for completion).
      - '`rich` can be disabled by setting `TYPER_USE_RICH` environment variable to
        `False` or `0`.'
      - The `typer-slim` package, which previously omitted `rich` and `shellingham`,
        was deprecated in version 0.22.0 and now installs the full `typer` package.
      sub_sections: {}
      module_or_feature: Core Architecture
      main_stack:
      - Click
      - rich
      - shellingham
      public_interfaces: []
      usability_signals:
      - Modular design
      - Configurable dependencies (rich)
    - heading: API & Functionality
      bullets:
      - API leverages type hints for strong editor support (autocompletion, type checks),
        which can reduce debugging time.
      sub_sections:
        Core API:
        - CLI commands are defined as standard Python functions.
        - Function parameters and their type hints are automatically converted to
          CLI arguments and options (e.g., a `bool` parameter becomes `--flag`/`--no-flag`).
        Application Structure:
        - Single-command CLIs are created with minimal code, typically an import and
          a `typer.run(my_function)` call.
        - Multi-command CLIs with subcommands use an instance of the `typer.Typer`
          class with the `@app.command()` decorator.
        Features:
        - '**Automatic Help:** Generates `--help` text from function signatures and
          docstrings.'
        - '**Shell Completion:** Provides tab completion for Bash, Zsh, Fish, and
          PowerShell, enabled by the user via an `--install-completion` flag.'
        - '**Script Runner:** The `typer` executable can run a script''s main function
          as a CLI (e.g., `typer main.py run`).'
      module_or_feature: Core API
      main_stack: []
      public_interfaces:
      - Python type hints
      - typer.run()
      - '@app.command()'
      - --help
      - --install-completion
      - typer <script> run
      usability_signals:
      - Strong editor support
      - Autocompletion
      - Type checks
      - Reduced debugging time
      - Automatic help generation
      - Tab completion
    - heading: Maturity & Project Status
      bullets:
      - '**License:** MIT.'
      - '**CI/CD:** Employs 16 GitHub Actions workflows for testing and publishing.'
      - '**Maintenance:** Actively maintained, with recent releases including version
        `0.24.2`.'
      - '**Security:** Vulnerabilities are reported privately to `security@tiangolo.com`.
        The policy advises using the latest versions for security fixes.'
      sub_sections: {}
      module_or_feature: Project Lifecycle
      main_stack: []
      public_interfaces: []
      usability_signals:
      - Actively maintained
      - Regular releases
      - Clear security policy
    - heading: Notable Issues & Developments
      bullets: []
      sub_sections:
        Refactoring:
        - Recent work includes vendoring parts of its core dependency, Click, to increase
          test coverage and internal control.
        Features:
        - Support for `*args` and `**kwargs` in command function signatures was added
          (#1654).
        Bug Fixes:
        - Shell completion logic was fixed for PowerShell command hints (#1685) and
          for `click.Path` arguments in a `TyperGroup` (#1673).
        - 'An optimization that skipped `result_callback` execution in single-command
          apps was fixed (#1631, #445).'
        - Type annotation edge cases were addressed for `Union` (#1683) and `Annotated`
          with `typer.Option(None)` (#1564).
        Error Handling:
        - Defining a command with multiple variadic arguments (e.g., multiple `List[...]`
          parameters) now raises a clear `UsageError` instead of an opaque `TypeError`
          from Click (#1555).
      module_or_feature: Recent Updates
      main_stack: []
      public_interfaces: []
      usability_signals:
      - Continuous improvement
      - Active bug resolution
      - Enhanced error messages
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


ATOMIC FACTS:
(see per-URL sections above)

SOURCE:
(see per-URL sections above)

Score each criterion. 5-15 sentences of prose per criterion, source-grounded. Calculate a composite score 0-100.
Final line of the file must be `estimated_composite: NN.N`.

Save the output at the path printed by the CLI. eval.json SHA256 of the already-computed standard evaluator run
(for enforcement only, do NOT open that file): 10f53f885e193ef61981071b970950981448ad612a2d6b808c5e43832649f707
