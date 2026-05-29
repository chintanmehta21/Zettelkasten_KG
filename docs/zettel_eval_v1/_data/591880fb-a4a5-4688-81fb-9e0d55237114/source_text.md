## Overview
- The Open Data Platform (ODP) is designed as a 'connect once, consume everywhere' infrastructure layer to integrate proprietary, licensed, and public data sources.

### Core argument
- The Open Data Platform (ODP) is designed as a 'connect once, consume everywhere' infrastructure layer to integrate proprietary, licensed, and public data sources.

### Architecture
- It exposes data through multiple surfaces including Python environments, the enterprise UI OpenBB Workspace, Excel, MCP servers for AI agents, and REST APIs, providing a unified access point for financial data.

### Stack
- Python, uvicorn, click, fastapi.

## Features and modules

### Overview
- The OpenBB-finance/OpenBB repository contains the Open Data Platform (ODP), an open-source financial data platform.
- It is designed for analysts, quants, and AI agents.
- ODP functions as a 'connect once, consume everywhere' infrastructure layer.
- It integrates proprietary, licensed, and public data sources.
- The platform covers topics such as equity, crypto, derivatives, economics, fixed-income, and options.

### Architecture / Modules
- The ODP exposes data through multiple surfaces.
- These surfaces include Python environments, the enterprise UI OpenBB Workspace (available at pro.openbb.co), Excel, MCP servers for AI agents, and REST APIs.

### Public API / Interfaces
- The platform exposes data via REST APIs.
- Specific endpoints and decorators mentioned include: `@openbb.co`, `@campus.fct.unl.pt`, `/summary`.
- Public surface: @openbb.co, @campus.fct.unl.pt, /summary.

### Operational Guidance
- The ODP can be installed via `pip install openbb`.
- A separate CLI is available via `pip install openbb-cli`.
- To integrate the ODP backend with the OpenBB Workspace, users need Python 3.9.21-3.12.
- Dependencies for Workspace integration are installed with `pip install "openbb[all]"`.
- A local FastAPI server is run via Uvicorn with the `openbb-api` command, which launches at `127.0.0.1:6900`.
- Usability signals: pip install openbb, pip install "openbb[all]", pip install openbb-cli, openbb-api.

### Tests
- Provider extensions are being refactored for V5 standards, often targeting 100% test coverage.

## Benchmarks and examples
- Provider extensions are being refactored for V5 standards, often targeting 100% test coverage.

## Closing remarks
- Roadmap: It exposes data through multiple surfaces including Python environments, the enterprise UI OpenBB Workspace, Excel, MCP servers for AI agents, and REST APIs, providing a unified access point for financial data.