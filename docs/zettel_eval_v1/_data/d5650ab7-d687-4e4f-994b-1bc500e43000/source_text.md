## Overview
- Dendron's architecture centers on plaintext markdown files, managed with Git, and organized into "vaults." It extends markdown with "gradual structure" primitives and uses schemas for consistency.

### Core argument
- Dendron's architecture centers on plaintext markdown files, managed with Git, and organized into "vaults." It extends markdown with "gradual structure" primitives and uses schemas for consistency.

### Architecture
- Navigation is supported through backlinks and a graph view.
- The system provides robust refactoring capabilities and supports rich content like mermaid diagrams and KaTeX.
- Vaults can be published as static Next.js websites.

### Stack
- TypeScript, JavaScript, HTML, Next.js.

## Features and modules

### Overview
- Dendron is an open-source, local-first, markdown-based Personal Knowledge Management (PKM) tool.
- It is designed for developers and integrates with VS Code and VSCodium.
- The project is in maintenance-only mode; active development has ceased.
- Dendron's mission is to manage any amount of knowledge, aiming to scale beyond 10,000 notes.
- Its design is developer-centric, targeting the efficiency of Vim and extensibility of Emacs within a text-centric, keyboard-focused UX.
- It employs a principle of "gradual structure," extending markdown with primitives that can be added as a knowledge base grows.
- Public surface: /sub.
- Usability signals: Integrates with VS Code and VSCodium, Licensed under Apache 2.0.

### Architecture / Modules
- The architecture uses plaintext files manageable with git.
- Knowledge is organized into "vaults" (git-backed folders).
- Key features include a unified lookup for finding/creating notes.
- Schemas are used for consistency and autocompletion.
- Navigation is supported via backlinks and a graph view.
- Robust refactoring capabilities are provided, preserving links.
- Supports mermaid diagrams and KaTeX for math.
- Supports note embedding.
- Vaults can be published as static Next.js websites with granular permissions.

### Public API / Interfaces
- The CLI includes the `/sub` interface.
- Public surface: /sub.

### Operational guidance
- The repository provides a `./setup.sh` script for development environment automation.
- Usability signals: ./setup.sh.

### Current Status / Issues
- The project is in maintenance-only mode, and active development has ceased.
- Recent issues involve bugs with Mermaid support overriding VS Code's native feature.
- Outdated documentation has been noted.
- CLI errors have been reported.
- Problems with image pasting and preview rendering have been observed.

## Closing remarks
- Roadmap: The project is currently in maintenance-only mode.